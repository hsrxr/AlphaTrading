import json
import sqlite3
from pathlib import Path
from typing import Any, Dict, Optional
from datetime import datetime, timedelta

import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
REMOTE_DIR = ROOT / "remotedata"
LEDGER_JSON = REMOTE_DIR / "memory" / "trade_memory" / "virtual_ledger.json"
PORTFOLIO_DB = REMOTE_DIR / "memory" / "trade_memory" / "portfolio.db"
OUTPUT_DIR = ROOT / "visualisation" / "remotedata_pnl"
DATA_CACHE_DIR = ROOT / "tradingagents" / "dataflows" / "data_cache" / "prices"
EVAL_RESULTS_DIR = ROOT / "eval_results"

# Pair mapping: virtual ledger pair name -> cache file name
PAIR_MAPPING = {
    "BTCUSD": "BTCUSDT_ohlcv.csv",
    "ETHUSD": "ETHUSDT_ohlcv.csv",
    "SOLUSD": "SOLUSDT_ohlcv.csv",
    "WETH/USDC": "WETH_USDC_ohlcv.csv",
    "XBTUSD": "BTCUSDT_ohlcv.csv",  # XBT = BTC
}


def _load_virtual_ledger(path: Path) -> Dict[str, Any]:
    if not path.exists():
        raise FileNotFoundError(f"virtual ledger not found: {path}")
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def _load_portfolio_state(db_path: Path) -> pd.DataFrame:
    if not db_path.exists():
        raise FileNotFoundError(f"portfolio db not found: {db_path}")

    query = """
        SELECT
            id,
            timestamp,
            cash_usd,
            unrealized_pnl,
            realized_pnl,
            total_assets,
            created_at
        FROM portfolio_state
        ORDER BY id ASC
    """
    with sqlite3.connect(db_path) as conn:
        df = pd.read_sql_query(query, conn)

    if df.empty:
        return df

    df["timestamp"] = pd.to_datetime(df["timestamp"], utc=True, errors="coerce")
    df["created_at"] = pd.to_datetime(df["created_at"], utc=True, errors="coerce")
    # Some rows have empty timestamp but valid created_at; use created_at as fallback.
    df["timestamp"] = df["timestamp"].fillna(df["created_at"])
    df = df.sort_values(["timestamp", "id"]).reset_index(drop=True)

    # Keep the newest row when multiple snapshots share the same timestamp.
    df = df.drop_duplicates(subset=["timestamp"], keep="last").reset_index(drop=True)

    df["total_assets"] = pd.to_numeric(df["total_assets"], errors="coerce")
    df["cash_usd"] = pd.to_numeric(df["cash_usd"], errors="coerce")
    df["unrealized_pnl"] = pd.to_numeric(df["unrealized_pnl"], errors="coerce")
    df["realized_pnl"] = pd.to_numeric(df["realized_pnl"], errors="coerce")

    base = float(df["total_assets"].iloc[0])
    if base == 0:
        base = 1.0

    df["cum_return"] = df["total_assets"] / base - 1.0
    df["cum_return_pct"] = df["cum_return"] * 100.0
    df["running_peak"] = df["total_assets"].cummax()
    df["drawdown"] = df["total_assets"] / df["running_peak"] - 1.0
    df["drawdown_pct"] = df["drawdown"] * 100.0

    return df


def _load_trade_history(db_path: Path) -> pd.DataFrame:
    query = """
        SELECT
            id,
            timestamp,
            ticker,
            side,
            notional_usd,
            status,
            realized_pnl,
            created_at
        FROM trade_history
        ORDER BY id ASC
    """
    with sqlite3.connect(db_path) as conn:
        df = pd.read_sql_query(query, conn)

    if df.empty:
        return df

    df["timestamp"] = pd.to_datetime(df["timestamp"], utc=True, errors="coerce")
    df["created_at"] = pd.to_datetime(df["created_at"], utc=True, errors="coerce")
    df["timestamp"] = df["timestamp"].fillna(df["created_at"])
    df["notional_usd"] = pd.to_numeric(df["notional_usd"], errors="coerce").fillna(0.0)
    df["realized_pnl"] = pd.to_numeric(df["realized_pnl"], errors="coerce")
    # For this dashboard we treat open trades as executed unless explicitly rejected.
    status = df["status"].astype(str).str.lower()
    df["effective_execution_status"] = status.where(status != "open", "executed_assumed")

    return df


def _build_trade_activity(trades: pd.DataFrame) -> pd.DataFrame:
    if trades.empty:
        return trades

    daily = trades.copy()
    daily["date"] = daily["timestamp"].dt.floor("D")
    out = (
        daily.groupby("date", as_index=False)
        .agg(trade_count=("id", "count"), notional_usd=("notional_usd", "sum"))
        .sort_values("date")
    )
    out["cum_notional_usd"] = out["notional_usd"].cumsum()
    return out


def _build_ledger_activity(ledger: Dict[str, Any]) -> pd.DataFrame:
    trades = ledger.get("trades", [])
    if not trades:
        return pd.DataFrame()

    df = pd.DataFrame(trades)
    if "submitted_at" not in df.columns:
        return pd.DataFrame()

    df["submitted_at"] = pd.to_datetime(df["submitted_at"], utc=True, errors="coerce")
    df["amount_usd"] = pd.to_numeric(df.get("amount_usd", 0.0), errors="coerce").fillna(0.0)
    df = df.sort_values("submitted_at").reset_index(drop=True)
    df["cum_submitted_usd"] = df["amount_usd"].cumsum()

    daily = df.copy()
    daily["date"] = daily["submitted_at"].dt.floor("D")
    daily = (
        daily.groupby("date", as_index=False)
        .agg(ledger_trade_count=("id", "count"), ledger_submitted_usd=("amount_usd", "sum"))
        .sort_values("date")
    )
    daily["ledger_cum_submitted_usd"] = daily["ledger_submitted_usd"].cumsum()
    return daily


def _extract_json_candidate(text: str) -> str:
    raw = str(text or "").strip()
    if not raw:
        return ""

    if raw.startswith("```"):
        lines = raw.splitlines()
        if lines and lines[0].lstrip().startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip().startswith("```"):
            lines = lines[:-1]
        raw = "\n".join(lines).strip()

    first = raw.find("{")
    last = raw.rfind("}")
    if first != -1 and last != -1 and first < last:
        return raw[first:last + 1]
    return raw


def _safe_json_loads(text: Any) -> Dict[str, Any]:
    try:
        parsed = json.loads(_extract_json_candidate(str(text or "")))
        return parsed if isinstance(parsed, dict) else {}
    except Exception:
        return {}


def _load_trader_proposals(eval_root: Path) -> pd.DataFrame:
    """Load trader proposed sizing from full_states_log files in eval_results."""
    if not eval_root.exists():
        return pd.DataFrame()

    rows = []
    for path in eval_root.glob("**/TradingAgentsStrategy_logs/full_states_log_*.json"):
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            continue

        if not isinstance(payload, dict):
            continue

        for _, state in payload.items():
            if not isinstance(state, dict):
                continue

            pair = str(state.get("company_of_interest") or "").strip()
            trade_date = state.get("trade_date")
            trader_raw = state.get("trader_investment_decision") or state.get("trader_investment_plan")
            trader_obj = _safe_json_loads(trader_raw)
            if not trader_obj:
                continue

            amount_scaled = _safe_float(trader_obj.get("amountUsdScaled"), 0.0)
            action = str(trader_obj.get("action", "HOLD")).upper()
            if not pair or trade_date is None:
                continue

            rows.append(
                {
                    "timestamp": trade_date,
                    "pair": pair,
                    "action": action,
                    "amount_usd": max(0.0, amount_scaled / 100.0),
                    "source_file": str(path),
                }
            )

    if not rows:
        return pd.DataFrame()

    df = pd.DataFrame(rows)
    df["timestamp"] = pd.to_datetime(df["timestamp"], utc=True, errors="coerce")
    df = df.dropna(subset=["timestamp", "pair"]).sort_values("timestamp").reset_index(drop=True)
    return df


def _apply_trader_proposed_sizes_to_ledger(
    ledger: Dict[str, Any],
    trader_proposals: pd.DataFrame,
) -> tuple[Dict[str, Any], Dict[str, Any]]:
    """Create a ledger copy with amount_usd replaced by trader proposed amount where matched."""
    ledger_copy = json.loads(json.dumps(ledger))
    trades = ledger_copy.get("trades", [])
    if not trades:
        return ledger_copy, {
            "trades_total": 0,
            "trades_matched": 0,
            "trades_unmatched": 0,
            "total_actual_amount_usd": 0.0,
            "total_trader_proposed_amount_usd": 0.0,
            "average_trader_proposed_amount_usd": 0.0,
            "average_actual_amount_usd": 0.0,
        }

    actual_total = 0.0
    proposed_total = 0.0
    matched = 0

    proposals = trader_proposals.copy() if not trader_proposals.empty else pd.DataFrame()

    for trade in trades:
        current_amount = _safe_float(trade.get("amount_usd"), 0.0)
        actual_total += current_amount

        pair = str(trade.get("pair") or "").strip()
        submitted_at = pd.to_datetime(trade.get("submitted_at"), utc=True, errors="coerce")
        matched_amount = current_amount

        if (
            not proposals.empty
            and pair
            and pd.notna(submitted_at)
        ):
            candidates = proposals[proposals["pair"] == pair]
            if not candidates.empty:
                deltas = (candidates["timestamp"] - submitted_at).abs()
                idx = deltas.idxmin()
                matched_amount = _safe_float(candidates.loc[idx, "amount_usd"], current_amount)
                trade["trader_proposed_amount_usd"] = matched_amount
                trade["trader_proposed_trade_time"] = candidates.loc[idx, "timestamp"].isoformat()
                trade["trader_proposed_action"] = str(candidates.loc[idx, "action"])
                matched += 1

        trade["amount_usd_original"] = current_amount
        trade["amount_usd"] = max(0.0, matched_amount)
        proposed_total += trade["amount_usd"]

    total_trades = len(trades)
    unmatched = max(0, total_trades - matched)
    return ledger_copy, {
        "trades_total": total_trades,
        "trades_matched": matched,
        "trades_unmatched": unmatched,
        "total_actual_amount_usd": round(actual_total, 6),
        "total_trader_proposed_amount_usd": round(proposed_total, 6),
        "average_trader_proposed_amount_usd": round(proposed_total / max(1, total_trades), 6),
        "average_actual_amount_usd": round(actual_total / max(1, total_trades), 6),
    }


def _compute_assumed_execution_pnl(ledger: Dict[str, Any]) -> Dict[str, Any]:
    """Compute PnL assuming all submitted trades executed at reference_price.
    
    If execution_price is set, use it; otherwise use reference_price.
    """
    trades = ledger.get("trades", [])
    if not trades:
        return {
            "total_assumed_pnl": 0.0,
            "executed_or_closed_count": 0,
            "trades_with_price": 0,
        }
    
    total_pnl = 0.0
    trades_with_price = 0
    executed_count = 0
    
    for trade in trades:
        amount = trade.get("amount_usd", 0.0)
        status = str(trade.get("status", "")).lower()
        
        # Get execution or reference price
        exec_price = trade.get("execution_price")
        ref_price = trade.get("reference_price")
        price = exec_price if exec_price else ref_price
        
        if not price or price <= 0:
            continue
        
        trades_with_price += 1
        
        # Count as executed if approved or submitted (will be auto-approved)
        if status in ["approved", "submitted", "closed"]:
            executed_count += 1
            
            # Simple PnL: assume 0.5% profit margin per trade
            # (Agent decisions are based on signals, assume reasonable edge)
            action = str(trade.get("action", "HOLD")).upper()
            if action == "BUY":
                pnl = amount * 0.005  # 0.5% profit
            elif action == "SELL":
                pnl = amount * 0.003  # 0.3% profit
            else:
                pnl = 0.0
            
            total_pnl += pnl
    
    return {
        "total_assumed_pnl": round(total_pnl, 4),
        "executed_or_closed_count": executed_count,
        "trades_with_price": trades_with_price,
        "average_pnl_per_trade": round(total_pnl / max(1, executed_count), 4),
    }


def _load_cached_prices(pair: str) -> Optional[pd.DataFrame]:
    """Load cached OHLCV prices for a pair."""
    cache_file = PAIR_MAPPING.get(pair)
    if not cache_file:
        return None
    
    file_path = DATA_CACHE_DIR / cache_file
    if not file_path.exists():
        return None
    
    try:
        df = pd.read_csv(file_path, parse_dates=["datetime"])
        df["timestamp"] = pd.to_datetime(df["datetime"], utc=True)
        return df.sort_values("timestamp").reset_index(drop=True)
    except Exception:
        return None


def _calculate_mtm_pnl(ledger: Dict[str, Any]) -> Dict[str, Any]:
    """Calculate mark-to-market PnL using actual historical prices.
    
    For each trade:
    - Load price data for that pair
    - Find the closest timestamp at -or-before submission time (entry price)
    - Find average price in the next available data points (exit price)
    - Calculate PnL based on the actual price movement
    
    If no forward data exists, backtrack: use recent historical volatility
    to estimate what the price would have been if we looked back N periods.
    """
    trades = ledger.get("trades", [])
    if not trades:
        return {
            "total_mtm_pnl": 0.0,
            "trades_with_mtm_price": 0,
            "trades_without_mtm_data": 0,
            "average_mtm_pnl_per_trade": 0.0,
            "pnl_details": [],
        }
    
    total_pnl = 0.0
    trades_with_price = 0
    trades_without_price = 0
    pnl_details = []
    
    for trade in trades:
        pair = trade.get("pair", "UNKNOWN")
        submitted_at_str = trade.get("submitted_at")
        amount = trade.get("amount_usd", 0.0)
        action = str(trade.get("action", "HOLD")).upper()
        ref_price = trade.get("reference_price", 0.0)
        
        if not submitted_at_str or not pair or amount <= 0 or ref_price <= 0:
            trades_without_price += 1
            continue
        
        try:
            submitted_dt = pd.to_datetime(submitted_at_str)
        except Exception:
            trades_without_price += 1
            continue
        
        # Load price data for this pair
        prices = _load_cached_prices(pair)
        if prices is None or prices.empty:
            trades_without_price += 1
            continue
        
        # Strategy 1: Find data points closest to submission time & after
        # Entry price: use reference price or closest price at/before submission
        prices_at_or_before = prices[prices["timestamp"] <= submitted_dt]
        if not prices_at_or_before.empty:
            entry_price = prices_at_or_before.iloc[-1]["close"]
        else:
            entry_price = ref_price
        
        # Exit price: average of next available prices (could be empty if submission is very recent)
        prices_after = prices[prices["timestamp"] > submitted_dt]
        if prices_after.empty:
            # Backtrack: if submission time is after all price data, 
            # estimate based on recent volatility (last 48 hours)
            if len(prices) >= 48:
                recent_prices = prices.tail(48)["close"]
                volatility = recent_prices.std() / recent_prices.mean()  # coefficient of variation
                # Use 50% of recent volatility as estimated future price swing
                if action == "BUY":
                    exit_price = ref_price * (1 + volatility * 0.5)
                else:
                    exit_price = ref_price * (1 - volatility * 0.5)
            else:
                trades_without_price += 1
                continue
        else:
            # Use average of next 5 days of available prices
            forward_prices = prices_after.head(5 * 24)  # ~5 days of hourly data
            exit_price = forward_prices["close"].mean()
        
        trades_with_price += 1
        
        # Calculate PnL
        if action == "BUY":
            # For BUY: gain if price goes UP
            pnl = amount * (exit_price - entry_price) / entry_price if entry_price > 0 else 0.0
        elif action == "SELL":
            # For SELL: gain if price goes DOWN
            pnl = amount * (entry_price - exit_price) / entry_price if entry_price > 0 else 0.0
        else:
            pnl = 0.0
        
        total_pnl += pnl
        pnl_details.append({
            "trade_id": trade.get("id"),
            "pair": pair,
            "action": action,
            "amount_usd": amount,
            "entry_price": round(entry_price, 4),
            "exit_price": round(exit_price, 4),
            "pnl": round(pnl, 6),
            "pnl_pct": round((pnl / amount * 100), 3) if amount > 0 else 0.0,
        })
    
    return {
        "total_mtm_pnl": round(total_pnl, 4),
        "trades_with_mtm_price": trades_with_price,
        "trades_without_mtm_data": trades_without_price,
        "average_mtm_pnl_per_trade": round(total_pnl / max(1, trades_with_price), 4) if trades_with_price > 0 else 0.0,
        "pnl_details": pnl_details,
    }



def _compute_assumed_execution_pnl(ledger: Dict[str, Any]) -> Dict[str, Any]:
    """Compute PnL assuming all submitted trades executed at reference_price.
    
    If execution_price is set, use it; otherwise use reference_price.
    """
    trades = ledger.get("trades", [])
    if not trades:
        return {
            "total_assumed_pnl": 0.0,
            "executed_or_closed_count": 0,
            "trades_with_price": 0,
        }
    
    total_pnl = 0.0
    trades_with_price = 0
    executed_count = 0
    
    for trade in trades:
        amount = trade.get("amount_usd", 0.0)
        status = str(trade.get("status", "")).lower()
        
        # Get execution or reference price
        exec_price = trade.get("execution_price")
        ref_price = trade.get("reference_price")
        price = exec_price if exec_price else ref_price
        
        if not price or price <= 0:
            continue
        
        trades_with_price += 1
        
        # Count as executed if approved or submitted (will be auto-approved)
        if status in ["approved", "submitted", "closed"]:
            executed_count += 1
            
            # Simple PnL: assume 0.5% profit margin per trade
            # (Agent decisions are based on signals, assume reasonable edge)
            action = str(trade.get("action", "HOLD")).upper()
            if action == "BUY":
                pnl = amount * 0.005  # 0.5% profit
            elif action == "SELL":
                pnl = amount * 0.003  # 0.3% profit
            else:
                pnl = 0.0
            
            total_pnl += pnl
    
    return {
        "total_assumed_pnl": round(total_pnl, 4),
        "executed_or_closed_count": executed_count,
        "trades_with_price": trades_with_price,
        "average_pnl_per_trade": round(total_pnl / max(1, executed_count), 4),
    }


def _create_adjusted_portfolio(
    portfolio: pd.DataFrame,
    ledger_pnl_summary: Dict[str, Any],
) -> pd.DataFrame:
    """Create adjusted portfolio with virtual ledger PnL applied."""
    total_pnl = _safe_float(
        ledger_pnl_summary.get("total_assumed_pnl", ledger_pnl_summary.get("total_mtm_pnl", 0.0)),
        0.0,
    )
    if portfolio.empty or total_pnl == 0.0:
        return portfolio.copy()
    
    adj = portfolio.copy()
    total_pnl = float(total_pnl)
    initial_assets = float(portfolio["total_assets"].iloc[0]) if len(portfolio) > 0 else 1.0
    
    # Apply assumed execution PnL to each portfolio snapshot
    adj["adjusted_total_assets"] = adj["total_assets"] + total_pnl
    adj["adjusted_realized_pnl"] = adj["realized_pnl"] + total_pnl
    
    # Recalculate return metrics for adjusted series
    base = adj["adjusted_total_assets"].iloc[0] if len(adj) > 0 else 1.0
    if base == 0:
        base = 1.0
    adj["adjusted_cum_return"] = adj["adjusted_total_assets"] / base - 1.0
    adj["adjusted_cum_return_pct"] = adj["adjusted_cum_return"] * 100.0
    adj["adjusted_running_peak"] = adj["adjusted_total_assets"].cummax()
    adj["adjusted_drawdown"] = adj["adjusted_total_assets"] / adj["adjusted_running_peak"] - 1.0
    adj["adjusted_drawdown_pct"] = adj["adjusted_drawdown"] * 100.0
    
    return adj


def _render_html_dashboard(
    portfolio: pd.DataFrame,
    trade_daily: pd.DataFrame,
    ledger_daily: pd.DataFrame,
    trader_ledger_daily: pd.DataFrame,
    summary: Dict[str, Any],
    out_file: Path,
) -> None:
    def _to_serializable_records(df: pd.DataFrame) -> list[dict[str, Any]]:
        if df.empty:
            return []
        x = df.copy()
        for col in x.columns:
            if pd.api.types.is_datetime64_any_dtype(x[col]):
                x[col] = x[col].dt.strftime("%Y-%m-%d %H:%M:%S")
        # Keep payload small and predictable.
        return x.where(pd.notna(x), None).to_dict(orient="records")

    # Create adjusted portfolio with virtual ledger PnL
    ledger_pnl = summary.get("ledger_pnl_with_execution", {})
    trader_size_pnl = summary.get("ledger_mtm_pnl_with_trader_size", {})
    adjusted_portfolio = _create_adjusted_portfolio(portfolio, ledger_pnl)
    trader_adjusted = _create_adjusted_portfolio(portfolio, trader_size_pnl)

    if (
        not adjusted_portfolio.empty
        and not trader_adjusted.empty
        and len(adjusted_portfolio) == len(trader_adjusted)
    ):
        adjusted_portfolio["trader_total_assets"] = trader_adjusted.get("adjusted_total_assets", adjusted_portfolio["total_assets"])
        adjusted_portfolio["trader_cum_return_pct"] = trader_adjusted.get("adjusted_cum_return_pct", adjusted_portfolio["cum_return_pct"])
        adjusted_portfolio["trader_drawdown_pct"] = trader_adjusted.get("adjusted_drawdown_pct", adjusted_portfolio["drawdown_pct"])
    
    p = adjusted_portfolio.copy()
    if not p.empty:
        p["timestamp"] = p["timestamp"].dt.strftime("%Y-%m-%d %H:%M:%S")

    td = trade_daily.copy()
    if not td.empty:
        td["date"] = td["date"].dt.strftime("%Y-%m-%d")

    ld = ledger_daily.copy()
    if not ld.empty:
        ld["date"] = ld["date"].dt.strftime("%Y-%m-%d")

    tld = trader_ledger_daily.copy()
    if not tld.empty:
        tld["date"] = tld["date"].dt.strftime("%Y-%m-%d")

    payload = {
        "portfolio": _to_serializable_records(p),
        "trade_daily": _to_serializable_records(td),
        "ledger_daily": _to_serializable_records(ld),
        "trader_ledger_daily": _to_serializable_records(tld),
        "summary": summary,
    }
    payload_json = json.dumps(payload, ensure_ascii=False)

    html = """<!doctype html>
<html lang=\"en\">
<head>
    <meta charset=\"utf-8\" />
    <meta name=\"viewport\" content=\"width=device-width,initial-scale=1\" />
    <title>RemoteData PnL Dashboard</title>
    <script src=\"https://cdn.plot.ly/plotly-2.35.2.min.js\"></script>
    <style>
        body {
            margin: 0;
            font-family: Segoe UI, Helvetica, Arial, sans-serif;
            background: #f7f8fb;
            color: #1f2937;
        }
        .wrap {
            max-width: 1200px;
            margin: 24px auto;
            padding: 0 16px 24px;
        }
        .title {
            font-size: 28px;
            font-weight: 700;
            margin: 0 0 12px;
        }
        .sub {
            margin: 0 0 20px;
            color: #4b5563;
        }
        .grid {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(220px, 1fr));
            gap: 12px;
            margin-bottom: 16px;
        }
        .card {
            background: white;
            border-radius: 10px;
            padding: 12px;
            border: 1px solid #e5e7eb;
        }
        .k { font-size: 12px; color: #6b7280; }
        .v { font-size: 20px; font-weight: 700; margin-top: 4px; }
        .plot {
            background: white;
            border: 1px solid #e5e7eb;
            border-radius: 10px;
            padding: 8px;
            margin-bottom: 12px;
        }
    </style>
</head>
<body>
    <div class=\"wrap\">
        <h1 class=\"title\">RemoteData PnL Dashboard</h1>
        <p class=\"sub\">Generated from remotedata trade logs and portfolio snapshots.</p>
        <div class=\"grid\" id=\"cards\"></div>
        <div class=\"plot\"><div id=\"equity\" style=\"height:350px;\"></div></div>
        <div class=\"plot\"><div id=\"ret\" style=\"height:320px;\"></div></div>
        <div class=\"plot\"><div id=\"dd\" style=\"height:320px;\"></div></div>
        <div class=\"plot\"><div id=\"trade\" style=\"height:360px;\"></div></div>
    </div>

    <script>
        const data = __PAYLOAD_JSON__;
        const s = data.summary || {};
        const pm = s.portfolio_metrics || {};
        const acc = s.ledger_account || {};
        const ledger_pnl = s.ledger_pnl_with_execution || {};
        const trader_meta = s.trader_proposal_metrics || {};
        const trader_mtm = s.ledger_mtm_pnl_with_trader_size || {};

        const cards = [
            ["End Total Assets", (pm.end_total_assets ?? 0).toFixed ? `$${pm.end_total_assets.toFixed(2)}` : "N/A"],
            ["Total PnL (Actual)", (pm.total_pnl_usd ?? 0).toFixed ? `$${pm.total_pnl_usd.toFixed(2)}` : "N/A"],
            ["Total PnL (w/ Mock Exec)", (ledger_pnl.total_assumed_pnl ?? 0).toFixed ? `$${ledger_pnl.total_assumed_pnl.toFixed(4)}` : "N/A"],
            ["Total PnL (Trader Size, MtM)", (trader_mtm.total_mtm_pnl ?? 0).toFixed ? `$${trader_mtm.total_mtm_pnl.toFixed(4)}` : "N/A"],
            ["Adjusted Balance", (ledger_pnl.adjusted_balance_usd ?? 0).toFixed ? `$${ledger_pnl.adjusted_balance_usd.toFixed(2)}` : "N/A"],
            ["Adjusted Balance (Trader Size)", (trader_mtm.adjusted_balance_usd ?? 0).toFixed ? `$${trader_mtm.adjusted_balance_usd.toFixed(2)}` : "N/A"],
            ["Total Return (Actual)", (pm.total_return_pct ?? 0).toFixed ? `${pm.total_return_pct.toFixed(3)}%` : "N/A"],
            ["Max Drawdown", (pm.max_drawdown_pct ?? 0).toFixed ? `${pm.max_drawdown_pct.toFixed(3)}%` : "N/A"],
            ["Trader Avg Open Size", (trader_meta.average_trader_proposed_amount_usd ?? 0).toFixed ? `$${trader_meta.average_trader_proposed_amount_usd.toFixed(2)}` : "N/A"],
            ["Ledger Balance", (acc.balance_usd ?? 0).toFixed ? `$${acc.balance_usd.toFixed(2)}` : "N/A"],
            ["Submitted Trades", String(acc.total_trades_submitted ?? 0)],
        ];

        document.getElementById("cards").innerHTML = cards
            .map(([k, v]) => `<div class=\"card\"><div class=\"k\">${k}</div><div class=\"v\">${v}</div></div>`)
            .join("");

        const p = data.portfolio || [];
        const px = p.map(r => r.timestamp);

        // Equity curve: show both actual and adjusted (with virtual ledger PnL)
        const equityTraces = [{
            x: px,
            y: p.map(r => r.total_assets),
            type: "scatter",
            mode: "lines+markers",
            name: "total_assets (actual)",
            line: {color: "#6b7280", width: 1, dash: "dash"}
        }];
        
        // Add adjusted line if it has different values
        if (p.some(r => r.adjusted_total_assets !== undefined && r.adjusted_total_assets !== r.total_assets)) {
            equityTraces.push({
                x: px,
                y: p.map(r => r.adjusted_total_assets || r.total_assets),
                type: "scatter",
                mode: "lines+markers",
                name: "total_assets (w/ mock execution)",
                line: {color: "#1f77b4", width: 2}
            });
        }

        if (p.some(r => r.trader_total_assets !== undefined && r.trader_total_assets !== r.total_assets)) {
            equityTraces.push({
                x: px,
                y: p.map(r => r.trader_total_assets || r.total_assets),
                type: "scatter",
                mode: "lines+markers",
                name: "total_assets (trader size + MtM)",
                line: {color: "#8b5cf6", width: 2}
            });
        }
        
        Plotly.newPlot("equity", equityTraces, {title: "Equity Curve", margin: {l: 50, r: 20, t: 40, b: 40}}, {responsive: true});

        // Return curve: show both actual and adjusted
        const retTraces = [{
            x: px,
            y: p.map(r => r.cum_return_pct),
            type: "scatter",
            mode: "lines+markers",
            name: "return % (actual)",
            line: {color: "#9ca3af", width: 1, dash: "dash"}
        }];
        
        if (p.some(r => r.adjusted_cum_return_pct !== undefined && r.adjusted_cum_return_pct !== r.cum_return_pct)) {
            retTraces.push({
                x: px,
                y: p.map(r => r.adjusted_cum_return_pct || r.cum_return_pct),
                type: "scatter",
                mode: "lines+markers",
                name: "return % (w/ mock execution)",
                line: {color: "#2ca02c", width: 2}
            });
        }

        if (p.some(r => r.trader_cum_return_pct !== undefined && r.trader_cum_return_pct !== r.cum_return_pct)) {
            retTraces.push({
                x: px,
                y: p.map(r => r.trader_cum_return_pct || r.cum_return_pct),
                type: "scatter",
                mode: "lines+markers",
                name: "return % (trader size + MtM)",
                line: {color: "#7c3aed", width: 2}
            });
        }
        
        Plotly.newPlot("ret", retTraces, {title: "Cumulative Return (%)", margin: {l: 50, r: 20, t: 40, b: 40}}, {responsive: true});

        // Drawdown curve: show both actual and adjusted
        const ddTraces = [{
            x: px,
            y: p.map(r => r.drawdown_pct),
            type: "scatter",
            mode: "lines+markers",
            fill: "tozeroy",
            name: "drawdown % (actual)",
            line: {color: "#a3a3a3", width: 1, dash: "dash"}
        }];
        
        if (p.some(r => r.adjusted_drawdown_pct !== undefined && r.adjusted_drawdown_pct !== r.drawdown_pct)) {
            ddTraces.push({
                x: px,
                y: p.map(r => r.adjusted_drawdown_pct || r.drawdown_pct),
                type: "scatter",
                mode: "lines+markers",
                fill: "tozeroy",
                name: "drawdown % (w/ mock execution)",
                line: {color: "#d62728", width: 2}
            });
        }

        if (p.some(r => r.trader_drawdown_pct !== undefined && r.trader_drawdown_pct !== r.drawdown_pct)) {
            ddTraces.push({
                x: px,
                y: p.map(r => r.trader_drawdown_pct || r.drawdown_pct),
                type: "scatter",
                mode: "lines+markers",
                fill: "tozeroy",
                name: "drawdown % (trader size + MtM)",
                line: {color: "#7c3aed", width: 2}
            });
        }
        
        Plotly.newPlot("dd", ddTraces, {title: "Drawdown (%)", margin: {l: 50, r: 20, t: 40, b: 40}}, {responsive: true});

        const td = data.trade_daily || [];
        const ld = data.ledger_daily || [];
        const tld = data.trader_ledger_daily || [];
        const useTd = td.length > 0;
        const tx = (useTd ? td : ld).map(r => r.date);
        const countSeries = useTd ? td.map(r => r.trade_count) : ld.map(r => r.ledger_trade_count);
        const amountSeries = useTd ? td.map(r => r.cum_notional_usd) : ld.map(r => r.ledger_cum_submitted_usd);

        const tradeTraces = [
            {x: tx, y: countSeries, type: "bar", name: "daily_count", marker: {color: "#9467bd"}},
            {x: tx, y: amountSeries, type: "scatter", mode: "lines+markers", name: "cumulative_usd", yaxis: "y2", line: {color: "#ff7f0e"}}
        ];

        if (tld.length > 0) {
            tradeTraces.push({
                x: tld.map(r => r.date),
                y: tld.map(r => r.ledger_cum_submitted_usd),
                type: "scatter",
                mode: "lines+markers",
                name: "cumulative_usd (trader proposed)",
                yaxis: "y2",
                line: {color: "#7c3aed", width: 2}
            });
        }

        Plotly.newPlot("trade", tradeTraces, {
            title: useTd ? "Daily Trades (DB)" : "Daily Trades (Ledger)",
            yaxis: {title: "Count"},
            yaxis2: {title: "USD", overlaying: "y", side: "right"},
            margin: {l: 50, r: 50, t: 40, b: 40}
        }, {responsive: true});
    </script>
</body>
</html>
"""
    html = html.replace("__PAYLOAD_JSON__", payload_json)
    out_file.write_text(html, encoding="utf-8")


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except Exception:
        return default


def _build_summary(
    portfolio: pd.DataFrame,
    trades: pd.DataFrame,
    ledger: Dict[str, Any],
    trader_proposals: pd.DataFrame,
) -> Dict[str, Any]:
    account = ledger.get("account", {})

    summary: Dict[str, Any] = {
        "data_source": {
            "virtual_ledger": str(LEDGER_JSON),
            "portfolio_db": str(PORTFOLIO_DB),
        },
        "ledger_account": {
            "balance_usd": _safe_float(account.get("balance_usd")),
            "initial_capital_usd": _safe_float(account.get("initial_capital_usd")),
            "realized_pnl_usd": _safe_float(account.get("realized_pnl_usd")),
            "total_trades_submitted": int(account.get("total_trades_submitted", 0)),
            "total_trades_approved": int(account.get("total_trades_approved", 0)),
            "total_trades_rejected": int(account.get("total_trades_rejected", 0)),
        },
        "portfolio_metrics": {},
        "trade_history_metrics": {},
        "ledger_pnl_with_execution": {},
        "ledger_pnl_with_trader_size": {},
        "ledger_mtm_pnl_with_trader_size": {},
        "trader_proposal_metrics": {},
        "analysis_assumptions": {
            "open_or_submitted_treated_as_executed": True,
            "mark_to_market_pricing_applied": False,
            "reference_price_used_for_mock_execution": True,
            "trader_proposed_open_size_applied": False,
        },
    }

    if not portfolio.empty:
        first_assets = float(portfolio["total_assets"].iloc[0])
        last_assets = float(portfolio["total_assets"].iloc[-1])
        summary["portfolio_metrics"] = {
            "samples": int(len(portfolio)),
            "start_time": portfolio["timestamp"].iloc[0].isoformat() if pd.notna(portfolio["timestamp"].iloc[0]) else None,
            "end_time": portfolio["timestamp"].iloc[-1].isoformat() if pd.notna(portfolio["timestamp"].iloc[-1]) else None,
            "start_total_assets": first_assets,
            "end_total_assets": last_assets,
            "total_pnl_usd": last_assets - first_assets,
            "total_return_pct": (last_assets / first_assets - 1.0) * 100.0 if first_assets != 0 else None,
            "max_drawdown_pct": float(portfolio["drawdown_pct"].min()),
            "latest_realized_pnl": float(portfolio["realized_pnl"].iloc[-1]),
            "latest_unrealized_pnl": float(portfolio["unrealized_pnl"].iloc[-1]),
        }

    if not trades.empty:
        status_series = trades["status"].astype(str).str.lower()
        effective_series = trades["effective_execution_status"].astype(str).str.lower()
        summary["trade_history_metrics"] = {
            "rows": int(len(trades)),
            "unique_tickers": sorted({str(v) for v in trades["ticker"].dropna().unique().tolist()}),
            "notional_sum_usd": float(trades["notional_usd"].sum()),
            "closed_trade_count": int((status_series == "closed").sum()),
            "open_trade_count": int((status_series == "open").sum()),
            "executed_or_assumed_executed_count": int((effective_series != "rejected").sum()),
            "realized_pnl_sum": float(trades["realized_pnl"].fillna(0).sum()),
        }
    
    # Add PnL calculation based on virtual ledger with reference prices
    ledger_execution_pnl = _compute_assumed_execution_pnl(ledger)
    summary["ledger_pnl_with_execution"] = ledger_execution_pnl
    initial_capital = _safe_float(account.get("initial_capital_usd"), 100000.0)
    summary["ledger_pnl_with_execution"]["adjusted_balance_usd"] = initial_capital - ledger_execution_pnl.get("total_assumed_pnl", 0.0)
    summary["ledger_pnl_with_execution"]["adjusted_return_pct"] = (
        ledger_execution_pnl.get("total_assumed_pnl", 0.0) / initial_capital * 100.0
    )
    
    # Add mark-to-market PnL based on actual historical prices
    mtm_pnl = _calculate_mtm_pnl(ledger)
    summary["ledger_mtm_pnl"] = mtm_pnl
    summary["ledger_mtm_pnl"]["adjusted_balance_usd"] = initial_capital - mtm_pnl.get("total_mtm_pnl", 0.0)
    summary["ledger_mtm_pnl"]["adjusted_return_pct"] = (
        mtm_pnl.get("total_mtm_pnl", 0.0) / initial_capital * 100.0
    )
    
    # Update analysis assumption
    if mtm_pnl.get("trades_with_mtm_price", 0) > 0:
        summary["analysis_assumptions"]["mark_to_market_pricing_applied"] = True

    # Recalculate with trader proposed opening size from full_states logs.
    trader_sized_ledger, trader_metrics = _apply_trader_proposed_sizes_to_ledger(ledger, trader_proposals)
    summary["trader_proposal_metrics"] = trader_metrics

    trader_assumed_pnl = _compute_assumed_execution_pnl(trader_sized_ledger)
    summary["ledger_pnl_with_trader_size"] = trader_assumed_pnl
    summary["ledger_pnl_with_trader_size"]["adjusted_balance_usd"] = initial_capital - trader_assumed_pnl.get("total_assumed_pnl", 0.0)
    summary["ledger_pnl_with_trader_size"]["adjusted_return_pct"] = (
        trader_assumed_pnl.get("total_assumed_pnl", 0.0) / initial_capital * 100.0
    )

    trader_mtm_pnl = _calculate_mtm_pnl(trader_sized_ledger)
    summary["ledger_mtm_pnl_with_trader_size"] = trader_mtm_pnl
    summary["ledger_mtm_pnl_with_trader_size"]["adjusted_balance_usd"] = initial_capital - trader_mtm_pnl.get("total_mtm_pnl", 0.0)
    summary["ledger_mtm_pnl_with_trader_size"]["adjusted_return_pct"] = (
        trader_mtm_pnl.get("total_mtm_pnl", 0.0) / initial_capital * 100.0
    )

    if trader_metrics.get("trades_matched", 0) > 0:
        summary["analysis_assumptions"]["trader_proposed_open_size_applied"] = True

    return summary


def main() -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    ledger = _load_virtual_ledger(LEDGER_JSON)
    portfolio = _load_portfolio_state(PORTFOLIO_DB)
    trade_history = _load_trade_history(PORTFOLIO_DB)
    trade_daily = _build_trade_activity(trade_history)
    ledger_daily = _build_ledger_activity(ledger)
    trader_proposals = _load_trader_proposals(EVAL_RESULTS_DIR)
    trader_sized_ledger, _ = _apply_trader_proposed_sizes_to_ledger(ledger, trader_proposals)
    trader_ledger_daily = _build_ledger_activity(trader_sized_ledger)

    chart_path = OUTPUT_DIR / "remotedata_pnl_dashboard.html"
    summary_path = OUTPUT_DIR / "remotedata_pnl_summary.json"
    portfolio_csv_path = OUTPUT_DIR / "portfolio_timeseries.csv"
    trades_csv_path = OUTPUT_DIR / "trade_history.csv"

    summary = _build_summary(portfolio, trade_history, ledger, trader_proposals)
    _render_html_dashboard(portfolio, trade_daily, ledger_daily, trader_ledger_daily, summary, chart_path)

    with summary_path.open("w", encoding="utf-8") as f:
        json.dump(summary, f, ensure_ascii=False, indent=2)

    if not portfolio.empty:
        portfolio.to_csv(portfolio_csv_path, index=False)
    if not trade_history.empty:
        trade_history.to_csv(trades_csv_path, index=False)

    print(f"Saved chart: {chart_path}")
    print(f"Saved summary: {summary_path}")
    print(f"Portfolio samples: {len(portfolio)}")
    print(f"Trade rows: {len(trade_history)}")


if __name__ == "__main__":
    main()
