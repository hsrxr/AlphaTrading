# TradingAgents/graph/propagation.py

from typing import Dict, Any, List, Optional
from tradingagents.agents.utils.agent_states import (
    AgentState,
    InvestDebateState,
    RiskDebateState,
)
from tradingagents.portfolio_manager import PortfolioManager


class Propagator:
    """Handles state initialization and propagation through the graph."""

    def __init__(self, max_recur_limit=100):
        """Initialize with configuration parameters."""
        self.max_recur_limit = max_recur_limit
        # Initialize portfolio manager for state persistence
        self.portfolio_manager = PortfolioManager(db_path="./trade_memory/portfolio.db")

    def create_initial_state(
        self, company_name: str, trade_date: str, trigger_context: Optional[str] = None
    ) -> Dict[str, Any]:
        """Create the initial state for the agent graph.
        
        Loads actual portfolio state from persistent database instead of hardcoding.
        First run initializes default state; subsequent runs load real portfolio.
        """
        messages: List[Any] = [("human", company_name)]
        if trigger_context:
            messages.append(("human", f"Aggregated trigger context:\n{trigger_context}"))

        # Load portfolio state from database (or initialize on first run)
        portfolio = self.portfolio_manager.load_latest_portfolio()
        
        # Generate global portfolio context for all agents
        cash_usd = portfolio.get("cash_usd", 100000.0)
        position_usd = portfolio.get("position_usd", 0.0)
        unrealized_pnl = portfolio.get("unrealized_pnl", 0.0)
        
        # Calculate drawdown metrics
        total_assets = cash_usd + position_usd + unrealized_pnl
        initial_capital = self.portfolio_manager.get_initial_capital()
        drawdown_pct = ((total_assets - initial_capital) / initial_capital * 100) if initial_capital > 0 else 0
        
        global_portfolio_context = (
            f"Current portfolio state as of {portfolio.get('timestamp', 'unknown')}:\n"
            f"- Total assets: ${total_assets:.2f}\n"
            f"- Cash balance: ${cash_usd:.2f}\n"
            f"- Open position exposure: ${position_usd:.2f}\n"
            f"- Unrealized PnL: ${unrealized_pnl:.2f} ({drawdown_pct:+.2f}%)\n"
            f"- Realized PnL (cumulative): ${portfolio.get('realized_pnl', 0.0):.2f}\n"
            f"\nRisk Constraints:\n"
            f"- RiskEngine is the only source of executable sizing/limits\n"
            f"- Trader should propose conviction-based sizing in USD cents\n"
            f"- Current position utilization: {(position_usd / total_assets * 100) if total_assets > 0 else 0:.1f}%"
        )

        return {
            "messages": messages,
            "company_of_interest": company_name,
            "trade_date": str(trade_date),
            "portfolio_balance": {
                "cash_usd": cash_usd,
                "position_usd": position_usd,
                "positions": portfolio.get("positions", {}),
                "unrealized_pnl": unrealized_pnl,
                "realized_pnl": portfolio.get("realized_pnl", 0.0),
            },
            "global_portfolio_context": global_portfolio_context,
            "investment_debate_state": InvestDebateState(
                {
                    "bull_history": "",
                    "bear_history": "",
                    "history": "",
                    "current_response": "",
                    "judge_decision": "",
                    "count": 0,
                }
            ),
            "risk_debate_state": RiskDebateState(
                {
                    "aggressive_history": "",
                    "conservative_history": "",
                    "neutral_history": "",
                    "history": "",
                    "latest_speaker": "",
                    "current_aggressive_response": "",
                    "current_conservative_response": "",
                    "current_neutral_response": "",
                    "judge_decision": "",
                    "count": 0,
                }
            ),
            "market_report": "",
            "fundamentals_report": "",
            "sentiment_report": "",
            "news_report": "",
            "quant_strategy_report": "",
        }

    def get_graph_args(self, callbacks: Optional[List] = None) -> Dict[str, Any]:
        """Get arguments for the graph invocation.

        Args:
            callbacks: Optional list of callback handlers for tool execution tracking.
                       Note: LLM callbacks are handled separately via LLM constructor.
        """
        config = {"recursion_limit": self.max_recur_limit}
        if callbacks:
            config["callbacks"] = callbacks
        return {
            "stream_mode": "values",
            "config": config,
        }
