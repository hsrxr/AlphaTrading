import { create } from "zustand";
import { mockDashboardSnapshot } from "@/data/mockData";
import { loadHistoricalExecutionTrailFromJson, loadRuntimeEventsFromJsonl } from "@/data/traceReplay";
import { getLivePollIntervalMs, getReplayDelayMs, refreshStreamSpeedFromApi } from "@/lib/streamSpeed";
import type {
  RuntimeEvent,
  TradeRecord,
  TradingDashboardSnapshot,
} from "@/types/trading";

interface DashboardState {
  baseSnapshot: TradingDashboardSnapshot;
  runtimeEvents: RuntimeEvent[];
  eventOffset: number;
  runId: string | null;
  trades: TradeRecord[];
  isRunning: boolean;
  runtimeMode: "live" | "mock";
  runtimeDetail: string | null;
  isRuntimeReady: boolean;
  autoTriggerEnabled: boolean;
  autoTriggerIntervalSec: number;
  runCount: number;
  lastRunAt: string | null;
  errorMessage: string | null;
  initializeRuntime: () => Promise<void>;
  startRun: () => Promise<void>;
  stopRun: () => void;
  setAutoTriggerEnabled: (enabled: boolean) => void;
  setAutoTriggerIntervalSec: (seconds: number) => void;
}

const API_BASE = import.meta.env.VITE_RUNTIME_API_BASE ?? "http://127.0.0.1:8765";
const MOCK_TRACE_PATH = import.meta.env.VITE_MOCK_TRACE_PATH ?? "/mock/full_trace_time.jsonl";
const MOCK_LEDGER_PATH = import.meta.env.VITE_MOCK_LEDGER_PATH ?? "/mock/virtual_ledger.json";
const MOCK_AGENT_INFO_PATH = import.meta.env.VITE_MOCK_AGENT_INFO_PATH ?? "/mock/agent-id.json";
const REQUEST_TIMEOUT_MS = 1400;
const BASE_MOCK_TOKEN_DELAY_MS = 4;
const BASE_MOCK_EVENT_DELAY_MS = 60;

const createIdleSnapshot = (pair?: string) => ({
  ...mockDashboardSnapshot,
  pair: pair ?? mockDashboardSnapshot.pair,
  agentFeed: [],
  agentProcessFeed: [],
  runtimeEvents: [],
  executionTrail: [],
});

const seedMockState = (
  runLabel?: string,
  pair?: string,
  detail?: string,
  executionTrail?: TradingDashboardSnapshot["executionTrail"],
) => ({
  baseSnapshot: {
    ...createIdleSnapshot(pair),
    executionTrail: executionTrail ?? [],
  },
  runtimeEvents: [],
  eventOffset: 0,
  runId: runLabel ?? null,
  trades: [],
  isRunning: false,
  runtimeMode: "mock" as const,
  runtimeDetail: detail ?? "Mock data loaded from full_trace_time.jsonl",
  isRuntimeReady: true,
  errorMessage: null,
});

let pollingTimer: ReturnType<typeof setInterval> | null = null;
let autoTriggerTimer: ReturnType<typeof setInterval> | null = null;
let mockReplayTimer: ReturnType<typeof setTimeout> | null = null;
let mockReplayEvents: RuntimeEvent[] = mockDashboardSnapshot.runtimeEvents;
let mockReplayPair = mockDashboardSnapshot.pair;

export const useDashboardStore = create<DashboardState>((set, get) => ({
  baseSnapshot: createIdleSnapshot(),
  runtimeEvents: [],
  eventOffset: 0,
  runId: null,
  trades: [],
  isRunning: false,
  runtimeMode: "mock",
  runtimeDetail: "Preparing mock trace replay",
  isRuntimeReady: false,
  autoTriggerEnabled: false,
  autoTriggerIntervalSec: 30,
  runCount: 0,
  lastRunAt: null,
  errorMessage: null,

  initializeRuntime: async () => {
    if (get().isRuntimeReady) {
      return;
    }

    await refreshStreamSpeedFromApi(API_BASE);

    const [traceReplay, executionTrail] = await Promise.all([
      loadRuntimeEventsFromJsonl(MOCK_TRACE_PATH),
      loadHistoricalExecutionTrailFromJson(MOCK_LEDGER_PATH, MOCK_AGENT_INFO_PATH),
    ]);

    if (traceReplay) {
      mockReplayEvents = traceReplay.events;
      mockReplayPair = traceReplay.pair;
    }

    if (import.meta.env.PROD) {
      set(
        seedMockState(
          undefined,
          mockReplayPair,
          `Mock trace loaded from ${MOCK_TRACE_PATH}`,
          executionTrail,
        ),
      );
      return;
    }

    const controller = new AbortController();
    const timeoutId = window.setTimeout(() => controller.abort(), REQUEST_TIMEOUT_MS);

    try {
      const response = await fetch(`${API_BASE}/healthz`, {
        signal: controller.signal,
      });

      if (!response.ok) {
        throw new Error(`health check failed: ${response.status}`);
      }

      set({
        runtimeMode: "live",
        runtimeDetail: `Connected to ${API_BASE}`,
        isRuntimeReady: true,
        errorMessage: null,
        baseSnapshot: {
          ...createIdleSnapshot(mockReplayPair),
          executionTrail,
        },
      });
    } catch {
      set(
        seedMockState(
          undefined,
          mockReplayPair,
          `Backend unavailable; replaying ${MOCK_TRACE_PATH}`,
          executionTrail,
        ),
      );
    } finally {
      window.clearTimeout(timeoutId);
    }
  },

  startRun: async () => {
    if (get().isRunning) {
      return;
    }

    await refreshStreamSpeedFromApi(API_BASE);

    if (pollingTimer) {
      clearInterval(pollingTimer);
      pollingTimer = null;
    }

    if (mockReplayTimer) {
      window.clearTimeout(mockReplayTimer);
      mockReplayTimer = null;
    }

    set((state: DashboardState) => ({
      runtimeEvents: [],
      eventOffset: 0,
      runId: null,
      trades: [],
      isRunning: true,
      runCount: state.runCount + 1,
      lastRunAt: new Date().toISOString(),
      errorMessage: null,
    }));

    if (get().runtimeMode === "mock") {
      const replayEvents = mockReplayEvents;
      const replayRunId = `mock-${Date.now()}`;
      let cursor = 0;

      set({
        runId: replayRunId,
        runtimeDetail: `Mock replay is running from ${MOCK_TRACE_PATH}`,
        baseSnapshot: {
          ...get().baseSnapshot,
          pair: mockReplayPair,
        },
      });

      const stepReplay = () => {
        const nextEvent = replayEvents[cursor];

        if (!nextEvent) {
          if (mockReplayTimer) {
            window.clearTimeout(mockReplayTimer);
            mockReplayTimer = null;
          }

          set({
            isRunning: false,
            eventOffset: replayEvents.length,
            trades: [],
            runtimeDetail: `Mock replay completed from ${MOCK_TRACE_PATH}`,
          });
          return;
        }

        cursor += 1;
        set((state) => ({
          runtimeEvents: [...state.runtimeEvents, nextEvent],
          eventOffset: cursor,
        }));

        const delayMs =
          nextEvent.event === "llm_token"
            ? getReplayDelayMs(BASE_MOCK_TOKEN_DELAY_MS)
            : getReplayDelayMs(BASE_MOCK_EVENT_DELAY_MS);
        mockReplayTimer = window.setTimeout(stepReplay, delayMs);
      };

      stepReplay();

      return;
    }

    try {
      const response = await fetch(`${API_BASE}/api/run/start`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
        },
        body: JSON.stringify({
          pair: get().baseSnapshot.pair,
          selectedAnalysts: ["market", "news", "quant"],
          parallelMode: true,
        }),
      });

      if (!response.ok) {
        throw new Error(`start run failed: ${response.status}`);
      }

      const payload = (await response.json()) as { runId: string };
      const runId = payload.runId;

      set({ runId });

      const pollIntervalMs = getLivePollIntervalMs(900);

      pollingTimer = setInterval(async () => {
        const { runId: activeRunId, eventOffset } = get();
        if (!activeRunId) {
          return;
        }

        try {
          const eventsRes = await fetch(
            `${API_BASE}/api/runs/${activeRunId}/events?after=${eventOffset}`,
          );
          if (!eventsRes.ok) {
            return;
          }
          const eventsPayload = (await eventsRes.json()) as {
            events: RuntimeEvent[];
            nextOffset: number;
            status: string;
            decision?: string | null;
            error?: string | null;
          };

          const newEvents = eventsPayload.events || [];

          set((state) => ({
            runtimeEvents: [...state.runtimeEvents, ...newEvents],
            eventOffset: eventsPayload.nextOffset ?? state.eventOffset,
          }));

          if (eventsPayload.status === "completed" || eventsPayload.status === "failed") {
            if (pollingTimer) {
              clearInterval(pollingTimer);
              pollingTimer = null;
            }

            if (eventsPayload.decision) {
              const decision = String(eventsPayload.decision);
              const syntheticTrade: TradeRecord = {
                id: `decision-${Date.now()}`,
                timestamp: new Date().toISOString(),
                pair: get().baseSnapshot.pair,
                side: decision.includes("BUY") ? "BUY" : "SELL",
                quantity: 0,
                price: 0,
                reason: decision,
              };
              set((state) => ({
                trades: [syntheticTrade, ...state.trades],
              }));
            }

            set({ isRunning: false });

            if (eventsPayload.status === "failed") {
              set({
                errorMessage:
                  eventsPayload.error ?? "runtime execution failed before trace output was generated",
              });
            }
          }
        } catch {
          // Keep polling loop resilient to transient failures.
        }
      }, pollIntervalMs);
    } catch (error) {
      set({
        ...seedMockState(),
        runtimeMode: "mock",
        runtimeDetail: "Runtime API was unavailable, so the dashboard fell back to mock data",
        errorMessage: error instanceof Error ? error.message : "failed to start runtime api run",
      });
    }
  },

  stopRun: () => {
    if (pollingTimer) {
      clearInterval(pollingTimer);
      pollingTimer = null;
    }

    if (mockReplayTimer) {
      window.clearTimeout(mockReplayTimer);
      mockReplayTimer = null;
    }

    set({ isRunning: false });
  },

  setAutoTriggerEnabled: (enabled: boolean) => {
    if (autoTriggerTimer) {
      clearInterval(autoTriggerTimer);
      autoTriggerTimer = null;
    }

    set({ autoTriggerEnabled: enabled });

    if (!enabled) {
      return;
    }

    const intervalMs = Math.max(5, get().autoTriggerIntervalSec) * 1000;
    autoTriggerTimer = setInterval(() => {
      if (!get().isRunning) {
        get().startRun();
      }
    }, intervalMs);
  },

  setAutoTriggerIntervalSec: (seconds: number) => {
    const safeSeconds = Math.max(5, Math.floor(seconds));
    set({ autoTriggerIntervalSec: safeSeconds });

    if (get().autoTriggerEnabled) {
      get().setAutoTriggerEnabled(true);
    }
  },
}));
