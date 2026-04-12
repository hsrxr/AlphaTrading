# TradingAgents/graph/trading_graph.py

import os
from pathlib import Path
import json
import logging
import time
import datetime
from datetime import date
from typing import Dict, Any, Tuple, List, Optional
from langgraph.prebuilt import ToolNode
from tradingagents.llm_clients import create_llm_client

from tradingagents.agents import *
from tradingagents.default_config import DEFAULT_CONFIG
from tradingagents.agents.utils.memory import FinancialSituationMemory
from tradingagents.agents.utils.agent_states import (
    AgentState,
    InvestDebateState,
    RiskDebateState,
)
from tradingagents.dataflows.config import set_config
from tradingagents.web3_layer.on_chain_integration import (
    create_on_chain_integrator,
    OnChainIntegrator,
    OnChainSubmissionResult,
)

# Import direct DEX tools from dataflow layer
from tradingagents.dataflows.geckoterminal_price import get_dex_ohlcv
from tradingagents.dataflows.calculate_indicators import (
    get_dex_indicators,
    get_builtin_quant_signals,
)
from tradingagents.dataflows.binance_price import (
    get_binance_ohlcv,
    get_binance_indicators,
    get_binance_builtin_quant_signals,
)
from tradingagents.dataflows.rss_processor import fetch_and_parse_crypto_news
from tradingagents.dataflows.get_full_articles import fetch_article_full_text
from tradingagents.triggers.observers import fetch_trigger_watch_news

from .conditional_logic import ConditionalLogic
from .setup import GraphSetup
from .parallel_setup import ParallelGraphSetup
from .propagation import Propagator
from .reflection import Reflector
from .signal_processing import SignalProcessor
from .progress_tracker import ProgressTracker, LangChainProgressCallback


logger = logging.getLogger(__name__)


class TradingAgentsGraph:
    """Main class that orchestrates the trading agents framework."""

    def __init__(
        self,
        selected_analysts=["market", "news", "quant"],
        debug=False,
        config: Optional[Dict[str, Any]] = None,
        callbacks: Optional[List] = None,
        parallel_mode: bool = False,
    ):
        """Initialize the trading agents graph and components.

        Args:
            selected_analysts: List of analyst types to include
            debug: Whether to run in debug mode
            config: Configuration dictionary. If None, uses default config
            callbacks: Optional list of callback handlers (e.g., for tracking LLM/tool stats)
            parallel_mode: If True, enables parallel execution of analysts, debates, and risk analysis.
                          If False, uses serial execution (default behavior).
        """
        self.debug = debug
        self.config = config or DEFAULT_CONFIG
        self.callbacks = callbacks or []
        self.parallel_mode = parallel_mode
        self.selected_analysts = selected_analysts
        self.use_trader_v2 = bool(self.config.get("use_trader_v2", False))

        if self.parallel_mode and len(selected_analysts) <= 2:
            logger.info(
                "parallel_mode=True with %s analysts. Overhead/retries may outweigh speedup.",
                len(selected_analysts),
            )

        logger.info(
            "Trader prompt mode: %s",
            "v2 (BUY/SELL only)" if self.use_trader_v2 else "legacy (BUY/SELL/HOLD)",
        )

        # Update the interface's config
        set_config(self.config)

        # Create necessary directories
        os.makedirs(
            os.path.join(self.config["project_dir"], "dataflows/data_cache"),
            exist_ok=True,
        )

        # Initialize LLMs with provider-specific thinking configuration
        llm_kwargs = self._get_provider_kwargs()

        # Progress tracking
        self.progress_tracker = ProgressTracker(
            verbose=self.config.get("enable_progress_tracking", True),
            enable_colors=self.config.get("enable_colored_output", True)
        )
        self.progress_callback = LangChainProgressCallback(self.progress_tracker)

        # Add callbacks to kwargs (internal progress callback + optional external callbacks)
        llm_callbacks = [self.progress_callback]
        if self.callbacks:
            llm_callbacks.extend(self.callbacks)
        llm_kwargs["callbacks"] = llm_callbacks

        deep_client = create_llm_client(
            provider=self.config["llm_provider"],
            model=self.config["deep_think_llm"],
            base_url=self.config.get("backend_url"),
            **llm_kwargs,
        )
        quick_client = create_llm_client(
            provider=self.config["llm_provider"],
            model=self.config["quick_think_llm"],
            base_url=self.config.get("backend_url"),
            **llm_kwargs,
        )

        self.deep_thinking_llm = deep_client.get_llm()
        self.quick_thinking_llm = quick_client.get_llm()
        
        # Initialize memories
        self.bull_memory = FinancialSituationMemory("bull_memory", self.config)
        self.bear_memory = FinancialSituationMemory("bear_memory", self.config)
        self.trader_memory = FinancialSituationMemory("trader_memory", self.config)
        self.invest_judge_memory = FinancialSituationMemory("invest_judge_memory", self.config)
        self.risk_manager_memory = FinancialSituationMemory("risk_manager_memory", self.config)

        # Create tool nodes
        self.tool_nodes = self._create_tool_nodes()

        # Initialize components
        self.conditional_logic = ConditionalLogic(
            max_debate_rounds=self.config["max_debate_rounds"],
            max_risk_discuss_rounds=self.config["max_risk_discuss_rounds"],
        )
        
        # Choose between parallel and serial graph setup
        if self.parallel_mode:
            self.graph_setup = ParallelGraphSetup(
                self.quick_thinking_llm,
                self.deep_thinking_llm,
                self.tool_nodes,
                self.bull_memory,
                self.bear_memory,
                self.trader_memory,
                self.invest_judge_memory,
                self.risk_manager_memory,
                self.conditional_logic,
                use_trader_v2=self.use_trader_v2,
            )
        else:
            self.graph_setup = GraphSetup(
                self.quick_thinking_llm,
                self.deep_thinking_llm,
                self.tool_nodes,
                self.bull_memory,
                self.bear_memory,
                self.trader_memory,
                self.invest_judge_memory,
                self.risk_manager_memory,
                self.conditional_logic,
                use_trader_v2=self.use_trader_v2,
            )

        self.propagator = Propagator()
        self.portfolio_manager = self.propagator.portfolio_manager
        self.reflector = Reflector(self.quick_thinking_llm)
        self.signal_processor = SignalProcessor(self.quick_thinking_llm)

        # State tracking
        self.curr_state = None
        self.ticker = None
        self.log_states_dict = {}  # date to full state dict
        self.current_trace_file: Optional[str] = None
        
        # Initialize on-chain integration (optional)
        self.on_chain_integrator: Optional[OnChainIntegrator] = None
        if self.config.get("enable_on_chain_submission", False):
            self.on_chain_integrator = create_on_chain_integrator(
                enable_simulation=self.config.get("on_chain_simulation_enabled", True),
                submit_hold_decisions=self.config.get("on_chain_submit_hold_decisions", False),
                auto_approve_on_timeout=self.config.get("on_chain_auto_approve_without_feedback", True),
            )
            if self.on_chain_integrator:
                logger.info("On-chain integration enabled")
            else:
                logger.warning(
                    "On-chain integration requested but not available (check prior logs for root cause, e.g. env/RPC/connectivity)."
                )
        else:
            logger.debug("On-chain integration disabled")
        
        # Initialize trade outcome recorder for memory feedback
        from tradingagents.graph.trade_outcome_recorder import create_trade_outcome_recorder
        self.trade_outcome_recorder = create_trade_outcome_recorder()
        logger.debug("Trade outcome recorder initialized")

        # Set up the primary graph
        self.graph = self.graph_setup.setup_graph(selected_analysts)

        # Keep a serial graph as fallback when parallel mode hits provider/tool-message constraints.
        self.serial_graph = None
        if self.parallel_mode:
            serial_setup = GraphSetup(
                self.quick_thinking_llm,
                self.deep_thinking_llm,
                self.tool_nodes,
                self.bull_memory,
                self.bear_memory,
                self.trader_memory,
                self.invest_judge_memory,
                self.risk_manager_memory,
                self.conditional_logic,
                use_trader_v2=self.use_trader_v2,
            )
            self.serial_graph = serial_setup.setup_graph(selected_analysts)

    def _invoke_graph(self, graph, init_agent_state, args):
        """Invoke a graph in debug or normal mode and return final state."""
        if self.debug or self.config.get("enable_progress_tracking", True):
            trace = []
            for idx, chunk in enumerate(graph.stream(init_agent_state, **args), start=1):
                step_name = f"Graph Step {idx}"
                self.progress_tracker.track_node_start(step_name, chunk)

                messages = chunk.get("messages", []) if isinstance(chunk, dict) else []
                if self.debug and messages:
                    messages[-1].pretty_print()

                self.progress_tracker.track_node_end(step_name, chunk)
                trace.append(chunk)

            if not trace:
                raise RuntimeError("Graph stream produced no chunks.")
            return trace[-1]

        return graph.invoke(init_agent_state, **args)

    def _get_provider_kwargs(self) -> Dict[str, Any]:
        """Get provider-specific kwargs for LLM client creation."""
        kwargs = {}
        provider = self.config.get("llm_provider", "").lower()

        llm_timeout = self.config.get("llm_timeout_seconds")
        if llm_timeout is not None:
            kwargs["timeout"] = llm_timeout

        llm_max_retries = self.config.get("llm_max_retries")
        if llm_max_retries is not None:
            kwargs["max_retries"] = llm_max_retries

        if self.config.get("enable_llm_streaming") is not None:
            kwargs["streaming"] = bool(self.config.get("enable_llm_streaming"))

        if provider == "google":
            thinking_level = self.config.get("google_thinking_level")
            if thinking_level:
                kwargs["thinking_level"] = thinking_level

        elif provider == "openai":
            reasoning_effort = self.config.get("openai_reasoning_effort")
            if reasoning_effort:
                kwargs["reasoning_effort"] = reasoning_effort

        return kwargs

    def _is_tool_call_sequence_error(self, exc: Exception) -> bool:
        """Detect provider errors caused by mismatched tool-call message sequences."""
        error_text = str(exc)
        return "tool_calls" in error_text and "tool_call_id" in error_text

    def _is_transient_connection_error(self, exc: Exception) -> bool:
        """Detect transient transport/API failures that should be retried."""
        error_text = str(exc).lower()
        transient_markers = (
            "connection error",
            "remoteprotocolerror",
            "incomplete chunked read",
            "timed out",
            "timeout",
            "temporarily unavailable",
            "connection reset",
            "service unavailable",
            "502",
            "503",
            "504",
        )
        return any(marker in error_text for marker in transient_markers)

    def _create_tool_nodes(self) -> Dict[str, ToolNode]:
        """Create tool nodes for different data sources using abstract methods."""
        return {
            "market": ToolNode(
                [
                    # Decentralized exchange data
                    get_dex_ohlcv,
                    get_dex_indicators,
                    # Centralized exchange data (Binance)
                    get_binance_ohlcv,
                    get_binance_indicators,
                ]
            ),
            "news": ToolNode(
                [
                    # News and insider information
                    # get_news,
                    # get_global_news,
                    # get_insider_transactions,
                    fetch_trigger_watch_news,
                    fetch_and_parse_crypto_news,
                    fetch_article_full_text,
                ]
            ),
            "quant": ToolNode(
                [
                    # Quant strategy signal analysis uses the same market data primitives.
                    get_dex_ohlcv,
                    get_dex_indicators,
                    get_builtin_quant_signals,
                    # Binance alternatives for symbols unavailable on DEX pools.
                    get_binance_ohlcv,
                    get_binance_indicators,
                    get_binance_builtin_quant_signals,
                ]
            ),
        }

    def propagate(self, company_name, trade_date, trigger_context: Optional[Any] = None):
        """Run the trading agents graph for a company on a specific date."""

        self.ticker = company_name
        args = self.propagator.get_graph_args()

        # Create per-run full trace log file for step-by-step I/O and LLM prompt/response.
        trace_dir = Path(f"eval_results/{company_name}/TradingAgentsStrategy_logs/")
        trace_dir.mkdir(parents=True, exist_ok=True)
        run_ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        safe_trade_date = str(trade_date).replace(":", "-").replace("/", "-")
        trace_file = trace_dir / f"full_trace_{safe_trade_date}_{run_ts}.jsonl"
        self.current_trace_file = str(trace_file)
        self.progress_tracker.start_run(
            str(trace_file),
            metadata={"company": company_name, "trade_date": str(trade_date), "parallel_mode": self.parallel_mode},
        )

        max_attempts = int(self.config.get("graph_invoke_retries", 3))
        base_backoff = float(self.config.get("graph_invoke_backoff_seconds", 2.0))

        current_graph = self.graph
        used_fallback = False
        final_state = None
        
        # Track overall execution
        self.progress_tracker.track_node_start("Trading Analysis", {"company": company_name, "date": trade_date})
        overall_start_time = time.time()

        for attempt in range(1, max_attempts + 1):
            if isinstance(trigger_context, str):
                trigger_context_text = trigger_context
            elif trigger_context is None:
                trigger_context_text = ""
            else:
                trigger_context_text = json.dumps(trigger_context, ensure_ascii=False)

            init_agent_state = self.propagator.create_initial_state(
                company_name,
                trade_date,
                trigger_context=trigger_context_text,
            )
            try:
                final_state = self._invoke_graph(current_graph, init_agent_state, args)
                break
            except Exception as exc:
                if (
                    self.parallel_mode
                    and self.serial_graph is not None
                    and not used_fallback
                    and self._is_tool_call_sequence_error(exc)
                ):
                    logger.warning(
                        "Parallel execution failed due to tool-call message sequencing. "
                        "Falling back to serial graph for this run."
                    )
                    self.progress_tracker.track_node_start("Fallback to Serial Execution", {})
                    current_graph = self.serial_graph
                    used_fallback = True
                    continue

                if self._is_transient_connection_error(exc) and attempt < max_attempts:
                    sleep_seconds = base_backoff * (2 ** (attempt - 1))
                    logger.warning(
                        "Transient connection/API error on attempt %s/%s. Retrying in %.1fs. Error: %s",
                        attempt,
                        max_attempts,
                        sleep_seconds,
                        exc,
                    )
                    time.sleep(sleep_seconds)
                    continue

                raise

        if final_state is None:
            raise RuntimeError("Graph execution failed without producing a final state.")

        # Track completion
        overall_duration = time.time() - overall_start_time
        self.progress_tracker.track_node_end("Trading Analysis", {"status": "completed", "duration": overall_duration})
        
        # Print summary only if progress tracking is enabled
        if self.config.get("enable_progress_tracking", True):
            self.progress_tracker.print_summary()

        # Store current state for reflection
        self.curr_state = final_state

        # Log state
        self._log_state(trade_date, final_state)

        submission_skipped = not bool(self.on_chain_integrator)
        trade_submitted = False
        checkpoint_submitted = False
        
        # Submit to on-chain contracts (if configured)
        if self.on_chain_integrator:
            try:
                submission_result = self.on_chain_integrator.submit_decision(
                    final_decision_json=final_state.get("final_trade_decision", ""),
                    current_price_usd_scaled=0,  # Optional: could be fetched from market data
                    trade_date=str(trade_date),
                    full_reasoning_jsonl_file=self.current_trace_file,
                )

                trade_submitted = bool(submission_result.trade_submitted)
                checkpoint_submitted = bool(submission_result.checkpoint_submitted)
                submission_skipped = bool((submission_result.metadata or {}).get("submission_skipped", False))
                
                if submission_result.trade_submitted:
                    logger.info(
                        f"TradeIntent submitted on-chain: {submission_result.trade_intent_hash}"
                    )
                
                if submission_result.checkpoint_submitted:
                    logger.info(
                        f"Checkpoint submitted on-chain: {submission_result.checkpoint_hash}"
                    )
                
                if submission_result.trade_error:
                    logger.error(f"TradeIntent submission error: {submission_result.trade_error}")
                
                if submission_result.checkpoint_error:
                    logger.error(f"Checkpoint submission error: {submission_result.checkpoint_error}")
                
                # Wait for RiskRouter feedback (approval/rejection)
                if submission_result.trade_submitted:
                    logger.info("Waiting for RiskRouter feedback...")
                    submission_result = self.on_chain_integrator.wait_for_feedback(
                        submission_result,
                        max_wait_seconds=120,
                        poll_interval_seconds=5,
                    )

                    # Apply feedback only if RiskRouter actually resolved the trade.
                    if submission_result.trade_approved or submission_result.trade_rejected:
                        self._apply_on_chain_feedback(
                            submission_result,
                            final_state,
                            trade_date,
                        )
                    else:
                        logger.warning(
                            "Skipping portfolio feedback application because no on-chain approval/rejection was received."
                        )
                    
            except Exception as e:
                logger.error(f"Unexpected error during on-chain submission: {e}", exc_info=True)

        logger.info(
            "On-chain submission summary: submission_skipped=%s, trade_submitted=%s, checkpoint_submitted=%s",
            submission_skipped,
            trade_submitted,
            checkpoint_submitted,
        )

        # Return decision and processed signal
        return final_state, self.process_signal(final_state["final_trade_decision"])


    def _log_state(self, trade_date, final_state):
        """Log the final state to a JSON file."""
        # Safely build investment_debate_state (may have partial fields in simplified architecture)
        invest_debate_log = {}
        if "investment_debate_state" in final_state:
            invest_debate = final_state["investment_debate_state"]
            invest_debate_log = {
                "bull_history": invest_debate.get("bull_history", ""),
                "bear_history": invest_debate.get("bear_history", ""),
                "history": invest_debate.get("history", ""),
                "current_response": invest_debate.get("current_response", ""),
                "judge_decision": invest_debate.get("judge_decision", ""),
            }
        
        # Safely build risk_debate_state (pure Python risk engine may not populate all fields)
        risk_debate_log = {}
        if "risk_debate_state" in final_state:
            risk_debate = final_state["risk_debate_state"]
            risk_debate_log = {
                "aggressive_history": risk_debate.get("aggressive_history", ""),
                "conservative_history": risk_debate.get("conservative_history", ""),
                "neutral_history": risk_debate.get("neutral_history", ""),
                "history": risk_debate.get("history", ""),
                "judge_decision": risk_debate.get("judge_decision", ""),
            }
        
        self.log_states_dict[str(trade_date)] = {
            "company_of_interest": final_state.get("company_of_interest", ""),
            "trade_date": final_state.get("trade_date", ""),
            "market_report": final_state.get("market_report", ""),
            "sentiment_report": final_state.get("sentiment_report", ""),
            "news_report": final_state.get("news_report", ""),
            "quant_strategy_report": final_state.get("quant_strategy_report", ""),
            "fundamentals_report": final_state.get("fundamentals_report", ""),
            "investment_debate_state": invest_debate_log,
            "trader_investment_decision": final_state.get("trader_investment_plan", ""),
            "risk_debate_state": risk_debate_log,
            "investment_plan": final_state.get("investment_plan", ""),
            "final_trade_decision": final_state.get("final_trade_decision", ""),
        }

        # Save to file
        directory = Path(f"eval_results/{self.ticker}/TradingAgentsStrategy_logs/")
        directory.mkdir(parents=True, exist_ok=True)
        safe_trade_date = str(trade_date)
        safe_trade_date = safe_trade_date.replace(":", "-").replace("/", "-").replace("\\", "-")

        with open(
            f"eval_results/{self.ticker}/TradingAgentsStrategy_logs/full_states_log_{safe_trade_date}.json",
            "w",
            encoding="utf-8",
        ) as f:
            json.dump(self.log_states_dict, f, indent=4)

    def reflect_and_remember(self, returns_losses):
        """Reflect on decisions and update memory based on returns."""
        self.reflector.reflect_bull_researcher(
            self.curr_state, returns_losses, self.bull_memory
        )
        self.reflector.reflect_bear_researcher(
            self.curr_state, returns_losses, self.bear_memory
        )
        self.reflector.reflect_trader(
            self.curr_state, returns_losses, self.trader_memory
        )
        self.reflector.reflect_invest_judge(
            self.curr_state, returns_losses, self.invest_judge_memory
        )
        self.reflector.reflect_risk_manager(
            self.curr_state, returns_losses, self.risk_manager_memory
        )

    def process_signal(self, full_signal):
        """Process a signal to extract the core decision."""
        return self.signal_processor.process_signal(full_signal)
    
    def _apply_on_chain_feedback(
        self,
        submission_result: "OnChainSubmissionResult",
        final_state: dict,
        trade_date,
    ) -> None:
        """Apply RiskRouter feedback to portfolio and memory.
        
        Args:
            submission_result: Result from wait_for_feedback()
            final_state: Final decision state from analysis
            trade_date: Date of the trade
        """
        from tradingagents.web3_layer import (
            create_portfolio_feedback_engine,
        )
        
        if not submission_result.trade_submitted:
            logger.warning("No trade submitted, skipping feedback application")
            return
        
        try:
            # Extract trade intent from metadata
            trade_intent = submission_result.metadata.get("trade_intent", {})
            if not trade_intent:
                logger.warning("No trade intent in submission result, cannot apply feedback")
                return
            
            # Create feedback engine
            feedback_engine = create_portfolio_feedback_engine(self.portfolio_manager)
            
            # Apply approved or rejected trade
            if submission_result.trade_approved and submission_result.approval_event:
                outcome = feedback_engine.apply_approved_trade(
                    approval_event=submission_result.approval_event,
                    trade_intent=trade_intent,
                    execution_price_usd=None,  # TODO: fetch from DEX execution logs
                    execution_amount_filled=None,
                )
                
                if outcome.success:
                    logger.info(f"Portfolio updated with approved trade: {outcome.message}")
                    
                    # Record in memory that trade was approved and executed
                    self._record_trade_outcome_in_memory(
                        decision_state=final_state,
                        approval_status="approved",
                        approval_event=submission_result.approval_event,
                        outcome=outcome,
                        trade_date=trade_date,
                    )
                else:
                    logger.error(f"Failed to apply approved trade: {outcome.message}")
            
            elif submission_result.trade_rejected and submission_result.rejection_event:
                outcome = feedback_engine.apply_rejected_trade(
                    rejection_event=submission_result.rejection_event,
                    trade_intent=trade_intent,
                )
                
                if outcome.success:
                    logger.info(f"Rejection recorded: {outcome.message}")
                    
                    # Record in memory that trade was rejected
                    self._record_trade_outcome_in_memory(
                        decision_state=final_state,
                        approval_status="rejected",
                        rejection_event=submission_result.rejection_event,
                        rejection_reason=submission_result.rejection_reason,
                        trade_date=trade_date,
                    )
                else:
                    logger.error(f"Failed to record rejection: {outcome.message}")

            elif submission_result.trade_approved and (submission_result.metadata or {}).get("auto_approved_on_timeout"):
                logger.warning(
                    "Trade treated as approved due to feedback timeout. "
                    "Skipping portfolio execution-price application because no approval event payload is available."
                )
                self._record_trade_outcome_in_memory(
                    decision_state=final_state,
                    approval_status="approved",
                    trade_date=trade_date,
                )
            
            else:
                logger.warning("No approval/rejection feedback available")
                if submission_result.metadata.get("feedback_timeout"):
                    logger.warning("Feedback collection timed out, trade status unknown")
                    # Could implement fallback recovery here
        
        except Exception as e:
            logger.error(f"Error applying on-chain feedback: {e}", exc_info=True)
    
    def _record_trade_outcome_in_memory(
        self,
        decision_state: dict,
        approval_status: str,
        trade_date,
        approval_event: Optional[Dict[str, Any]] = None,
        rejection_event: Optional[Dict[str, Any]] = None,
        rejection_reason: Optional[str] = None,
        outcome: Optional["TradeExecutionOutcome"] = None,
    ) -> None:
        """Record the trade outcome in agent memory for learning.
        
        Args:
            decision_state: Final decision state
            approval_status: "approved" or "rejected"
            trade_date: Date of trade
            approval_event: TradeApprovalEvent dict (if approved)
            rejection_event: TradeRejectionEvent dict (if rejected)
            rejection_reason: Rejection reason (if rejected)
            outcome: TradeExecutionOutcome (if approved)
        """
        try:
            # Collect all agent memories
            agent_memories = {
                "bull": self.bull_memory,
                "bear": self.bear_memory,
                "trader": self.trader_memory,
                "invest_judge": self.invest_judge_memory,
                "risk_manager": self.risk_manager_memory,
            }
            
            # Record in all agent memories using the outcome recorder
            results = self.trade_outcome_recorder.record_trade_outcome_for_all_agents(
                agent_memories=agent_memories,
                decision_state=decision_state,
                approval_status=approval_status,
                trade_date=str(trade_date),
                approval_event=approval_event,
                rejection_event=rejection_event,
                rejection_reason=rejection_reason,
                portfolio_outcome=outcome.to_dict() if outcome else None,
            )
            
            # Log results
            success_count = sum(1 for v in results.values() if v)
            logger.info(
                f"Trade outcome recorded in {success_count}/{len(results)} agent memories "
                f"[status: {approval_status}]"
            )
        
        except Exception as e:
            logger.error(f"Error recording trade outcome in memory: {e}", exc_info=True)
