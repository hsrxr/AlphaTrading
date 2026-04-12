# 交易规模分析：为什么只有 $0.22 per trade？

## 问题概述

虽然虚拟账户有 **$100,000 初始资本**，但所有 39 + 13 = 52 笔交易的规模都被设置为 **$0.22**，导致：

- **总交易金额**: $8.58 (虚拟账户) + $11.44 (trade_history) = $19.99
- **总 PnL 变化**: 仅 $3.76（MtM）相对于初始资本
- **相对回报率**: 0.00376%（虽然盈利率 43.84% 很高）

## 数据证据

```
虚拟账户交易:  39笔 × $0.22 = $8.58 USD
trade_history:  52笔 × $0.22 = $11.44 USD
───────────────────────────────────
虽然盈利率达 56% (WETH)、118% (SOL) 等，但基数太小
最终只产生 $3.7611 利润
```

## 代码追踪：$0.22 从何而来

### 1️⃣ 交易提交流程

```python
# on_chain_integration.py (line 287)
trade_id = self.ledger.submit_trade(
    amount_usd=amount_usd_scaled / 100.0,  # ← $0.22 来自这里
    ...
)

# amount_usd_scaled 的来源 (line 237-239)
if "amountUsdScaled" in trade_intent:
    amount_usd_scaled = int(trade_intent.get("amountUsdScaled", 0))
else:
    amount_usd_scaled = int(float(order.get("notional_usd", 0)) * 100)
```

### 2️⃣ Risk Engine 审批

```python
# risk_engine.py (line 105-155)
requested_amount_usd_scaled = int(trader_intent["amountUsdScaled"])
requested_notional_usd = requested_amount_usd_scaled / 100.0  # 例: 22 / 100 = $0.22

# Risk 计算
max_order_notional = risk_basis * max_single_order_pct  # 10% of available cash
risk_cap_notional = min(max_order_notional, hard_max_trade_usd)  # cap at $500

# 最后批准通常是 min() 操作的结果
approved_notional = min(requested_notional_usd, risk_cap_notional, available_for_buy)
```

### 3️⃣ Trader Agent 的决策

Trader 从分析师和辩论中生成 `trader_investment_plan` JSON，包含：
```json
{
  "action": "BUY",
  "pair": "WETH/USDC",
  "amountUsdScaled": 22,  // ← 这里被设置为 22 ($0.22)
  "confidence": 0.85,
  "reasoning": "..."
}
```

**关键问题**: 为什么 Trader Agent 的 amountUsdScaled 被设置为 22，而不是更大的值？

## 可能的根本原因

### 🔴 原因 1: 测试/演示账户模式
```python
# 如果这是一个演示或测试运行，交易规模可能被意图设置得很小
# 用来展示系统功能而不是实际交易
```

### 🔴 原因 2: Trader Agent Prompt 中的约束
```
Trader 的 system prompt 可能包含对 amountUsdScaled 的约束或建议
例如: "为了安全起见，建议 amountUsdScaled 不超过 100"
```

### 🔴 原因 3: Portfolio Balance 约束
```python
# risk_engine 中
available_for_buy = max(0.0, target_gross_limit - position_usd)
# 如果当前持仓很多或 cash 很少，available_for_buy 会被严格限制
```

## 如何增加交易规模？

### 方案 1: 修改 Trader Agent Prompt 的金额建议

在 `tradingagents/agents/trader/trader.py` 中，调整建议的 amountUsdScaled 范围：

```python
# 从约束:
# "amountUsdScaled should be conservative (< 100 cents = $1)"

# 改为:
# "amountUsdScaled should be 1-5% of portfolio capital"
# 例: $100K × 2% = $2,000, so amountUsdScaled = 200,000
```

### 方案 2: 修改 Risk Engine 的最大订单比例

```python
# risk_engine.py (line 128)
max_single_order_pct = 0.10  # 现在是 10%

# 可改为:
max_single_order_pct = 0.20  # 20% (更激进)
```

### 方案 3: 直接在测试中设置更大的初始交易

如果这确实是演示账户，增加初始 amountUsdScaled：

```python
# 从 22 改为 50000
# 即 $500 per trade (而不是 $0.22)

with open("remotedata/memory/trade_memory/virtual_ledger.json") as f:
    ledger = json.load(f)

for trade in ledger["trades"]:
    trade["amount_usd"] = 500.0  # 改为 $500

json.dump(ledger, open("remotedata/memory/trade_memory/virtual_ledger.json", "w"))
```

### 方案 4: 修改 Portfolio Manager 的初始资本设置

```python
# portfolio_manager.py 中
initial_capital = 100000.0  # 当前设置

# 可以增加到更大值，这样 10% 的单笔订单会更大：
# 虽然不会直接改 amount_usd，但会增加 available_for_buy
```

## 性能影响分析

如果我们将交易规模增加 **100 倍** 从 $0.22 → $22:

| 指标 | 当前 | 增加100倍后 |
|------|------|-----------|
| 单笔交易规模 | $0.22 | $22 |
| 总交易金额 | $8.58 | $858 |
| 56% 盈利率下的增益 | $0.124 | $12.4 |
| 总 PnL (39笔) | $3.76 | $376 |
| **相对初始资本** | **0.0038%** | **0.376%** |

这样虽然相对收益从 0.0038% → 0.376%，但仍然太小。要达到 1% 的回报率，需要：
- 交易金额 × 43.84% 盈利率 = 1%
- 交易金额 = 1% / 43.84% ≈ **2.28% 的初始资本**
- 即 $100K × 2.28% = $2,280 per trade

## 结论

**$0.22 的交易规模极可能是：**

1. ✅ **演示/测试配置** - 用小金额展示系统工作原理
2. ✅ **Trader Agent 保守估计** - LLM 对"安全的交易大小"偏于谨慎
3. ✅ **Risk Engine 限制** - 虽然有 $100K 可用，但最大订单限制在10%，累积头寸40%

**改进建议：**
- 如果这是实盘，应该增加 Trader Agent 的 amountUsdScaled 建议到 2-5% 范围
- 如果这是演示，保持 $0.22 但注明这是测试模式
- 添加配置参数允许用户调整风险偏好和交易规模

---

## 附录：完整 MT-to-M PnL vs 初始资本对比

```
初始资本:           $100,000.00
虚拟账户余额:        $99,991.42 (deducted $8.58)

交易统计:
  虚拟交易:         39 笔 (虚拟账户记录)
  实际交易:         52 笔 (portfolio.db)
  平均规模:         $0.22 per trade

PnL 分析:
  参考价格盈利:      $0.0429   (0.5% BUY, 0.3% SELL 假设)
  Mark-to-Market:   $3.7611   (基于实际价格变动)
  相对初始资本:      0.00376%

按标的盈利能力:
  WETH/USDC:        +56.93% ✅ (18笔, +$2.25)
  ETHUSD:           +55.79% ✅ (8笔, +$0.98)
  SOLUSD:           +117.8%  ✅✅ (3笔, +$0.78)
  BTCUSD:           -11.49%  ❌ (10笔, -$0.25)
  
总体胜率:          94.9% (37/39)
```
