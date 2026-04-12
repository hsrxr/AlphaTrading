const githubUrl = import.meta.env.VITE_GITHUB_URL ?? "https://github.com/";
const pitchVideoUrl = import.meta.env.VITE_PITCH_VIDEO_URL ?? "https://www.youtube.com/";

export function HackathonBanner(): React.JSX.Element {
  return (
    <div className="border-b border-amber-400/30 bg-gradient-to-r from-amber-400/20 via-rose-500/10 to-cyan-400/20 px-3 py-2 text-sm text-amber-50 shadow-[0_8px_30px_rgba(251,191,36,0.12)] backdrop-blur">
      <div className="mx-auto flex max-w-[1920px] flex-wrap items-center justify-between gap-2">
        <p className="font-medium">
          👋 Welcome Judges! This is a live simulation of the AlphaAgenting runtime. The actual engine uses LangGraph,
          ChromaDB, and Python in the backend.
        </p>
        <div className="flex items-center gap-3 text-xs font-semibold uppercase tracking-[0.12em] text-amber-100/90">
          <a className="transition hover:text-white" href={githubUrl} target="_blank" rel="noreferrer">
            View GitHub
          </a>
          <span className="text-amber-100/40">|</span>
          <a className="transition hover:text-white" href={pitchVideoUrl} target="_blank" rel="noreferrer">
            Watch Pitch Video
          </a>
        </div>
      </div>
    </div>
  );
}