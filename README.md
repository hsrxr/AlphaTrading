# AlphaAgenting🤑

多代理 LLM 加密交易框架，包含从行情/新闻采集、分析决策、风险约束到链上提交与可视化监控的完整闭环。

本 README 基于当前仓库实现重构，重点说明三件事：

1. 这个项目实际实现了哪些功能。
2. 这些功能背后的原理和设计取舍。
3. 如何在本地快速跑起来（CLI、Runtime API、Trigger、Dashboard、链上 Path B）。

## 1. 项目定位

TradingAgents 不是单一模型调用脚本，而是一个面向交易场景的多角色协作系统：

- 使用 LangGraph 编排多节点 Agent 工作流。
- 把“分析”与“风控”拆分为两个阶段，避免 LLM 直接决定最终可执行订单。
- 通过持久化组合状态（SQLite）+ 记忆库（ChromaDB）实现跨轮次上下文。
- 可选接入 Sepolia 共享合约（ERC-8004 Path B）实现链上提交与反馈回流。

## 2. 功能实现总览

### 2.1 多代理协作决策

核心编排入口：tradingagents/graph/trading_graph.py

主要角色流如下：

1. Analyst 阶段
2. Bull/Bear 研究辩论阶段
3. Trader 生成 TradeIntent 草案
4. Risk Engine 做硬约束校验与裁剪
5. 输出 final_trade_decision

当前简化架构中主要分析师为：market、news、quant（见 graph setup）。

### 2.2 串行与并行双模式

- 串行模式：tradingagents/graph/setup.py
- 并行模式：tradingagents/graph/parallel_setup.py

并行模式会把 Analyst 子图隔离并发执行，再统一合并上下文，兼顾速度与稳定性。

### 2.3 风险引擎（确定性硬规则）

实现位置：tradingagents/agents/managers/risk_engine.py

关键点：

- 从 Trader JSON 提取 TradeIntent。
- 按账户状态计算可交易额度。
- 将请求订单裁剪为可执行订单。
- BUY/SELL/HOLD 最终由硬规则落地，而非只依赖模型语言输出。

当前实现中的关键硬约束（以 risk_engine.py 为准）：

- max_position_pct = 0.40
- max_single_order_pct = 0.10
- hard_max_trade_usd = 500.0

说明：default_config.py 中存在 max_position_pct/max_single_order_pct 配置项，但风险引擎当前代码内写死了上述值。

### 2.4 组合状态持久化

实现位置：tradingagents/portfolio_manager.py

使用 SQLite 保存：

- portfolio_state（现金、仓位、PnL、总资产快照）
- trade_history（开平仓历史）

并在首轮运行时自动初始化资金基线，后续运行复用状态。

### 2.5 虚拟账本与链上反馈

实现位置：

- tradingagents/virtual_ledger.py
- tradingagents/web3_layer/on_chain_integration.py
- tradingagents/web3_layer/trade_status_checker.py
- tradingagents/web3_layer/portfolio_feedback.py

流程：

1. 提交 TradeIntent 后先在本地账本预留资金。
2. 轮询 RiskRouter 事件等待 approved/rejected。
3. 根据反馈更新虚拟账本与组合状态。
4. 将结果回写 Agent 记忆（trade outcome recorder）。

### 2.6 Runtime API + Web Dashboard

后端：runtime_api_server.py（默认 127.0.0.1:8765）

主要接口：

- GET /healthz
- GET /api/runs
- POST /api/run/start
- GET /api/runs/{runId}/events?after=0

前端：web-dashboard（React 19 + Vite + TypeScript + Tailwind + Zustand + Recharts）

### 2.7 Trigger Runtime（事件驱动唤醒）

实现位置：

- trigger_main.py
- tradingagents/triggers/runtime.py
- tradingagents/triggers/observers.py

通过观察器与事件总线监控：

- 小时边界
- 新闻源轮询
- 价格行为

在聚合窗口内形成 market shock 后唤醒交易图执行。

### 2.8 ERC-8004 Path B 链上集成

主要实现：

- web3_path_b.py
- tradingagents/web3_layer/client.py

能力包含：

- agent 注册
- claim allocation
- EIP-712 TradeIntent 签名
- RiskRouter simulate/submit
- ValidationRegistry checkpoint 记分

## 3. 背后原理与设计

### 3.1 分层决策原则

项目把“推理能力”和“交易约束”解耦：

- 上游 Agent 负责信息解释、观点生成。
- 下游 Risk Engine 负责强约束执行。

这样能降低 LLM 幻觉直接转化为资金风险的概率。

### 3.2 先可追溯，再高性能

每次运行会产出 trace/full_state 日志，Runtime API 还能按 offset 增量拉取事件。

设计目标是先做到可观测、可审计，再谈吞吐和并发优化。

### 3.3 事件驱动而非固定轮询交易

Trigger Runtime 通过事件总线聚合多源信号后再唤醒 Agent，减少无效调用。

### 3.4 链上异步反馈闭环

链上提交不是终点，系统会等待 RiskRouter 的 approve/reject 反馈，并回流到：

- 组合状态
- 虚拟账本
- Agent 记忆

即形成“决策 -> 执行 -> 反馈 -> 记忆”的最小学习闭环。

## 4. 技术栈

### 4.1 后端/AI

- Python 3.10+
- LangGraph
- LangChain Core / OpenAI / Anthropic / Google GenAI
- Pandas / requests / feedparser / beautifulsoup4
- Typer + Rich（CLI）

### 4.2 数据与状态

- SQLite（组合与交易历史）
- JSONL/JSON（trace 与输出）
- ChromaDB + sentence-transformers（语义记忆）

### 4.3 链上

- web3.py
- eth-account
- EIP-712 typed data signing
- Sepolia（共享合约地址内置，可覆盖）

### 4.4 前端可视化

- React 19
- TypeScript
- Vite 8
- TailwindCSS
- Zustand
- Recharts

## 5. 核心目录导览

- tradingagents/graph：主工作流编排、并行/串行图、传播与反思
- tradingagents/agents：分析师、研究员、交易员、风险引擎节点
- tradingagents/dataflows：行情、指标、新闻工具
- tradingagents/triggers：事件观察器与运行时调度
- tradingagents/web3_layer：链上客户端、提交集成、反馈处理
- cli：交互式终端入口
- web-dashboard：前端仪表盘
- runtime_api_server.py：后端 API
- trigger_main.py：事件驱动入口

## 6. 快速开始

### 6.1 环境要求

- Python >= 3.10
- Node.js >= 18（前端可视化需要）
- 至少一个 LLM Provider 的 API Key

### 6.2 安装

```bash
python -m venv .venv
# Windows
.\.venv\Scripts\Activate.ps1

pip install -r requirements.txt
```

### 6.3 配置环境变量

在项目根目录创建 .env，最小示例：

```env
DEEPSEEK_API_KEY=your_deepseek_key
OPENAI_API_KEY=your_openai_key
ANTHROPIC_API_KEY=your_anthropic_key
```

### 6.4 运行单次分析

```bash
python main.py
```

### 6.5 使用 CLI

```bash
tradingagents
# 或
python -m cli.main
```

## 7. Runtime API + Dashboard

### 7.1 启动后端

```bash
python runtime_api_server.py
```

### 7.2 启动前端

```bash
cd web-dashboard
npm install
npm run dev
```

默认后端地址为 [http://127.0.0.1:8765](http://127.0.0.1:8765)。

## 8. Trigger 模式

```bash
python trigger_main.py
```

可通过 default_config.py 与环境变量控制：

- 观察交易对
- 聚合窗口
- cooldown
- 轮询周期
- 新闻源过滤

## 9. 链上 Path B 使用

先在 .env 配置（示例）：

```env
SEPOLIA_RPC_URL=https://ethereum-sepolia-rpc.publicnode.com
OPERATOR_PRIVATE_KEY=0x...
AGENT_WALLET_PRIVATE_KEY=0x...
AGENT_ID=123
```

常用命令：

```bash
python web3_path_b.py register --name my-agent --description "demo"
python web3_path_b.py claim --agent-id 123
python web3_path_b.py balance --agent-id 123
python web3_path_b.py simulate-intent --agent-id 123 --action BUY --amount-usd-scaled 25000
python web3_path_b.py submit-intent --agent-id 123 --action BUY --amount-usd-scaled 25000
```

## 10. 关键运行产物

- eval_results/{PAIR}/TradingAgentsStrategy_logs/full_trace_*.jsonl
- eval_results/{PAIR}/TradingAgentsStrategy_logs/full_states_log_*.json
- trade_memory/portfolio.db
- trade_memory/virtual_ledger.json

## 11. 注意事项

1. 当前风险引擎 hard cap 为 500 USD/单，适合测试与演示，不适合作为生产资金管理上限。
2. 链上提交依赖 Sepolia RPC 与 gas，且 checkpoint 提交钱包需有可用 ETH。
3. 并行模式在部分 Provider 的工具调用消息约束下可能回退到串行执行（代码已内置 fallback）。

## 12. 许可

MIT License，见 LICENSE。
