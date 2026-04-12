import type {
  AgentProcessMessage,
  AgentStateMessage,
  ExecutionTrailRecord,
  RiskAlert,
  PricePoint,
  RuntimeEvent,
  TradeExecutionMarker,
  TradeRecord,
  TradingDashboardSnapshot,
} from "@/types/trading";

const baseTime = new Date("2026-04-12T10:36:08Z").getTime();

const makeTs = (minuteOffset: number): string =>
  new Date(baseTime + minuteOffset * 60_000).toISOString();

export const mockPriceSeries: PricePoint[] = [
  { timestamp: makeTs(0), price: 2213.01, volume: 1840 },
  { timestamp: makeTs(1), price: 2211.42, volume: 2012 },
  { timestamp: makeTs(2), price: 2208.95, volume: 2238 },
  { timestamp: makeTs(3), price: 2206.72, volume: 2414 },
  { timestamp: makeTs(4), price: 2205.17, volume: 2575 },
  { timestamp: makeTs(5), price: 2203.44, volume: 2198 },
  { timestamp: makeTs(6), price: 2201.26, volume: 2681 },
  { timestamp: makeTs(7), price: 2198.8, volume: 2942 },
  { timestamp: makeTs(8), price: 2196.53, volume: 2634 },
  { timestamp: makeTs(9), price: 2194.24, volume: 3078 },
  { timestamp: makeTs(10), price: 2192.05, volume: 2816 },
  { timestamp: makeTs(11), price: 2190.63, volume: 3150 },
  { timestamp: makeTs(12), price: 2189.42, volume: 3321 },
  { timestamp: makeTs(13), price: 2188.11, volume: 3011 },
  { timestamp: makeTs(14), price: 2186.93, volume: 3458 },
  { timestamp: makeTs(15), price: 2185.9, volume: 3366 },
];

export const mockExecutionMarkers: TradeExecutionMarker[] = [
  { id: "exec-1", timestamp: makeTs(0), side: "SELL", price: 2213.01 },
];

export const mockAgentFeed: AgentStateMessage[] = [
  {
    id: "feed-1",
    timestamp: makeTs(2),
    agent: "Market Analyst",
    tone: "neutral",
    summary: "Market report: momentum fatigue after the run-up, but broader structure stays above 50/200 SMA.",
    confidence: 0.74,
  },
  {
    id: "feed-2-news",
    timestamp: makeTs(3),
    agent: "News Analyst",
    tone: "neutral",
    summary: "News report highlights ceasefire shock and Morgan Stanley ETF launch as primary short-horizon catalysts.",
    confidence: 0.79,
  },
  {
    id: "feed-2-quant",
    timestamp: makeTs(3),
    agent: "Quant Analyst",
    tone: "neutral",
    summary: "Quant report shows blended LONG with conflict from GTJA_191 max-strength SHORT mean-reversion pressure.",
    confidence: 0.77,
  },
  {
    id: "feed-3",
    timestamp: makeTs(5),
    agent: "Bull Researcher",
    tone: "bullish",
    summary: "Bull case: ETF launch plus structural support favors continuation after consolidation.",
    confidence: 0.81,
  },
  {
    id: "feed-4",
    timestamp: makeTs(5),
    agent: "Bear Researcher",
    tone: "bearish",
    summary: "Bear case: momentum crossover and resistance rejection suggest pullback before continuation.",
    confidence: 0.63,
  },
  {
    id: "feed-5",
    timestamp: makeTs(7),
    agent: "Trader",
    tone: "execution",
    summary: "Trader outputs final JSON intent and chooses HOLD due to conflicted signal quality.",
    confidence: 0.96,
  },
  {
    id: "feed-6",
    timestamp: makeTs(8),
    agent: "Risk Engine",
    tone: "risk",
    summary: "Risk engine validates TradeIntent and enforces max_single_order_pct and drawdown constraints.",
    confidence: 0.88,
  },
];

export const mockAgentProcessFeed: AgentProcessMessage[] = [
  {
    id: "proc-1",
    timestamp: makeTs(2),
    agent: "Market Analyst",
    stage: "thought",
    title: "Market Structure Check",
    content: "Excerpted from full_states_log: momentum weakens after the squeeze, but macro trend remains above key moving averages.",
  },
  {
    id: "proc-2-news",
    timestamp: makeTs(3),
    agent: "News Analyst",
    stage: "thought",
    title: "News Catalyst Scan",
    content: "Excerpted from full_states_log: ceasefire relief and Morgan Stanley ETF launch dominate the next 6-24h narrative.",
  },
  {
    id: "proc-2-quant",
    timestamp: makeTs(3),
    agent: "Quant Analyst",
    stage: "thought",
    title: "Quant Blend",
    content: "Excerpted from full_states_log: blended LONG signal with a strong conflicting mean-reversion SHORT factor.",
  },
  {
    id: "proc-3",
    timestamp: makeTs(5),
    agent: "Bull Researcher",
    stage: "thought",
    title: "Bull Thesis",
    content: "Bull response excerpt: catalyst-driven continuation is favored if price reclaims resistance with volume.",
  },
  {
    id: "proc-4",
    timestamp: makeTs(5),
    agent: "Bear Researcher",
    stage: "thought",
    title: "Bear Counterpoint",
    content: "Bear response excerpt: overextension and MACD crossover argue for corrective pullback before trend continuation.",
  },
  {
    id: "proc-5",
    timestamp: makeTs(7),
    agent: "Trader",
    stage: "output",
    title: "Trader Decision",
    content: "Trader outputs TradeIntent JSON with HOLD action due to conflict between qualitative and quantitative drivers.",
  },
  {
    id: "proc-6",
    timestamp: makeTs(8),
    agent: "Risk Engine",
    stage: "output",
    title: "Risk Validation",
    content: "Risk engine finalizes constraints and confirms capped order shape with max_single_order_pct and drawdown checks.",
  },
];

export const mockRuntimeEvents: RuntimeEvent[] = [
  {
    id: "evt-1",
    timestamp: makeTs(0),
    event: "run_started",
    actor: "System",
    detail: "Trading run started for ETHUSD with multi-agent parallel mode.",
  },
  {
    id: "evt-2",
    timestamp: makeTs(1),
    event: "node_start",
    actor: "Graph",
    detail: "Node started: Trading analysis bootstrap state.",
  },
  {
    id: "evt-market-token-1",
    timestamp: makeTs(2),
    event: "llm_token",
    actor: "Market Analyst",
    detail: "Now I have a complete picture. Let me compile the hourly trading analysis for XBTUSD... ",
  },
  {
    id: "evt-market-token-2",
    timestamp: makeTs(2),
    event: "llm_token",
    actor: "Market Analyst",
    detail: "MACD just crossed bearish, RSI rolled down from overbought, but price still trades above 50-SMA and 200-SMA... ",
  },
  {
    id: "evt-market-token-3",
    timestamp: makeTs(2),
    event: "llm_token",
    actor: "Market Analyst",
    detail: "Key zones remain 71,800-71,955 resistance and 70,800 support with 69,730 as strong downside magnet.",
  },
  {
    id: "evt-news-token-1",
    timestamp: makeTs(2),
    event: "llm_token",
    actor: "News Analyst",
    detail: "Now let me analyze these key stories and provide a comprehensive trading impact analysis for XBTUSD... ",
  },
  {
    id: "evt-news-token-2",
    timestamp: makeTs(2),
    event: "llm_token",
    actor: "News Analyst",
    detail: "Primary catalysts are the Iran ceasefire shock and Morgan Stanley ETF launch; both can move positioning in the next 6-24h... ",
  },
  {
    id: "evt-news-token-3",
    timestamp: makeTs(2),
    event: "llm_token",
    actor: "News Analyst",
    detail: "Need to balance bullish flow narrative against temporary-ceasefire fragility and resistance at 76k.",
  },
  {
    id: "evt-quant-token-1",
    timestamp: makeTs(2),
    event: "llm_token",
    actor: "Quant Analyst",
    detail: "Now I have the built-in quant signals. Let me analyze them and provide the required output... ",
  },
  {
    id: "evt-quant-token-2",
    timestamp: makeTs(2),
    event: "llm_token",
    actor: "Quant Analyst",
    detail: "alpha101 factors lean LONG while gtja_191 is max-strength SHORT, which is a classic conflict between momentum and mean reversion... ",
  },
  {
    id: "evt-quant-token-3",
    timestamp: makeTs(2),
    event: "llm_token",
    actor: "Quant Analyst",
    detail: "Blended output stays LONG but confidence should be haircut due to cross-factor disagreement.",
  },
  {
    id: "evt-market-call",
    timestamp: makeTs(3),
    event: "llm_call",
    actor: "Market Analyst",
    detail:
      "## Hourly Trading Analysis (excerpt from full_states_log)\n\n"
      + "- Trend: primary bullish, short-term momentum fatigue\n"
      + "- MACD crossed below signal, histogram turned negative\n"
      + "- RSI cooled from overbought, allowing either pullback or range\n"
      + "- Immediate resistance: 71,800-71,955\n"
      + "- Key support: 70,800, then 69,730 (50-SMA)\n\n"
      + "**Execution implication**: wait for confirmation break above 71,800 or breakdown below 70,800 before directional commitment.",
  },
  {
    id: "evt-news-call",
    timestamp: makeTs(3),
    event: "llm_call",
    actor: "News Analyst",
    detail:
      "## News Catalyst Map (excerpt from full_states_log)\n\n"
      + "1. US-Iran ceasefire headline drove a risk-on repricing and short squeeze.\n"
      + "2. Morgan Stanley ETF launch is an institutional flow catalyst in-session.\n"
      + "3. Structural BTC accumulation between 60k-70k supports dip demand.\n\n"
      + "**6-24h read**: bullish catalyst stack is real, but headline half-life and resistance rejection risk remain active.",
  },
  {
    id: "evt-quant-call",
    timestamp: makeTs(3),
    event: "llm_call",
    actor: "Quant Analyst",
    detail:
      "## Quant Strategy Signal Report (excerpt from full_states_log)\n\n"
      + "- alpha101_12: LONG (weak)\n"
      + "- alpha101_2_variant: LONG (moderate)\n"
      + "- gtja_191_variant: SHORT (max strength)\n\n"
      + "**Blended quant view**: LONG(1.0), with explicit warning that mean-reversion pressure can cause pullbacks before continuation.",
  },
  {
    id: "evt-bull-token-1",
    timestamp: makeTs(5),
    event: "llm_token",
    actor: "Bull Researcher",
    detail: "Bull Analyst drafting thesis: catalyst-driven continuation remains valid if price closes back above 71,800... ",
  },
  {
    id: "evt-bull-token-2",
    timestamp: makeTs(5),
    event: "llm_token",
    actor: "Bull Researcher",
    detail: "Institutional flow narrative plus accumulation shelf argues against aggressive downside extrapolation... ",
  },
  {
    id: "evt-bull-token-3",
    timestamp: makeTs(5),
    event: "llm_token",
    actor: "Bull Researcher",
    detail: "Invalidation remains strict below 70,500.",
  },
  {
    id: "evt-bear-token-1",
    timestamp: makeTs(5),
    event: "llm_token",
    actor: "Bear Researcher",
    detail: "Bear Analyst drafting thesis: exhaustion after short squeeze raises pullback probability toward 69,730 support... ",
  },
  {
    id: "evt-bear-token-2",
    timestamp: makeTs(5),
    event: "llm_token",
    actor: "Bear Researcher",
    detail: "MACD rollover plus resistance rejection implies upside continuation needs fresh confirmation... ",
  },
  {
    id: "evt-bear-token-3",
    timestamp: makeTs(5),
    event: "llm_token",
    actor: "Bear Researcher",
    detail: "Invalidation remains strict above 72,000 with momentum re-acceleration.",
  },
  {
    id: "evt-bull-call",
    timestamp: makeTs(6),
    event: "llm_call",
    actor: "Bull Researcher",
    detail:
      "## Bull Rebuttal (excerpt from full_states_log)\n\n"
      + "- ETF launch is a live catalyst, not just a stale headline.\n"
      + "- Strong accumulation zone reduces deep downside probability.\n"
      + "- First MACD fatigue after squeeze often resolves via consolidation, not immediate reversal.\n\n"
      + "**Trade framing**: continuation trigger above 71,800; invalidate below 70,500.",
  },
  {
    id: "evt-bear-call",
    timestamp: makeTs(6),
    event: "llm_call",
    actor: "Bear Researcher",
    detail:
      "## Bear Rebuttal (excerpt from full_states_log)\n\n"
      + "- Post-squeeze momentum deterioration is visible in MACD and resistance behavior.\n"
      + "- Max-strength mean-reversion signal should not be ignored for 6-24h horizon.\n"
      + "- If 71,800 reclaim fails and 70,800 breaks, pullback toward 69,730 becomes the base path.\n\n"
      + "**Risk framing**: invalidate bearish exhaustion thesis only if price reclaims 72,000 with positive momentum.",
  },
  {
    id: "evt-trader-token-1",
    timestamp: makeTs(7),
    event: "llm_token",
    actor: "Trader",
    detail: "Trader is consolidating market/news/quant/research reports and preparing strict TradeIntent JSON output... ",
  },
  {
    id: "evt-trader-token-2",
    timestamp: makeTs(7),
    event: "llm_token",
    actor: "Trader",
    detail: "Signal conflict remains high; portfolio context favors conservative action over directional overreach... ",
  },
  {
    id: "evt-trader-token-3",
    timestamp: makeTs(7),
    event: "llm_token",
    actor: "Trader",
    detail: "Formatting final TradeIntent payload.",
  },
  {
    id: "evt-trader-call",
    timestamp: makeTs(7),
    event: "llm_call",
    actor: "Trader",
    detail:
      "## Trader Output (excerpt from full_states_log)\n\n"
      + "```json\n"
      + "{\n"
      + "  \"agentId\": 40,\n"
      + "  \"pair\": \"ETHUSD\",\n"
      + "  \"action\": \"SELL\",\n"
      + "  \"amountUsdScaled\": 226,\n"
      + "  \"maxSlippageBps\": 100\n"
      + "}\n"
      + "```\n\n"
      + "Reasoning: bearish momentum and risk reduction with full ETH long exposure.",
  },
  {
    id: "evt-risk-token-1",
    timestamp: makeTs(8),
    event: "llm_token",
    actor: "Risk Engine",
    detail: "Risk engine validating TradeIntent against drawdown and position constraints... ",
  },
  {
    id: "evt-risk-token-2",
    timestamp: makeTs(8),
    event: "llm_token",
    actor: "Risk Engine",
    detail: "Applying max_single_order_pct and hard_max_trade_usd caps; checking risk_status semantics... ",
  },
  {
    id: "evt-risk-token-3",
    timestamp: makeTs(8),
    event: "llm_token",
    actor: "Risk Engine",
    detail: "Composing final constrained order output.",
  },
  {
    id: "evt-risk-call",
    timestamp: makeTs(8),
    event: "llm_call",
    actor: "Risk Engine",
    detail:
      "## Risk Decision (excerpt from full_states_log)\n\n"
      + "- risk_status: `allowed`\n"
      + "- max_single_order_pct: `0.1`\n"
      + "- hard_max_trade_usd: `null`\n"
      + "- requested_notional_usd: `2.26`\n\n"
      + "Final note: TradeIntent validated and capped under drawdown, position, and per-trade notional constraints.",
  },
  {
    id: "evt-8",
    timestamp: makeTs(15),
    event: "run_completed",
    actor: "System",
    detail: "Trading run completed; portfolio metrics, trade history, and risk feedback persisted.",
  },
];

export const mockTrades: TradeRecord[] = [
  {
    id: "trade-1",
    side: "SELL",
    timestamp: makeTs(0),
    pair: "ETHUSD",
    quantity: 0.001,
    price: 2213.01,
    reason: "Risk engine final intent execution from latest test: SELL 226 cents ($2.26).",
  },
];

export const mockRiskAlerts: RiskAlert[] = [
  {
    id: "risk-2",
    timestamp: makeTs(12),
    severity: "info",
    source: "Risk Engine",
    message: "Risk check passed for latest replayed intent.",
  },
];

export const mockExecutionTrail: ExecutionTrailRecord[] = [
  {
    id: "exec-trace-1",
    timestamp: makeTs(0),
    pair: "ETHUSD",
    side: "SELL",
    notionalUsd: 2.26,
    status: "Submitted",
    venue: "AlphaAgenting Runtime",
    txHash: "0xdraftf31d8a0e7c4b9b8a1c1d2e3f4a5b6c7d8e9f001",
    note: "Trader emitted the initial TradeIntent from the consensus node.",
  },
  {
    id: "exec-trace-2",
    timestamp: makeTs(1),
    pair: "ETHUSD",
    side: "SELL",
    notionalUsd: 2.26,
    status: "Submitted",
    venue: "Risk Engine",
    txHash: "0xrisk7c3f2c2d9c8b5a1f4e6d7c8b9a0f1e2d3c4b5a6",
    note: "Validated final trade_intent and preserved per-order risk constraints.",
  },
  {
    id: "exec-trace-3",
    timestamp: makeTs(2),
    pair: "ETHUSD",
    side: "SELL",
    notionalUsd: 2.26,
    status: "Timeout",
    venue: "Sepolia ERC-8004",
    txHash: "0xpendingaf4b2c1d0e9f8a7b6c5d4e3f2a1b0c9d8e7f6",
    note: "Submitted for on-chain validation and awaiting settlement confirmation.",
  },
  {
    id: "exec-trace-4",
    timestamp: makeTs(3),
    pair: "ETHUSD",
    side: "SELL",
    notionalUsd: 2.26,
    status: "Success",
    venue: "Sepolia ERC-8004",
    txHash: "0xsuccce55a12b3c4d5e6f7a8b9c0d1e2f3a4b5c6d7",
    note: "Receipt confirmed and the runtime trace was written back to the dashboard.",
  },
];

export const mockDashboardSnapshot: TradingDashboardSnapshot = {
  pair: "ETHUSD",
  metrics: {
    timestamp: makeTs(15),
    portfolioValue: 2.167678,
    pnl: -0.032322,
    drawdownPct: -1.469168,
    riskExposure: 1,
    status: "degraded",
  },
  priceSeries: mockPriceSeries,
  agentFeed: mockAgentFeed,
  agentProcessFeed: mockAgentProcessFeed,
  runtimeEvents: mockRuntimeEvents,
  trades: mockTrades,
  riskAlerts: mockRiskAlerts,
  executionTrail: mockExecutionTrail,
  executionMarkers: mockExecutionMarkers,
};
