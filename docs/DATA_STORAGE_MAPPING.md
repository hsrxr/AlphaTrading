# Trading Records & PnL Data Storage Mapping

Comprehensive guide to all locations where trading records and PnL data are saved when `trigger_main.py` runs.

---

## 1. TRIGGER RUNTIME OUTPUT SOURCES

### Main Entry Points
- **File**: [trigger_main.py](trigger_main.py)
- **Function**: `_persist_eval_result()` (lines 62-88)
- **Function**: `main()` (lines 90+)

### Primary Output: Trigger Runtime Results
**Directory**: `eval_results/{PAIR}/trigger_runtime_results/`

**Files Generated**:
- `final_result_{TIMESTAMP}.json` - Final trading decision and market shock context

**Data Stored** (JSON format):
```json
{
  "saved_at": "2026-04-09T08:33:32.123456+00:00",
  "pair": "ETHUSD",
  "market_shock": { /* MarketShockEvent data */ },
  "event_types": ["price_action", "news", ...],
  "event_count": 3,
  "decision_raw": "raw decision string",
  "decision_json": { /* parsed decision object */ },
  "final_state": { /* complete graph execution state */ }
}
```

**Example Pairs with Results**:
- `eval_results/BTCUSD/trigger_runtime_results/final_result_*.json`
- `eval_results/ETHUSD/trigger_runtime_results/final_result_*.json`
- `eval_results/SOLUSD/trigger_runtime_results/final_result_*.json`

---

## 2. RUNTIME EXECUTION LOGGING

### Logs Directory
**Path**: `logs/`

**Files Created**:
- `trigger_runtime_{YYYYMMDD}.log` - Early log files (format: `trigger_runtime_20260408.log`)
- `trigger_runtime_{YYYYMMDDHHmmss}.log` - Timestamped logs (format: `trigger_runtime_20260409165253.log`)

**Environment Variable**: `TRIGGER_LOG_DIR` (defaults to `logs/`)

**Log Level**: `INFO` (includes streaming to console + file)

**Log Format**: `%(asctime)s | %(levelname)s | %(name)s | %(message)s`

**Key Entries Logged**:
- Trigger wakeup events
- Agent decision process
- On-chain submission results
- RiskRouter feedback (approval/rejection)
- Virtual ledger balance updates

---

## 3. TRADING AGENTS GRAPH OUTPUTS

### Full Trace Files (JSONL)
**Directory**: `eval_results/{PAIR}/TradingAgentsStrategy_logs/`

**Filename**: `full_trace_{SAFE_TRADE_DATE}_{TIMESTAMP}.jsonl`

**Example**: `full_trace_2026-04-08 13-13-46.442661+00-00_20260408_211346.jsonl`

**Data Type**: Line-delimited JSON (JSONL)

**Events Logged** (one per line):
- `run_started` - Graph execution start with metadata
- `node_start` - Node execution start (agent name, state keys)
- `node_end` - Node execution end (duration, output)
- `llm_call` - LLM prompt/response with duration and tool calls
- `llm_token` - Streaming tokens for real-time tracking
- `tool_start` / `tool_end` - Data tool execution events

**Use Case**: Real-time debugging, analyzing agent decision process step-by-step

**File Size**: 1-5 MB per run (includes full LLM prompts/responses)

---

### Full States Log (JSON)
**Directory**: `eval_results/{PAIR}/TradingAgentsStrategy_logs/`

**Filename**: `full_states_log_{SAFE_TRADE_DATE}.json`

**Example**: `full_states_log_2026-04-08 13-13-46.442661+00-00.json`

**Data Type**: JSON (pretty-printed, indexed by timestamp)

**Structure**:
```json
{
  "2026-04-08 13:13:46.442661+00:00": {
    "company_of_interest": "BTCUSD",
    "trade_date": "2026-04-08 13:13:46.442661+00:00",
    "market_report": "...",
    "sentiment_report": "...",
    "news_report": "...",
    "quant_strategy_report": "...",
    "fundamentals_report": "...",
    "investment_debate_state": { /* bull/bear history and judge decision */ },
    "trader_investment_decision": "...",
    "risk_debate_state": { /* aggressive/conservative/neutral debate */ },
    "investment_plan": "...",
    "final_trade_decision": "..." /* on-chain formatted JSON */
  }
}
```

**Key Fields**:
- **market_report**: Technical analysis (moving averages, RSI, MACD, Bollinger Bands, ATR)
- **sentiment_report**: Sentiment analysis (empty in current runs)
- **news_report**: News catalyst analysis and trading implications
- **quant_strategy_report**: Quantitative factor signals (alpha101_12, alpha101_2_variant, gtja_191_variant)
- **investment_debate_state**: Bull vs Bear debate with judge decision
- **final_trade_decision**: Structured JSON with action, pair, amount, confidence, reasons

**Use Case**: Comprehensive decision documentation, audit trail, backtesting

---

## 4. VIRTUAL LEDGER (TRADE MEMORY)

### Ledger File
**Path**: `trade_memory/virtual_ledger.json`

**Initialization**: 100% auto-created on first run

**Structure**:
```json
{
  "account": {
    "balance_usd": 99996.78,
    "initial_capital_usd": 100000.0,
    "created_at": "2026-04-09T08:30:15.776346+00:00",
    "realized_pnl_usd": 0.0,
    "total_trades_submitted": 14,
    "total_trades_approved": 0,
    "total_trades_rejected": 0
  },
  "trades": [
    {
      "id": "3c8084c27176068e_0",
      "agent_id": 40,
      "pair": "ETHUSD",
      "action": "SELL",
      "amount_usd": 0.23,
      "intent_hash": "3c8084c27176068ec7cb24f1d...",
      "confidence": 0.75,
      "notes": "Risk reduction due to overleveraged portfolio...",
      "status": "submitted",  /* submitted → approved/rejected → closed */
      "submitted_at": "2026-04-09T08:33:24.417570+00:00",
      "reserved_balance": 0.23,
      "approved_at": null,
      "rejected_at": null,
      "rejection_reason": null,
      "closed_at": null,
      "realized_pnl": null
    }
  ],
  "last_saved": "2026-04-09T08:33:32.123456+00:00"
}
```

**Account Summary Fields**:
- `balance_usd` - Current available cash
- `realized_pnl_usd` - Cumulative realized profits/losses
- `total_trades_submitted` - Count of all trade submissions
- `total_trades_approved` - Count of RiskRouter approvals
- `total_trades_rejected` - Count of RiskRouter rejections

**Trade Status Lifecycle**:
1. **submitted** - Initial submission to RiskRouter
   - `reserved_balance` is immediately deducted from account
2. **approved** - RiskRouter approved the trade
   - Balance remains reserved
   - `execution_price` recorded if available
3. **rejected** - RiskRouter rejected the trade
   - Balance returned to account
   - `rejection_reason` provided
4. **closed** - Trade exited (future implementation)
   - `exit_price` and `realized_pnl` recorded

**Persistence**: Updated after every trade submission, approval, rejection, or status change

**Access Pattern**:
```python
from tradingagents.virtual_ledger import create_virtual_ledger
ledger = create_virtual_ledger("./trade_memory/virtual_ledger.json")
balance = ledger.get_balance()
summary = ledger.get_account_summary()
```

---

## 5. PORTFOLIO DATABASE

### SQLite Database
**Path**: `trade_memory/portfolio.db`

**Tables**:

#### portfolio_state
```sql
CREATE TABLE portfolio_state (
  id INTEGER PRIMARY KEY,
  timestamp TEXT,
  cash_usd REAL,
  positions TEXT (JSON),  /* flexible multi-asset JSON */
  unrealized_pnl REAL,
  realized_pnl REAL,
  total_assets REAL,
  created_at DATETIME
)
```

**Use**: Snapshots of portfolio state at key moments

**Record Example**:
- timestamp: "2026-04-09T08:33:32.123456+00:00"
- cash_usd: 99996.78
- positions: `{"ETHUSD": {"quantity": 10, "cost": 5000}}`
- unrealized_pnl: -500.25
- realized_pnl: 0.0
- total_assets: 99496.53

#### trade_history
```sql
CREATE TABLE trade_history (
  id INTEGER PRIMARY KEY,
  timestamp TEXT,
  ticker TEXT,
  side TEXT (BUY/SELL),
  quantity REAL,
  entry_price REAL,
  notional_usd REAL,
  status TEXT (open/closed),
  exit_price REAL,
  realized_pnl REAL,
  created_at DATETIME
)
```

**Use**: Historical trade records with entry/exit data

**Access Pattern**:
```python
from tradingagents.portfolio_manager import PortfolioManager
pm = PortfolioManager("./trade_memory/portfolio.db")
summary = pm.get_account_summary()
```

---

## 6. ON-CHAIN SUBMISSION RECORDS

### Checkpoints JSONL
**Path**: `checkpoints.jsonl` (project root)

**Default Location**: Can be customized via `OnChainIntegrator` initialization

**Filename Format**: `checkpoints.jsonl` (no timestamps)

**Data Type**: Line-delimited JSON (append-only log)

**Structure Per Line**:
```json
{
  "checkpointHash": "0x3f...",
  "checkpoint": {
    "agentId": 40,
    "timestamp": 1712673632,
    "action": "BUY",
    "pair": "ETHUSD",
    "amountUsdScaled": 20000,  /* in cents */
    "priceUsdScaled": 320000,
    "reasoningHash": "0x7d..."
  },
  "score": 100,
  "notes": "TradingAgent decision: ...",
  "savedAt": 1712673632
}
```

**Use**: Audit trail of all on-chain ValidationRegistry submissions

**Persistence**: Appended after each successful checkpoint submission

**Access Pattern**: Read line-by-line as JSONL (no single JSON object)

---

## 7. AGENT ID & METADATA

### Agent Registration File
**Path**: `agent-id.json` (project root)

**Sample Content**:
```json
{
  "agentId": 40,
  "agentWallet": "0xBE6Dc64196b14256771dB6D27Eb0Ea8b52B00643",
  "name": "TradingAgent",
  "description": "AI trading agent",
  "capabilities": ["trade_submission", "on_chain_integration"],
  "claim": {
    "balanceEth": 5.0,
    "claimedAt": "2026-04-09T08:30:00Z"
  }
}
```

**Use**: Agent registration metadata, wallet info, allocation balance

**Populated By**: `web3_path_b.py` registration script

---

## 8. CHROMADB VECTOR STORE

### Vector Database
**Path**: `trade_memory/chromadb/chroma.sqlite3`

**Use**: Persistent memory and semantic search for agent reflections

**Collections** (implicit):
- Bull analyst memory (learned patterns)
- Bear analyst memory
- Quant analyst memory
- Trader memory
- Risk manager memory

**Access Pattern**: Used internally by reflector to retrieve similar past trades

---

## SUMMARY: DATA FLOW DURING TRIGGER_MAIN RUN

```
┌─────────────────┐
│  trigger_main   │
└────────┬────────┘
         │
         ├─→ logs/trigger_runtime_{ts}.log
         │   (execution logs)
         │
         ├─→ eval_results/{PAIR}/TradingAgentsStrategy_logs/
         │   ├── full_trace_{ts}.jsonl (execution trace)
         │   └── full_states_log_{ts}.json (decision state)
         │
         ├─→ eval_results/{PAIR}/trigger_runtime_results/
         │   └── final_result_{ts}.json (market shock + decision)
         │
         ├─→ trade_memory/virtual_ledger.json
         │   (trade submissions, approvals, rejections)
         │
         ├─→ trade_memory/portfolio.db
         │   (portfolio snapshots and trade history)
         │
         └─→ checkpoints.jsonl
             (on-chain validation records)
```

---

## ACCESSING TRADE RECORDS & PnL

### Quick Commands

**Get Latest Virtual Ledger**:
```bash
cat trade_memory/virtual_ledger.json | jq '.account'
```

**Get Latest Trading Decision**:
```bash
ls -lt eval_results/*/TradingAgentsStrategy_logs/full_states_log_*.json | head -1
cat eval_results/ETHUSD/TradingAgentsStrategy_logs/full_states_log_*.json | jq '.[] | .final_trade_decision'
```

**Get Latest Trigger Result**:
```bash
ls -lt eval_results/*/trigger_runtime_results/final_result_*.json | head -1
cat eval_results/BTCUSD/trigger_runtime_results/final_result_*.json | jq '.'
```

**Get Trade Submissions**:
```bash
cat trade_memory/virtual_ledger.json | jq '.trades[] | {id, pair, action, amount_usd, status, submitted_at}'
```

**Get Checkpoint Submissions**:
```bash
cat checkpoints.jsonl | jq '{checkpoint: .checkpoint, score: .score, savedAt: .savedAt}'
```

**Get Portfolio Account Summary**:
```python
from tradingagents.portfolio_manager import PortfolioManager
pm = PortfolioManager("./trade_memory/portfolio.db")
summary = pm.get_account_summary()
print(f"Balance: ${summary['cash_usd']:.2f}")
print(f"Realized PnL: ${summary.get('realized_pnl', 0):.2f}")
```

---

## KEY INSIGHTS

1. **Virtual Ledger (JSON)** is the single source of truth for trade tracking
2. **Full Trace (JSONL)** captures every LLM call and graph step for debugging
3. **Full States Log (JSON)** provides comprehensive decision documentation
4. **Portfolio DB (SQLite)** enables historical queries and analytics
5. **Trigger Results (JSON)** captures market context that triggered the decision
6. **Checkpoints (JSONL)** provides immutable audit trail for on-chain integration

All data is human-readable (JSON/JSONL) and organized by trading pair for easy navigation.
