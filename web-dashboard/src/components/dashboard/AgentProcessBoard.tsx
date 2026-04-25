import { useEffect, useMemo, useRef } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";

import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { ScrollArea } from "@/components/ui/scroll-area";
import { useDashboardStore } from "@/store/dashboardStore";
import type { RuntimeEvent } from "@/types/trading";

const analystActors = ["Market Analyst", "News Analyst", "Quant Analyst"];
const analystActorSet = new Set(analystActors);

const analystBorderMap: Record<string, string> = {
  "Market Analyst": "border-cyan-500/30",
  "News Analyst": "border-emerald-500/30",
  "Quant Analyst": "border-violet-500/30",
  "Bull Researcher": "border-amber-500/30",
  "Bear Researcher": "border-rose-500/30",
};

const parallelResearchActors = ["Bull Researcher", "Bear Researcher"];
const serialDownstreamOrder = ["Trader", "Risk Engine", "System", "Unknown"];

const eventDisplayAllowlist = new Set(["llm_call", "llm_token", "tool_call", "tool_start", "tool_end", "node_start", "node_end", "error"]);

const isAnalystToken = (item: RuntimeEvent): boolean => item.event === "llm_token" && analystActorSet.has(item.actor);

type ConversationSession = {
  id: string;
  startedAt: string;
  thinkingText: string;
  hasResult: boolean;
  events: RuntimeEvent[];
};

type ToolCallInfo = {
  id: string;
  name: string;
  args: string;
};

function StreamingText({ text, className }: { text: string; className?: string }): React.JSX.Element {
  return (
    <div className={className}>
      <ReactMarkdown remarkPlugins={[remarkGfm]}>{text}</ReactMarkdown>
    </div>
  );
}

function normalizeActorName(value: string): string {
  const text = value.toLowerCase();
  if (text.includes("market")) return "Market Analyst";
  if (text.includes("news")) return "News Analyst";
  if (text.includes("quant")) return "Quant Analyst";
  if (text.includes("bull")) return "Bull Researcher";
  if (text.includes("bear")) return "Bear Researcher";
  if (text.includes("risk")) return "Risk Engine";
  if (text.includes("trade")) return "Trader";
  if (text.includes("system")) return "System";
  return value;
}

function reassignToolEvents(events: RuntimeEvent[]): RuntimeEvent[] {
  const activeByLane: Record<string, string | null> = {
    analyst: null,
    research: null,
    serial: null,
  };

  const laneOfActor = (actor: string): "analyst" | "research" | "serial" => {
    if (analystActors.includes(actor)) return "analyst";
    if (parallelResearchActors.includes(actor)) return "research";
    return "serial";
  };

  return events.map((rawEvent) => {
    const event = { ...rawEvent, actor: normalizeActorName(rawEvent.actor) };
    const isToolEvent = event.event === "tool_start" || event.event === "tool_end";

    if (!isToolEvent) {
      if (event.event === "llm_call" || event.event === "llm_token" || event.event === "node_start") {
        const lane = laneOfActor(event.actor);
        activeByLane[lane] = event.actor;
      }
      return event;
    }

    const explicitActor = normalizeActorName(String((event.raw as Record<string, unknown> | undefined)?.analyst ?? ""));
    if (explicitActor && explicitActor !== "") {
      event.actor = explicitActor;
      activeByLane[laneOfActor(explicitActor)] = explicitActor;
      return event;
    }

    const nearestActor = activeByLane.analyst ?? activeByLane.research ?? activeByLane.serial;
    if (nearestActor) {
      event.actor = nearestActor;
    }
    return event;
  });
}

function extractFinalTradeDecision(raw: Record<string, unknown> | undefined): string {
  if (!raw) {
    return "";
  }

  const direct = raw.final_trade_decision;
  return typeof direct === "string" ? direct : "";
}

function expandRiskEngineDecisionEvents(events: RuntimeEvent[]): RuntimeEvent[] {
  const expanded: RuntimeEvent[] = [];

  for (let index = 0; index < events.length; index += 1) {
    const event = events[index];
    expanded.push(event);

    if (event.event !== "llm_call" || event.actor !== "Trader") {
      continue;
    }

    const finalDecision = extractFinalTradeDecision(event.raw as Record<string, unknown> | undefined);
    if (!finalDecision) {
      continue;
    }

    const nextEvent = events[index + 1];
    if (
      nextEvent &&
      nextEvent.event === "llm_call" &&
      nextEvent.actor === "Risk Engine" &&
      nextEvent.timestamp === event.timestamp &&
      nextEvent.detail === finalDecision
    ) {
      continue;
    }

    expanded.push({
      id: `${event.id}-risk-fallback`,
      timestamp: event.timestamp,
      event: "llm_call",
      actor: "Risk Engine",
      detail: finalDecision,
      raw: {
        event: "llm_call",
        analyst: "Risk Engine",
        response: finalDecision,
        synthetic: true,
      },
    });
  }

  return expanded;
}

function eventLabel(eventName: string): string {
  if (eventName === "llm_call") return "response";
  if (eventName === "llm_token") return "thinking(stream)";
  if (eventName === "tool_call") return "tool:call";
  if (eventName === "tool_start") return "tool:start";
  if (eventName === "tool_end") return "tool:end";
  if (eventName === "node_start") return "node:start";
  if (eventName === "node_end") return "node:end";
  return eventName;
}

function buildConversationSessions(rows: RuntimeEvent[]): ConversationSession[] {
  const sessions: ConversationSession[] = [];
  let current: ConversationSession | null = null;
  let index = 1;

  const startSession = (timestamp: string): ConversationSession => ({
    id: `session-${index++}`,
    startedAt: timestamp,
    thinkingText: "",
    hasResult: false,
    events: [],
  });

  for (const row of rows) {
    if (!current) {
      current = startSession(row.timestamp);
    }

    if (row.event === "llm_token") {
      current.thinkingText = `${current.thinkingText}${row.detail}`;
      continue;
    }

    if (row.event === "llm_call") {
      current.hasResult = true;
      current.events.push(row);
      sessions.push(current);
      current = null;
      continue;
    }

    current.events.push(row);
  }

  if (current && (current.thinkingText || current.events.length > 0)) {
    sessions.push(current);
  }

  return sessions;
}

function extractToolCalls(events: RuntimeEvent[], thinkingText?: string): ToolCallInfo[] {
  const getToolName = (raw: Record<string, unknown>, fallbackActor: string): string => {
    const tool = raw.tool;
    if (tool && typeof tool === "object") {
      const toolRec = tool as Record<string, unknown>;
      if (typeof toolRec.name === "string" && toolRec.name.trim().length > 0) {
        return toolRec.name;
      }
    }

    const direct = raw.tool_name ?? raw.toolName ?? raw.name;
    if (typeof direct === "string" && direct.trim().length > 0) {
      return direct;
    }

    return fallbackActor;
  };

  const stringifyArgs = (value: unknown): string => {
    if (typeof value === "string") {
      return value;
    }
    if (value === undefined || value === null) {
      return "";
    }
    try {
      return JSON.stringify(value);
    } catch {
      return String(value);
    }
  };

  const getToolArgs = (raw: Record<string, unknown>, fallbackDetail: string): string => {
    const directPayload =
      raw.payload ?? raw.args ?? raw.arguments ?? raw.input ?? raw.input_str ?? raw.query ?? raw.params ?? raw.parameters;

    const fromDirect = stringifyArgs(directPayload);
    if (fromDirect.trim().length > 0) {
      return fromDirect;
    }

    const tool = raw.tool;
    if (tool && typeof tool === "object") {
      const toolRec = tool as Record<string, unknown>;
      const nested = toolRec.args ?? toolRec.arguments ?? toolRec.input;
      const nestedText = stringifyArgs(nested);
      if (nestedText.trim().length > 0) {
        return nestedText;
      }
    }

    const separator = fallbackDetail.indexOf(":");
    if (separator >= 0 && separator < fallbackDetail.length - 1) {
      return fallbackDetail.slice(separator + 1).trim();
    }

    return fallbackDetail;
  };

  const directToolStarts = events
    .filter((event) => event.event === "tool_start" || event.event === "tool_call")
    .map((event) => {
      const raw = (event.raw as Record<string, unknown> | undefined) ?? {};
      const name = getToolName(raw, event.actor);
      const payloadText = getToolArgs(raw, event.detail);

      return {
        id: event.id,
        name,
        args: payloadText.length > 140 ? `${payloadText.slice(0, 140)}...` : payloadText,
      };
    });

  if (directToolStarts.length > 0) {
    return directToolStarts;
  }

  const llmCallFallbacks: ToolCallInfo[] = [];
  for (const event of events) {
    if (event.event !== "llm_call") {
      continue;
    }

    const raw = (event.raw as Record<string, unknown> | undefined) ?? {};
    const toolCalls = raw.tool_calls;
    if (!Array.isArray(toolCalls)) {
      continue;
    }

    toolCalls.forEach((call, idx) => {
      if (!call || typeof call !== "object") {
        return;
      }
      const asRecord = call as Record<string, unknown>;
      const fn = (asRecord.function as Record<string, unknown> | undefined) ?? undefined;
      const name =
        (typeof fn?.name === "string" && fn.name) ||
        (typeof asRecord.name === "string" && asRecord.name) ||
        "tool";
      const argsRaw = fn?.arguments ?? asRecord.arguments ?? asRecord.args ?? "";
      const argsText = typeof argsRaw === "string" ? argsRaw : JSON.stringify(argsRaw);
      llmCallFallbacks.push({
        id: `${event.id}-fallback-${idx}`,
        name,
        args: argsText.length > 140 ? `${argsText.slice(0, 140)}...` : argsText,
      });
    });
  }

  if (llmCallFallbacks.length > 0) {
    return llmCallFallbacks;
  }

  const promptToolFallbacks: ToolCallInfo[] = [];
  for (const event of events) {
    if (event.event !== "llm_call") {
      continue;
    }

    const raw = (event.raw as Record<string, unknown> | undefined) ?? {};
    const prompt = typeof raw.prompt === "string" ? raw.prompt : "";
    if (!prompt) {
      continue;
    }

    const toolBlocks = Array.from(prompt.matchAll(/\[tool\]\s*([\s\S]*?)(?=\n\[(?:ai|human|system|tool)\]|$)/gi));
    if (toolBlocks.length === 0) {
      continue;
    }

    toolBlocks.forEach((match, idx) => {
      const content = (match[1] ?? "").trim();
      if (!content) {
        return;
      }

      const firstLine = content.split("\n", 1)[0]?.trim() ?? "";
      const looksLikeTable = firstLine.includes("|") || firstLine.toLowerCase().includes("rows x");
      const inferredName = looksLikeTable ? "tool_output_table" : "tool_output";

      promptToolFallbacks.push({
        id: `${event.id}-prompt-tool-${idx}`,
        name: inferredName,
        args: content.length > 140 ? `${content.slice(0, 140)}...` : content,
      });
    });
  }

  if (promptToolFallbacks.length > 0) {
    return promptToolFallbacks;
  }

  const text = thinkingText ?? "";
  if (!text) {
    return [];
  }

  const matches = Array.from(text.matchAll(/(?:call\s+)?([a-zA-Z_][a-zA-Z0-9_]{2,})\s*\(([^)]{0,180})\)/g));
  const likelyToolPatterns = /^(get_|fetch_|query_|search_|calc_|calculate_|compute_|read_|load_|parse_|extract_)/i;
  const dedup = new Set<string>();
  const inferred: ToolCallInfo[] = [];

  for (const match of matches) {
    const name = (match[1] || "").trim();
    const args = (match[2] || "").trim();
    if (!name) {
      continue;
    }
    if (!likelyToolPatterns.test(name)) {
      continue;
    }

    const key = `${name}:${args}`;
    if (dedup.has(key)) {
      continue;
    }
    dedup.add(key);

    inferred.push({
      id: `inferred-${inferred.length + 1}`,
      name,
      args: args.length > 140 ? `${args.slice(0, 140)}...` : args,
    });
  }

  return inferred;
}

function ActorConversation({ actor, rows }: { actor: string; rows: RuntimeEvent[] }): React.JSX.Element {
  const sessions = useMemo(() => buildConversationSessions(rows), [rows]);

  return (
    <div className="min-w-0 space-y-2">
      {sessions.map((session, idx) => (
        <div key={`${actor}-${session.id}`} className="min-w-0 rounded-lg border border-zinc-800 bg-zinc-950/60 p-1.5">
          {/** Pre-compute tool tags so they can render even when no token stream is present. */}
          {(() => {
            const toolCalls = extractToolCalls(session.events, session.thinkingText);
            return (
              <>
          <div className="mb-2 flex items-center justify-between gap-2">
            <p className="text-[9px] uppercase tracking-[0.1em] text-zinc-400">Call #{idx + 1}</p>
            <p className="font-mono text-[10px] text-zinc-500">{new Date(session.startedAt).toLocaleTimeString()}</p>
          </div>

          {session.thinkingText ? (
            <div className="mb-2 flex min-w-0 justify-start">
              <div className="min-w-0 max-w-[96%] rounded-xl border border-cyan-500/20 bg-cyan-950/20 p-2">
                <p className="text-[9px] uppercase tracking-[0.08em] text-cyan-300/80">Live Thinking</p>
                <StreamingText text={session.thinkingText} className="agent-markdown mt-1 text-xs leading-5 text-zinc-100" />
              </div>
            </div>
          ) : null}

          {toolCalls.length > 0 ? (
            <div className="mb-2 space-y-1">
              {toolCalls.map((tool) => (
                <div
                  key={tool.id}
                  className="min-w-0 rounded-md border border-amber-500/30 bg-amber-950/20 px-2 py-1 text-[10px] text-amber-200"
                >
                  <span className="font-semibold">Tool:</span> {tool.name}
                  <span className="mx-1 text-amber-300/70">|</span>
                  <span className="font-semibold">Args:</span> {tool.args}
                </div>
              ))}
            </div>
          ) : null}

          <div className="space-y-2">
            {session.events
              .map((event) => (
                <div key={event.id} className="min-w-0 rounded-md border border-zinc-800 bg-zinc-900/50 p-1.5">
                  <div className="flex items-center justify-between gap-2">
                    <p className="text-[9px] uppercase tracking-[0.08em] text-zinc-500">{eventLabel(event.event)}</p>
                    <p className="font-mono text-[10px] text-zinc-500">{new Date(event.timestamp).toLocaleTimeString()}</p>
                  </div>
                  <div className="agent-markdown mt-1 text-xs text-zinc-200">
                    <ReactMarkdown remarkPlugins={[remarkGfm]}>{event.detail}</ReactMarkdown>
                  </div>
                </div>
              ))}
          </div>
              </>
            );
          })()}
        </div>
      ))}
    </div>
  );
}

function AutoFollowScrollArea({
  className,
  watchKey,
  children,
}: {
  className?: string;
  watchKey: string;
  children: React.ReactNode;
}): React.JSX.Element {
  const containerRef = useRef<HTMLDivElement | null>(null);
  const shouldFollowRef = useRef(true);

  const updateFollowState = (): void => {
    const el = containerRef.current;
    if (!el) return;
    const distanceToBottom = el.scrollHeight - (el.scrollTop + el.clientHeight);
    shouldFollowRef.current = distanceToBottom <= 24;
  };

  useEffect(() => {
    const el = containerRef.current;
    if (!el || !shouldFollowRef.current) {
      return;
    }

    const id = window.requestAnimationFrame(() => {
      const current = containerRef.current;
      if (!current) return;
      current.scrollTop = current.scrollHeight;
    });

    return () => window.cancelAnimationFrame(id);
  }, [watchKey]);

  return (
    <ScrollArea ref={containerRef} className={className} onScroll={updateFollowState}>
      {children}
    </ScrollArea>
  );
}

export function AgentProcessBoard(): React.JSX.Element {
  const events = useDashboardStore((state) => state.runtimeEvents);

  const displayEvents = useMemo(
    () =>
      expandRiskEngineDecisionEvents(reassignToolEvents(events)).filter(
        (item) => eventDisplayAllowlist.has(item.event) && !isAnalystToken(item),
      ),
    [events],
  );

  const analystEvents = (actor: string) =>
    displayEvents.filter(
      (item) => item.actor === actor && ["llm_call", "llm_token", "tool_call", "tool_start", "tool_end", "error"].includes(item.event),
    );

  const parallelResearchPresent = parallelResearchActors.filter((actor) =>
    displayEvents.some(
      (item) =>
        item.actor === actor && ["llm_call", "llm_token", "tool_call", "tool_start", "tool_end", "node_start", "node_end", "error"].includes(item.event),
    ),
  );

  const downstreamActors = serialDownstreamOrder.filter((actor) =>
    displayEvents.some(
      (item) =>
        item.actor === actor && ["llm_call", "llm_token", "tool_call", "tool_start", "tool_end", "node_start", "node_end", "error"].includes(item.event),
    ),
  );

  const riskEngineRows = displayEvents.filter(
    (item) =>
      item.actor === "Risk Engine" && ["llm_call", "llm_token", "tool_call", "tool_start", "tool_end", "node_start", "node_end", "error"].includes(item.event),
  );

  const shouldShowRiskEngine = riskEngineRows.length > 0 || displayEvents.some((item) => item.actor === "Trader" && extractFinalTradeDecision(item.raw as Record<string, unknown> | undefined) !== "");

  return (
    <Card className="h-full">
      <CardHeader>
        <CardTitle>Agent Runtime Main Stage</CardTitle>
      </CardHeader>
      <CardContent className="h-[78vh] min-h-[760px]">
        <ScrollArea className="h-full">
          <div className="space-y-4 pr-1">
            <section>
              <p className="mb-2 text-[11px] uppercase tracking-[0.14em] text-zinc-400">Parallel Core Analysts</p>
              <div className="grid gap-2 xl:grid-cols-3">
                {analystActors.map((actor) => {
                  const rows = analystEvents(actor);
                  const watchKey = `${actor}-${rows.length}-${rows.at(-1)?.id ?? "none"}-${rows
                    .filter((row) => row.event === "llm_token")
                    .reduce((sum, row) => sum + row.detail.length, 0)}`;
                  return (
                    <article
                      key={actor}
                      className={`flex min-w-0 h-[700px] flex-col rounded-lg border bg-zinc-950/70 p-2 ${analystBorderMap[actor] ?? "border-zinc-700"}`}
                    >
                      <h3 className="text-xs font-semibold text-zinc-100">{actor}</h3>
                        <AutoFollowScrollArea className="mt-2 h-[650px] min-w-0 pr-1" watchKey={watchKey}>
                        <ActorConversation actor={actor} rows={rows} />
                      </AutoFollowScrollArea>
                    </article>
                  );
                })}
              </div>
            </section>

            {parallelResearchPresent.length > 0 ? (
              <section>
                <p className="mb-2 text-[11px] uppercase tracking-[0.14em] text-zinc-400">Bull vs Bear Research Lab</p>
                <div className="grid gap-2 lg:grid-cols-2">
                  {parallelResearchPresent.map((actor) => {
                    const rows = displayEvents.filter(
                      (item) => item.actor === actor && ["llm_call", "llm_token", "tool_call", "tool_start", "tool_end", "node_start", "node_end", "error"].includes(item.event),
                    );
                    const watchKey = `${actor}-${rows.length}-${rows.at(-1)?.id ?? "none"}-${rows
                      .filter((row) => row.event === "llm_token")
                      .reduce((sum, row) => sum + row.detail.length, 0)}`;
                    return (
                      <article
                        key={actor}
                        className={`min-w-0 rounded-lg border bg-zinc-950/70 p-2 ${analystBorderMap[actor] ?? "border-zinc-700"}`}
                      >
                        <h3 className="text-xs font-semibold text-zinc-100">{actor}</h3>
                        <AutoFollowScrollArea className="mt-2 max-h-[520px] min-w-0 pr-1" watchKey={watchKey}>
                          <ActorConversation actor={actor} rows={rows} />
                        </AutoFollowScrollArea>
                      </article>
                    );
                  })}
                </div>
              </section>
            ) : null}

            <section>
              <p className="mb-2 text-[11px] uppercase tracking-[0.14em] text-zinc-400">Sequential Decision Chain</p>
              <div className="space-y-3">
                {downstreamActors
                  .filter((actor) => actor !== "Risk Engine")
                  .map((actor) => {
                    const rows = displayEvents.filter(
                      (item) => item.actor === actor && ["llm_call", "llm_token", "tool_call", "tool_start", "tool_end", "node_start", "node_end", "error"].includes(item.event),
                    );
                    const watchKey = `${actor}-${rows.length}-${rows.at(-1)?.id ?? "none"}-${rows
                      .filter((row) => row.event === "llm_token")
                      .reduce((sum, row) => sum + row.detail.length, 0)}`;
                    return (
                      <article key={actor} className="min-w-0 rounded-lg border border-zinc-700 bg-zinc-950/70 p-2">
                        <h3 className="text-xs font-semibold text-zinc-100">{actor}</h3>
                        <AutoFollowScrollArea className="mt-2 max-h-[440px] min-w-0 pr-1" watchKey={watchKey}>
                          <ActorConversation actor={actor} rows={rows} />
                        </AutoFollowScrollArea>
                      </article>
                    );
                  })}
                {shouldShowRiskEngine ? (
                  <article className="min-w-0 rounded-lg border border-amber-500/50 bg-amber-950/20 p-2">
                    <h3 className="text-xs font-semibold text-zinc-100">Risk Engine</h3>
                    <AutoFollowScrollArea className="mt-2 max-h-[440px] min-w-0 pr-1" watchKey={`risk-engine-${riskEngineRows.length}-${riskEngineRows.at(-1)?.id ?? "none"}`}>
                      <ActorConversation actor="Risk Engine" rows={riskEngineRows} />
                    </AutoFollowScrollArea>
                  </article>
                ) : null}
              </div>
            </section>
          </div>
        </ScrollArea>
      </CardContent>
    </Card>
  );
}
