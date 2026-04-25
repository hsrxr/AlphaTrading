import type { ExecutionTrailRecord, RuntimeEvent } from "@/types/trading";

type TraceLoadResult = {
  pair: string;
  events: RuntimeEvent[];
};

type FullStateSnapshot = {
  final_trade_decision?: unknown;
};

type HistoricalLedger = {
  account?: {
    agent_id?: number;
    wallet_address?: string;
  };
  trades?: Array<Record<string, unknown>>;
};

type AgentIdentityRecord = {
  agentId?: number;
  agentWallet?: string;
  registry?: {
    txHash?: string;
    blockNumber?: number;
    timestamp?: string;
  };
  claim?: {
    txHash?: string;
    blockNumber?: number;
    timestamp?: string;
  };
};

const allowedEvents = new Set<RuntimeEvent["event"]>([
  "run_started",
  "node_start",
  "llm_call",
  "llm_token",
  "tool_call",
  "tool_start",
  "tool_end",
  "node_end",
  "run_completed",
  "error",
]);

const toIsoTimestamp = (value: unknown): string => {
  if (typeof value !== "string" || value.length === 0) {
    return new Date().toISOString();
  }

  if (value.includes("T")) {
    return value;
  }

  return value.replace(" ", "T");
};

const getActor = (record: Record<string, unknown>): string => {
  if (typeof record.analyst === "string" && record.analyst.length > 0) {
    return record.analyst;
  }

  if (typeof record.sender === "string" && record.sender.length > 0) {
    return record.sender;
  }

  const nodeName = typeof record.node_name === "string" ? record.node_name : "";
  if (nodeName.toLowerCase().includes("risk")) {
    return "Risk Engine";
  }
  if (nodeName.toLowerCase().includes("trader")) {
    return "Trader";
  }

  if (record.event === "run_started" || record.event === "run_completed") {
    return "System";
  }

  return "Graph";
};

const getDetail = (record: Record<string, unknown>): string => {
  if (record.event === "llm_token") {
    return typeof record.token === "string" ? record.token : "";
  }

  if (record.event === "llm_call") {
    if (typeof record.response === "string" && record.response.length > 0) {
      return record.response;
    }
    if (typeof record.prompt === "string" && record.prompt.length > 0) {
      return record.prompt.slice(0, 600);
    }
    return "llm_call";
  }

  if (record.event === "node_start" || record.event === "node_end") {
    const nodeName = typeof record.node_name === "string" ? record.node_name : "node";
    const duration = typeof record.duration === "number" ? ` (${record.duration.toFixed(2)}s)` : "";
    return `${nodeName}${duration}`;
  }

  if (record.event === "run_started") {
    const metadata = (record.metadata as Record<string, unknown> | undefined) ?? {};
    const company = typeof metadata.company === "string" ? metadata.company : "UNKNOWN";
    return `Trading run started for ${company}`;
  }

  if (record.event === "run_completed") {
    return "Trading run completed";
  }

  if (record.event === "error") {
    return typeof record.error === "string" ? record.error : "runtime error";
  }

  return JSON.stringify(record).slice(0, 600);
};

const normalizeMockTraceActor = (actor: string, path: string): string => {
  if (path.includes("full_trace_time.jsonl") && actor === "Risk Engine") {
    return "Trader";
  }

  return actor;
};

const formatTrailStatus = (trade: Record<string, unknown>): ExecutionTrailRecord["status"] => {
  const feedbackStatus = typeof trade.feedback_status === "string" ? trade.feedback_status.toLowerCase() : "";
  const status = typeof trade.status === "string" ? trade.status.toLowerCase() : "";

  if (feedbackStatus === "timeout") {
    return "Timeout";
  }

  if (status === "submitted") {
    return "Submitted";
  }

  if (status === "rejected") {
    return "Failed";
  }

  if (status === "closed" || status === "filled" || status === "executed") {
    return "Success";
  }

  return "Submitted";
};

const formatTrailSide = (value: unknown): ExecutionTrailRecord["side"] => {
  if (value === "BUY" || value === "SELL") {
    return value;
  }

  return "N/A";
};

export async function loadHistoricalExecutionTrailFromJson(
  ledgerPath: string,
  agentInfoPath: string,
): Promise<ExecutionTrailRecord[]> {
  try {
    const [ledgerResponse, agentResponse] = await Promise.all([
      fetch(ledgerPath, { cache: "no-cache" }),
      fetch(agentInfoPath, { cache: "no-cache" }),
    ]);

    if (!ledgerResponse.ok || !agentResponse.ok) {
      return [];
    }

    const [ledgerData, agentInfoData] = (await Promise.all([
      ledgerResponse.json(),
      agentResponse.json(),
    ])) as [HistoricalLedger, AgentIdentityRecord];

    const trail: ExecutionTrailRecord[] = [];

    if (typeof agentInfoData.registry?.txHash === "string") {
      trail.push({
        id: `registry-${agentInfoData.registry.txHash.slice(0, 12)}`,
        timestamp: agentInfoData.registry.timestamp ?? new Date().toISOString(),
        pair: "SYSTEM",
        side: "N/A",
        notionalUsd: 0,
        status: "Registry",
        venue: "Agent Registry",
        txHash: agentInfoData.registry.txHash,
        note: `Agent ${agentInfoData.agentId ?? ledgerData.account?.agent_id ?? "unknown"} registered on-chain.`,
      });
    }

    if (typeof agentInfoData.claim?.txHash === "string") {
      trail.push({
        id: `claim-${agentInfoData.claim.txHash.slice(0, 12)}`,
        timestamp: agentInfoData.claim.timestamp ?? new Date().toISOString(),
        pair: "SYSTEM",
        side: "N/A",
        notionalUsd: 0,
        status: "Claimed",
        venue: "Agent Registry",
        txHash: agentInfoData.claim.txHash,
        note: `Agent wallet ${agentInfoData.agentWallet ?? "unknown"} claimed the registry entry.`,
      });
    }

    for (const trade of ledgerData.trades ?? []) {
      const submittedAt = typeof trade.submitted_at === "string" ? trade.submitted_at : new Date().toISOString();
      const intentHash = typeof trade.intent_hash === "string" ? trade.intent_hash : `${submittedAt}-${trail.length}`;
      const notes = typeof trade.notes === "string" ? trade.notes : "";
      const feedbackReason = typeof trade.feedback_reason === "string" ? trade.feedback_reason : "";

      trail.push({
        id: typeof trade.id === "string" ? trade.id : `trade-${trail.length}`,
        timestamp: submittedAt,
        pair: typeof trade.pair === "string" ? trade.pair : "UNKNOWN",
        side: formatTrailSide(trade.action),
        notionalUsd: typeof trade.amount_usd === "number" ? trade.amount_usd : 0,
        status: formatTrailStatus(trade),
        venue: "Virtual Ledger",
        txHash: intentHash,
        note: `${notes}${feedbackReason ? ` · ${feedbackReason}` : ""}`,
      });
    }

    return trail.sort((left, right) => Date.parse(left.timestamp) - Date.parse(right.timestamp));
  } catch {
    return [];
  }
}

export async function loadRuntimeEventsFromJsonl(path: string): Promise<TraceLoadResult | null> {
  try {
    const response = await fetch(path, { cache: "no-cache" });
    if (!response.ok) {
      return null;
    }

    const text = await response.text();
    const lines = text.split(/\r?\n/).filter((line) => line.trim().length > 0);
    const events: RuntimeEvent[] = [];
    let pair = "WETH/USDC";

    lines.forEach((line, index) => {
      let parsed: unknown;
      try {
        parsed = JSON.parse(line);
      } catch {
        return;
      }

      if (!parsed || typeof parsed !== "object") {
        return;
      }

      const record = parsed as Record<string, unknown>;
      const eventName = record.event;
      if (typeof eventName !== "string" || !allowedEvents.has(eventName as RuntimeEvent["event"])) {
        return;
      }

      if (eventName === "run_started") {
        const metadata = (record.metadata as Record<string, unknown> | undefined) ?? {};
        if (typeof metadata.company === "string" && metadata.company.length > 0) {
          pair = metadata.company;
        }
      }

      const actor = normalizeMockTraceActor(getActor(record), path);
      const finalTradeDecision = typeof record.final_trade_decision === "string" ? record.final_trade_decision : null;

      events.push({
        id: `trace-${index + 1}`,
        timestamp: toIsoTimestamp(record.timestamp),
        event: eventName as RuntimeEvent["event"],
        actor,
        detail: getDetail(record),
        raw: record,
      });

      if (eventName === "llm_call" && actor === "Trader" && finalTradeDecision) {
        events.push({
          id: `trace-${index + 1}-risk`,
          timestamp: toIsoTimestamp(record.timestamp),
          event: "llm_call",
          actor: "Risk Engine",
          detail: finalTradeDecision,
          raw: {
            event: "llm_call",
            analyst: "Risk Engine",
            response: finalTradeDecision,
            synthetic: true,
          },
        });
      }
    });

    if (events.length === 0) {
      return null;
    }

    return { pair, events };
  } catch {
    return null;
  }
}

export async function loadFinalTradeDecisionFromFullStates(path: string): Promise<string | null> {
  try {
    const response = await fetch(path, { cache: "no-cache" });
    if (!response.ok) {
      return null;
    }

    const payload = (await response.json()) as Record<string, FullStateSnapshot>;
    const firstState = Object.values(payload)[0];
    if (!firstState) {
      return null;
    }

    return typeof firstState.final_trade_decision === "string" ? firstState.final_trade_decision : null;
  } catch {
    return null;
  }
}

export function injectFinalTradeDecisionIntoEvents(
  events: RuntimeEvent[],
  finalTradeDecision: string | null,
): RuntimeEvent[] {
  if (!finalTradeDecision || finalTradeDecision.trim().length === 0) {
    return events;
  }

  const traderCallIndex = [...events]
    .map((event, index) => ({ event, index }))
    .filter((item) => item.event.event === "llm_call" && item.event.actor === "Trader")
    .at(-1)?.index;

  if (traderCallIndex === undefined) {
    return events;
  }

  const updated = [...events];
  const traderEvent = updated[traderCallIndex];
  updated[traderCallIndex] = {
    ...traderEvent,
    raw: {
      ...((traderEvent.raw as Record<string, unknown> | undefined) ?? {}),
      final_trade_decision: finalTradeDecision,
    },
  };

  const alreadyHasRiskDecision = updated.some(
    (event) => event.actor === "Risk Engine" && event.event === "llm_call" && event.detail === finalTradeDecision,
  );

  if (alreadyHasRiskDecision) {
    return updated;
  }

  updated.splice(traderCallIndex + 1, 0, {
    id: `${traderEvent.id}-risk-from-full-state`,
    timestamp: traderEvent.timestamp,
    event: "llm_call",
    actor: "Risk Engine",
    detail: finalTradeDecision,
    raw: {
      event: "llm_call",
      analyst: "Risk Engine",
      response: finalTradeDecision,
      synthetic: true,
      source: "full_states_log",
    },
  });

  return updated;
}
