"""Virtual ledger for maintaining local trading account with $50,000 initial capital.

This module manages:
- Virtual cash balance (initialized to $50,000)
- Trade submissions and their status
- Account balance updates based on RiskRouter feedback
- Persistent ledger history (JSON-based)
"""

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Any, Optional, List

logger = logging.getLogger(__name__)


class VirtualLedger:
    """Manage virtual trading account with local balance tracking."""

    INITIAL_CAPITAL_USD = 100000.0

    def __init__(self, ledger_path: str = "./trade_memory/virtual_ledger.json"):
        """Initialize virtual ledger.

        Args:
            ledger_path: Path to JSON ledger file
        """
        self.ledger_path = Path(ledger_path)
        self.ledger_path.parent.mkdir(parents=True, exist_ok=True)
        self._load_or_init()

    def _load_or_init(self) -> None:
        """Load existing ledger or initialize new one."""
        if self.ledger_path.exists():
            try:
                with self.ledger_path.open("r", encoding="utf-8") as f:
                    data = json.load(f)
                    self.account = data.get("account", {})
                    self.trades = data.get("trades", [])
                    logger.info(
                        "Loaded virtual ledger: cash=$%.2f, trades=%d",
                        self.account.get("balance_usd", 0),
                        len(self.trades),
                    )
            except Exception as e:
                logger.error("Failed to load ledger, reinitializing: %s", e)
                self._create_new()
        else:
            self._create_new()

    def _create_new(self) -> None:
        """Create a fresh ledger with initial capital."""
        self.account = {
            "balance_usd": self.INITIAL_CAPITAL_USD,
            "initial_capital_usd": self.INITIAL_CAPITAL_USD,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "realized_pnl_usd": 0.0,
            "total_trades_submitted": 0,
            "total_trades_approved": 0,
            "total_trades_rejected": 0,
        }
        self.trades = []
        self._persist()
        logger.info("Created new virtual ledger with $%.2f initial capital", self.INITIAL_CAPITAL_USD)

    def _persist(self) -> None:
        """Save ledger to disk."""
        with self.ledger_path.open("w", encoding="utf-8") as f:
            json.dump(
                {
                    "account": self.account,
                    "trades": self.trades,
                    "last_saved": datetime.now(timezone.utc).isoformat(),
                },
                f,
                ensure_ascii=False,
                indent=2,
            )

    def get_balance(self) -> float:
        """Get current available cash balance in USD."""
        return self.account.get("balance_usd", self.INITIAL_CAPITAL_USD)

    def get_account_summary(self) -> Dict[str, Any]:
        """Get full account summary."""
        return {
            "balance_usd": self.get_balance(),
            "initial_capital_usd": self.account.get("initial_capital_usd", self.INITIAL_CAPITAL_USD),
            "realized_pnl_usd": self.account.get("realized_pnl_usd", 0.0),
            "total_trades_submitted": self.account.get("total_trades_submitted", 0),
            "total_trades_approved": self.account.get("total_trades_approved", 0),
            "total_trades_rejected": self.account.get("total_trades_rejected", 0),
            "created_at": self.account.get("created_at"),
        }

    def submit_trade(
        self,
        agent_id: int,
        pair: str,
        action: str,
        amount_usd: float,
        intent_hash: str,
        confidence: float = 0.5,
        notes: str = "",
        reference_price: Optional[float] = None,
    ) -> str:
        """Record a trade submission and reserve balance immediately.

        Args:
            agent_id: Agent ID
            pair: Trading pair (e.g., "ETHUSD")
            action: "BUY" or "SELL"
            amount_usd: Trade amount in USD
            intent_hash: RiskRouter intent hash
            confidence: Trade confidence (0-1)
            notes: Additional notes
            reference_price: Reference price at submission time (for mock execution)

        Returns:
            Trade ID for tracking
        """
        trade_id = f"{intent_hash[:16]}_{len(self.trades)}"
        
        current_balance = self.get_balance()
        if current_balance < amount_usd:
            logger.warning(
                "Insufficient balance for trade submission: need $%.2f, have $%.2f",
                amount_usd,
                current_balance,
            )
        
        trade = {
            "id": trade_id,
            "agent_id": agent_id,
            "pair": pair,
            "action": action.upper(),
            "amount_usd": amount_usd,
            "intent_hash": intent_hash,
            "confidence": confidence,
            "notes": notes,
            "reference_price": reference_price,  # Mock execution price if auto-approved
            "status": "submitted",  # submitted -> approved/rejected -> closed
            "submitted_at": datetime.now(timezone.utc).isoformat(),
            "reserved_balance": amount_usd,  # Reserve immediately on submission
            "approved_at": None,
            "rejected_at": None,
            "rejection_reason": None,
            "closed_at": None,
            "execution_price": None,  # Set when approved
            "realized_pnl": None,
        }
        
        self.trades.append(trade)
        
        # Reduce balance on submission (reserve the amount)
        new_balance = max(0.0, current_balance - amount_usd)
        self.account["balance_usd"] = new_balance
        self.account["total_trades_submitted"] = self.account.get("total_trades_submitted", 0) + 1
        self._persist()
        
        logger.info(
            "Trade submitted: agent=%d, pair=%s, action=%s, amount=$%.2f, hash=%s",
            agent_id,
            pair,
            action,
            amount_usd,
            intent_hash[:16],
        )
        
        return trade_id

    def approve_trade(
        self,
        intent_hash: str,
        execution_price: Optional[float] = None,
    ) -> bool:
        """Mark trade as approved by RiskRouter.
        
        Note: Balance is already reserved at submission time, so this just
        updates the trade status to indicate RiskRouter approval.
        If execution_price is not provided, uses reference_price from submission.

        Args:
            intent_hash: RiskRouter intent hash
            execution_price: Optional execution price (if not provided, uses reference_price)

        Returns:
            True if trade was found and approved, False otherwise
        """
        for trade in self.trades:
            if trade["intent_hash"] == intent_hash and trade["status"] == "submitted":
                # Balance already reserved at submission, just mark as approved
                trade["status"] = "approved"
                trade["approved_at"] = datetime.now(timezone.utc).isoformat()
                
                # Use provided execution_price, or fallback to reference_price
                final_execution_price = execution_price or trade.get("reference_price")
                trade["execution_price"] = final_execution_price
                
                # Calculate realized PnL if we have both amount and price
                if final_execution_price and trade.get("amount_usd", 0) > 0:
                    trade["realized_pnl"] = (trade["amount_usd"] * final_execution_price) / 100.0 if final_execution_price < 1 else trade["amount_usd"]
                    logger.info(
                        "Trade approved with PnL calculation: hash=%s, price=$%.4f, amount=$%.2f, pnl=$%.2f",
                        intent_hash[:16],
                        final_execution_price if final_execution_price >= 1 else final_execution_price * 100,
                        trade["amount_usd"],
                        trade.get("realized_pnl", 0),
                    )
                
                self.account["total_trades_approved"] = self.account.get("total_trades_approved", 0) + 1
                self._persist()
                
                logger.info(
                    "Trade approved: hash=%s, amount=$%.2f, execution_price=$%.4f, balance=$%.2f",
                    intent_hash[:16],
                    trade["amount_usd"],
                    final_execution_price if final_execution_price else 0.0,
                    self.get_balance(),
                )
                return True
        
        logger.warning("Trade not found or already processed: hash=%s", intent_hash[:16])
        return False

    def reject_trade(
        self,
        intent_hash: str,
        reason: str = "",
    ) -> bool:
        """Mark trade as rejected by RiskRouter and return reserved balance.

        Args:
            intent_hash: RiskRouter intent hash
            reason: Rejection reason

        Returns:
            True if trade was found and rejected, False otherwise
        """
        for trade in self.trades:
            if trade["intent_hash"] == intent_hash and trade["status"] == "submitted":
                # Return reserved balance to account
                reserved = trade.get("reserved_balance", 0)
                trade["status"] = "rejected"
                trade["rejected_at"] = datetime.now(timezone.utc).isoformat()
                trade["rejection_reason"] = reason
                
                # Return balance to account
                new_balance = self.get_balance() + reserved
                self.account["balance_usd"] = new_balance
                self.account["total_trades_rejected"] = self.account.get("total_trades_rejected", 0) + 1
                self._persist()
                
                logger.info(
                    "Trade rejected: hash=%s, reason=%s, returned=$%.2f, balance=$%.2f",
                    intent_hash[:16],
                    reason or "unknown",
                    reserved,
                    new_balance,
                )
                return True
        
        logger.warning("Trade not found or already processed: hash=%s", intent_hash[:16])
        return False

    def mark_trade_feedback_timeout(
        self,
        intent_hash: str,
        reason: str = "feedback_timeout",
    ) -> bool:
        """Mark a submitted trade as unresolved when on-chain feedback does not arrive.

        This keeps the reserved balance in place and records that the trade is still
        pending an external confirmation instead of treating it as rejected.
        """
        for trade in self.trades:
            if trade["intent_hash"] == intent_hash and trade["status"] == "submitted":
                trade["feedback_status"] = "timeout"
                trade["feedback_reason"] = reason
                trade["last_checked_at"] = datetime.now(timezone.utc).isoformat()
                self._persist()

                logger.info(
                    "Trade feedback timeout recorded: hash=%s, reason=%s, balance=$%.2f",
                    intent_hash[:16],
                    reason,
                    self.get_balance(),
                )
                return True

        logger.warning("Trade not found or already processed for timeout marker: hash=%s", intent_hash[:16])
        return False

    def close_trade(
        self,
        intent_hash: str,
        exit_price: float,
        realized_pnl: Optional[float] = None,
    ) -> bool:
        """Close an approved trade and record PnL.

        Args:
            intent_hash: RiskRouter intent hash
            exit_price: Exit price for the trade
            realized_pnl: Realized P&L (if None, calculate from prices)

        Returns:
            True if trade was found and closed, False otherwise
        """
        for trade in self.trades:
            if trade["intent_hash"] == intent_hash and trade["status"] == "approved":
                reserved = trade.get("reserved_balance", 0)
                entry_price = trade.get("execution_price")
                
                # Calculate PnL if not provided
                if realized_pnl is None and entry_price is not None:
                    if trade["action"] == "BUY":
                        realized_pnl = reserved * (exit_price - entry_price) / entry_price
                    else:  # SELL
                        realized_pnl = reserved * (entry_price - exit_price) / entry_price
                else:
                    realized_pnl = realized_pnl or 0.0
                
                # Return reserved balance + PnL to account
                trade["status"] = "closed"
                trade["closed_at"] = datetime.now(timezone.utc).isoformat()
                trade["exit_price"] = exit_price
                trade["realized_pnl"] = realized_pnl
                
                new_balance = self.get_balance() + reserved + realized_pnl
                self.account["balance_usd"] = new_balance
                self.account["realized_pnl_usd"] = self.account.get("realized_pnl_usd", 0.0) + realized_pnl
                self._persist()
                
                logger.info(
                    "Trade closed: hash=%s, exit=$%.2f, pnl=$%.2f, balance=$%.2f",
                    intent_hash[:16],
                    exit_price,
                    realized_pnl,
                    new_balance,
                )
                return True
        
        logger.warning("Trade not found or not approved: hash=%s", intent_hash[:16])
        return False

    def get_trade_by_hash(self, intent_hash: str) -> Optional[Dict[str, Any]]:
        """Retrieve a trade by its intent hash."""
        for trade in self.trades:
            if trade["intent_hash"] == intent_hash:
                return trade
        return None

    def get_trades_by_status(self, status: str) -> List[Dict[str, Any]]:
        """Get all trades with a specific status."""
        return [t for t in self.trades if t["status"] == status]

    def get_ledger(self) -> Dict[str, Any]:
        """Get complete ledger data including account and trades."""
        return {
            "account": self.account,
            "trades": self.trades,
            "summary": self.get_account_summary(),
        }

    def print_summary(self) -> None:
        """Print a human-readable account summary."""
        summary = self.get_account_summary()
        print("\n" + "=" * 60)
        print("VIRTUAL ACCOUNT SUMMARY")
        print("=" * 60)
        print(f"Initial Capital:      ${summary['initial_capital_usd']:.2f}")
        print(f"Current Balance:      ${summary['balance_usd']:.2f}")
        print(f"Realized P&L:         ${summary['realized_pnl_usd']:.2f}")
        print(f"Total Submitted:      {summary['total_trades_submitted']}")
        print(f"Total Approved:       {summary['total_trades_approved']}")
        print(f"Total Rejected:       {summary['total_trades_rejected']}")
        print("=" * 60 + "\n")


def create_virtual_ledger(
    ledger_path: str = "./trade_memory/virtual_ledger.json",
) -> VirtualLedger:
    """Factory function to create or load virtual ledger."""
    return VirtualLedger(ledger_path=ledger_path)
