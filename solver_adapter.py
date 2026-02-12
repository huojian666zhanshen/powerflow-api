# solver_adapter.py
from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple
import math
import numpy as np


class SolverAdapter:
    """
    DC + AC 潮流求解适配器（用于 FastAPI / MCP）

    method="dc":
      case = {
        "baseMVA": 100,
        "bus": [{"id" or "bus_i", "type", "Pd", "Pg"}, ...],
        "branch": [{"f/t 或 fbus/tbus 或 from/to", "x", "rateA"(optional)}, ...]
      }

    method="ac":
      case = {
        "baseMVA": 100,
        "bus":    [[MATPOWER bus row], ...],
        "gen":    [[MATPOWER gen row], ...],
        "branch": [[MATPOWER branch row], ...],
        (optional) "version": "2"
      }

    输出统一（纯潮流，不做越限判断）：
      {
        "converged": bool,
        "method": "dc"|"ac",
        "bus": [...],
        "branch": [...],
        (optional) "bus_vm": [...],   # AC 快捷电压向量
        (optional) "error": "..."
      }
    """

    def run_pf(
        self,
        case: Dict[str, Any],
        method: str = "dc",
        options: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        m = str(method).lower().strip()
        options = options or {}

        if m == "dc":
            return self._run_dc(case)
        if m == "ac":
            return self._run_ac_pypower(case, options)

        raise ValueError(f"Unknown method={method}, only supports dc/ac")

    # ============================================================
    # DC
    # ============================================================
    def _run_dc(self, case: Dict[str, Any]) -> Dict[str, Any]:
        buses_raw = case.get("bus")
        branches_raw = case.get("branch")
        if not isinstance(buses_raw, list) or not buses_raw:
            raise ValueError("DC: case.bus must be a non-empty list")
        if not isinstance(branches_raw, list) or not branches_raw:
            raise ValueError("DC: case.branch must be a non-empty list")

        base_mva = float(case.get("baseMVA", 100.0))
        if base_mva <= 0:
            raise ValueError("DC: baseMVA must be positive")

        buses, bus_ids = self._normalize_buses_dc(buses_raw)
        branches = self._normalize_branches_dc(branches_raw)

        n = len(bus_ids)
        id2idx = {bid: i for i, bid in enumerate(bus_ids)}

        slack_idx = self._find_slack_index_dc(buses)

        # P injections (pu): (Pg - Pd)/baseMVA
        P = np.zeros(n, dtype=float)
        for i, b in enumerate(buses):
            Pd = float(b.get("Pd", 0.0))
            Pg = float(b.get("Pg", 0.0))
            P[i] = (Pg - Pd) / base_mva

        # Build B matrix
        B = np.zeros((n, n), dtype=float)
        for k, br in enumerate(branches):
            f_id, t_id = br["f"], br["t"]
            if f_id not in id2idx or t_id not in id2idx:
                raise ValueError(f"DC: branch[{k}] references unknown bus: f={f_id}, t={t_id}")
            f = id2idx[f_id]
            t = id2idx[t_id]
            x = float(br["x"])
            if x == 0.0:
                raise ValueError(f"DC: branch[{k}] x cannot be 0")

            bij = 1.0 / x
            B[f, f] += bij
            B[t, t] += bij
            B[f, t] -= bij
            B[t, f] -= bij

        theta = self._solve_dc_angles(B, P, slack_idx)

        # branch flows (pu): Pft = (theta_f - theta_t)/x
        branch_out: List[Dict[str, Any]] = []
        for k, br in enumerate(branches):
            f = id2idx[br["f"]]
            t = id2idx[br["t"]]
            x = float(br["x"])
            Pft = (theta[f] - theta[t]) / x
            branch_out.append({"idx": k, "Pft_pu": float(Pft)})

        bus_out: List[Dict[str, Any]] = []
        for i, bid in enumerate(bus_ids):
            bus_out.append({
                "id": int(bid),
                "Va_deg": float(theta[i] * 180.0 / math.pi),
                "Pinj_pu": float(P[i]),
            })

        return {
            "converged": True,
            "method": "dc",
            "bus": bus_out,
            "branch": branch_out,
        }

    def _normalize_buses_dc(self, buses_raw: List[Any]) -> Tuple[List[Dict[str, Any]], List[int]]:
        buses: List[Dict[str, Any]] = []
        bus_ids: List[int] = []

        # MATPOWER bus cols (0-index):
        # 0 BUS_I, 1 TYPE, 2 PD, 3 QD, 7 VM, 8 VA ...
        type_map = {1: "pq", 2: "pv", 3: "slack"}

        for i, b in enumerate(buses_raw):
            # ---- case A: object list ----
            if isinstance(b, dict):
                raw_id = b.get("id", b.get("bus_i", None))
                if raw_id is None:
                    raise ValueError(f"DC: bus[{i}] missing id/bus_i")

                bid = int(raw_id)
                if bid in bus_ids:
                    raise ValueError(f"DC: duplicated bus id={bid}")

                buses.append({
                    "id": bid,
                    "type": b.get("type", "pq"),
                    "Pd": float(b.get("Pd", 0.0)),
                    "Pg": float(b.get("Pg", 0.0)),
                })
                bus_ids.append(bid)
                continue

            # ---- case B: MATPOWER 2D row (list/tuple) ----
            if isinstance(b, (list, tuple, np.ndarray)):
                if len(b) < 3:
                    raise ValueError(f"DC: bus[{i}] MATPOWER row too short, need at least 3 cols")
                bid = int(b[0])
                if bid in bus_ids:
                    raise ValueError(f"DC: duplicated bus id={bid}")

                btype_num = int(b[1]) if len(b) > 1 else 1
                Pd = float(b[2]) if len(b) > 2 else 0.0

                buses.append({
                    "id": bid,
                    "type": type_map.get(btype_num, "pq"),
                    "Pd": Pd,
                    "Pg": 0.0,  # 若需要按 gen 汇总 Pg，可在上游先处理或另写补丁
                })
                bus_ids.append(bid)
                continue

            raise ValueError(f"DC: bus[{i}] must be an object or MATPOWER row")

        return buses, bus_ids

    def _normalize_branches_dc(self, branches_raw: List[Any]) -> List[Dict[str, Any]]:
        out: List[Dict[str, Any]] = []
        for i, br in enumerate(branches_raw):

            # ---- case A: object list ----
            if isinstance(br, dict):
                f = br.get("f", None)
                t = br.get("t", None)
                if f is None or t is None:
                    f = br.get("fbus", br.get("from", None))
                    t = br.get("tbus", br.get("to", None))
                if f is None or t is None:
                    raise ValueError(f"DC: branch[{i}] missing endpoints")
                if "x" not in br:
                    raise ValueError(f"DC: branch[{i}] missing x")
                out.append({
                    "f": int(f),
                    "t": int(t),
                    "x": float(br["x"]),
                })
                continue

            # ---- case B: MATPOWER row ----
            # MATPOWER branch cols: 0 F_BUS, 1 T_BUS, 2 BR_R, 3 BR_X, 5 RATE_A
            if isinstance(br, (list, tuple, np.ndarray)):
                if len(br) < 4:
                    raise ValueError(f"DC: branch[{i}] MATPOWER row too short, need at least 4 cols")
                f = int(br[0])
                t = int(br[1])
                x = float(br[3])
                out.append({"f": f, "t": t, "x": x})
                continue

            raise ValueError(f"DC: branch[{i}] must be an object or MATPOWER row")

        return out

    def _find_slack_index_dc(self, buses: List[Dict[str, Any]]) -> int:
        for i, b in enumerate(buses):
            t = b.get("type", None)
            if isinstance(t, (int, float)) and int(t) == 3:
                return i
            if isinstance(t, str) and t.strip().lower() in ("slack", "ref", "swing"):
                return i
        return 0

    def _solve_dc_angles(self, B: np.ndarray, P: np.ndarray, slack_idx: int) -> np.ndarray:
        n = B.shape[0]
        theta = np.zeros(n, dtype=float)
        if n <= 1:
            return theta

        mask = np.ones(n, dtype=bool)
        mask[slack_idx] = False
        B_red = B[mask][:, mask]
        P_red = P[mask]

        if B_red.shape[0] == 0:
            return theta

        try:
            theta_red = np.linalg.solve(B_red, P_red)
        except np.linalg.LinAlgError as e:
            raise ValueError(f"DC: singular B matrix / disconnected network: {e}")

        theta[mask] = theta_red
        theta[slack_idx] = 0.0
        return theta

    # ============================================================
    # AC (PYPOWER)
    # ============================================================
    def _run_ac_pypower(self, case: Dict[str, Any], options: Dict[str, Any]) -> Dict[str, Any]:
        """
        使用 PYPOWER runpf 进行 AC 潮流（纯潮流，不做越限判断）。
        关键：bus/gen/branch 必须是 2D ndarray；列数不够则补 0。
        """
        try:
            from pypower.runpf import runpf
            from pypower.ppoption import ppoption
        except Exception as e:
            return {
                "converged": False,
                "method": "ac",
                "bus": [],
                "branch": [],
                "error": f"PYPOWER not available: {e}",
            }

        if "bus" not in case or "gen" not in case or "branch" not in case:
            raise ValueError("AC: case must contain bus/gen/branch in MATPOWER format")

        base_mva = float(case.get("baseMVA", 100.0))
        if base_mva <= 0:
            raise ValueError("AC: baseMVA must be positive")

        bus = self._to_ndarray_2d(case["bus"], dtype=float, name="bus")
        gen = self._to_ndarray_2d(case["gen"], dtype=float, name="gen")
        branch = self._to_ndarray_2d(case["branch"], dtype=float, name="branch")

        bus = self._pad_cols(bus, min_cols=13, name="bus")
        gen = self._pad_cols(gen, min_cols=21, name="gen")
        branch = self._pad_cols(branch, min_cols=13, name="branch")

        ppc = {
            "version": str(case.get("version", "2")),
            "baseMVA": base_mva,
            "bus": bus,
            "gen": gen,
            "branch": branch,
        }

        ppopt = ppoption(VERBOSE=0, OUT_ALL=0)
        for k, v in (options or {}).items():
            try:
                ppopt[k] = v
            except Exception:
                pass

        try:
            results, success = runpf(ppc, ppopt)
        except Exception as e:
            return {
                "converged": False,
                "method": "ac",
                "bus": [],
                "branch": [],
                "error": f"PYPOWER runpf failed: {e}",
            }

        bus_r = results["bus"]
        gen_r = results["gen"]
        br_r = results["branch"]

        # bus: 0 BUS_I, 2 PD, 3 QD, 7 VM, 8 VA, 11 VMAX, 12 VMIN
        bus_out: List[Dict[str, Any]] = []
        for i in range(bus_r.shape[0]):
            bus_id = int(bus_r[i, 0])
            Pd = float(bus_r[i, 2])
            Qd = float(bus_r[i, 3])
            Vm = float(bus_r[i, 7])
            Va = float(bus_r[i, 8])
            Vmax = float(bus_r[i, 11]) if bus_r.shape[1] > 11 else None
            Vmin = float(bus_r[i, 12]) if bus_r.shape[1] > 12 else None
            bus_out.append({
                "id": bus_id,
                "Vm_pu": Vm,
                "Va_deg": Va,
                "Pd_MW": Pd,
                "Qd_Mvar": Qd,
                "Vmax_pu": Vmax,
                "Vmin_pu": Vmin,
            })

        # 汇总每个母线的 Pg/Qg
        PgQg_by_bus: Dict[int, Dict[str, float]] = {}
        for i in range(gen_r.shape[0]):
            b = int(gen_r[i, 0])
            Pg = float(gen_r[i, 1])
            Qg = float(gen_r[i, 2])
            if b not in PgQg_by_bus:
                PgQg_by_bus[b] = {"Pg_MW": 0.0, "Qg_Mvar": 0.0}
            PgQg_by_bus[b]["Pg_MW"] += Pg
            PgQg_by_bus[b]["Qg_Mvar"] += Qg

        for rec in bus_out:
            b = rec["id"]
            rec["Pg_MW"] = PgQg_by_bus.get(b, {}).get("Pg_MW", 0.0)
            rec["Qg_Mvar"] = PgQg_by_bus.get(b, {}).get("Qg_Mvar", 0.0)

        # branch: 0 F_BUS, 1 T_BUS, 13 PF,14 QF,15 PT,16 QT, 5 RATE_A
        branch_out: List[Dict[str, Any]] = []
        for i in range(br_r.shape[0]):
            f = int(br_r[i, 0])
            t = int(br_r[i, 1])
            Pf = float(br_r[i, 13]) if br_r.shape[1] > 13 else None
            Qf = float(br_r[i, 14]) if br_r.shape[1] > 14 else None
            Pt = float(br_r[i, 15]) if br_r.shape[1] > 15 else None
            Qt = float(br_r[i, 16]) if br_r.shape[1] > 16 else None
            rateA = float(br_r[i, 5]) if br_r.shape[1] > 5 else None
            branch_out.append({
                "idx": i,
                "fbus": f,
                "tbus": t,
                "Pf_MW": Pf,
                "Qf_Mvar": Qf,
                "Pt_MW": Pt,
                "Qt_Mvar": Qt,
                "rateA_MVA": rateA,
            })

        bus_vm = [float(rec["Vm_pu"]) for rec in bus_out]

        return {
            "converged": bool(success),
            "method": "ac",
            "bus": bus_out,
            "bus_vm": bus_vm,
            "branch": branch_out,
        }

    # -------------------- helpers --------------------
    def _to_ndarray_2d(self, x: Any, dtype=float, name: str = "array") -> np.ndarray:
        arr = np.asarray(x, dtype=dtype)
        if arr.ndim != 2:
            raise ValueError(f"AC: {name} must be a 2D array-like, got shape={arr.shape}")
        return arr

    def _pad_cols(self, arr: np.ndarray, min_cols: int, name: str) -> np.ndarray:
        r, c = arr.shape
        if c >= min_cols:
            return arr
        pad = np.zeros((r, min_cols - c), dtype=arr.dtype)
        return np.hstack([arr, pad])
