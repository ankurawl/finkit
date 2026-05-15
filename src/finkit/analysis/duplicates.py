from __future__ import annotations

from finkit.db import Database


def find_duplicates(
    db: Database,
    tolerance_days: int = 3,
    tolerance_amount: float = 0.01,
    account_name: str | None = None,
) -> list[dict]:
    account_filter = ""
    params: list = [tolerance_days, tolerance_days, tolerance_amount]

    if account_name is not None:
        row = db.fetchone("SELECT id FROM accounts WHERE name = ?", (account_name,))
        if row is None:
            raise ValueError(f"Account '{account_name}' not found")
        account_filter = "AND (p1.account_id = ? OR p2.account_id = ?)"
        params.extend([row["id"], row["id"]])

    sql = f"""
        SELECT
            t1.uuid AS uuid1, t1.date AS date1,
            COALESCE(t1.normalized_payee, t1.payee) AS payee1,
            t1.source_file_id AS source1,
            t2.uuid AS uuid2, t2.date AS date2,
            COALESCE(t2.normalized_payee, t2.payee) AS payee2,
            t2.source_file_id AS source2,
            p1.amount AS amount1, p2.amount AS amount2,
            a1.name AS account1, a2.name AS account2
        FROM transactions t1
        JOIN postings p1 ON p1.transaction_id = t1.id
        JOIN accounts a1 ON p1.account_id = a1.id
        JOIN transactions t2 ON t2.id > t1.id
        JOIN postings p2 ON p2.transaction_id = t2.id
        JOIN accounts a2 ON p2.account_id = a2.id
        WHERE t1.source_file_id IS NOT NULL
          AND t2.source_file_id IS NOT NULL
          AND t1.source_file_id != t2.source_file_id
          AND t2.date BETWEEN date(t1.date, '-' || ? || ' days')
                          AND date(t1.date, '+' || ? || ' days')
          AND ABS(CAST(p1.amount AS REAL) - CAST(p2.amount AS REAL)) <= ?
          {account_filter}
        ORDER BY t1.date, t1.id
    """

    rows = db.fetchall(sql, tuple(params))

    seen_pairs: set[tuple[str, str]] = set()
    results: list[dict] = []

    for r in rows:
        pair_key = (min(r["uuid1"], r["uuid2"]), max(r["uuid1"], r["uuid2"]))
        if pair_key in seen_pairs:
            continue
        seen_pairs.add(pair_key)

        payee1 = r["payee1"] or ""
        payee2 = r["payee2"] or ""
        payee_match = payee1.lower() == payee2.lower() if payee1 and payee2 else False
        date_exact = r["date1"] == r["date2"]
        amount_exact = r["amount1"] == r["amount2"]

        if amount_exact and date_exact and payee_match:
            confidence = "high"
        elif amount_exact and date_exact:
            confidence = "high"
        elif amount_exact:
            confidence = "medium"
        else:
            confidence = "low"

        results.append({
            "uuid1": r["uuid1"],
            "uuid2": r["uuid2"],
            "date1": r["date1"],
            "date2": r["date2"],
            "payee1": r["payee1"],
            "payee2": r["payee2"],
            "amount": r["amount1"],
            "account1": r["account1"],
            "account2": r["account2"],
            "source_file_id_1": r["source1"],
            "source_file_id_2": r["source2"],
            "confidence": confidence,
        })

    return results
