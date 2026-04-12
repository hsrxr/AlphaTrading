import { useEffect, useMemo, useRef, useState } from "react";

import { AgentProcessBoard } from "@/components/dashboard/AgentProcessBoard";
import { RecentTradesTable } from "@/components/dashboard/RecentTradesTable";
import { RunTimeline } from "@/components/dashboard/RunTimeline";
import { HackathonBanner } from "@/components/layout/HackathonBanner";
import { AppSidebar, type SidebarSectionKey } from "@/components/layout/AppSidebar";
import { RunControlPanel } from "@/components/layout/RunControlPanel";
import { TopMetricsHeader } from "@/components/layout/TopMetricsHeader";
import { useDashboardStore } from "@/store/dashboardStore";

function App(): React.JSX.Element {
  const pair = useDashboardStore((state) => state.baseSnapshot.pair);
  const initializeRuntime = useDashboardStore((state) => state.initializeRuntime);
  const [isSidebarCollapsed, setIsSidebarCollapsed] = useState(false);
  const [activeSection, setActiveSection] = useState<SidebarSectionKey>("live-pulse");

  useEffect(() => {
    void initializeRuntime();
  }, [initializeRuntime]);

  const sectionRefs = useRef<Record<SidebarSectionKey, HTMLElement | null>>({
    "live-pulse": null,
    "market-lens": null,
    "agent-mesh": null,
    "risk-sentinel": null,
    execution: null,
  });

  const sectionTitles = useMemo<Record<SidebarSectionKey, string>>(
    () => ({
      "live-pulse": "Live Pulse",
      "market-lens": "Market Lens",
      "agent-mesh": "Agent Mesh",
      "risk-sentinel": "Risk Sentinel",
      execution: "Execution",
    }),
    [],
  );

  const handleNavigate = (section: SidebarSectionKey): void => {
    setActiveSection(section);
    const target = sectionRefs.current[section];
    if (!target) {
      return;
    }
    target.scrollIntoView({ behavior: "smooth", block: "start" });
  };

  return (
    <div className="min-h-screen bg-matrix">
      <HackathonBanner />
      <div className="mx-auto flex min-h-[calc(100vh-49px)] max-w-[1920px]">
        <AppSidebar
          isCollapsed={isSidebarCollapsed}
          onToggle={() => setIsSidebarCollapsed((prev) => !prev)}
          activeSection={activeSection}
          onNavigate={handleNavigate}
        />

        <main className="min-w-0 flex-1 p-2 md:p-3">
          <div className="space-y-3 md:space-y-4">
            <header
              className="space-y-4 animate-riseIn"
              ref={(el) => {
                sectionRefs.current["live-pulse"] = el;
                sectionRefs.current["risk-sentinel"] = el;
              }}
            >
              <div className="flex flex-wrap items-end justify-between gap-2">
                <div>
                  <p className="text-xs uppercase tracking-[0.2em] text-emerald-300/80">Hackathon Dashboard</p>
                  <h1 className="text-xl font-semibold text-zinc-100 md:text-2xl">TradingAgents Live Reasoning Console</h1>
                </div>
                <p className="font-mono text-xs text-zinc-500">{pair} | agent runtime process</p>
              </div>
              <TopMetricsHeader />
              <RunControlPanel />
            </header>

            <section
              className="animate-riseIn"
              ref={(el) => {
                sectionRefs.current["agent-mesh"] = el;
              }}
            >
              <p className="mb-2 text-[11px] uppercase tracking-[0.14em] text-zinc-500">{sectionTitles["agent-mesh"]}</p>
              <AgentProcessBoard />
            </section>

            <section
              className="animate-riseIn"
              ref={(el) => {
                sectionRefs.current.execution = el;
                sectionRefs.current["market-lens"] = el;
                sectionRefs.current["risk-sentinel"] = el;
              }}
            >
              <p className="mb-2 text-[11px] uppercase tracking-[0.14em] text-zinc-500">{sectionTitles.execution}</p>
              <RecentTradesTable />
            </section>
          </div>

          <aside className="pointer-events-none fixed bottom-4 right-4 z-40 h-[230px] w-[260px] animate-riseIn sm:h-[250px] sm:w-[280px]">
            <RunTimeline compact floating />
          </aside>
        </main>
      </div>
    </div>
  );
}

export default App;
