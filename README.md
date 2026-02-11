# PowerFlow API

**PowerFlow API** 是一个基于 FastAPI 的电网潮流计算工具，支持 DC 和 AC 潮流分析，适用于配电网调度与优化。该工具提供标准化的 API 接口，能够快速执行电网的潮流计算并返回各节点和支路的功率、电压信息，支持与智能决策系统（如 GridGPT）集成。

## 功能概述
- **DC潮流**：简化的直流潮流计算，适用于大规模电网分析。
- **AC潮流**：基于 PYPOWER 的交流潮流计算，能够处理更复杂的电力系统网络。

## 主要功能
- 计算电网的潮流，输出包括电压、电流、功率流等信息。
- 提供 `/run_pf` API 接口，支持用户提交电网数据，并返回潮流计算结果。
- 提供 `/health` 路由来检查 API 的健康状态。

## API接口

### 1. **POST /run_pf**
执行潮流计算，支持指定电网数据和计算方法（DC 或 AC）。

#### 请求体格式：
```json
{
  "case": {
    "case_id": "case30",          // 电网案例ID（可选，支持 'case30', 'case14' 等）
    "baseMVA": 100,               // 基准功率（默认为 100）
    "bus": [                      // 电网节点（母线）信息
      {
        "id": 1,                   // 母线ID
        "type": "pq",              // 母线类型："pq" 为负荷母线，"pv" 为发电母线，"slack" 为参考母线
        "Pd": 50,                  // 负荷功率（MW）
        "Qg": 20                   // 负荷无功功率（MVar）
      },
      {
        "id": 2,
        "type": "pv",
        "Pg": 40,                  // 发电功率（MW）
        "Qg": 15
      }
    ],
    "branch": [                   // 电网支路（线路）信息
      {
        "f": 1,                    // 起始母线ID
        "t": 2,                    // 终止母线ID
        "x": 0.1                   // 电阻（pu）
      },
      {
        "f": 2,
        "t": 3,
        "x": 0.15
      }
    ]
  },
  "method": "dc",                // 潮流计算方法："dc" 为直流潮流计算，"ac" 为交流潮流计算
  "options": {                   // 可选参数（如有特殊需求）
    "max_iter": 100,             // 最大迭代次数
    "tolerance": 1e-6            // 计算容忍度
  }
}
说明：
case: 电网的基本数据。

case_id: 可以选择预定义的电网案例，如 case30 或 case14。如果没有指定，您需要提供完整的电网数据。

baseMVA: 基准功率，通常为100，但可以根据实际情况调整。

bus: 母线（电网节点）信息。每个母线可以包含负荷和发电功率、无功功率以及类型等。

branch: 电网支路信息。每个支路连接两个母线，具有电阻值 x。

method: 选择计算方法，dc 是直流潮流计算，ac 是交流潮流计算。

options: 可选的配置参数，例如最大迭代次数 max_iter 和容忍度 tolerance。

### 响应体格式：
{
  "converged": true,             // 是否计算收敛（bool类型）
  "method": "dc",                // 使用的潮流计算方法
  "bus": [                       // 每个母线的计算结果
    {
      "id": 1,                    // 母线ID
      "Va_deg": 5.5,              // 母线电压相位角（度）
      "Pinj_pu": 0.5              // 母线的功率注入（pu）
    },
    {
      "id": 2,
      "Va_deg": 2.3,
      "Pinj_pu": 0.4
    }
  ],
  "branch": [                    // 每个支路的计算结果
    {
      "idx": 0,                   // 支路索引
      "Pft_pu": 0.02              // 支路功率流（pu）
    },
    {
      "idx": 1,
      "Pft_pu": 0.03
    }
  ]
}
说明：
converged: 计算是否收敛，true 表示成功收敛，false 表示计算未收敛。

method: 返回使用的计算方法（dc 或 ac）。

bus: 每个母线的计算结果。

id: 母线的 ID。

Va_deg: 母线电压相位角，单位为度。

Pinj_pu: 母线的功率注入，单位为 pu（标幺）。

branch: 每个支路的计算结果。

idx: 支路的索引。

Pft_pu: 支路功率流，单位为 pu（标幺）。

##安装与运行
1. 克隆仓库：
git clone https://github.com/yourusername/powerflow-api.git
2. 安装依赖：
pip install -r requirements.txt
3. 启动 FastAPI 服务：
uvicorn main:app --reload
4. 访问 API：
服务启动后，您可以访问 http://gridgpt.dev 来使用 API。

##许可证
本项目使用 MIT 许可证，详情请见 LICENSE 文件。

##贡献
欢迎贡献！请按照以下步骤进行：

Fork 本仓库。

提交您的更改。

创建一个 Pull Request。

感谢您使用 PowerFlow API！
