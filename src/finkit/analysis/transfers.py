from __future__ import annotations

from decimal import Decimal

from finkit.db import Database


def detect_transfers(
    db: Database, tolerance_days: int = 3,
) -> list[dict]:
    sql = """
        SELECT
            t.uuid, t.date, t.payee,
            COALESCE(t.normalized_payee, t.payee) AS display_payee,
            t.source_file_id,
            p_real.id AS real_posting_id,
            a_real.name AS real_account,
            p_real.amount AS real_amount,
            p_uncat.id AS uncat_posting_id,
            a_uncat.name AS uncat_account,
            p_uncat.amount AS uncat_amount
        FROM transactions t
        JOIN postings p_real ON p_real.transaction_id = t.id
        JOIN accounts a_real ON p_real.account_id = a_real.id
        JOIN postings p_uncat ON p_uncat.transaction_id = t.id
        JOIN accounts a_uncat ON p_uncat.account_id = a_uncat.id
        WHERE a_real.type IN ('Assets', 'Liabilities')
          AND a_uncat.name LIKE '%Uncategorized%'
          AND (SELECT COUNT(*) FROM postings WHERE transaction_id = t.id) = 2
        ORDER BY t.date
    """
    candidates = db.fetchall(sql)

    outgoing = []
    incoming = []

    for c in candidates:
        real_amt = Decimal(str(c["real_amount"]))
        if real_amt < 0:
            outgoing.append(c)
        else:
            incoming.append(c)

    results = []
    used_incoming: set[str] = set()
    tolerance = Decimal("0.01")

    for out in outgoing:
        out_amt = abs(Decimal(str(out["real_amount"])))
        out_date = out["date"]

        for inc in incoming:
            if inc["uuid"] in used_incoming:
                continue
            if inc["uuid"] == out["uuid"]:
                continue

            inc_amt = abs(Decimal(str(inc["real_amount"])))
            if abs(out_amt - inc_amt) > tolerance:
                continue

            date_match_sql = db.fetchone(
                "SELECT ABS(julianday(?) - julianday(?)) AS diff",
                (out_date, inc["date"]),
            )
            if date_match_sql and date_match_sql["diff"] > tolerance_days:
                continue

            date_exact = out_date == inc["date"]
            confidence = "high" if date_exact else "medium"

            results.append({
                "outgoing_uuid": out["uuid"],
                "outgoing_date": out["date"],
                "outgoing_account": out["real_account"],
                "outgoing_amount": out["real_amount"],
                "incoming_uuid": inc["uuid"],
                "incoming_date": inc["date"],
                "incoming_account": inc["real_account"],
                "incoming_amount": inc["real_amount"],
                "confidence": confidence,
            })
            used_incoming.add(inc["uuid"])
            break

    return results
