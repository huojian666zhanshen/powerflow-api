from __future__ import annotations

from typing import Any, Dict, Optional
import traceback

import numpy as np
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.openapi.utils import get_openapi
from pydantic import BaseModel, Field

from pypower.api import case14, case30
from solver_adapter import SolverAdapter

app = FastAPI(title="Powerflow API", version="0.1.1")


class PFRequest(BaseModel):
    case: Dict[str, Any] = Field(..., description="电网 case（JSON）；支持 {case_id: case14/case30} 或完整 MATPOWER dict")
    method: str = Field("dc", description="dc 或 ac")
    options: Optional[Dict[str, Any]] = Field(None, description="可选参数")


solver = SolverAdapter()


# -------------------------
# Helpers: case_id -> full MATPOWER dict (JSON-friendly)
# -------------------------
def _np_to_list(x: Any) -> Any:
    if isinstance(x, np.ndarray):
        return x.tolist()
    return x


def expand_case_if_needed(case: Dict[str, Any]) -> Dict[str, Any]:
    """
    支持 {"case_id":"case30"} / {"id":"case30"} / {"name":"case30"} 这种输入
    展开成完整 MATPOWER dict（bus/gen/branch 为 list[list]，便于 JSON）
    """
    if not isinstance(case, dict):
        raise ValueError("case must be a dict")

    cid = case.get("case_id") or case.get("id") or case.get("name")
    if cid is None:
        return case  # 已经是完整 MATPOWER dict

    cid = str(cid).strip().lower()
    if cid in ("case14", "ieee14", "ieee-14", "14"):
        c = case14()
    elif cid in ("case30", "ieee30", "ieee-30", "30"):
        c = case30()
    else:
        raise ValueError(f"unknown case_id: {cid}")

    out: Dict[str, Any] = {}
    for k, v in c.items():
        out[k] = _np_to_list(v)

    out["baseMVA"] = float(out.get("baseMVA", 100.0))
    out["version"] = str(out.get("version", "2"))
    return out


# -------------------------
# Routes
# -------------------------
@app.get("/health", tags=["system"])
def health():
    return {"ok": True}


@app.post("/run_pf", tags=["powerflow"])
def run_pf(req: PFRequest):
    """
    统一入口：
    - 支持 case_id（展开为完整 MATPOWER）
    - 发生错误时返回 JSON（便于上游/决策服务定位）
    """
    try:
        method = str(req.method).lower().strip()
        case = expand_case_if_needed(req.case)
        options = req.options

        result = solver.run_pf(case=case, method=method, options=options)

        # ✅ 确保任何 numpy 都不会漏到 JSON（solver 已经做了大部分，这里兜底）
        def _sanitize(obj: Any) -> Any:
            if isinstance(obj, np.ndarray):
                return obj.tolist()
            if isinstance(obj, dict):
                return {k: _sanitize(v) for k, v in obj.items()}
            if isinstance(obj, list):
                return [_sanitize(x) for x in obj]
            return obj

        return _sanitize(result)

    except ValueError as e:
        # 输入问题 -> 400
        return JSONResponse(status_code=400, content={"error": str(e)})

    except Exception as e:
        # 内部异常 -> 500（返回 trace 便于定位）
        traceback.print_exc()
        return JSONResponse(
            status_code=500,
            content={"error": str(e), "trace": traceback.format_exc()[:4000]},
        )


# ====== Dify 兼容：OpenAPI “净化器” ======
def _rewrite_anyof_nullable(node: Any) -> Any:
    if isinstance(node, dict):
        for k in list(node.keys()):
            node[k] = _rewrite_anyof_nullable(node[k])

        if "anyOf" in node and isinstance(node["anyOf"], list):
            variants = node["anyOf"]
            non_null = [v for v in variants if not (isinstance(v, dict) and v.get("type") == "null")]
            if len(non_null) == 1 and len(non_null) != len(variants):
                merged = dict(non_null[0])
                merged["nullable"] = True
                for keep in ("title", "description", "default", "example"):
                    if keep in node and keep not in merged:
                        merged[keep] = node[keep]
                return merged
        return node

    if isinstance(node, list):
        return [_rewrite_anyof_nullable(x) for x in node]

    return node


def _strip_422(schema: Dict[str, Any]) -> None:
    for path_item in schema.get("paths", {}).values():
        if not isinstance(path_item, dict):
            continue
        for op in path_item.values():
            if isinstance(op, dict):
                responses = op.get("responses")
                if isinstance(responses, dict):
                    responses.pop("422", None)


def _fix_health_schema(schema: Dict[str, Any]) -> None:
    try:
        s = schema["paths"]["/health"]["get"]["responses"]["200"]["content"]["application/json"]["schema"]
        if isinstance(s, dict) and len(s) == 0:
            schema["paths"]["/health"]["get"]["responses"]["200"]["content"]["application/json"]["schema"] = {
                "type": "object"
            }
    except Exception:
        pass


def custom_openapi():
    schema = get_openapi(
        title=app.title,
        version=app.version,
        routes=app.routes,
    )
    schema["openapi"] = "3.0.2"

    # 先放相对路径，占位；真正的 servers 在 /openapi.json 里动态注入
    schema["servers"] = [{"url": "/"}]

    _strip_422(schema)
    schema = _rewrite_anyof_nullable(schema)
    _fix_health_schema(schema)

    app.openapi_schema = schema
    return app.openapi_schema


@app.get("/openapi.json", include_in_schema=False)
def openapi_json(request: Request):
    schema = custom_openapi()
    base_url = str(request.base_url).rstrip("/")
    schema = dict(schema)
    schema["servers"] = [{"url": base_url}]
    return JSONResponse(schema)


app.openapi = custom_openapi
