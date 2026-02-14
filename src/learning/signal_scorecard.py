import logging
from collections import defaultdict
from datetime import datetime

from src.shared.database import Database

logger = logging.getLogger(__name__)


def update_scorecard(account_id: str, period: str = None) -> dict:
    """Update signal source accuracy metrics for an account."""
    db = Database()

    if period is None:
        period = f"all_time_{datetime.now().strftime('%Y%m')}"

    outcomes = db.get_trade_outcomes(account_id, limit=10000)
    if not outcomes:
        return {}

    # Group by signal source
    by_source = defaultdict(lambda: {
        "total": 0, "acted_on": 0, "wins": 0, "losses": 0,
        "returns": [], "best": None, "worst": None,
    })

    for o in outcomes:
        source = o.get("signal_source") or o.get("strategy", "unknown")
        pnl = float(o.get("realized_pnl", 0) or 0)
        pnl_pct = float(o.get("pnl_pct", 0) or 0)

        by_source[source]["total"] += 1
        by_source[source]["acted_on"] += 1
        by_source[source]["returns"].append(pnl_pct)

        if pnl > 0:
            by_source[source]["wins"] += 1
        else:
            by_source[source]["losses"] += 1

        # Track best/worst
        trade_info = {"symbol": o.get("symbol"), "pnl": pnl, "pnl_pct": pnl_pct}
        if by_source[source]["best"] is None or pnl > by_source[source]["best"]["pnl"]:
            by_source[source]["best"] = trade_info
        if by_source[source]["worst"] is None or pnl < by_source[source]["worst"]["pnl"]:
            by_source[source]["worst"] = trade_info

    # Also count signals that weren't acted on
    try:
        signals_resp = (
            db.client.table("signals")
            .select("source, acted_on")
            .eq("account_id", account_id)
            .execute()
        )
        for sig in signals_resp.data:
            source = sig.get("source", "unknown")
            by_source[source]["total"] += 1
            if sig.get("acted_on"):
                by_source[source]["acted_on"] += 1
    except Exception:
        pass

    # Upsert scorecards
    updated = {}
    for source, data in by_source.items():
        import numpy as np
        avg_return = round(float(np.mean(data["returns"])), 2) if data["returns"] else 0
        total = data["wins"] + data["losses"]
        win_rate = round(data["wins"] / total * 100, 1) if total > 0 else 0

        scorecard = {
            "account_id": account_id,
            "signal_source": source,
            "period": period,
            "total_signals": data["total"],
            "acted_on": data["acted_on"],
            "wins": data["wins"],
            "losses": data["losses"],
            "win_rate": win_rate,
            "avg_return_pct": avg_return,
            "best_trade": data["best"],
            "worst_trade": data["worst"],
        }
        db.upsert_scorecard(scorecard)
        updated[source] = scorecard

    logger.info(f"Updated scorecard for {account_id}: {len(updated)} sources")
    return updated
