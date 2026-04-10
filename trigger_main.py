import logging
import json
import os
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict

from dotenv import load_dotenv
from tradingagents.default_config import DEFAULT_CONFIG
from tradingagents.graph.trading_graph import TradingAgentsGraph
from tradingagents.triggers.runtime import build_default_runtime
from tradingagents.triggers.models import MarketShockEvent


load_dotenv()


def _configure_logging() -> Path:
    """Configure logging to both console and local file."""
    log_dir = Path(os.getenv("TRIGGER_LOG_DIR", "logs"))
    log_dir.mkdir(parents=True, exist_ok=True)
    # Save logs with timestamp for easier debugging
    log_file = log_dir / f"trigger_runtime_{datetime.now().strftime('%Y%m%d%H%M%S')}.log"

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
        handlers=[
            logging.StreamHandler(),
            logging.FileHandler(log_file, encoding="utf-8"),
        ],
        force=True,
    )
    return log_file


def _get_max_runtime_seconds() -> int:
    """Read max runtime from env, defaulting to 3 hours."""
    raw = os.getenv("TRIGGER_MAX_RUNTIME_SECONDS", "108000")
    try:
        value = int(raw)
    except ValueError:
        logging.warning("Invalid TRIGGER_MAX_RUNTIME_SECONDS=%s; using 600", raw)
        return 600
    return max(1, value)


def _json_default(value: Any) -> str:
    if isinstance(value, datetime):
        return value.isoformat()
    return str(value)


def _safe_pair_name(pair: str) -> str:
    return pair.replace("/", "_").replace("\\", "_").strip()


def _persist_eval_result(
    market_shock: MarketShockEvent,
    final_state: Dict[str, Any],
    decision: str,
) -> None:
    pair = _safe_pair_name(market_shock.pair)
    out_dir = Path("eval_results") / pair / "trigger_runtime_results"
    out_dir.mkdir(parents=True, exist_ok=True)

    ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S_%f")
    out_file = out_dir / f"final_result_{ts}.json"

    try:
        parsed_decision = json.loads(decision)
    except (TypeError, json.JSONDecodeError):
        parsed_decision = None

    payload = {
        "saved_at": datetime.now(timezone.utc).isoformat(),
        "pair": market_shock.pair,
        "market_shock": market_shock.to_context(),
        "event_types": sorted({event.event_type for event in market_shock.trigger_events}),
        "event_count": len(market_shock.trigger_events),
        "decision_raw": decision,
        "decision_json": parsed_decision,
        "final_state": final_state,
    }

    with out_file.open("w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2, default=_json_default)

    logging.info("Saved full eval result JSON: %s", out_file.resolve())

def main() -> None:
    log_file = _configure_logging()

    config = DEFAULT_CONFIG.copy()
    config["enable_on_chain_submission"] = True
    # Only keep verified Base DEX pools in trigger runtime.
    # BNBUSD has no verified Base pool in the current data source set.
    config["trigger_pairs"] = ["ETHUSD", "BTCUSD", "SOLUSD"]

    graph = TradingAgentsGraph(
        debug=True,
        selected_analysts=["market", "news", "quant"],
        config=config,
        parallel_mode=True,
    )

    runtime = build_default_runtime(
        graph=graph,
        pairs=config.get("trigger_pairs", ["ETHUSD"]),
        source_allowlist=config.get("trigger_news_sources", ["sec", "twitter", "project"]),
        twitter_handles=config.get("trigger_twitter_accounts", []),
        nitter_instances=config.get("trigger_nitter_instances", []),
        aggregation_window_seconds=config.get("trigger_aggregation_window_seconds", 90),
        cooldown_seconds=config.get("trigger_cooldown_seconds", 300),
        poll_interval_seconds=config.get("trigger_poll_interval_seconds", 10),
    )
    runtime.on_decision = _persist_eval_result

    max_runtime_seconds = _get_max_runtime_seconds()
    started_at = time.monotonic()
    logging.info("Trigger runtime started; max runtime: %s seconds", max_runtime_seconds)
    logging.info("Local log file: %s", log_file.resolve())

    try:
        while (time.monotonic() - started_at) < max_runtime_seconds:
            cycle_now = datetime.now(timezone.utc)
            try:
                runtime.run_once(now=cycle_now)
            except Exception as exc:
                logging.exception("Trigger runtime cycle failed: %s", exc)

            remaining = max_runtime_seconds - (time.monotonic() - started_at)
            if remaining <= 0:
                break

            sleep_seconds = min(runtime.poll_interval_seconds, remaining)
            time.sleep(sleep_seconds)
    except KeyboardInterrupt:
        logging.info("Trigger runtime interrupted by user")

    logging.info("Trigger runtime finished after %s seconds", int(time.monotonic() - started_at))


if __name__ == "__main__":
    main()
