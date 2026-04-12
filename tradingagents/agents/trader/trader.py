import functools
import time
import json
import os


def _build_trader_node(llm, memory, allow_hold: bool):
    def trader_node(state, name):
        company_name = state["company_of_interest"]
        investment_plan = state.get("investment_plan", "")
        debate_history = state.get("investment_debate_state", {}).get("history", "")
        portfolio_balance = state.get("portfolio_balance", {})
        global_portfolio_context = state.get("global_portfolio_context", "Portfolio context unavailable.")
        market_research_report = state["market_report"]
        sentiment_report = state["sentiment_report"]
        news_report = state["news_report"]
        quant_strategy_report = state.get("quant_strategy_report", "")
        fundamentals_report = state["fundamentals_report"]

        curr_situation = f"{market_research_report}\n\n{sentiment_report}\n\n{news_report}\n\n{quant_strategy_report}\n\n{fundamentals_report}"
        past_memories = memory.get_memories(curr_situation, n_matches=3)

        past_memory_str = ""
        if past_memories:
            for i, rec in enumerate(past_memories, 1):
                past_memory_str += rec["recommendation"] + "\n\n"
        else:
            past_memory_str = "No past memories found."

        agent_id = int(os.getenv("AGENT_ID", "0") or "0")
        agent_wallet = os.getenv("AGENT_WALLET_ADDRESS", "")
        deadline_hint = int(time.time()) + 300
        action_schema = '"BUY" | "SELL" | "HOLD"' if allow_hold else '"BUY" | "SELL"'
        hold_decision_rule = (
            "- If signal quality is weak or conflicting, choose HOLD with amountUsdScaled=0."
            if allow_hold
            else "- HOLD is not allowed. If confidence is weak, still choose BUY or SELL and reduce amountUsdScaled."
        )
        action_requirement = (
            "- action must be exactly BUY, SELL, or HOLD."
            if allow_hold
            else "- action must be exactly BUY or SELL. HOLD is invalid."
        )

        context = {
            "role": "user",
            "content": f"You are the Chief Trader and portfolio manager for {company_name} in the crypto market. Use the merged analyst context and bull/bear debate transcript to produce a **TradeIntent** for RiskRouter.\n\nDecision rules:\n- Prioritize executable short-horizon setups over long-term narratives.\n{hold_decision_rule}\n- Pair must be tradable as a pair string, e.g. ETHUSDC, BTCUSDT, XBTUSD.\n- Do not self-impose cash-based hard caps in this step; RiskEngine will enforce executable limits.\n\nMerged Analyst Context:\n{investment_plan}\n\nBull/Bear Debate Transcript:\n{debate_history}\n\nGlobal Portfolio Context:\n{global_portfolio_context}\n\nPortfolio Balance:\n{json.dumps(portfolio_balance, ensure_ascii=False)}\n\nOutput STRICT JSON ONLY using this shape (TradeIntent + required metadata):\n{{\n  \"agentId\": {agent_id},\n  \"agentWallet\": \"{agent_wallet}\",\n  \"pair\": \"{company_name}\",\n  \"action\": {action_schema},\n  \"amountUsdScaled\": integer,\n  \"maxSlippageBps\": integer,\n  \"nonce\": integer,\n  \"deadline\": integer,\n  \"confidence\": number between 0 and 1,\n  \"reasoning\": \"concise rationale for this intent\"\n}}\n\nField guidance:\n- amountUsdScaled is USD * 100 (e.g., 250.00 USD -> 25000).\n- UNIT SAFETY CHECK (required before finalizing):\n  1) Choose intended_notional_usd (human-readable USD amount).\n  2) Compute amountUsdScaled = round(intended_notional_usd * 100).\n  3) Verify reverse check: amountUsdScaled / 100 == intended_notional_usd (within 0.01).\n- Anti-mistake templates:\n  - $100.00 -> 10000\n  - $1,000.00 -> 100000\n  - $10,000.00 -> 1000000\n  - $0.22 -> 22\n  - $2.20 -> 220\n- Never output 22 or 220 unless your intended notional is exactly $0.22 or $2.20.\n- maxSlippageBps default 100 unless strong reason.\n- nonce should be 0 as placeholder (will be replaced before submit).\n- deadline should be unix seconds, use ~now+300. Example: {deadline_hint}.\n- confidence must reflect conviction quality and consistency.\n- reasoning should be concise and directly explain the action.",
        }

        messages = [
            {
                "role": "system", 
                "content": f"""You are the Chief Trader for a crypto, hourly-frequency strategy. Produce strict JSON only (no markdown, no prose outside JSON).
Requirements:
{action_requirement}
- amountUsdScaled must be an integer >= 0 and in cents.
- Perform a unit sanity check so USD and cents never mismatch.
- maxSlippageBps must be a positive integer.
- nonce must be an integer placeholder (0 is acceptable).
- deadline must be unix seconds.
- confidence must be a float in [0, 1].
- reasoning must be a concise plain-text rationale.
Leverage these past lessons: {past_memory_str}""",
            },
            context,
        ]

        result = llm.invoke(messages)

        return {
            "messages": [result],
            "trader_investment_plan": result.content,
            "sender": name,
        }

    return functools.partial(trader_node, name="Trader")


def create_trader(llm, memory):
    """Legacy trader prompt: allows BUY/SELL/HOLD."""
    return _build_trader_node(llm, memory, allow_hold=True)


def create_trader_v2(llm, memory):
    """V2 trader prompt: restricts action to BUY or SELL only."""
    return _build_trader_node(llm, memory, allow_hold=False)
