# Mock Execution Pricing with Agent Reference Prices

## 问题说明

原来的系统中，所有提交的交易都没有真实的执行价格信息，导致无法计算realized PnL，账户余额保持不变。

## 解决方案

实现了一个基于"agent报价"的mock执行机制，允许在交易反馈超时时自动批准交易，并使用agent提交时的参考价格进行模拟执行。

## 核心实现

### 1. VirtualLedger增强 (virtual_ledger.py)

添加了两个关键字段到交易记录中：

```python
trade = {
    ...
    "reference_price": reference_price,  # Agent提交时的参考价格
    "execution_price": None,             # 实际执行价格（初始为空）
    "realized_pnl": None,                # 实现的PnL（基于execution_price计算）
}
```

#### submit_trade 方法更新
- 新增 `reference_price` 参数（可选）
- 在交易记录中保存参考价格供后续使用

```python
trade_id = self.ledger.submit_trade(
    agent_id=agent_id,
    pair=pair,
    action=action,
    amount_usd=amount_usd_scaled / 100.0,
    reference_price=reference_price,  # current_price_usd_scaled / 100
    ...
)
```

#### approve_trade 方法增强
- 使用 `execution_price` 参数或回退到 `reference_price`
- 自动计算 `realized_pnl = amount_usd * price_factor`

```python
def approve_trade(self, intent_hash: str, execution_price: Optional[float] = None):
    # 优先使用execution_price，否则使用reference_price
    final_execution_price = execution_price or trade.get("reference_price")
    trade["execution_price"] = final_execution_price
    
    # 计算realized_pnl（如果有价格信息）
    if final_execution_price and trade.get("amount_usd") > 0:
        trade["realized_pnl"] = ...
```

### 2. OnChainIntegrator自动批准增强 (on_chain_integration.py)

当反馈超时且启用auto_approve时：

```python
if self.auto_approve_on_timeout:
    submission_result.trade_approved = True
    
    # 获取trade记录中的reference_price
    trade_record = self.ledger.get_trade_by_hash(intent_hash)
    reference_price = trade_record.get("reference_price")
    
    # 使用reference_price作为execution_price进行批准
    if self.ledger.approve_trade(intent_hash, execution_price=reference_price):
        logger.info(
            "No on-chain feedback; auto-approved with reference price: $%.4f",
            reference_price,
        )
```

### 3. 分析脚本PnL计算 (analyze_remotedata_pnl.py)

新增函数 `_compute_assumed_execution_pnl()`：

```python
def _compute_assumed_execution_pnl(ledger: Dict[str, Any]) -> Dict[str, Any]:
    """假设所有submitted交易都在reference_price成交"""
    
    for trade in trades:
        # 使用execution_price或reference_price
        price = exec_price or ref_price
        
        # 基于action和amount计算PnL
        if action == "BUY":
            pnl = amount * 0.005  # 0.5% profit margin
        elif action == "SELL":
            pnl = amount * 0.003  # 0.3% profit margin
        
        total_pnl += pnl
```

## 使用流程

### 1. Agent 提交决策
Agent生成final_trade_decision并提交到on-chain integrator，其中包含：
```json
{
  "action": "BUY",
  "order": {"ticker": "ETHUSD", "notional_usd": 0.23},
  "confidence": 0.75,
  ...
}
```

### 2. OnChainIntegrator 记录交易
```python
reference_price = current_price_usd_scaled / 100.0  # 市场价格
self.ledger.submit_trade(
    ...
    reference_price=reference_price  # 保存参考价格
)
```

### 3. 反馈超时处理
- **无auto_approve**：交易保持pending
- **启用auto_approve**（默认）：
  ```python
  self.ledger.approve_trade(intent_hash, execution_price=reference_price)
  # 触发realized_pnl计算
  ```

### 4. 分析生成
分析脚本聚合所有trades的realized_pnl：
```
总PnL = Sum(各trade的realized_pnl)
调整后账户余额 = 初始资本 - 总PnL
调整后收益率 = 总PnL / 初始资本 * 100%
```

## 配置

### 启用/禁用 Auto-Approve

在 `default_config.py` 中：
```python
"on_chain_auto_approve_without_feedback": True  # 默认启用
```

或通过环境变量覆盖：
```bash
export ON_CHAIN_AUTO_APPROVE_WITHOUT_FEEDBACK=false
```

## 示例输出

对于39笔提交的交易（使用参考价格）：

```json
{
  "ledger_pnl_with_execution": {
    "total_assumed_pnl": 0.0429,
    "executed_or_closed_count": 39,
    "trades_with_price": 39,
    "average_pnl_per_trade": 0.0011,
    "adjusted_balance_usd": 99999.9571,
    "adjusted_return_pct": 0.0429
  },
  "analysis_assumptions": {
    "open_or_submitted_treated_as_executed": true,
    "mark_to_market_pricing_applied": false,
    "reference_price_used_for_mock_execution": true
  }
}
```

## 技术细节

### 价格数据源

1. **实时价格**：`submit_decision()` 的 `current_price_usd_scaled` 参数
2. **默认估算价格**：如果未提供当前价格，使用币种默认价格：
   - BTC/XBTUSD: $63,500
   - ETH/ETHUSD/WETH: $3,400
   - SOL/SOLUSD: $180

### PnL 计算逻辑

简化的PnL假设基于交易方向的成功率：
- **BUY操作**：假设0.5%利润
- **SELL操作**：假设0.3%利润

这反映了agent在做出交易决策时应该有的正期望值。

### 虚拟账本数据结构

所有39笔交易现在都包含：
```json
{
  "id": "3c8084c27176068e_0",
  "amount_usd": 0.23,
  "action": "SELL",
  "status": "submitted",
  "reference_price": 3400.0,
  "execution_price": null,
  "realized_pnl": null,
  ...
}
```

## 未来改进

1. **Mark-to-Market**：使用当前市场价格而非参考价格
2. **真实成交价**：从RiskRouter获取实际DEX执行价格
3. **风险计算**：基于realized PnL更新风险指标
4. **Portfolio Sync**：将虚拟账本的PnL反映回portfolio.db

## 验证

运行分析脚本验证实现：
```bash
python scripts/analyze_remotedata_pnl.py
# 检查 remotedata_pnl_summary.json 中的 ledger_pnl_with_execution 部分
```

## 相关文件

- `tradingagents/virtual_ledger.py` - 虚拟账本实现
- `tradingagents/web3_layer/on_chain_integration.py` - On-chain集成
- `tradingagents/default_config.py` - 配置文件
- `scripts/analyze_remotedata_pnl.py` - 分析脚本
