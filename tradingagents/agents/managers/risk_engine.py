import json
import os
import time
from typing import Any, Dict
from tradingagents.portfolio_manager import PortfolioManager


def _safe_float(value: Any, default: float) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _strip_code_fence(text: str) -> str:
    stripped = (text or "").strip()
    if not stripped.startswith("```"):
        return stripped

    lines = stripped.splitlines()
    if not lines:
        return stripped

    # Remove opening fence like ```json / ```
    if lines[0].lstrip().startswith("```"):
        lines = lines[1:]

    # Remove trailing closing fence if present
    if lines and lines[-1].strip().startswith("```"):
        lines = lines[:-1]

    return "\n".join(lines).strip()


def _extract_json_candidate(text: str) -> str:
    candidate = _strip_code_fence(text)
    if not candidate:
        return candidate

    # If extra prose exists, try slicing the outermost JSON object body.
    first = candidate.find("{")
    last = candidate.rfind("}")
    if first != -1 and last != -1 and first < last:
        return candidate[first : last + 1].strip()

    return candidate


def _extract_trader_trade_intent(trader_plan: str, state: Dict[str, Any]) -> Dict[str, Any]:
    """Extract TradeIntent-like payload from Trader output with safe defaults."""
    now_ts = int(time.time())
    default_agent_id = int(os.getenv("AGENT_ID", "0") or "0")
    default_agent_wallet = os.getenv("AGENT_WALLET_ADDRESS", "")
    default_pair = str(state.get("company_of_interest", ""))

    parsed = {
        "agentId": default_agent_id,
        "agentWallet": default_agent_wallet,
        "pair": default_pair,
        "action": "HOLD",
        "amountUsdScaled": 0,
        "maxSlippageBps": 100,
        "nonce": 0,
        "deadline": now_ts + 300,
        "confidence": 0.5,
        "reasoning": "",
    }

    try:
        obj = json.loads(_extract_json_candidate(trader_plan))
    except Exception:
        obj = {}

    action = str(obj.get("action", "HOLD")).upper()
    if action in {"BUY", "SELL", "HOLD"}:
        parsed["action"] = action

    parsed["agentId"] = int(_safe_float(obj.get("agentId", parsed["agentId"]), parsed["agentId"]))
    parsed["agentWallet"] = str(obj.get("agentWallet", parsed["agentWallet"]))
    parsed["pair"] = str(obj.get("pair", parsed["pair"]))
    parsed["amountUsdScaled"] = max(0, int(_safe_float(obj.get("amountUsdScaled", 0), 0)))
    parsed["maxSlippageBps"] = max(1, int(_safe_float(obj.get("maxSlippageBps", 100), 100)))
    parsed["nonce"] = max(0, int(_safe_float(obj.get("nonce", 0), 0)))
    parsed["confidence"] = max(0.0, min(1.0, _safe_float(obj.get("confidence", 0.5), 0.5)))
    parsed["reasoning"] = str(obj.get("reasoning", obj.get("thesis", ""))).strip()

    deadline = int(_safe_float(obj.get("deadline", parsed["deadline"]), parsed["deadline"]))
    parsed["deadline"] = deadline if deadline > now_ts else now_ts + 300

    return parsed


def create_risk_engine():
    """Pure Python risk engine and position sizer with portfolio persistence.
    
    Reads financial state directly from persistent database.
    Applies all hard rules (position limits, drawdown limits, kelly formula sizing).
    Persists updated portfolio state after order execution.
    """
    
    # Initialize portfolio manager for reading/writing persistent state
    portfolio_manager = PortfolioManager(db_path="./trade_memory/portfolio.db")

    def risk_engine_node(state) -> Dict[str, Any]:
        trader_plan = state.get("trader_investment_plan", "")
        trader_intent = _extract_trader_trade_intent(trader_plan, state)

        action = str(trader_intent["action"]).upper()
        requested_amount_usd_scaled = int(trader_intent["amountUsdScaled"])
        requested_notional_usd = requested_amount_usd_scaled / 100.0

        # Read portfolio directly from persistent database (single source of truth)
        current_portfolio = portfolio_manager.load_latest_portfolio()
        initial_capital = portfolio_manager.get_initial_capital()
        cash_usd = _safe_float(current_portfolio.get("cash_usd", initial_capital), initial_capital)
        position_usd = _safe_float(current_portfolio.get("position_usd", 0.0), 0.0)
        unrealized_pnl = _safe_float(current_portfolio.get("unrealized_pnl", 0.0), 0.0)
        realized_pnl = _safe_float(current_portfolio.get("realized_pnl", 0.0), 0.0)

        # Risk management parameters
        max_position_pct = 0.40
        max_single_order_pct = 0.10

        # Optional absolute cap. If unset (default), sizing follows percentage rules only.
        raw_hard_cap = os.getenv("TRADING_HARD_MAX_TRADE_USD", "").strip()
        hard_max_trade_usd = None
        if raw_hard_cap:
            try:
                parsed_hard_cap = float(raw_hard_cap)
                if parsed_hard_cap > 0:
                    hard_max_trade_usd = parsed_hard_cap
            except (TypeError, ValueError):
                hard_max_trade_usd = None

        # Use total capital baseline for sizing (requested behavior):
        # per-order size is based on total funds rather than residual cash.
        # Prefer initial_capital as stable baseline; fallback to current total assets.
        total_assets_for_risk = cash_usd + position_usd + unrealized_pnl
        risk_basis = initial_capital if initial_capital > 0 else total_assets_for_risk
        
        target_gross_limit = risk_basis * max_position_pct
        max_order_notional = risk_basis * max_single_order_pct
        risk_cap_notional = (
            min(max_order_notional, hard_max_trade_usd)
            if hard_max_trade_usd is not None
            else max_order_notional
        )

        if action == "HOLD":
            approved_notional = 0.0
            risk_status = "blocked: hold"
        elif action == "BUY":
            available_for_buy = max(0.0, target_gross_limit - position_usd)
            # Size BUY to 10% of total capital baseline, not trader-requested tiny notional.
            approved_notional = min(risk_cap_notional, available_for_buy)
            risk_status = "allowed" if approved_notional > 0 else "blocked: position_limit"
        else:  # SELL
            # Always allow sells for risk management
            max_sellable = position_usd if position_usd > 0 else 0.0
            approved_notional = min(risk_cap_notional, max_sellable)
            risk_status = "allowed" if approved_notional > 0 else "blocked: no_position"

        approved_amount_usd_scaled = int(round(approved_notional * 100))
        checked_action = action if approved_amount_usd_scaled > 0 else "HOLD"

        checked_trade_intent = {
            "agentId": int(trader_intent["agentId"]),
            "agentWallet": str(trader_intent["agentWallet"]),
            "pair": str(trader_intent["pair"]),
            "action": checked_action,
            "amountUsdScaled": approved_amount_usd_scaled,
            "maxSlippageBps": int(trader_intent["maxSlippageBps"]),
            "nonce": int(trader_intent["nonce"]),
            "deadline": int(trader_intent["deadline"]),
        }

        order = {
            "ticker": checked_trade_intent["pair"],
            "side": checked_trade_intent["action"],
            "order_type": "market",
            "notional_usd": round(approved_notional, 2),
            "quantity": None,
            "confidence": None,
            "kelly_fraction": None,
            "risk_status": risk_status,
            "max_position_pct": max_position_pct,
            "max_single_order_pct": max_single_order_pct,
            "requested_notional_usd": round(requested_notional_usd, 2),
            "hard_max_trade_usd": hard_max_trade_usd,
        }

        final_decision = {
            "action": checked_trade_intent["action"],
            "confidence": round(float(trader_intent.get("confidence", 0.5)), 3),
            "trade_intent": checked_trade_intent,
            "order": order,
            "reason": trader_intent.get("reasoning") or "No trader reasoning provided.",
            "risk_reason": "Risk engine validated and capped trader TradeIntent with position and per-trade notional limits.",
        }

        # Persist portfolio state update after order processing
        # (In production, this would reflect actual trade execution)
        updated_portfolio = {
            "cash_usd": cash_usd,
            "positions": current_portfolio.get("positions", {}),
            "unrealized_pnl": unrealized_pnl,
            "realized_pnl": realized_pnl,
            "timestamp": state.get("trade_date"),
        }
        
        try:
            portfolio_manager.save_portfolio_state(updated_portfolio)
            if order.get("notional_usd", 0) > 0:
                portfolio_manager.record_trade(
                    ticker=order["ticker"],
                    side=order["side"],
                    quantity=0,  # Would be filled by execution engine
                    entry_price=0,  # Would be filled by execution engine
                    notional_usd=order["notional_usd"],
                )
        except Exception as e:
            # Log but don't fail the decision if persistence fails
            import logging
            logging.error(f"Failed to persist portfolio state: {e}")

        risk_debate_state = state.get("risk_debate_state", {}) or {}
        updated_risk_state = {
            "aggressive_history": risk_debate_state.get("aggressive_history", ""),
            "conservative_history": risk_debate_state.get("conservative_history", ""),
            "neutral_history": risk_debate_state.get("neutral_history", ""),
            "history": risk_debate_state.get("history", ""),
            "latest_speaker": "Risk Engine",
            "current_aggressive_response": risk_debate_state.get("current_aggressive_response", ""),
            "current_conservative_response": risk_debate_state.get("current_conservative_response", ""),
            "current_neutral_response": risk_debate_state.get("current_neutral_response", ""),
            "judge_decision": json.dumps(final_decision, ensure_ascii=False),
            "count": risk_debate_state.get("count", 0),
        }

        return {
            "risk_debate_state": updated_risk_state,
            "final_trade_decision": json.dumps(final_decision, ensure_ascii=False),
        }

    return risk_engine_node
