import json
import os
import threading
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Dict, List, Optional
from urllib.parse import parse_qs, urlparse

from tradingagents.default_config import DEFAULT_CONFIG
from tradingagents.graph.trading_graph import TradingAgentsGraph

HOST = "127.0.0.1"
PORT = 8765


@dataclass
class RunState:
    run_id: str
    pair: str
    trade_date: str
    selected_analysts: List[str]
    parallel_mode: bool
    status: str = "queued"
    created_at: str = field(default_factory=lambda: datetime.now().isoformat())
    updated_at: str = field(default_factory=lambda: datetime.now().isoformat())
    trace_file: Optional[str] = None
    decision: Optional[str] = None
    error: Optional[str] = None
    graph: Optional[TradingAgentsGraph] = None


RUNS: Dict[str, RunState] = {}
RUNS_LOCK = threading.Lock()


@dataclass
class ReplaySpeedConfig:
    speed_multiplier: float = 1.0


SPEED_CONFIG = ReplaySpeedConfig()
SPEED_LOCK = threading.Lock()


def _load_local_env() -> None:
    """Load key=value pairs from project .env into process env if missing."""
    env_path = Path(__file__).resolve().parent / ".env"
    if not env_path.exists():
        return

    for raw_line in env_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value


_load_local_env()


def _iso_now() -> str:
    return datetime.now().isoformat()


def _clamp_speed_multiplier(value: Any) -> float:
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return 1.0
    return max(0.25, min(64.0, numeric))


def _actor_from_prompt(prompt: str) -> str:
    text = (prompt or "").lower()
    mappings = [
        ("crypto market analyst", "Market Analyst"),
        ("crypto news analyst", "News Analyst"),
        ("quantitative strategy signal analyst", "Quant Analyst"),
        ("bull researcher", "Bull Researcher"),
        ("bear researcher", "Bear Researcher"),
        ("risk management", "Risk Engine"),
        ("trader", "Trader"),
    ]
    for key, actor in mappings:
        if key in text:
            return actor
    return "Unknown"


def _normalize_event(raw: Dict[str, Any], idx: int) -> Dict[str, Any]:
    event = str(raw.get("event", "unknown"))
    timestamp = str(raw.get("timestamp", _iso_now()))

    if event == "llm_call":
        prompt = str(raw.get("prompt", ""))
        actor = str(raw.get("analyst") or "Unknown")
        if actor == "Unknown":
            actor = _actor_from_prompt(prompt)
        detail = str(raw.get("response", ""))[:800]
        return {
            "id": f"evt-{idx}",
            "timestamp": timestamp,
            "event": "llm_call",
            "actor": actor,
            "detail": detail,
            "raw": raw,
        }

    if event == "llm_token":
        actor = str(raw.get("analyst") or "Unknown")
        token = str(raw.get("token", ""))
        return {
            "id": f"evt-{idx}",
            "timestamp": timestamp,
            "event": "llm_token",
            "actor": actor,
            "detail": token,
            "raw": raw,
        }

    if event in ("tool_start", "tool_end"):
        tool_name = str(raw.get("tool_name", "tool"))
        payload = str(raw.get("payload", ""))
        detail = f"{tool_name}: {payload[:240]}"
        return {
            "id": f"evt-{idx}",
            "timestamp": timestamp,
            "event": event,
            "actor": tool_name,
            "detail": detail,
            "raw": raw,
        }

    if event == "node_start":
        node_name = str(raw.get("node_name", "node"))
        return {
            "id": f"evt-{idx}",
            "timestamp": timestamp,
            "event": "node_start",
            "actor": node_name,
            "detail": f"node started: {node_name}",
            "raw": raw,
        }

    if event == "node_end":
        node_name = str(raw.get("node_name", "node"))
        return {
            "id": f"evt-{idx}",
            "timestamp": timestamp,
            "event": "node_end",
            "actor": node_name,
            "detail": f"node finished: {node_name}",
            "raw": raw,
        }

    if event in ("run_started", "summary"):
        return {
            "id": f"evt-{idx}",
            "timestamp": timestamp,
            "event": "run_started",
            "actor": "System",
            "detail": "run started",
            "raw": raw,
        }

    if event in ("run_completed",):
        return {
            "id": f"evt-{idx}",
            "timestamp": timestamp,
            "event": "run_completed",
            "actor": "System",
            "detail": "run completed",
            "raw": raw,
        }

    return {
        "id": f"evt-{idx}",
        "timestamp": timestamp,
        "event": event,
        "actor": "Unknown",
        "detail": json.dumps(raw, ensure_ascii=False)[:600],
        "raw": raw,
    }


def _read_trace_events(trace_file: str, after: int) -> Dict[str, Any]:
    path = Path(trace_file)
    if not path.exists():
        return {"events": [], "nextOffset": after}

    events: List[Dict[str, Any]] = []
    line_idx = 0
    with path.open("r", encoding="utf-8") as f:
        for line in f:
            line_idx += 1
            if line_idx <= after:
                continue
            line = line.strip()
            if not line:
                continue
            try:
                raw = json.loads(line)
            except json.JSONDecodeError:
                continue
            events.append(_normalize_event(raw, line_idx))

    return {"events": events, "nextOffset": line_idx}


def _run_job(run_state: RunState) -> None:
    run_state.status = "running"
    run_state.updated_at = _iso_now()

    config = DEFAULT_CONFIG.copy()
    config["enable_progress_tracking"] = True
    config["enable_llm_streaming"] = True

    # Fallback: if DeepSeek is configured but key is missing, use OpenAI defaults.
    if config.get("llm_provider") == "deepseek":
        import os

        if not os.getenv("DEEPSEEK_API_KEY") and os.getenv("OPENAI_API_KEY"):
            config["llm_provider"] = "openai"
            config["backend_url"] = None
            config["deep_think_llm"] = "gpt-4o-mini"
            config["quick_think_llm"] = "gpt-4o-mini"

    try:
        graph = TradingAgentsGraph(
            debug=True,
            selected_analysts=run_state.selected_analysts,
            config=config,
            parallel_mode=run_state.parallel_mode,
        )
        run_state.graph = graph
    except Exception as exc:
        run_state.status = "failed"
        run_state.error = f"graph_init_failed: {exc}"
        run_state.updated_at = _iso_now()
        return

    try:
        _, decision = graph.propagate(run_state.pair, run_state.trade_date)
        run_state.decision = str(decision)
        run_state.status = "completed"
    except Exception as exc:
        run_state.status = "failed"
        run_state.error = str(exc)
    finally:
        trace_file = getattr(graph, "current_trace_file", None)
        if trace_file:
            run_state.trace_file = str(trace_file)
        run_state.updated_at = _iso_now()


class RequestHandler(BaseHTTPRequestHandler):
    server_version = "TradingAgentsRuntimeAPI/0.1"

    def _set_headers(self, status: int = 200) -> None:
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()

    def _json(self, payload: Dict[str, Any], status: int = 200) -> None:
        self._set_headers(status)
        self.wfile.write(json.dumps(payload, ensure_ascii=False).encode("utf-8"))

    def do_OPTIONS(self) -> None:
        self._set_headers(204)

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        path = parsed.path
        query = parse_qs(parsed.query)

        if path == "/healthz":
            return self._json({"ok": True, "time": _iso_now()})

        if path == "/api/replay/speed":
            with SPEED_LOCK:
                speed_multiplier = SPEED_CONFIG.speed_multiplier
            return self._json(
                {
                    "speedMultiplier": speed_multiplier,
                    "min": 0.25,
                    "max": 64.0,
                    "updatedAt": _iso_now(),
                }
            )

        if path == "/api/runs":
            with RUNS_LOCK:
                runs = [
                    {
                        "runId": rs.run_id,
                        "pair": rs.pair,
                        "tradeDate": rs.trade_date,
                        "status": rs.status,
                        "createdAt": rs.created_at,
                        "updatedAt": rs.updated_at,
                        "traceFile": rs.trace_file,
                        "decision": rs.decision,
                        "error": rs.error,
                    }
                    for rs in RUNS.values()
                ]
            runs.sort(key=lambda x: x["createdAt"], reverse=True)
            return self._json({"runs": runs})

        if path.startswith("/api/runs/") and path.endswith("/events"):
            parts = path.strip("/").split("/")
            run_id = parts[2] if len(parts) >= 4 else ""
            after = int((query.get("after") or ["0"])[0])

            with RUNS_LOCK:
                run_state = RUNS.get(run_id)
            if not run_state:
                return self._json({"error": "run_not_found"}, status=404)

            if run_state.graph and getattr(run_state.graph, "current_trace_file", None) and not run_state.trace_file:
                run_state.trace_file = str(run_state.graph.current_trace_file)

            if not run_state.trace_file:
                synthetic_events: List[Dict[str, Any]] = []
                next_offset = after
                if run_state.status == "failed" and run_state.error and after == 0:
                    synthetic_events.append(
                        {
                            "id": "evt-local-1",
                            "timestamp": run_state.updated_at,
                            "event": "error",
                            "actor": "System",
                            "detail": run_state.error,
                            "raw": {"error": run_state.error},
                        }
                    )
                    next_offset = 1
                return self._json(
                    {
                        "runId": run_state.run_id,
                        "status": run_state.status,
                        "traceFile": run_state.trace_file,
                        "decision": run_state.decision,
                        "error": run_state.error,
                        "events": synthetic_events,
                        "nextOffset": next_offset,
                    }
                )

            payload = _read_trace_events(run_state.trace_file, after)
            payload.update(
                {
                    "runId": run_state.run_id,
                    "status": run_state.status,
                    "traceFile": run_state.trace_file,
                    "decision": run_state.decision,
                    "error": run_state.error,
                }
            )
            return self._json(payload)

        return self._json({"error": "not_found"}, status=404)

    def do_POST(self) -> None:
        parsed = urlparse(self.path)

        if parsed.path == "/api/replay/speed":
            try:
                content_len = int(self.headers.get("Content-Length", "0"))
                body_raw = self.rfile.read(content_len) if content_len > 0 else b"{}"
                body = json.loads(body_raw.decode("utf-8"))
            except Exception:
                return self._json({"error": "invalid_json"}, status=400)

            requested = body.get("speedMultiplier")
            if requested is None:
                return self._json({"error": "speedMultiplier_required"}, status=400)

            normalized = _clamp_speed_multiplier(requested)
            with SPEED_LOCK:
                SPEED_CONFIG.speed_multiplier = normalized

            return self._json(
                {
                    "ok": True,
                    "speedMultiplier": normalized,
                    "min": 0.25,
                    "max": 64.0,
                    "updatedAt": _iso_now(),
                }
            )

        if parsed.path != "/api/run/start":
            return self._json({"error": "not_found"}, status=404)

        try:
            content_len = int(self.headers.get("Content-Length", "0"))
            body_raw = self.rfile.read(content_len) if content_len > 0 else b"{}"
            body = json.loads(body_raw.decode("utf-8"))
        except Exception:
            return self._json({"error": "invalid_json"}, status=400)

        pair = str(body.get("pair") or "WETH/USDC")
        trade_date = str(body.get("tradeDate") or datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
        selected = body.get("selectedAnalysts") or ["market", "news", "quant"]
        parallel_mode = bool(body.get("parallelMode", True))

        run_id = uuid.uuid4().hex[:12]
        run_state = RunState(
            run_id=run_id,
            pair=pair,
            trade_date=trade_date,
            selected_analysts=list(selected),
            parallel_mode=parallel_mode,
        )

        with RUNS_LOCK:
            RUNS[run_id] = run_state

        thread = threading.Thread(target=_run_job, args=(run_state,), daemon=True)
        thread.start()

        return self._json(
            {
                "runId": run_id,
                "status": run_state.status,
                "pair": pair,
                "tradeDate": trade_date,
            }
        )


def run_server() -> None:
    server = ThreadingHTTPServer((HOST, PORT), RequestHandler)
    print(f"Runtime API listening on http://{HOST}:{PORT}")
    server.serve_forever()


if __name__ == "__main__":
    run_server()
