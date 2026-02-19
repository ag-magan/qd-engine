import logging
from datetime import date, datetime
from typing import Any, Optional

from supabase import create_client, Client

from src.shared.config import SUPABASE_URL, SUPABASE_KEY

logger = logging.getLogger(__name__)


def get_db() -> Client:
    """Create and return a Supabase client."""
    return create_client(SUPABASE_URL, SUPABASE_KEY)


class Database:
    """Wrapper around Supabase client with helper methods for common queries."""

    def __init__(self):
        self.client = get_db()

    # --- Signals ---

    def insert_signal(self, signal: dict) -> Optional[dict]:
        try:
            resp = self.client.table("signals").insert(signal).execute()
            return resp.data[0] if resp.data else None
        except Exception as e:
            logger.error(f"Failed to insert signal: {e}")
            return None

    def signal_exists(self, account_id: str, source: str, symbol: str,
                      signal_type: str, since_hours: int = 24) -> bool:
        """Check if a similar signal already exists within the time window."""
        try:
            from datetime import timedelta, timezone
            cutoff = (datetime.now(timezone.utc) - timedelta(hours=since_hours)).isoformat()
            resp = (
                self.client.table("signals")
                .select("id")
                .eq("account_id", account_id)
                .eq("source", source)
                .eq("symbol", symbol)
                .eq("signal_type", signal_type)
                .gte("created_at", cutoff)
                .execute()
            )
            return len(resp.data) > 0
        except Exception as e:
            logger.error(f"Failed to check signal existence: {e}")
            return False

    def get_existing_signal_keys(self, account_id: str, source: str,
                                  since_hours: int = 24) -> set:
        """Batch fetch existing (symbol, signal_type) pairs for a source.

        Returns a set for O(1) dedup lookups instead of one API call per signal.
        """
        try:
            from datetime import timedelta, timezone
            cutoff = (datetime.now(timezone.utc) - timedelta(hours=since_hours)).isoformat()
            resp = (
                self.client.table("signals")
                .select("symbol,signal_type")
                .eq("account_id", account_id)
                .eq("source", source)
                .gte("created_at", cutoff)
                .execute()
            )
            return {(row["symbol"], row["signal_type"]) for row in resp.data}
        except Exception as e:
            logger.error(f"Failed to batch fetch signal keys: {e}")
            return set()

    def insert_signals_batch(self, signals: list, batch_size: int = 500) -> list:
        """Insert signals in batches. Returns list of saved rows with IDs."""
        saved = []
        for i in range(0, len(signals), batch_size):
            batch = signals[i:i + batch_size]
            try:
                resp = self.client.table("signals").insert(batch).execute()
                saved.extend(resp.data)
            except Exception as e:
                logger.error(f"Failed to insert signal batch ({len(batch)} signals): {e}")
        return saved

    # --- Trades ---

    def insert_trade(self, trade: dict) -> Optional[dict]:
        try:
            resp = self.client.table("trades").insert(trade).execute()
            return resp.data[0] if resp.data else None
        except Exception as e:
            logger.error(f"Failed to insert trade: {e}")
            return None

    def update_trade(self, trade_id: int, updates: dict) -> Optional[dict]:
        try:
            resp = (
                self.client.table("trades")
                .update(updates)
                .eq("id", trade_id)
                .execute()
            )
            return resp.data[0] if resp.data else None
        except Exception as e:
            logger.error(f"Failed to update trade {trade_id}: {e}")
            return None

    def get_open_trades(self, account_id: str) -> list:
        try:
            resp = (
                self.client.table("trades")
                .select("*")
                .eq("account_id", account_id)
                .in_("status", ["submitted", "filled", "partially_filled",
                                "OrderStatus.PENDING_NEW", "OrderStatus.ACCEPTED",
                                "OrderStatus.NEW", "pending_new"])
                .execute()
            )
            return resp.data
        except Exception as e:
            logger.error(f"Failed to get open trades: {e}")
            return []

    def get_todays_trades(self, account_id: str) -> list:
        try:
            today = date.today().isoformat()
            resp = (
                self.client.table("trades")
                .select("*")
                .eq("account_id", account_id)
                .gte("created_at", today)
                .execute()
            )
            return resp.data
        except Exception as e:
            logger.error(f"Failed to get today's trades: {e}")
            return []

    # --- Trade Outcomes ---

    def insert_trade_outcome(self, outcome: dict) -> Optional[dict]:
        try:
            resp = self.client.table("trade_outcomes").insert(outcome).execute()
            return resp.data[0] if resp.data else None
        except Exception as e:
            logger.error(f"Failed to insert trade outcome: {e}")
            return None

    def get_trade_outcomes(self, account_id: str, limit: int = 50) -> list:
        try:
            resp = (
                self.client.table("trade_outcomes")
                .select("*")
                .eq("account_id", account_id)
                .order("created_at", desc=True)
                .limit(limit)
                .execute()
            )
            return resp.data
        except Exception as e:
            logger.error(f"Failed to get trade outcomes: {e}")
            return []

    def get_outcomes_by_strategy(self, account_id: str, strategy: str, limit: int = 50) -> list:
        try:
            resp = (
                self.client.table("trade_outcomes")
                .select("*")
                .eq("account_id", account_id)
                .eq("strategy", strategy)
                .order("created_at", desc=True)
                .limit(limit)
                .execute()
            )
            return resp.data
        except Exception as e:
            logger.error(f"Failed to get outcomes by strategy: {e}")
            return []

    # --- Learnings ---

    def get_learnings(self, account_id: str, active_only: bool = True) -> list:
        try:
            q = (
                self.client.table("strategy_learnings")
                .select("*")
                .eq("account_id", account_id)
            )
            if active_only:
                q = q.eq("is_active", True)
            resp = q.order("created_at", desc=True).execute()
            return resp.data
        except Exception as e:
            logger.error(f"Failed to get learnings: {e}")
            return []

    def insert_learning(self, learning: dict) -> Optional[dict]:
        try:
            resp = self.client.table("strategy_learnings").insert(learning).execute()
            return resp.data[0] if resp.data else None
        except Exception as e:
            logger.error(f"Failed to insert learning: {e}")
            return None

    def deactivate_learning(self, learning_id: int) -> None:
        try:
            self.client.table("strategy_learnings").update(
                {"is_active": False}
            ).eq("id", learning_id).execute()
        except Exception as e:
            logger.error(f"Failed to deactivate learning {learning_id}: {e}")

    # --- Signal Scorecard ---

    def get_scorecard(self, account_id: str, signal_source: str = None) -> list:
        try:
            q = (
                self.client.table("signal_scorecard")
                .select("*")
                .eq("account_id", account_id)
            )
            if signal_source:
                q = q.eq("signal_source", signal_source)
            resp = q.execute()
            return resp.data
        except Exception as e:
            logger.error(f"Failed to get scorecard: {e}")
            return []

    def upsert_scorecard(self, scorecard: dict) -> Optional[dict]:
        try:
            resp = (
                self.client.table("signal_scorecard")
                .upsert(scorecard, on_conflict="account_id,signal_source,period")
                .execute()
            )
            return resp.data[0] if resp.data else None
        except Exception as e:
            logger.error(f"Failed to upsert scorecard: {e}")
            return None

    # --- Portfolio Snapshots ---

    def upsert_snapshot(self, snapshot: dict) -> Optional[dict]:
        try:
            resp = (
                self.client.table("portfolio_snapshots")
                .upsert(snapshot, on_conflict="account_id,snapshot_date")
                .execute()
            )
            return resp.data[0] if resp.data else None
        except Exception as e:
            logger.error(f"Failed to upsert snapshot: {e}")
            return None

    def get_snapshots(self, account_id: str, limit: int = 30) -> list:
        try:
            resp = (
                self.client.table("portfolio_snapshots")
                .select("*")
                .eq("account_id", account_id)
                .order("snapshot_date", desc=True)
                .limit(limit)
                .execute()
            )
            return resp.data
        except Exception as e:
            logger.error(f"Failed to get snapshots: {e}")
            return []

    def get_latest_snapshot(self, account_id: str) -> Optional[dict]:
        try:
            resp = (
                self.client.table("portfolio_snapshots")
                .select("*")
                .eq("account_id", account_id)
                .order("snapshot_date", desc=True)
                .limit(1)
                .execute()
            )
            return resp.data[0] if resp.data else None
        except Exception as e:
            logger.error(f"Failed to get latest snapshot: {e}")
            return None

    # --- Claude Analyses ---

    def log_analysis(self, analysis: dict) -> Optional[dict]:
        try:
            resp = self.client.table("claude_analyses").insert(analysis).execute()
            return resp.data[0] if resp.data else None
        except Exception as e:
            logger.error(f"Failed to log analysis: {e}")
            return None

    # --- Theses ---

    def insert_thesis(self, thesis: dict) -> Optional[dict]:
        try:
            resp = self.client.table("theses").insert(thesis).execute()
            return resp.data[0] if resp.data else None
        except Exception as e:
            logger.error(f"Failed to insert thesis: {e}")
            return None

    def get_open_theses(self, account_id: str) -> list:
        try:
            resp = (
                self.client.table("theses")
                .select("*")
                .eq("account_id", account_id)
                .is_("outcome", "null")
                .execute()
            )
            return resp.data
        except Exception as e:
            logger.error(f"Failed to get open theses: {e}")
            return []

    def update_thesis(self, thesis_id: int, updates: dict) -> Optional[dict]:
        try:
            resp = (
                self.client.table("theses")
                .update(updates)
                .eq("id", thesis_id)
                .execute()
            )
            return resp.data[0] if resp.data else None
        except Exception as e:
            logger.error(f"Failed to update thesis {thesis_id}: {e}")
            return None

    # --- Adaptive Config ---

    def get_adaptive_config(self, account_id: str, parameter: str = None,
                            strategy: str = None) -> list:
        try:
            q = (
                self.client.table("adaptive_config")
                .select("*")
                .eq("account_id", account_id)
            )
            if parameter:
                q = q.eq("parameter", parameter)
            if strategy:
                q = q.eq("strategy", strategy)
            resp = q.execute()
            return resp.data
        except Exception as e:
            logger.error(f"Failed to get adaptive config: {e}")
            return []

    def upsert_adaptive_config(self, config: dict) -> Optional[dict]:
        try:
            resp = (
                self.client.table("adaptive_config")
                .upsert(config, on_conflict="account_id,parameter,strategy")
                .execute()
            )
            return resp.data[0] if resp.data else None
        except Exception as e:
            logger.error(f"Failed to upsert adaptive config: {e}")
            return None

    # --- Signal Weights ---

    def get_signal_weights(self, account_id: str) -> dict:
        """Return signal weights as {source: weight} dict."""
        try:
            resp = (
                self.client.table("signal_weights")
                .select("*")
                .eq("account_id", account_id)
                .execute()
            )
            return {row["signal_source"]: row["weight"] for row in resp.data}
        except Exception as e:
            logger.error(f"Failed to get signal weights: {e}")
            return {}

    def upsert_signal_weight(self, weight: dict) -> Optional[dict]:
        try:
            resp = (
                self.client.table("signal_weights")
                .upsert(weight, on_conflict="account_id,signal_source")
                .execute()
            )
            return resp.data[0] if resp.data else None
        except Exception as e:
            logger.error(f"Failed to upsert signal weight: {e}")
            return None

    # --- Pies ---

    def get_active_pie(self, account_id: str) -> Optional[dict]:
        try:
            resp = (
                self.client.table("pies")
                .select("*, pie_allocations(*)")
                .eq("account_id", account_id)
                .eq("is_active", True)
                .order("created_at", desc=True)
                .limit(1)
                .execute()
            )
            return resp.data[0] if resp.data else None
        except Exception as e:
            logger.error(f"Failed to get active pie: {e}")
            return None

    def create_pie(self, pie: dict, allocations: list) -> Optional[dict]:
        try:
            account_id = pie["account_id"]

            # Insert new pie as inactive (old pie stays active if this fails)
            pie["is_active"] = False
            resp = self.client.table("pies").insert(pie).execute()
            pie_data = resp.data[0]

            # Insert allocations
            for alloc in allocations:
                alloc["pie_id"] = pie_data["id"]
            self.client.table("pie_allocations").insert(allocations).execute()

            # Deactivate old pies (new pie is inactive, so won't be affected)
            self.client.table("pies").update(
                {"is_active": False}
            ).eq("account_id", account_id).eq("is_active", True).execute()

            # Activate new pie
            self.client.table("pies").update(
                {"is_active": True}
            ).eq("id", pie_data["id"]).execute()
            pie_data["is_active"] = True

            return pie_data
        except Exception as e:
            logger.error(f"Failed to create pie: {e}")
            return None

    # --- Health Checks ---

    def log_health_check(self, check: dict) -> Optional[dict]:
        try:
            resp = self.client.table("health_checks").insert(check).execute()
            return resp.data[0] if resp.data else None
        except Exception as e:
            logger.error(f"Failed to log health check: {e}")
            return None

    # --- Accounts ---

    def get_account(self, account_id: str) -> Optional[dict]:
        try:
            resp = (
                self.client.table("accounts")
                .select("*")
                .eq("id", account_id)
                .limit(1)
                .execute()
            )
            return resp.data[0] if resp.data else None
        except Exception as e:
            logger.error(f"Failed to get account: {e}")
            return None

    def get_all_accounts(self) -> list:
        try:
            resp = (
                self.client.table("accounts")
                .select("*")
                .eq("is_active", True)
                .execute()
            )
            return resp.data
        except Exception as e:
            logger.error(f"Failed to get all accounts: {e}")
            return []
