from __future__ import annotations

from finkit.db import Database


def import_report(db: Database, source_file_id: int | None = None) -> dict:
    if source_file_id is not None:
        sf_filter = "WHERE sf.id = ?"
        sf_params: tuple = (source_file_id,)
    else:
        sf_filter = ""
        sf_params = ()

    source_files_sql = f"""
        SELECT sf.id, sf.path, sf.institution, sf.imported_at, sf.original_filename,
               COUNT(t.id) AS transaction_count,
               MIN(t.date) AS min_date,
               MAX(t.date) AS max_date
        FROM source_files sf
        LEFT JOIN transactions t ON t.source_file_id = sf.id
        {sf_filter}
        GROUP BY sf.id
        ORDER BY sf.imported_at DESC
    """
    source_files = db.fetchall(source_files_sql, sf_params)

    source_file_list = []
    for sf in source_files:
        date_range = None
        if sf["min_date"] and sf["max_date"]:
            date_range = f"{sf['min_date']} to {sf['max_date']}"
        source_file_list.append({
            "id": sf["id"],
            "path": sf["path"],
            "institution": sf["institution"],
            "transaction_count": sf["transaction_count"],
            "date_range": date_range,
        })

    uncat_rows = db.fetchall("""
        SELECT t.uuid, COALESCE(t.normalized_payee, t.payee) AS payee,
               t.date, p.amount, a.name AS account_name
        FROM transactions t
        JOIN postings p ON p.transaction_id = t.id
        JOIN accounts a ON p.account_id = a.id
        WHERE a.name LIKE '%Uncategorized%'
        ORDER BY t.date DESC
        LIMIT 200
    """)
    uncategorized = {
        "count": len(uncat_rows),
        "transactions": [
            {"uuid": r["uuid"], "payee": r["payee"], "date": r["date"],
             "amount": r["amount"], "account": r["account_name"]}
            for r in uncat_rows
        ],
    }

    try:
        from finkit.analysis.duplicates import find_duplicates
        potential_duplicates = find_duplicates(db, tolerance_days=3, tolerance_amount=0.01)
    except Exception:
        potential_duplicates = []

    balance_rows = db.fetchall("""
        SELECT a.name AS account, a.type,
               SUM(CAST(p.amount AS REAL)) AS balance
        FROM accounts a
        JOIN postings p ON p.account_id = a.id
        GROUP BY a.id
        HAVING (a.type = 'Assets' AND balance < -0.01)
            OR (a.type = 'Liabilities' AND balance > 0.01)
    """)
    balance_anomalies = []
    for r in balance_rows:
        issue = "negative asset" if r["type"] == "Assets" else "positive liability"
        balance_anomalies.append({
            "account": r["account"],
            "balance": str(round(r["balance"], 2)),
            "issue": issue,
        })

    monthly_rows = db.fetchall("""
        SELECT a.name AS account, a.type,
               strftime('%Y-%m', t.date) AS year_month,
               MIN(t.date) AS min_date,
               MAX(t.date) AS max_date
        FROM accounts a
        JOIN postings p ON p.account_id = a.id
        JOIN transactions t ON t.id = p.transaction_id
        WHERE a.type IN ('Assets', 'Liabilities')
        GROUP BY a.id, strftime('%Y-%m', t.date)
        ORDER BY a.name, year_month
    """)
    account_months: dict[str, list[str]] = {}
    account_ranges: dict[str, tuple[str, str]] = {}
    for r in monthly_rows:
        name = r["account"]
        ym = r["year_month"]
        account_months.setdefault(name, []).append(ym)
        if name not in account_ranges:
            account_ranges[name] = (ym, ym)
        else:
            account_ranges[name] = (account_ranges[name][0], ym)

    missing_periods = []
    for acct_name, months in account_months.items():
        if len(months) < 2:
            continue
        start_ym, end_ym = account_ranges[acct_name]
        sy, sm = int(start_ym[:4]), int(start_ym[5:7])
        ey, em = int(end_ym[:4]), int(end_ym[5:7])

        expected = set()
        y, m = sy, sm
        while (y, m) <= (ey, em):
            expected.add(f"{y:04d}-{m:02d}")
            m += 1
            if m > 12:
                m = 1
                y += 1

        actual = set(months)
        missing = sorted(expected - actual)
        if missing:
            missing_periods.append({
                "account": acct_name,
                "missing_months": missing,
            })

    orphaned = [sf for sf in source_file_list if sf["transaction_count"] == 0]

    summary_row = db.fetchone("""
        SELECT COUNT(*) AS total_transactions,
               MIN(date) AS min_date,
               MAX(date) AS max_date
        FROM transactions
    """)
    status_rows = db.fetchall("""
        SELECT status, COUNT(*) AS count FROM transactions GROUP BY status
    """)
    type_rows = db.fetchall("""
        SELECT a.type, COUNT(DISTINCT t.id) AS count
        FROM transactions t
        JOIN postings p ON p.transaction_id = t.id
        JOIN accounts a ON p.account_id = a.id
        GROUP BY a.type
    """)

    summary = {
        "total_transactions": summary_row["total_transactions"] if summary_row else 0,
        "date_range": f"{summary_row['min_date']} to {summary_row['max_date']}" if summary_row and summary_row["min_date"] else None,
        "by_status": {r["status"]: r["count"] for r in status_rows},
        "by_account_type": {r["type"]: r["count"] for r in type_rows},
        "source_file_count": len(source_file_list),
    }

    return {
        "source_files": source_file_list,
        "uncategorized": uncategorized,
        "potential_duplicates": potential_duplicates,
        "balance_anomalies": balance_anomalies,
        "missing_periods": missing_periods,
        "orphaned_source_files": orphaned,
        "summary": summary,
    }
