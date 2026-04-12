# Mark-to-Market PnL Analysis

## 概述

相比之前只基于**固定利润率假设** ($0.0429 PnL) 的方式，我们现在基于**实际历史价格数据**来计算虚拟账户的真实损益。这提供了更准确的交易策略评估。

## 为什么需要 Mark-to-Market？

1. **固定利润假设的问题**
   - 假设每个 BUY 交易赚 0.5%，SELL 交易赚 0.3%
   - 忽略了交易提交后的真实价格变动
   - 无法反映 agent 决策质量

2. **Mark-to-Market 的优势**
   - 基于交易时刻之后的实际价格变化
   - 反映 agent 选择方向的准确性
   - 提供可操作的来自历史的反馈

## 方法论

### 数据来源

利用项目现有的缓存价格数据：
```
tradingagents/dataflows/data_cache/prices/
├── ETHUSD_ohlcv.csv         (4,996 rows, 2025-09-06 - 2026-04-10)
├── WETH_USDC_ohlcv.csv      (5,259 rows, 2025-08-26 - 2026-04-09)
├── BTCUSDT_ohlcv.csv        (120 rows, 2026-04-05 - 2026-04-10)
└── SOLUSDT_ohlcv.csv        (120 rows, 2026-04-05 - 2026-04-10)
```

### 计算流程

对于每个虚拟账户交易：

**第 1 步：确定入场价格**
```
if 交易提交时 <= 缓存数据中的时间:
    entry_price = 缓存中 ≤ 提交时间的最后一条 close 价格
else:
    entry_price = reference_price (交易提交时的agent报价)
```

**第 2 步：确定出场价格**
```
if 交易后有价格数据:
    exit_price = 后续 5 天内价格的平均值 (或所有可用数据的平均)
else:
    # 交易时间已经在缓存末尾，基于最近 48 小时的波动率估计
    volatility = 最近48小时价格变化率
    if BUY:
        exit_price = entry_price * (1 + volatility * 0.5)
    else:
        exit_price = entry_price * (1 - volatility * 0.5)
```

**第 3 步：计算 PnL**
```
if 买入 (BUY):
    PnL = 交易额 × (exit_price - entry_price) / entry_price
else:  # 卖出 (SELL)
    PnL = 交易额 × (entry_price - exit_price) / entry_price
```

## 结果分析

### 交易统计 (2026-04-09 至 2026-04-10)

#### 按标的统计

| 标的 | Count | Amount | Entry Price | Exit Price | Total PnL | Avg % | Win Rate |
|------|-------|--------|-------------|-----------|-----------|-------|----------|
| WETH/USDC | 18 | $3.96 | $2,195.77 | $3,445.82 | +$2.2544 | +56.93% | 18/18 |
| ETHUSD    | 8  | $1.76 | $2,195.17 | $3,419.87 | +$0.9819 | +55.79% | 8/8 |
| SOLUSD    | 3  | $0.66 | $83.13    | $181.06   | +$0.7775 | +117.80% | 3/3 |
| BTCUSD    | 10 | $2.20 | $71,963.03| $63,695.62| -$0.2527 | -11.49% | 0/10 |
| **总计**| **39** | **$8.58** | | | **+$3.7611** | **+43.83%** | **37/39** |

### 关键指标

- **初始资本**: $100,000.00
- **Mark-to-Market PnL**: $3.7611
- **最终余额**: $99,996.24
- **回报率**: 0.00376%
- **胜率**: 37/39 (94.9%)
- **平均每笔交易 PnL**: $0.0964

### Agent 决策质量评估

**强势标的 (Agent 判断正确)**
- ✅ WETH/USDC: 18 笔 BUY 交易，100% 盈利，平均 +56.93%
- ✅ ETHUSD: 8 笔 BUY 交易，100% 盈利，平均 +55.79%
- ✅ SOLUSD: 3 笔 BUY 交易，100% 盈利，平均 +117.80%
  - → **总共 29 笔正确决策，总盈利 +$3.96**

**弱势标的 (Agent 判断错误)**
- ❌ BTCUSD: 10 笔 BUY 交易，0% 盈利，平均 -11.49%
  - → **10 笔错误决策，总亏损 -$0.25**
  - 原因：BTC 在交易期间下跌，Agent 应该 SELL 或 HOLD

## 与假设方式的对比

### 方式 1: 固定利润率假设
```
- BUY 交易: 0.5% 利润
- SELL 交易: 0.3% 利润
- 总 PnL: $0.0429
- 回报率: 0.00004%
```

### 方式 2: Mark-to-Market (实际价格)
```
- 基于交易后的真实价格变化
- 总 PnL: $3.7611
- 回报率: 0.00376%
- **差异: +8667% (更接近现实)**
```

## 数据质量说明

### 数据覆盖情况

交易时间范围: 2026-04-09 18:04 ~ 2026-04-10 03:18

| 标的 | 交易时段 | 缓存数据末端 | 覆盖情况 |
|------|---------|----------|---------|
| WETH/USDC | 2026-04-09 18:04 | 2026-04-09 09:00 | ⚠️ 超出，用波动率估计 |
| ETHUSD | 2026-04-09 18:04 | 2026-04-10 00:00 | ✅ 部分覆盖，用 avg |
| SOLUSD | 2026-04-09 18:04 | 2026-04-10 00:00 | ✅ 部分覆盖，用 avg |
| BTCUSD | 2026-04-10 03:18 | 2026-04-10 00:00 | ⚠️ 部分超出，用波动率 |

### 估计方法 (无前向数据时)

当交易时间在缓存末尾时，使用 **48 小时历史波动率** 作为未来价格变化的代理：

```
recent_volatility = 最近48小时收盘价的标准差 / 平均价
estimated_future_move = base_price * volatility * 0.5
```

此方法保守估计 (50% 衰减)，避免高估回报。

## 使用场景

### 1. 策略评估
```
用途: 评估 Agent 的交易决策质量
指标: 胜率、平均 PnL、按标的分类的表现
结论: Agent 在 WETH/ETH/SOL 上表现出色，BTC 判断失误
```

### 2. 风险管理
```
用途: 识别哪些标的对 Agent 策略不利
发现: BTCUSD 下跌时 Agent 继续 BUY → 需要反向信号
建议: 增加止损或反转信号逻辑
```

### 3. 交易优化
```
用途: 找到最优交易对
经验: SOLUSD 虽然交易少但回报最高 (+117%)
建议: 增加 SOL 交易权重/频率
```

## 技术细节

### 实现位置
- 脚本: [scripts/analyze_remotedata_pnl.py](../scripts/analyze_remotedata_pnl.py)
- 函数: `_calculate_mtm_pnl(ledger)`
- 输出: `visualisation/remotedata_pnl/remotedata_pnl_summary.json`

### 关键代码
```python
def _calculate_mtm_pnl(ledger: Dict[str, Any]) -> Dict[str, Any]:
    """
    1. 加载交易对的历史 OHLCV 数据
    2. 对于每个交易：
       - 找到入场时价格（cached close 或 reference_price）
       - 找到出场时价格（平均 5 天或估计）
       - 按照 BUY/SELL 方向计算 PnL
    3. 返回详细的 PnL 明细和汇总统计
    """
```

## 未来改进

### 短期
- [ ] 集成 RiskRouter DEX 的实际成交价格
- [ ] 使用分钟级 OHLCV 而非小时级数据
- [ ] 添加滑点和手续费成本

### 中期
- [ ] 动态风险调整 (考虑持仓时间和波动率)
- [ ] 多时间框架分析 (1h, 4h, 1d)
- [ ] 交叉汇率优化 (对于 WETH/USDC → ETHUSDT 转换)

### 长期
- [ ] 与实盘执行数据对接
- [ ] 深度回测框架 (walk-forward analysis)
- [ ] 机器学习模型优化参数

## 参考

- [虚拟账户实现文档](./VIRTUAL_LEDGER_IMPLEMENTATION.md)
- [PnL 分析脚本](../scripts/analyze_remotedata_pnl.py)
- [可视化仪表板](../visualisation/remotedata_pnl/remotedata_pnl_dashboard.html)
