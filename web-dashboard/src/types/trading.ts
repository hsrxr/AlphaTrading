export type AgentName =
  | "Market Analyst"
  | "News Analyst"
  | "Quant Analyst"
  | "Bull Researcher"
  | "Bear Researcher"
  | "Risk Engine"
  | "Trader"
  | "System"
  | "Unknown";

export type TradeSide = "BUY" | "SELL";
export type AgentTone = "bullish" | "bearish" | "neutral" | "risk" | "execution";

export interface PortfolioMetrics {
  timestamp: string;
  portfolioValue: number;
  pnl: number;
  drawdownPct: number;
  riskExposure: number;
  status: "running" | "degraded" | "halted";
}

export interface PricePoint {
  timestamp: string;
  price: number;
  volume: number;
}

export interface AgentStateMessage {
  id: string;
  timestamp: string;
  agent: AgentName;
  tone: AgentTone;
  summary: string;
  confidence: number;
}

export interface AgentProcessMessage {
  id: string;
  timestamp: string;
  agent: AgentName;
  stage: "thought" | "tool" | "output";
  title: string;
  content: string;
}

export interface RuntimeEvent {
  id: string;
  timestamp: string;
  event:
    | "run_started"
    | "node_start"
    | "llm_call"
    | "llm_token"
    | "tool_call"
    | "tool_start"
    | "tool_end"
    | "node_end"
    | "run_completed"
    | "error";
  actor: string;
  detail: string;
  raw?: Record<string, unknown>;
}

export interface TradeRecord {
  id: string;
  timestamp: string;
  pair: string;
  side: TradeSide;
  quantity: number;
  price: number;
  reason: string;
}

export interface RiskAlert {
  id: string;
  timestamp: string;
  severity: "info" | "warning" | "critical";
  source: string;
  message: string;
}

export interface ExecutionTrailRecord {
  id: string;
  timestamp: string;
  pair: string;
  side: TradeSide | "N/A";
  notionalUsd: number;
  status: "Registry" | "Claimed" | "Submitted" | "Timeout" | "Failed" | "Success";
  venue: string;
  txHash: string;
  note: string;
}

export interface TradeExecutionMarker {
  id: string;
  timestamp: string;
  side: TradeSide;
  price: number;
}

export interface TradingDashboardSnapshot {
  pair: string;
  metrics: PortfolioMetrics;
  priceSeries: PricePoint[];
  agentFeed: AgentStateMessage[];
  agentProcessFeed: AgentProcessMessage[];
  runtimeEvents: RuntimeEvent[];
  trades: TradeRecord[];
  riskAlerts: RiskAlert[];
  executionTrail: ExecutionTrailRecord[];
  executionMarkers: TradeExecutionMarker[];
}
