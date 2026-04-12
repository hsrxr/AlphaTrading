"""Portfolio state persistence using SQLite with automatic schema initialization.

Manages the single source of truth for:
- Cash balance
- Positions (JSON format for flexible multi-asset support)
- Realized/unrealized PnL tracking
- Historical portfolio snapshots for audit trail
"""

import sqlite3
import json
import os
import requests
from datetime import datetime
from pathlib import Path
from typing import Dict, Any, Optional, List
import logging

logger = logging.getLogger(__name__)


class PortfolioManager:
    """Manage persistent portfolio state in SQLite database."""

    def __init__(self, db_path: str = "./trade_memory/portfolio.db"):
        """Initialize portfolio manager and ensure schema exists.
        
        Args:
            db_path: Path to SQLite database file
        """
        self.db_path = db_path
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)
        self._init_schema()

    def _init_schema(self):
        """Create portfolio_state table if it doesn't exist."""
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS portfolio_state (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp TEXT NOT NULL,
                    cash_usd REAL NOT NULL,
                    positions TEXT NOT NULL,
                    unrealized_pnl REAL NOT NULL DEFAULT 0.0,
                    realized_pnl REAL NOT NULL DEFAULT 0.0,
                    total_assets REAL NOT NULL,
                    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
                )
            """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS trade_history (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp TEXT NOT NULL,
                    ticker TEXT NOT NULL,
                    side TEXT NOT NULL,
                    quantity REAL NOT NULL,
                    entry_price REAL NOT NULL,
                    notional_usd REAL NOT NULL,
                    status TEXT DEFAULT 'open',
                    exit_price REAL,
                    realized_pnl REAL,
                    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
                )
            """)
            conn.commit()

    def _read_claim_balance_eth(self) -> Optional[float]:
        """Read claimed ETH balance from agent-id.json if available."""
        try:
            project_root = Path(self.db_path).resolve().parent.parent
            agent_id_path = project_root / "agent-id.json"
            if not agent_id_path.exists():
                return None

            payload = json.loads(agent_id_path.read_text(encoding="utf-8"))
            balance_eth = payload.get("claim", {}).get("balanceEth")
            if balance_eth is None:
                return None

            value = float(balance_eth)
            return value if value > 0 else None
        except Exception:
            return None

    def _resolve_eth_usd_rate(self) -> float:
        """Resolve ETH/USD conversion rate for claim balance conversion.

        Priority:
        1) TRADING_ETH_USD_RATE env var
        2) ETH_USD_RATE env var
        3) live ETHUSD quote (Binance ETHUSDT, fallback CoinGecko)
        4) fallback 2000.0
        """
        for env_key in ("TRADING_ETH_USD_RATE", "ETH_USD_RATE"):
            raw = os.getenv(env_key)
            if not raw:
                continue
            try:
                value = float(raw)
                if value > 0:
                    return value
            except (TypeError, ValueError):
                continue

        timeout_s = float(os.getenv("TRADING_PRICE_TIMEOUT_SECONDS", "5") or "5")

        # Prefer Binance live quote. Binance spot mostly exposes ETHUSDT rather than ETHUSD.
        # For this conversion we treat USDT ~= USD.
        try:
            resp = requests.get(
                "https://api.binance.com/api/v3/ticker/price",
                params={"symbol": "ETHUSDT"},
                timeout=timeout_s,
            )
            resp.raise_for_status()
            payload = resp.json()
            rate = float(payload.get("price", 0))
            if rate > 0:
                logger.info("Resolved ETH/USD rate from Binance ETHUSDT: %.2f", rate)
                return rate
        except Exception as exc:
            logger.warning("Failed to fetch Binance ETHUSDT live quote: %s", exc)

        # Fallback to CoinGecko public simple price endpoint.
        try:
            resp = requests.get(
                "https://api.coingecko.com/api/v3/simple/price",
                params={"ids": "ethereum", "vs_currencies": "usd"},
                timeout=timeout_s,
            )
            resp.raise_for_status()
            payload = resp.json()
            rate = float(payload.get("ethereum", {}).get("usd", 0))
            if rate > 0:
                logger.info("Resolved ETH/USD rate from CoinGecko: %.2f", rate)
                return rate
        except Exception as exc:
            logger.warning("Failed to fetch CoinGecko ETH/USD quote: %s", exc)

        return 2000.0

    def get_initial_capital(self) -> float:
        """Resolve initial capital from env or agent-id.json claim balance.

        Priority:
        1) TRADING_INITIAL_CASH_USD env var
        2) agent-id.json -> claim.balanceEth converted to USD (only if TRADING_USE_CLAIM_BALANCE=true)
        3) fallback 100000.0
        """
        raw_env = os.getenv("TRADING_INITIAL_CASH_USD")
        if raw_env:
            try:
                value = float(raw_env)
                if value > 0:
                    return value
            except (TypeError, ValueError):
                pass

        use_claim_balance = str(os.getenv("TRADING_USE_CLAIM_BALANCE", "false")).strip().lower() in {
            "1",
            "true",
            "yes",
            "on",
        }
        if use_claim_balance:
            balance_eth = self._read_claim_balance_eth()
            if balance_eth is not None:
                eth_usd_rate = self._resolve_eth_usd_rate()
                converted = balance_eth * eth_usd_rate
                logger.info(
                    "Resolved initial capital from claim balance: %.6f ETH * %.2f USD/ETH = %.2f USD",
                    balance_eth,
                    eth_usd_rate,
                    converted,
                )
                return converted

        return 100000.0

    def load_latest_portfolio(self) -> Dict[str, Any]:
        """Load the latest portfolio state from database.
        
        Returns:
            Dict with cash_usd, positions, unrealized_pnl, realized_pnl
            Returns default initial state if no record exists.
        """
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.execute("""
                SELECT cash_usd, positions, unrealized_pnl, realized_pnl, timestamp
                FROM portfolio_state
                ORDER BY id DESC
                LIMIT 1
            """)
            row = cursor.fetchone()

        if row:
            cash_usd, positions_json, unrealized_pnl, realized_pnl, timestamp = row
            positions = json.loads(positions_json) if positions_json else {}

            # Auto-heal legacy rows with tiny cash baseline to configured initial capital.
            claim_eth = self._read_claim_balance_eth()
            expected_usd = self.get_initial_capital()
            if (
                expected_usd >= 1000.0
                and float(cash_usd) < expected_usd * 0.01
                and expected_usd >= 1.0
                and not positions
            ):
                logger.warning(
                    "Detected tiny/legacy portfolio baseline (cash_usd=%.6f). "
                    "Auto-correcting to %.2f USD.",
                    cash_usd,
                    expected_usd,
                )
                cash_usd = expected_usd
                self.save_portfolio_state(
                    {
                        "cash_usd": cash_usd,
                        "positions": positions,
                        "unrealized_pnl": unrealized_pnl,
                        "realized_pnl": realized_pnl,
                        "timestamp": datetime.utcnow().isoformat(),
                    }
                )
            
            logger.info(
                f"Loaded portfolio state from {timestamp}: "
                f"cash=${cash_usd:.2f}, positions={positions}"
            )
            
            return {
                "cash_usd": cash_usd,
                "positions": positions,
                "position_usd": sum(p.get("notional_usd", 0) for p in positions.values()),
                "unrealized_pnl": unrealized_pnl,
                "realized_pnl": realized_pnl,
                "timestamp": timestamp,
            }
        else:
            # First initialization: inject initial capital
            logger.info("No portfolio state found; initializing with default state")
            initial_capital = self.get_initial_capital()
            default_state = {
                "cash_usd": initial_capital,
                "positions": {},
                "position_usd": 0.0,
                "unrealized_pnl": 0.0,
                "realized_pnl": 0.0,
                "timestamp": datetime.utcnow().isoformat(),
            }
            self.save_portfolio_state(default_state)
            return default_state

    def save_portfolio_state(self, portfolio_state: Dict[str, Any]) -> None:
        """Persist portfolio state to database.
        
        Args:
            portfolio_state: Dict with cash_usd, positions, unrealized_pnl, realized_pnl
        """
        timestamp = portfolio_state.get("timestamp", datetime.utcnow().isoformat())
        cash_usd = portfolio_state.get("cash_usd", 100000.0)
        positions = portfolio_state.get("positions", {})
        unrealized_pnl = portfolio_state.get("unrealized_pnl", 0.0)
        realized_pnl = portfolio_state.get("realized_pnl", 0.0)
        
        # Calculate total assets
        position_usd = sum(p.get("notional_usd", 0) for p in positions.values())
        total_assets = cash_usd + position_usd + unrealized_pnl

        with sqlite3.connect(self.db_path) as conn:
            conn.execute("""
                INSERT INTO portfolio_state
                (timestamp, cash_usd, positions, unrealized_pnl, realized_pnl, total_assets)
                VALUES (?, ?, ?, ?, ?, ?)
            """, (
                timestamp,
                cash_usd,
                json.dumps(positions, ensure_ascii=False),
                unrealized_pnl,
                realized_pnl,
                total_assets,
            ))
            conn.commit()

        logger.debug(
            f"Saved portfolio: cash=${cash_usd:.2f}, "
            f"position=${position_usd:.2f}, "
            f"unrealized_pnl=${unrealized_pnl:.2f}"
        )

    def record_trade(
        self,
        ticker: str,
        side: str,
        quantity: float,
        entry_price: float,
        notional_usd: float,
    ) -> int:
        """Record a trade execution in history ledger.
        
        Args:
            ticker: Trading pair symbol
            side: 'BUY' or 'SELL'
            quantity: Quantity executed
            entry_price: Execution price
            notional_usd: Order size in USD
            
        Returns:
            Trade ID (primary key)
        """
        timestamp = datetime.utcnow().isoformat()
        
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.execute("""
                INSERT INTO trade_history
                (timestamp, ticker, side, quantity, entry_price, notional_usd, status)
                VALUES (?, ?, ?, ?, ?, ?, 'open')
            """, (timestamp, ticker, side, quantity, entry_price, notional_usd))
            conn.commit()
            trade_id = cursor.lastrowid

        logger.info(
            f"Recorded trade #{trade_id}: {side} {quantity} {ticker} @ ${entry_price} "
            f"(${notional_usd:.2f})"
        )
        return trade_id

    def close_trade(
        self,
        trade_id: int,
        exit_price: float,
        realized_pnl: float,
    ) -> None:
        """Close a trade and record realized PnL.
        
        Args:
            trade_id: Trade ID to close
            exit_price: Exit execution price
            realized_pnl: Realized profit/loss amount
        """
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("""
                UPDATE trade_history
                SET status='closed', exit_price=?, realized_pnl=?
                WHERE id=?
            """, (exit_price, realized_pnl, trade_id))
            conn.commit()

        logger.debug(f"Closed trade #{trade_id}: realized_pnl=${realized_pnl:.2f}")

    def get_portfolio_history(
        self,
        limit: int = 100,
    ) -> List[Dict[str, Any]]:
        """Retrieve historical portfolio snapshots.
        
        Args:
            limit: Maximum number of records to return
            
        Returns:
            List of portfolio state dicts ordered by timestamp DESC
        """
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.execute("""
                SELECT timestamp, cash_usd, positions, unrealized_pnl, realized_pnl, total_assets
                FROM portfolio_state
                ORDER BY timestamp DESC
                LIMIT ?
            """, (limit,))
            rows = cursor.fetchall()

        return [
            {
                "timestamp": row[0],
                "cash_usd": row[1],
                "positions": json.loads(row[2]),
                "unrealized_pnl": row[3],
                "realized_pnl": row[4],
                "total_assets": row[5],
            }
            for row in rows
        ]

    def get_trade_history(
        self,
        ticker: Optional[str] = None,
        status: Optional[str] = None,
        limit: int = 100,
    ) -> List[Dict[str, Any]]:
        """Retrieve trade execution history.
        
        Args:
            ticker: Filter by ticker symbol
            status: Filter by status ('open', 'closed')
            limit: Maximum records to return
            
        Returns:
            List of trade records ordered by timestamp DESC
        """
        query = "SELECT * FROM trade_history WHERE 1=1"
        params = []

        if ticker:
            query += " AND ticker=?"
            params.append(ticker)

        if status:
            query += " AND status=?"
            params.append(status)

        query += " ORDER BY timestamp DESC LIMIT ?"
        params.append(limit)

        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.execute(query, params)
            rows = cursor.fetchall()

        # Get column names
        col_names = [desc[0] for desc in cursor.description] if rows else []

        return [dict(zip(col_names, row)) for row in rows]
