# PowerFlow API

**PowerFlow API** 是一个基于 FastAPI 的电网潮流计算工具，支持 DC 和 AC 潮流分析，适用于配电网调度与优化。该工具提供标准化的 API 接口，能够快速执行电网的潮流计算并返回各节点和支路的功率、电压信息，支持与智能决策系统集成。

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
    "case_id": "case30",
    "baseMVA": 100,
    "bus": [ ... ],
    "branch": [ ... ]
  },
  "method": "dc",
  "options": { ... }
}
#### 响应体格式：
{
  "converged": true,
  "method": "dc",
  "bus": [ ... ],
  "branch": [ ... ]
}

###2. GET /health

检查服务是否正常运行。

响应格式：
{
  "ok": true
}

安装与运行
1. 克隆仓库：
git clone https://github.com/yourusername/powerflow-api.git

2. 安装依赖：
pip install -r requirements.txt

3. 启动 FastAPI 服务：
uvicorn main:app --reload

4. 访问 API：

服务启动后，您可以访问 http://127.0.0.1:8000 来使用 API。

许可证

本项目使用 MIT 许可证
，详情请见 LICENSE 文件。

贡献

欢迎贡献！请按照以下步骤进行：

Fork 本仓库。

提交您的更改。

创建一个 Pull Request。

感谢您使用 PowerFlow API！
