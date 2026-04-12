import os

DEFAULT_CONFIG = {
    # Paths
    "project_dir": os.path.abspath(os.path.join(os.path.dirname(__file__), ".")),
    "results_dir": os.getenv("TRADINGAGENTS_RESULTS_DIR", "./results"),
    "data_cache_dir": os.path.join(
        os.path.abspath(os.path.join(os.path.dirname(__file__), ".")),
        "dataflows/data_cache",
    ),

    # LLM settings
    "llm_provider": "deepseek",  # "openai", "google", "deepseek", etc.
    "deep_think_llm": "deepseek-reasoner",  # For in-depth analysis and reasoning
    "quick_think_llm": "deepseek-chat",
    "backend_url": "https://api.deepseek.com/v1",

    # Provider-specific thinking configuration
    "google_thinking_level": None,      # "high", "minimal", etc.
    "openai_reasoning_effort": None,    # "medium", "high", "low"
    "llm_timeout_seconds": 180.0,
    "llm_max_retries": 5,
    "enable_llm_streaming": True,

    # Debate and discussion settings
    "max_debate_rounds": 1,
    # Kept for compatibility with existing CLI wiring.
    "max_risk_discuss_rounds": 1,
    "max_recur_limit": 100,
    "graph_invoke_retries": 3,
    "graph_invoke_backoff_seconds": 2.0,

    # Deterministic risk-engine settings
    "max_position_pct": 0.20,
    "max_single_order_pct": 0.10,

    # Progress tracking settings
    "enable_progress_tracking": True,   # Enable real-time progress display
    "enable_colored_output": True,      # Use colored output for better readability
    "use_trader_v2": True,             # False=legacy trader (BUY/SELL/HOLD), True=v2 trader (BUY/SELL only)
    "enable_on_chain_submission": False,      # Whether to submit trades on-chain (requires additional config)
    "on_chain_submit_hold_decisions": False,  # Whether HOLD decisions should still submit TradeIntent to RiskRouter
    "on_chain_auto_approve_without_feedback": True,  # Treat feedback-timeout trades as locally approved

    # Outer trigger runtime settings
    "enable_trigger_runtime": False,
    "trigger_pairs": ["ETHUSD", "BTCUSD", "BNBUSD", "SOLUSD",],
    "trigger_poll_interval_seconds": 10,
    "trigger_aggregation_window_seconds": 90,
    "trigger_cooldown_seconds": 300,
    "trigger_news_lookback_minutes": 240,
    "trigger_news_sources": ["sec", "twitter", "project"],
    "trigger_twitter_accounts": [
        "@tier10k",
        "@DeItaone",
        "@binance",
        "@ethereum",
        "@VitalikButerin",
        "@Tether_to",
        "@paoloardoino",
        "@lookonchain",
        "@zachxbt",
        "@whale_alert",
        "@CryptoHayes",
        "@elonmusk",
        "@peach_miasma",
    ],
    "trigger_nitter_instances": [
        "https://nitter.net",
        "https://nitter.1d4.us",
        "https://nitter.poast.org",
        "https://nitter.privacydev.net",
    ],
}
