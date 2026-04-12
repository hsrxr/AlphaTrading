"""Context merger node for broadcasting global portfolio state to all agents.

This middleware injects portfolio awareness into all analyst prompts,
preventing agents from generating recommendations that violate risk constraints.
"""

from typing import Dict, Any
from datetime import datetime
from tradingagents.portfolio_manager import PortfolioManager
import logging

logger = logging.getLogger(__name__)


def create_context_merge_node():
    """Create a graph node that merges portfolio context into agent state.
    
    This node runs after initial data gathering to inject portfolio constraints
    into all downstream analyst agents. It refreshes the global_portfolio_context
    field based on the latest database state.
    
    Returns:
        Callable that takes state dict and returns updated state dict
    """
    portfolio_manager = PortfolioManager(db_path="./trade_memory/portfolio.db")

    def context_merge_node(state: Dict[str, Any]) -> Dict[str, Any]:
        """Merge current portfolio context into state for all agents to respect.
        
        Args:
            state: Current agent state
            
        Returns:
            Updated state with refreshed global_portfolio_context
        """
        try:
            # Load latest portfolio state from database
            portfolio = portfolio_manager.load_latest_portfolio()
            
            cash_usd = portfolio.get("cash_usd", 10000.0)
            position_usd = portfolio.get("position_usd", 0.0)
            unrealized_pnl = portfolio.get("unrealized_pnl", 0.0)
            realized_pnl = portfolio.get("realized_pnl", 0.0)
            
            # Calculate portfolio metrics
            total_assets = cash_usd + position_usd + unrealized_pnl
            initial_capital = portfolio_manager.get_initial_capital()
            
            drawdown_pct = (
                ((total_assets - initial_capital) / initial_capital * 100)
                if initial_capital > 0 else 0
            )
            
            risk_basis = total_assets if total_assets > 0 else portfolio_manager.get_initial_capital()

            position_utilization = (
                (position_usd / max(risk_basis, 1e-9) * 100)
                if risk_basis > 0 else 0
            )
            
            # Format global context for injection into prompts
            global_portfolio_context = (
                f"=== PORTFOLIO STATE (as of {portfolio.get('timestamp', 'current')}) ===\n"
                f"Total Assets: ${total_assets:.2f}\n"
                f"Cash Balance: ${cash_usd:.2f}\n"
                f"Open Position Value: ${position_usd:.2f}\n"
                f"Unrealized PnL: ${unrealized_pnl:+.2f} ({drawdown_pct:+.2f}% from baseline)\n"
                f"Realized PnL (cumulative): ${realized_pnl:+.2f}\n"
                f"\n=== RISK CONSTRAINTS ===\n"
                f"Sizing and hard limits are enforced by RiskEngine at execution time.\n"
                f"Trader should propose intent by signal conviction, not by local cash math.\n"
                f"Current position utilization: {position_utilization:.1f}%\n"
                f"Drawdown from baseline: {drawdown_pct:+.2f}%\n"
                f"\n=== DECISION CONSTRAINTS ===\n"
                f"PRIORITIZE RISK MANAGEMENT if drawdown approaches -5%\n"
                f"BE CONSERVATIVE if position utilization > 80%"
            )
            
            # Update state with refreshed context
            state["global_portfolio_context"] = global_portfolio_context
            
            # Also ensure portfolio_balance is in sync
            state["portfolio_balance"] = {
                "cash_usd": cash_usd,
                "position_usd": position_usd,
                "positions": portfolio.get("positions", {}),
                "unrealized_pnl": unrealized_pnl,
                "realized_pnl": realized_pnl,
            }
            
            logger.debug(f"Updated global portfolio context: {total_assets:.2f} total assets")
            
        except Exception as e:
            logger.error(f"Error merging portfolio context: {e}")
            # Fallback to empty context if database fails
            if "global_portfolio_context" not in state:
                state["global_portfolio_context"] = (
                    "Portfolio context unavailable. Proceed with standard risk limits.\n"
                    "RiskEngine is the only source of executable sizing limits.\n"
                    "Trader output should use conviction-based USD cents sizing."
                )

        return state

    return context_merge_node
