import json
from pathlib import Path
from typing import Any, Dict, Optional

import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
OUTPUT_DIR = ROOT / "visualisation" / "remotedata_pnl"
DATA_CACHE_DIR = ROOT / "tradingagents" / "dataflows" / "data_cache" / "prices"
EVAL_RESULTS_DIR = ROOT / "eval_results"
REMOTE_EVAL_RESULTS_DIR = ROOT / "remotedata" / "results" / "eval_results"

PAIR_MAPPING = {
    "BTCUSD": "BTCUSDT_ohlcv.csv",
    "ETHUSD": "ETHUSDT_ohlcv.csv",
    "SOLUSD": "SOLUSDT_ohlcv.csv",
    "WETH/USDC": "WETH_USDC_ohlcv.csv",
    "XBTUSD": "BTCUSDT_ohlcv.csv",
}

SIZE_RULES_USD = {
    220: 10000.0,  # 10% of 100000
    22: 5000.0,    # 5% of 100000
}

PAIR_ALIAS = {
    "ETHUSD": "ETH_COMBINED",
    "WETH/USDC": "ETH_COMBINED",
}


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except Exception:
        return default


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


def _load_cached_prices(pair: str) -> Optional[pd.DataFrame]:
    cache_file = PAIR_MAPPING.get(pair)
    if not cache_file:
        return None

    file_path = DATA_CACHE_DIR / cache_file
    if not file_path.exists():
        return None

    try:
        df = pd.read_csv(file_path, parse_dates=["datetime"])
        df["timestamp"] = pd.to_datetime(df["datetime"], utc=True, errors="coerce")
        df["close"] = pd.to_numeric(df["close"], errors="coerce")
        df = df.dropna(subset=["timestamp", "close"]).sort_values("timestamp").reset_index(drop=True)
        return df
    except Exception:
        return None


def _price_at_or_before(prices: pd.DataFrame, ts: pd.Timestamp) -> Optional[float]:
    x = prices[prices["timestamp"] <= ts]
    if x.empty:
        return None
    return float(x.iloc[-1]["close"])


def _price_at_or_after(prices: pd.DataFrame, ts: pd.Timestamp) -> Optional[float]:
    x = prices[prices["timestamp"] >= ts]
    if x.empty:
        return None
    return float(x.iloc[0]["close"])


def _estimate_exit_price(prices: pd.DataFrame, entry_price: float, hold_hours: int) -> float:
    """Estimate exit when future bars are unavailable.

    Use recent momentum as a conservative proxy for forward move.
    """
    if prices.empty or entry_price <= 0:
        return entry_price

    lookback = max(6, min(hold_hours, 72))
    closes = prices["close"].tail(lookback + 1)
    if len(closes) < 2:
        return entry_price

    first = float(closes.iloc[0])
    last = float(closes.iloc[-1])
    if first <= 0:
        return entry_price

    momentum_ret = (last - first) / first
    capped_ret = max(-0.03, min(0.03, momentum_ret))
    return entry_price * (1.0 + capped_ret)


def _load_trader_decisions(eval_root: Path) -> pd.DataFrame:
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
            decision_obj = _safe_json_loads(state.get("trader_investment_decision"))

            if not pair or not trade_date or not decision_obj:
                continue

            action = str(decision_obj.get("action", "")).strip().upper()
            amount_scaled = int(round(_safe_float(decision_obj.get("amountUsdScaled"), 0.0)))

            rows.append(
                {
                    "timestamp": trade_date,
                    "pair": pair,
                    "action": action,
                    "amount_usd_scaled": amount_scaled,
                    "source_file": str(path),
                }
            )

    if not rows:
        return pd.DataFrame()

    df = pd.DataFrame(rows)
    df["timestamp"] = pd.to_datetime(df["timestamp"], utc=True, errors="coerce")
    df = df.dropna(subset=["timestamp"]).sort_values("timestamp").reset_index(drop=True)
    return df


def _apply_size_rules(decisions: pd.DataFrame) -> tuple[pd.DataFrame, Dict[str, Any]]:
    if decisions.empty:
        return decisions.copy(), {
            "raw_decisions": 0,
            "buy_sell_decisions": 0,
            "used_decisions": 0,
            "skipped_unmapped_scaled": 0,
            "scaled_22_count": 0,
            "scaled_220_count": 0,
            "buy_count": 0,
            "sell_count": 0,
        }

    d = decisions.copy()
    d = d[d["action"].isin(["BUY", "SELL"])].copy()
    d["amount_usd"] = d["amount_usd_scaled"].map(SIZE_RULES_USD)

    raw_count = len(decisions)
    buy_sell_count = len(d)
    used = d.dropna(subset=["amount_usd"]).copy()

    stats = {
        "raw_decisions": int(raw_count),
        "buy_sell_decisions": int(buy_sell_count),
        "used_decisions": int(len(used)),
        "skipped_unmapped_scaled": int(buy_sell_count - len(used)),
        "scaled_22_count": int((used["amount_usd_scaled"] == 22).sum()),
        "scaled_220_count": int((used["amount_usd_scaled"] == 220).sum()),
        "buy_count": int((used["action"] == "BUY").sum()),
        "sell_count": int((used["action"] == "SELL").sum()),
    }

    used = used.sort_values("timestamp").reset_index(drop=True)
    return used, stats


def _backtest_from_decisions(
    decisions: pd.DataFrame,
    initial_capital_usd: float = 100000.0,
    hold_hours: int = 24,
) -> tuple[pd.DataFrame, Dict[str, Any]]:
    if decisions.empty:
        return pd.DataFrame(), {
            "initial_capital_usd": initial_capital_usd,
            "end_equity_usd": initial_capital_usd,
            "total_pnl_usd": 0.0,
            "total_return_pct": 0.0,
            "max_drawdown_pct": 0.0,
            "trades_executed": 0,
            "trades_skipped_no_price": 0,
            "win_rate_pct": 0.0,
            "average_trade_pnl_usd": 0.0,
            "hold_hours": hold_hours,
        }

    price_cache: Dict[str, Optional[pd.DataFrame]] = {}

    def get_prices(pair: str) -> Optional[pd.DataFrame]:
        if pair not in price_cache:
            price_cache[pair] = _load_cached_prices(pair)
        return price_cache[pair]

    equity = float(initial_capital_usd)
    rows = []
    wins = 0
    executed = 0
    skipped = 0

    for _, row in decisions.iterrows():
        pair = str(row["pair"])
        action = str(row["action"])  # BUY / SELL
        ts = pd.to_datetime(row["timestamp"], utc=True, errors="coerce")
        amount = _safe_float(row["amount_usd"], 0.0)

        if pd.isna(ts) or amount <= 0:
            skipped += 1
            continue

        prices = get_prices(pair)
        if prices is None or prices.empty:
            skipped += 1
            continue

        entry = _price_at_or_before(prices, ts)
        # Use fixed forward horizon to convert decision into realized PnL sample.
        exit_ts = ts + pd.Timedelta(hours=hold_hours)
        exit_price = _price_at_or_after(prices, exit_ts)

        if exit_price is None and entry is not None:
            exit_price = _estimate_exit_price(prices, entry, hold_hours)

        if entry is None or exit_price is None or entry <= 0:
            skipped += 1
            continue

        if action == "BUY":
            pnl = amount * (exit_price - entry) / entry
        else:  # SELL
            pnl = amount * (entry - exit_price) / entry

        executed += 1
        if pnl > 0:
            wins += 1

        equity += pnl
        rows.append(
            {
                "timestamp": ts,
                "pair": pair,
                "action": action,
                "amount_usd_scaled": int(row["amount_usd_scaled"]),
                "amount_usd": amount,
                "entry_price": entry,
                "exit_price": exit_price,
                "trade_pnl_usd": pnl,
                "equity_usd": equity,
            }
        )

    if not rows:
        return pd.DataFrame(), {
            "initial_capital_usd": initial_capital_usd,
            "end_equity_usd": initial_capital_usd,
            "total_pnl_usd": 0.0,
            "total_return_pct": 0.0,
            "max_drawdown_pct": 0.0,
            "trades_executed": 0,
            "trades_skipped_no_price": skipped,
            "win_rate_pct": 0.0,
            "average_trade_pnl_usd": 0.0,
            "hold_hours": hold_hours,
        }

    trades = pd.DataFrame(rows).sort_values("timestamp").reset_index(drop=True)
    trades["cum_return_pct"] = (trades["equity_usd"] / initial_capital_usd - 1.0) * 100.0
    trades["running_peak"] = trades["equity_usd"].cummax()
    trades["drawdown_pct"] = (trades["equity_usd"] / trades["running_peak"] - 1.0) * 100.0

    total_pnl = float(trades["trade_pnl_usd"].sum())
    end_equity = float(trades["equity_usd"].iloc[-1])

    summary = {
        "initial_capital_usd": float(initial_capital_usd),
        "end_equity_usd": end_equity,
        "total_pnl_usd": total_pnl,
        "total_return_pct": (end_equity / initial_capital_usd - 1.0) * 100.0,
        "max_drawdown_pct": float(trades["drawdown_pct"].min()),
        "trades_executed": int(executed),
        "trades_skipped_no_price": int(skipped),
        "win_rate_pct": (wins / executed * 100.0) if executed > 0 else 0.0,
        "average_trade_pnl_usd": total_pnl / executed if executed > 0 else 0.0,
        "hold_hours": int(hold_hours),
    }
    return trades, summary


def _resample_curve(trades: pd.DataFrame, freq: str = "1H") -> pd.DataFrame:
    if trades.empty:
        return pd.DataFrame()

    curve = trades[["timestamp", "equity_usd", "cum_return_pct", "drawdown_pct"]].copy()
    curve = curve.set_index("timestamp").sort_index()
    sampled = curve.resample(freq).last().ffill().reset_index()
    return sampled


def _build_daily_notional(trades: pd.DataFrame) -> pd.DataFrame:
    if trades.empty:
        return pd.DataFrame()

    x = trades.copy()
    x["date"] = x["timestamp"].dt.floor("D")
    out = (
        x.groupby("date", as_index=False)
        .agg(
            trade_count=("action", "count"),
            notional_usd=("amount_usd", "sum"),
            pnl_usd=("trade_pnl_usd", "sum"),
        )
        .sort_values("date")
    )
    out["cum_notional_usd"] = out["notional_usd"].cumsum()
    return out


def _normalize_pair(pair: str) -> str:
    return PAIR_ALIAS.get(str(pair), str(pair))


def _build_pair_curves(trades: pd.DataFrame) -> pd.DataFrame:
    if trades.empty:
        return pd.DataFrame()

    x = trades.copy()
    x["pair_group"] = x["pair"].map(_normalize_pair)
    x = x.sort_values("timestamp")
    x["pair_cum_pnl_usd"] = x.groupby("pair_group")["trade_pnl_usd"].cumsum()

    out = x[["timestamp", "pair_group", "pair_cum_pnl_usd"]].copy()
    # Resample per pair to keep dashboard readable and aligned.
    frames = []
    for pair_name, g in out.groupby("pair_group"):
        r = g.set_index("timestamp").sort_index().resample("1h").last().ffill().reset_index()
        r["pair_group"] = pair_name
        frames.append(r)

    if not frames:
        return pd.DataFrame()
    return pd.concat(frames, ignore_index=True)


def _render_html_dashboard(
    sampled_curve: pd.DataFrame,
    daily: pd.DataFrame,
    pair_curves: pd.DataFrame,
    summary: Dict[str, Any],
    out_file: Path,
) -> None:
    def to_records(df: pd.DataFrame) -> list[dict[str, Any]]:
        if df.empty:
            return []
        x = df.copy()
        for col in x.columns:
            if pd.api.types.is_datetime64_any_dtype(x[col]):
                x[col] = x[col].dt.strftime("%Y-%m-%d %H:%M:%S")
        return x.where(pd.notna(x), None).to_dict(orient="records")

    payload = {
        "curve": to_records(sampled_curve),
        "daily": to_records(daily),
        "pair_curves": to_records(pair_curves),
        "summary": summary,
    }

    payload_json = json.dumps(payload, ensure_ascii=False)

    html = """<!doctype html>
<html lang=\"en\">
<head>
    <meta charset=\"utf-8\" />
    <meta name=\"viewport\" content=\"width=device-width,initial-scale=1\" />
    <title>RemoteData Decision PnL</title>
    <script src=\"https://cdn.plot.ly/plotly-2.35.2.min.js\"></script>
    <style>
        body { margin: 0; font-family: Segoe UI, Helvetica, Arial, sans-serif; background: #f7f8fb; color: #111827; }
        .wrap { max-width: 1100px; margin: 20px auto; padding: 0 12px 20px; }
        h1 { margin: 0 0 8px; font-size: 26px; }
        .sub { margin: 0 0 14px; color: #4b5563; }
        .grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr)); gap: 10px; margin-bottom: 12px; }
        .card { background: white; border: 1px solid #e5e7eb; border-radius: 10px; padding: 10px; }
        .k { font-size: 12px; color: #6b7280; }
        .v { font-size: 19px; font-weight: 700; margin-top: 4px; }
        .plot { background: white; border: 1px solid #e5e7eb; border-radius: 10px; padding: 6px; margin-bottom: 10px; }
    </style>
</head>
<body>
    <div class=\"wrap\">
        <h1>Decision-Based PnL Dashboard</h1>
        <p class=\"sub\">Only from full_states_log trader_investment_decision, with size mapping 220->10%, 22->5%.</p>
        <div class=\"grid\" id=\"cards\"></div>
        <div class=\"plot\"><div id=\"equity\" style=\"height:340px;\"></div></div>
        <div class=\"plot\"><div id=\"ret\" style=\"height:320px;\"></div></div>
        <div class=\"plot\"><div id=\"pair\" style=\"height:340px;\"></div></div>
        <div class=\"plot\"><div id=\"notional\" style=\"height:320px;\"></div></div>
    </div>

    <script>
        const data = __PAYLOAD_JSON__;
        const s = data.summary || {};
        const m = s.backtest_metrics || {};
        const d = s.decision_metrics || {};

        const cards = [
            ["Initial Capital", `$${(m.initial_capital_usd ?? 0).toFixed(2)}`],
            ["End Equity", `$${(m.end_equity_usd ?? 0).toFixed(2)}`],
            ["Total PnL", `$${(m.total_pnl_usd ?? 0).toFixed(2)}`],
            ["Total Return", `${(m.total_return_pct ?? 0).toFixed(3)}%`],
            ["Max Drawdown", `${(m.max_drawdown_pct ?? 0).toFixed(3)}%`],
            ["Executed Trades", String(m.trades_executed ?? 0)],
            ["Used Decisions", String(d.used_decisions ?? 0)],
            ["22 Count / 220 Count", `${d.scaled_22_count ?? 0} / ${d.scaled_220_count ?? 0}`],
        ];

        document.getElementById("cards").innerHTML = cards
            .map(([k, v]) => `<div class=\"card\"><div class=\"k\">${k}</div><div class=\"v\">${v}</div></div>`)
            .join("");

        const curve = data.curve || [];
        const cx = curve.map(r => r.timestamp);

        Plotly.newPlot("equity", [{
            x: cx,
            y: curve.map(r => r.equity_usd),
            type: "scatter",
            mode: "lines",
            name: "equity_usd",
            line: {color: "#2563eb", width: 2}
        }], {
            title: "Resampled Equity Curve",
            margin: {l: 50, r: 20, t: 40, b: 40}
        }, {responsive: true});

        Plotly.newPlot("ret", [
            {
                x: cx,
                y: curve.map(r => r.cum_return_pct),
                type: "scatter",
                mode: "lines",
                name: "cum_return_pct",
                line: {color: "#059669", width: 2}
            },
            {
                x: cx,
                y: curve.map(r => r.drawdown_pct),
                type: "scatter",
                mode: "lines",
                name: "drawdown_pct",
                line: {color: "#dc2626", width: 2}
            }
        ], {
            title: "Return and Drawdown (%)",
            margin: {l: 50, r: 20, t: 40, b: 40}
        }, {responsive: true});

        const pairCurves = data.pair_curves || [];
        const groups = [...new Set(pairCurves.map(r => r.pair_group))];
        const palette = ["#2563eb", "#dc2626", "#059669", "#7c3aed", "#f59e0b", "#0ea5e9"];
        const pairTraces = groups.map((g, idx) => {
            const rows = pairCurves.filter(r => r.pair_group === g);
            return {
                x: rows.map(r => r.timestamp),
                y: rows.map(r => r.pair_cum_pnl_usd),
                type: "scatter",
                mode: "lines",
                name: g,
                line: {color: palette[idx % palette.length], width: 2}
            };
        });

        Plotly.newPlot("pair", pairTraces, {
            title: "PnL Curve by Pair (ETHUSD + WETH/USDC merged)",
            margin: {l: 50, r: 20, t: 40, b: 40},
            yaxis: {title: "Cumulative PnL (USD)"}
        }, {responsive: true});

        const daily = data.daily || [];
        Plotly.newPlot("notional", [
            {
                x: daily.map(r => r.date),
                y: daily.map(r => r.notional_usd),
                type: "bar",
                name: "daily_notional_usd",
                marker: {color: "#7c3aed"}
            },
            {
                x: daily.map(r => r.date),
                y: daily.map(r => r.pnl_usd),
                type: "scatter",
                mode: "lines+markers",
                name: "daily_pnl_usd",
                yaxis: "y2",
                line: {color: "#f59e0b", width: 2}
            }
        ], {
            title: "Daily Notional and PnL",
            yaxis: {title: "Notional (USD)"},
            yaxis2: {title: "PnL (USD)", overlaying: "y", side: "right"},
            margin: {l: 50, r: 50, t: 40, b: 40}
        }, {responsive: true});
    </script>
</body>
</html>
"""

    html = html.replace("__PAYLOAD_JSON__", payload_json)
    out_file.write_text(html, encoding="utf-8")


def main() -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    source_root = REMOTE_EVAL_RESULTS_DIR if REMOTE_EVAL_RESULTS_DIR.exists() else EVAL_RESULTS_DIR
    raw_decisions = _load_trader_decisions(source_root)
    decisions, decision_metrics = _apply_size_rules(raw_decisions)

    trades, backtest_metrics = _backtest_from_decisions(
        decisions,
        initial_capital_usd=100000.0,
        hold_hours=24,
    )

    sampled_curve = _resample_curve(trades, freq="1h")
    daily = _build_daily_notional(trades)
    pair_curves = _build_pair_curves(trades)

    pair_metrics: Dict[str, Any] = {}
    if not pair_curves.empty:
        last_rows = (
            pair_curves.sort_values("timestamp")
            .groupby("pair_group", as_index=False)
            .tail(1)
        )
        for _, row in last_rows.iterrows():
            pair_metrics[str(row["pair_group"])] = {
                "final_cum_pnl_usd": round(_safe_float(row["pair_cum_pnl_usd"], 0.0), 6)
            }

    summary = {
        "data_source": {
            "eval_results_root": str(source_root),
            "decision_field": "trader_investment_decision",
            "action_used": ["BUY", "SELL"],
            "size_rules_usd": {"220": 10000.0, "22": 5000.0},
            "sampling": "1h",
        },
        "decision_metrics": decision_metrics,
        "backtest_metrics": backtest_metrics,
        "pair_metrics": pair_metrics,
        "pair_alias": {
            "ETHUSD": "ETH_COMBINED",
            "WETH/USDC": "ETH_COMBINED",
        },
    }

    chart_path = OUTPUT_DIR / "remotedata_pnl_dashboard.html"
    summary_path = OUTPUT_DIR / "remotedata_pnl_summary.json"
    trades_csv_path = OUTPUT_DIR / "decision_trade_pnl.csv"
    curve_csv_path = OUTPUT_DIR / "equity_curve_1h.csv"
    pair_curve_csv_path = OUTPUT_DIR / "pair_pnl_curve_1h.csv"

    _render_html_dashboard(sampled_curve, daily, pair_curves, summary, chart_path)
    summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")

    if not trades.empty:
        trades.to_csv(trades_csv_path, index=False)
    if not sampled_curve.empty:
        sampled_curve.to_csv(curve_csv_path, index=False)
    if not pair_curves.empty:
        pair_curves.to_csv(pair_curve_csv_path, index=False)

    print(f"Saved chart: {chart_path}")
    print(f"Saved summary: {summary_path}")
    print(f"Decisions used: {decision_metrics.get('used_decisions', 0)}")
    print(f"Trades executed: {backtest_metrics.get('trades_executed', 0)}")


if __name__ == "__main__":
    main()
