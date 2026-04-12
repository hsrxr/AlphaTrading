import { useDashboardStore } from "@/store/dashboardStore";

export function RunControlPanel(): React.JSX.Element {
  const isRunning = useDashboardStore((state) => state.isRunning);
  const runtimeMode = useDashboardStore((state) => state.runtimeMode);
  const runtimeDetail = useDashboardStore((state) => state.runtimeDetail);
  const autoTriggerEnabled = useDashboardStore((state) => state.autoTriggerEnabled);
  const autoTriggerIntervalSec = useDashboardStore((state) => state.autoTriggerIntervalSec);
  const runCount = useDashboardStore((state) => state.runCount);
  const runId = useDashboardStore((state) => state.runId);
  const lastRunAt = useDashboardStore((state) => state.lastRunAt);
  const errorMessage = useDashboardStore((state) => state.errorMessage);
  const startRun = useDashboardStore((state) => state.startRun);
  const stopRun = useDashboardStore((state) => state.stopRun);
  const setAutoTriggerEnabled = useDashboardStore((state) => state.setAutoTriggerEnabled);
  const setAutoTriggerIntervalSec = useDashboardStore((state) => state.setAutoTriggerIntervalSec);

  return (
    <section className="rounded-xl border border-emerald-500/20 bg-[#0b1411]/80 p-4 backdrop-blur">
      <div className="flex flex-wrap items-center gap-3">
        <button
          type="button"
          onClick={startRun}
          disabled={isRunning}
          className="rounded-md border border-emerald-500/40 bg-emerald-500/15 px-3 py-2 text-sm font-medium text-emerald-200 transition hover:bg-emerald-500/25 disabled:cursor-not-allowed disabled:opacity-50"
        >
          {isRunning ? "Running..." : "Run Now"}
        </button>

        <button
          type="button"
          onClick={stopRun}
          disabled={!isRunning}
          className="rounded-md border border-rose-500/40 bg-rose-500/10 px-3 py-2 text-sm font-medium text-rose-200 transition hover:bg-rose-500/20 disabled:cursor-not-allowed disabled:opacity-50"
        >
          Stop
        </button>

        <button
          type="button"
          onClick={() => setAutoTriggerEnabled(!autoTriggerEnabled)}
          className={`rounded-md border px-3 py-2 text-sm font-medium transition ${
            autoTriggerEnabled
              ? "border-cyan-500/40 bg-cyan-500/15 text-cyan-200 hover:bg-cyan-500/25"
              : "border-zinc-600 bg-zinc-800/80 text-zinc-200 hover:bg-zinc-700/80"
          }`}
        >
          {autoTriggerEnabled ? "Auto Trigger: ON" : "Auto Trigger: OFF"}
        </button>

        <label className="flex items-center gap-2 text-sm text-zinc-300">
          Interval(s)
          <input
            type="number"
            min={5}
            value={autoTriggerIntervalSec}
            onChange={(event) => setAutoTriggerIntervalSec(Number(event.target.value || 5))}
            className="w-20 rounded-md border border-zinc-700 bg-zinc-900 px-2 py-1 font-mono text-zinc-100"
          />
        </label>
      </div>

      <div className="mt-3 flex flex-wrap gap-4 text-xs text-zinc-400">
        <p>
          mode: <span className="font-mono text-zinc-200">{runtimeMode.toUpperCase()}</span>
        </p>
        <p>run_count: <span className="font-mono text-zinc-200">{runCount}</span></p>
        <p>status: <span className="font-mono text-zinc-200">{isRunning ? "running" : "idle"}</span></p>
        <p>run_id: <span className="font-mono text-zinc-200">{runId ?? "-"}</span></p>
        <p>
          last_run: <span className="font-mono text-zinc-200">{lastRunAt ? new Date(lastRunAt).toLocaleTimeString() : "-"}</span>
        </p>
      </div>

      <p className="mt-2 text-xs text-zinc-500">{runtimeDetail}</p>

      {errorMessage ? (
        <p className="mt-2 text-xs text-rose-300">runtime_api_error: {errorMessage}</p>
      ) : null}
    </section>
  );
}
