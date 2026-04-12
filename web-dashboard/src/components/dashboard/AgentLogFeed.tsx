import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { ScrollArea } from "@/components/ui/scroll-area";
import { Badge } from "@/components/ui/badge";
import { useDashboardStore } from "@/store/dashboardStore";
import type { AgentName } from "@/types/trading";

const agentColorMap: Record<AgentName, string> = {
  "Bull Researcher": "text-emerald-300 border-emerald-500/40 bg-emerald-500/10",
  "Bear Researcher": "text-rose-300 border-rose-500/40 bg-rose-500/10",
  "Market Analyst": "text-cyan-300 border-cyan-500/40 bg-cyan-500/10",
  "News Analyst": "text-lime-300 border-lime-500/40 bg-lime-500/10",
  "Quant Analyst": "text-indigo-300 border-indigo-500/40 bg-indigo-500/10",
  "Risk Engine": "text-amber-300 border-amber-500/40 bg-amber-500/10",
  Trader: "text-violet-300 border-violet-500/40 bg-violet-500/10",
  System: "text-sky-300 border-sky-500/40 bg-sky-500/10",
  Unknown: "text-zinc-300 border-zinc-500/40 bg-zinc-500/10",
};

export function AgentLogFeed(): React.JSX.Element {
  const events = useDashboardStore((state) => state.runtimeEvents);

  const feed = events
    .filter((event) => event.event === "llm_call")
    .map((event) => ({
      id: event.id,
      timestamp: event.timestamp,
      agent: event.actor as AgentName,
      summary: event.detail,
    }));

  return (
    <Card className="h-full">
      <CardHeader>
        <CardTitle>Multi-Agent Live Feed</CardTitle>
      </CardHeader>
      <CardContent className="h-[360px]">
        <ScrollArea className="h-full space-y-3">
          <div className="space-y-3">
            {feed.length > 0 ? (
              feed.map((item) => (
                <article key={item.id} className="rounded-md border border-zinc-800 bg-zinc-950/80 p-3">
                  <div className="mb-1 flex items-center justify-between gap-2">
                    <Badge className={agentColorMap[item.agent] ?? agentColorMap.Unknown} variant="muted">
                      {item.agent}
                    </Badge>
                    <span className="font-mono text-xs text-zinc-500">
                      {new Date(item.timestamp).toLocaleTimeString()}
                    </span>
                  </div>
                  <p className="text-sm text-zinc-200">{item.summary}</p>
                  <p className="mt-1 text-[11px] uppercase tracking-[0.08em] text-zinc-500">live trace</p>
                </article>
              ))
            ) : (
              <div className="rounded-md border border-dashed border-zinc-800 bg-zinc-950/50 p-4 text-sm text-zinc-400">
                No live agent output yet. Start a run to stream the trace here.
              </div>
            )}
          </div>
        </ScrollArea>
      </CardContent>
    </Card>
  );
}
