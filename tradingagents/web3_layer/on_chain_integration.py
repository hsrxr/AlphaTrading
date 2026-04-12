"""
Automatic on-chain integration for TradingAgents.

This module handles the automatic submission of TradeIntents and Checkpoints
to the Sepolia hackathon contracts after each agent decision.
"""

import json
import logging
import time
from pathlib import Path
from dataclasses import dataclass, field
from typing import Any, Dict, Optional

from tradingagents.web3_layer.client import HackathonWeb3Client
from tradingagents.virtual_ledger import create_virtual_ledger

logger = logging.getLogger(__name__)


@dataclass
class OnChainSubmissionResult:
    """Result of an on-chain submission."""
    trade_submitted: bool
    trade_intent_hash: Optional[str] = None
    trade_error: Optional[str] = None
    
    checkpoint_submitted: bool = False
    checkpoint_hash: Optional[str] = None
    checkpoint_error: Optional[str] = None
    
    # Feedback from RiskRouter (populated after waiting for result)
    trade_approved: bool = False
    trade_rejected: bool = False
    approval_event: Optional[Dict[str, Any]] = None
    rejection_event: Optional[Dict[str, Any]] = None
    rejection_reason: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)  # Additional info about the submission


class TradeIntentAdapter:
    """Adapts agent final decision to TradingRouter's TradeIntent format."""
    
    @staticmethod
    def parse_final_decision(decision_json: str) -> Dict[str, Any]:
        """Parse final trade decision JSON from agent."""
        try:
            return json.loads(decision_json)
        except (json.JSONDecodeError, TypeError) as e:
            logger.error(f"Failed to parse final decision JSON: {e}")
            return {}
    
    @staticmethod
    def build_trade_intent(
        agent_id: int,
        agent_wallet: str,
        pair: str,
        action: str,
        amount_usd_scaled: int,
        nonce: int,
        deadline: Optional[int] = None,
        max_slippage_bps: int = 100,
    ) -> Dict[str, Any]:
        """Build a TradeIntent from agent decision parameters.
        
        Args:
            agent_id: Agent's ERC-721 token ID
            agent_wallet: Agent's wallet address for signing
            pair: Trading pair (e.g., "XBTUSD", "WETH/USDC")
            action: "BUY", "SELL", or "HOLD"
            amount_usd_scaled: Amount in cents (e.g., $500 = 50000)
            nonce: Current nonce from AgentRegistry
            deadline: Unix timestamp (defaults to now + 5 minutes)
            max_slippage_bps: Maximum slippage in basis points (default 100 = 1%)
        
        Returns:
            TradeIntent dict ready for signing
        """
        if deadline is None:
            deadline = int(time.time()) + 300  # 5 minutes from now
        
        return {
            "agentId": int(agent_id),
            "agentWallet": agent_wallet,
            "pair": pair,
            "action": action.upper(),
            "amountUsdScaled": int(amount_usd_scaled),
            "maxSlippageBps": int(max_slippage_bps),
            "nonce": int(nonce),
            "deadline": int(deadline),
        }
    
    @staticmethod
    def should_submit(
        decision: Dict[str, Any],
        submit_hold_decisions: bool = False,
    ) -> bool:
        """Check if decision warrants on-chain submission.

        By default HOLD actions are skipped unless submit_hold_decisions=True.
        """
        if not decision:
            return False
        
        action = decision.get("action", "").upper()
        if action == "HOLD" and not submit_hold_decisions:
            logger.info("Action is HOLD, skipping on-chain submission")
            return False
        
        order = decision.get("order", {})
        notional = order.get("notional_usd", 0)
        if notional <= 0:
            logger.info(f"Order notional is {notional}, skipping submission")
            return False
        
        return True


class OnChainIntegrator:
    """Orchestrates TradeIntent and Checkpoint submission to chain."""

    FIXED_CHECKPOINT_SCORE = 100
    
    def __init__(
        self,
        web3_client: HackathonWeb3Client,
        agent_id: int,
        agent_wallet: str,
        checkpoint_score: int = 75,
        enable_simulation: bool = True,
        submit_hold_decisions: bool = False,
        auto_approve_on_timeout: bool = True,
        checkpoint_notes_prefix: str = "TradingAgent decision:",
        checkpoint_log_file: str = "checkpoints.jsonl",
        ledger_path: str = "./trade_memory/virtual_ledger.json",
    ):
        """Initialize the on-chain integrator.
        
        Args:
            web3_client: Connected HackathonWeb3Client instance
            agent_id: Agent's registered ID
            agent_wallet: Agent's wallet for signing
            checkpoint_score: Default score for checkpoints (0-100)
            enable_simulation: If True, simulate intents before submission
            submit_hold_decisions: If True, submit HOLD actions to RiskRouter
            auto_approve_on_timeout: If True, when no on-chain feedback arrives in
                the wait window, treat the trade as approved for local bookkeeping.
            checkpoint_notes_prefix: Prefix for checkpoint notes
            checkpoint_log_file: Local JSONL file for checkpoint audit trail
            ledger_path: Path to virtual ledger JSON file
        """
        self.client = web3_client
        self.agent_id = int(agent_id)
        self.agent_wallet = agent_wallet
        self.checkpoint_score = max(0, min(100, int(checkpoint_score)))
        self.enable_simulation = enable_simulation
        self.submit_hold_decisions = bool(submit_hold_decisions)
        self.auto_approve_on_timeout = bool(auto_approve_on_timeout)
        self.checkpoint_notes_prefix = checkpoint_notes_prefix
        self.checkpoint_log_file = checkpoint_log_file
        self.ledger = create_virtual_ledger(ledger_path=ledger_path)

    @staticmethod
    def _normalize_tx_hash(tx_hash: Any) -> str:
        """Normalize tx hash across providers that return str or bytes-like objects."""
        if tx_hash is None:
            raise ValueError("Missing transaction hash")
        if isinstance(tx_hash, str):
            return tx_hash
        if hasattr(tx_hash, "hex"):
            return tx_hash.hex()
        return str(tx_hash)
    
    def submit_decision(
        self,
        final_decision_json: str,
        current_price_usd_scaled: int = 0,
        trade_date: Optional[str] = None,
        full_reasoning_jsonl_file: Optional[str] = None,
    ) -> OnChainSubmissionResult:
        """Submit an agent decision to the on-chain contracts.
        
        This method:
        1. Parses the final decision JSON
        2. Checks if submission is needed (skips HOLD)
        3. Builds and optionally simulates TradeIntent
        4. Signs and submits TradeIntent to RiskRouter
        5. Constructs and submits Checkpoint to ValidationRegistry
        
        Args:
            final_decision_json: JSON string from TradingAgentsGraph.analyze()
            current_price_usd_scaled: Current price in cents (used for checkpoint)
            trade_date: Optional trade date for logging
            full_reasoning_jsonl_file: Optional path to full_trace_*.jsonl; when present,
                its full content is used as the checkpoint reasoning-hash input.
        
        Returns:
            OnChainSubmissionResult with submission status and hashes
        """
        result = OnChainSubmissionResult(
            trade_submitted=False,
            checkpoint_submitted=False,
            metadata={
                "agent_id": self.agent_id,
                "timestamp": int(time.time()),
                "trade_date": trade_date,
            }
        )
        
        # Parse decision
        decision = TradeIntentAdapter.parse_final_decision(final_decision_json)
        if not decision:
            result.trade_error = "Failed to parse final decision JSON"
            logger.error(result.trade_error)
            return result
        
        # Check if we should submit
        if not TradeIntentAdapter.should_submit(
            decision,
            submit_hold_decisions=self.submit_hold_decisions,
        ):
            result.metadata["submission_skipped"] = True
            return result
        
        # Extract parameters (prefer structured TradeIntent from risk engine)
        trade_intent = decision.get("trade_intent", {}) if isinstance(decision, dict) else {}
        action = str(trade_intent.get("action", decision.get("action", "HOLD"))).upper()
        pair = self._normalize_pair(str(trade_intent.get("pair", "")))

        order = decision.get("order", {})
        if not pair or pair == "UNKNOWN":
            ticker = order.get("ticker", "UNKNOWN")
            pair = self._normalize_pair(ticker)

        # Prefer on-chain scaled cents; fallback to legacy notional_usd (USD float)
        if "amountUsdScaled" in trade_intent:
            amount_usd_scaled = int(trade_intent.get("amountUsdScaled", 0))
        else:
            amount_usd_scaled = int(float(order.get("notional_usd", 0)) * 100)

        max_slippage_bps = int(trade_intent.get("maxSlippageBps", 100))
        intent_deadline = trade_intent.get("deadline")
        intent_deadline = int(intent_deadline) if intent_deadline is not None else None
        reasoning = decision.get("reason", "")
        
        logger.info(
            f"Submitting on-chain: action={action}, pair={pair}, "
            f"amount={amount_usd_scaled/100:.2f} USD"
        )
        
        try:
            # RiskRouter validates TradeIntent against its own intent nonce.
            nonce = self.client.get_intent_nonce(self.agent_id)
            
            # Build TradeIntent
            intent = TradeIntentAdapter.build_trade_intent(
                agent_id=self.agent_id,
                agent_wallet=self.agent_wallet,
                pair=pair,
                action=action,
                amount_usd_scaled=amount_usd_scaled,
                nonce=nonce,
                deadline=intent_deadline,
                max_slippage_bps=max_slippage_bps,
            )
            
            # Simulate if enabled
            if self.enable_simulation:
                is_valid, reason = self.client.simulate_intent(intent)
                if not is_valid:
                    result.trade_error = f"Simulation failed: {reason}"
                    logger.warning(result.trade_error)
                    return result
                logger.info(f"Intent simulation successful: {reason}")
            
            # Sign and submit
            signature = self.client.sign_trade_intent(intent)
            tx_result = self.client.submit_trade_intent(intent, signature)

            result.trade_intent_hash = self._normalize_tx_hash(tx_result.tx_hash)
            result.trade_submitted = True
            
            # Record trade in virtual ledger with reference price for mock execution
            confidence = float(decision.get("confidence", 0.5))
            notes_raw = decision.get("reason", "")
            reference_price = current_price_usd_scaled / 100.0 if current_price_usd_scaled > 0 else None
            trade_id = self.ledger.submit_trade(
                agent_id=self.agent_id,
                pair=pair,
                action=action,
                amount_usd=amount_usd_scaled / 100.0,
                reference_price=reference_price,
                intent_hash=result.trade_intent_hash,
                confidence=confidence,
                notes=str(notes_raw)[:500],
            )
            result.metadata["virtual_trade_id"] = trade_id
            logger.info(f"Trade recorded in virtual ledger: {trade_id}, balance=${self.ledger.get_balance():.2f}")
            logger.info(f"TradeIntent submitted: {result.trade_intent_hash}")
            
            result.metadata["trade_intent"] = intent
            result.metadata["intent_nonce"] = nonce

            # Post ValidationRegistry checkpoint after RiskRouter submission.
            try:
                checkpoint_notes = f"{self.checkpoint_notes_prefix} {str(reasoning).strip()}".strip()
                checkpoint_hash_input = str(reasoning)
                if full_reasoning_jsonl_file:
                    trace_path = Path(full_reasoning_jsonl_file)
                    if trace_path.exists():
                        checkpoint_hash_input = trace_path.read_text(encoding="utf-8")
                    else:
                        logger.warning(
                            "Full reasoning JSONL file not found, fallback to concise reason: %s",
                            full_reasoning_jsonl_file,
                        )
                checkpoint_hash, checkpoint = self.client.build_checkpoint_hash(
                    agent_id=self.agent_id,
                    action=action,
                    pair=pair,
                    amount_usd_scaled=amount_usd_scaled,
                    price_usd_scaled=int(current_price_usd_scaled),
                    reasoning=checkpoint_hash_input,
                )

                checkpoint_tx = self.client.post_checkpoint_attestation(
                    agent_id=self.agent_id,
                    checkpoint_hash=checkpoint_hash,
                    score=self.FIXED_CHECKPOINT_SCORE,
                    notes=checkpoint_notes,
                )

                self.client.append_checkpoint_jsonl(
                    log_file=self.checkpoint_log_file,
                    checkpoint_hash=checkpoint_hash,
                    checkpoint=checkpoint,
                    score=self.FIXED_CHECKPOINT_SCORE,
                    notes=checkpoint_notes,
                )

                result.checkpoint_hash = checkpoint_hash
                result.checkpoint_submitted = True
                result.metadata["checkpoint"] = checkpoint
                result.metadata["checkpoint_score"] = self.FIXED_CHECKPOINT_SCORE
                result.metadata["checkpoint_notes"] = checkpoint_notes
                result.metadata["checkpoint_hash_source"] = (
                    full_reasoning_jsonl_file if full_reasoning_jsonl_file else "final_trade_decision.reason"
                )
                result.metadata["checkpoint_tx_hash"] = self._normalize_tx_hash(checkpoint_tx.tx_hash)
                logger.info(f"Checkpoint submitted: {checkpoint_hash}")
            except Exception as checkpoint_err:
                result.checkpoint_error = f"Checkpoint submission failed: {checkpoint_err}"
                logger.error(result.checkpoint_error, exc_info=True)
            
        except Exception as e:
            result.trade_error = f"TradeIntent submission failed: {str(e)}"
            logger.error(result.trade_error, exc_info=True)
            return result
        
        return result
    
    def wait_for_feedback(
        self,
        submission_result: OnChainSubmissionResult,
        max_wait_seconds: int = 300,
        poll_interval_seconds: int = 5,
    ) -> OnChainSubmissionResult:
        """Wait for and collect RiskRouter feedback (approval/rejection).
        
        This method polls RiskRouter events until the submitted trade receives
        approval or rejection, or until timeout.
        
        Args:
            submission_result: Result from submit_decision()
            max_wait_seconds: Maximum time to wait (default 5 minutes)
            poll_interval_seconds: Time between polls (default 5 seconds)
        
        Returns:
            Updated submission_result with approval/rejection feedback
        """
        if not submission_result.trade_submitted:
            logger.warning("No trade was submitted, skipping feedback wait")
            return submission_result

        if not submission_result.trade_intent_hash:
            logger.warning("No trade intent hash in submission result, skipping feedback wait")
            if not submission_result.metadata:
                submission_result.metadata = {}
            submission_result.metadata["feedback_skipped_no_intent_hash"] = True
            return submission_result
        
        try:
            from tradingagents.web3_layer.trade_status_checker import (
                create_trade_status_checker,
            )
            
            checker = create_trade_status_checker(self.client)
            intent_hash = submission_result.trade_intent_hash
            
            logger.info(
                f"Waiting for RiskRouter feedback on trade {intent_hash[:16]}... "
                f"(timeout: {max_wait_seconds}s)"
            )
            
            result = checker.poll_trade_result(
                agent_id=self.agent_id,
                intent_hash=intent_hash,
                max_wait_seconds=max_wait_seconds,
                poll_interval_seconds=poll_interval_seconds,
            )
            
            if result:
                if result["status"] == "approved":
                    submission_result.trade_approved = True
                    submission_result.approval_event = result.get("event")
                    logger.info(f"Trade APPROVED: {intent_hash[:16]}...")
                    
                    # Update virtual ledger: approve trade and reserve balance
                    self.ledger.approve_trade(intent_hash)
                    logger.info(f"Virtual ledger updated: balance=${self.ledger.get_balance():.2f}")
                
                elif result["status"] == "rejected":
                    submission_result.trade_rejected = True
                    submission_result.rejection_event = result.get("event")
                    submission_result.rejection_reason = result.get("reason", "Unknown")
                    logger.warning(
                        f"Trade REJECTED: {intent_hash[:16]}... - {submission_result.rejection_reason}"
                    )
                    
                    # Update virtual ledger: mark trade as rejected (no balance change)
                    self.ledger.reject_trade(intent_hash, reason=submission_result.rejection_reason)
            else:
                logger.warning(
                    f"No feedback received for trade {intent_hash[:16]}... "
                    f"within {max_wait_seconds}s. Explicit reason: no matching TradeApproved/TradeRejected event was observed in polling window (possible pending tx, RPC indexing lag, or event/agent mismatch)."
                )
                if not submission_result.metadata:
                    submission_result.metadata = {}
                submission_result.metadata["feedback_timeout"] = True
                if self.auto_approve_on_timeout:
                    submission_result.trade_approved = True
                    submission_result.metadata["auto_approved_on_timeout"] = True
                    # Get the trade record to retrieve reference_price for mock execution
                    trade_record = self.ledger.get_trade_by_hash(intent_hash)
                    reference_price = trade_record.get("reference_price") if trade_record else None
                    if self.ledger.approve_trade(intent_hash, execution_price=reference_price):
                        logger.info(
                            "No on-chain feedback in window; auto-approved locally with mock execution: %s..., balance=$%.2f, reference_price=$%.4f",
                            intent_hash[:16],
                            self.ledger.get_balance(),
                            reference_price if reference_price else 0.0,
                        )
                else:
                    if self.ledger.mark_trade_feedback_timeout(
                        intent_hash,
                        reason="RiskRouter feedback timeout; trade remains pending in virtual ledger",
                    ):
                        logger.info(
                            f"Virtual ledger marked trade as timeout-pending: {intent_hash[:16]}..."
                        )
        
        except Exception as e:
            logger.error(f"Error waiting for feedback: {e}", exc_info=True)
            if not submission_result.metadata:
                submission_result.metadata = {}
            submission_result.metadata["feedback_error"] = str(e)
        
        return submission_result
    
    @staticmethod
    def _normalize_pair(ticker: str) -> str:
        """Normalize ticker to pair format.
        
        Examples:
            "WETH/USDC" -> "WETH/USDC"
            "XBTUSD" -> "XBTUSD"
            "weth" -> "WETH/USDC" (if applicable)
        """
        if not ticker:
            return "UNKNOWN"
        
        ticker = ticker.upper().strip()
        
        # Already normalized (contains /)
        if "/" in ticker:
            return ticker
        
        # Common mappings for single tokens
        single_token_pairs = {
            "WETH": "WETH/USDC",
            "ETH": "WETH/USDC",
            "USDC": "USDC/USD",
            "USDT": "USDT/USD",
        }
        
        if ticker in single_token_pairs:
            return single_token_pairs[ticker]
        
        # Default: assume it's already a valid pair
        return ticker


def create_on_chain_integrator(
    rpc_url: Optional[str] = None,
    operator_private_key: Optional[str] = None,
    agent_private_key: Optional[str] = None,
    agent_id: Optional[int] = None,
    agent_wallet: Optional[str] = None,
    enable_simulation: bool = True,
    submit_hold_decisions: bool = False,
    auto_approve_on_timeout: Optional[bool] = None,
) -> Optional[OnChainIntegrator]:
    """Factory function to create an OnChainIntegrator from environment variables.
    
    Environment variables read:
    - SEPOLIA_RPC_URL: RPC endpoint
    - OPERATOR_PRIVATE_KEY: Operator wallet private key
    - AGENT_WALLET_PRIVATE_KEY: Agent wallet private key for signing intents
    - AGENT_ID: Agent's registered ID
    - AGENT_WALLET: Agent's wallet address
    
    All parameters can override environment variables.
    
    Returns:
        OnChainIntegrator instance, or None if required variables missing
    """
    import os
    from dotenv import load_dotenv
    
    load_dotenv()
     
    rpc_url = rpc_url or os.getenv("SEPOLIA_RPC_URL")
    operator_key = operator_private_key or os.getenv("OPERATOR_PRIVATE_KEY")
    agent_key = agent_private_key or os.getenv("AGENT_WALLET_PRIVATE_KEY")
    agent_id = agent_id or os.getenv("AGENT_ID")
    agent_wallet = agent_wallet or os.getenv("AGENT_WALLET_ADDRESS")
    if auto_approve_on_timeout is None:
        raw_auto_approve = os.getenv("ON_CHAIN_AUTO_APPROVE_WITHOUT_FEEDBACK", "true")
        auto_approve_on_timeout = str(raw_auto_approve).strip().lower() in {
            "1", "true", "yes", "on"
        }
    
    if not all([rpc_url, operator_key, agent_key, agent_id, agent_wallet]):
        missing = []
        if not rpc_url:
            missing.append("SEPOLIA_RPC_URL")
        if not operator_key:
            missing.append("OPERATOR_PRIVATE_KEY")
        if not agent_key:
            missing.append("AGENT_WALLET_PRIVATE_KEY")
        if not agent_id:
            missing.append("AGENT_ID")
        if not agent_wallet:
            missing.append("AGENT_WALLET")
        
        logger.warning(
            f"Cannot create OnChainIntegrator: missing environment variables {missing}. "
            "On-chain submission will be disabled."
        )
        return None
    
    try:
        client = HackathonWeb3Client(
            rpc_url=rpc_url,
            operator_private_key=operator_key,
            agent_private_key=agent_key,
        )
        
        integrator = OnChainIntegrator(
            web3_client=client,
            agent_id=int(agent_id),
            agent_wallet=agent_wallet,
            enable_simulation=enable_simulation,
            submit_hold_decisions=submit_hold_decisions,
            auto_approve_on_timeout=bool(auto_approve_on_timeout),
        )
        
        logger.info(f"OnChainIntegrator initialized for agent {agent_id}")
        return integrator
        
    except Exception as e:
        logger.error(f"Failed to initialize OnChainIntegrator: {e}", exc_info=True)
        return None
