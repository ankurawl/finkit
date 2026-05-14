from __future__ import annotations

from decimal import Decimal

from finkit.db import Database

_TOLERANCE = Decimal("0.01")

_FORM_DISPATCHERS: dict[str, str] = {
    "w2": "_reconcile_w2",
    "1099_int": "_reconcile_1099_int",
    "1099_div": "_reconcile_1099_div",
    "1099_b": "_reconcile_1099_b",
    "form16": "_reconcile_form16",
}


def _account_total(db: Database, pattern: str, year: int) -> tuple[Decimal, int, list[str]]:
    """Returns (total_amount, transaction_count, account_names) for accounts matching pattern in the given year."""
    start = f"{year}-01-01"
    end = f"{year}-12-31"

    row = db.fetchone(
        """
        SELECT COALESCE(SUM(ABS(CAST(p.amount AS REAL))), 0) as total,
               COUNT(DISTINCT t.id) as txn_count
        FROM postings p
        JOIN transactions t ON p.transaction_id = t.id
        JOIN accounts a ON p.account_id = a.id
        WHERE a.name LIKE ? AND t.date BETWEEN ? AND ?
        """,
        (pattern, start, end),
    )

    total = Decimal(str(row["total"])) if row else Decimal("0")
    txn_count = row["txn_count"] if row else 0

    acct_rows = db.fetchall(
        """
        SELECT DISTINCT a.name
        FROM postings p
        JOIN transactions t ON p.transaction_id = t.id
        JOIN accounts a ON p.account_id = a.id
        WHERE a.name LIKE ? AND t.date BETWEEN ? AND ?
        ORDER BY a.name
        """,
        (pattern, start, end),
    )
    account_names = [r["name"] for r in acct_rows]

    return total, txn_count, account_names


def _make_comparison(
    field: str,
    form_value: str,
    ledger_value: Decimal,
    note: str | None = None,
) -> dict:
    form_dec = Decimal(str(form_value))
    difference = abs(form_dec - ledger_value)

    if ledger_value == Decimal("0") and form_dec > Decimal("0"):
        status = "missing"
    elif difference <= _TOLERANCE:
        status = "match"
    else:
        status = "mismatch"

    result: dict = {
        "field": field,
        "form_value": str(form_dec),
        "ledger_value": str(ledger_value),
        "difference": str(difference),
        "status": status,
    }
    if note:
        result["note"] = note
    return result


def _build_result(
    form_type: str,
    year: int,
    comparisons: list[dict],
    missing_income: list[dict] | None = None,
) -> dict:
    total = len(comparisons)
    matched = sum(1 for c in comparisons if c["status"] == "match")
    mismatched = sum(1 for c in comparisons if c["status"] == "mismatch")
    missing = sum(1 for c in comparisons if c["status"] == "missing")

    return {
        "form_type": form_type,
        "year": year,
        "comparisons": comparisons,
        "missing_income": missing_income or [],
        "summary": {
            "total_fields": total,
            "matched": matched,
            "mismatched": mismatched,
            "missing": missing,
        },
    }


def _reconcile_w2(db: Database, year: int, fields: dict) -> dict:
    comparisons: list[dict] = []

    field_map: dict[str, str] = {
        "wages": "Income:Salary:%",
        "federal_tax": "Expenses:Taxes:Federal%",
        "state_tax": "Expenses:Taxes:State%",
        "ss_tax": "Expenses:Taxes:SocialSecurity%",
        "medicare_tax": "Expenses:Taxes:Medicare%",
    }

    wages_total = Decimal("0")
    for field_name in ("wages", "federal_tax", "state_tax", "ss_tax", "medicare_tax"):
        if field_name not in fields:
            continue
        pattern = field_map[field_name]
        total, _, _ = _account_total(db, pattern, year)
        if field_name == "wages":
            wages_total = total
        comparisons.append(_make_comparison(field_name, fields[field_name], total))

    for field_name in ("ss_wages", "medicare_wages"):
        if field_name not in fields:
            continue
        note = "Compared against wages total (usually the same)"
        comparisons.append(
            _make_comparison(field_name, fields[field_name], wages_total, note=note)
        )

    if "employer" in fields:
        pass  # informational only, not compared

    return _build_result("w2", year, comparisons)


def _reconcile_1099_int(db: Database, year: int, fields: dict) -> dict:
    comparisons: list[dict] = []
    missing_income: list[dict] = []

    if "interest" in fields:
        total, _, _ = _account_total(db, "Income:Interest:%", year)
        comp = _make_comparison("interest", fields["interest"], total)
        comparisons.append(comp)

        form_dec = Decimal(str(fields["interest"]))
        if comp["status"] == "missing" and form_dec > Decimal("0"):
            payer = fields.get("payer", "Unknown")
            missing_income.append({
                "type": "interest",
                "payer": payer,
                "amount": str(form_dec),
                "suggested_transaction": {
                    "date": f"{year}-12-31",
                    "payee": payer,
                    "narration": "Interest income (from 1099-INT)",
                    "postings": [
                        {"account": f"Income:Interest:{payer}", "amount": str(-form_dec), "currency": "USD"},
                        {"account": "Assets:Uncategorized", "amount": str(form_dec), "currency": "USD"},
                    ],
                    "tags": ["tax-reconciliation"],
                },
            })

    return _build_result("1099_int", year, comparisons, missing_income)


def _reconcile_1099_div(db: Database, year: int, fields: dict) -> dict:
    comparisons: list[dict] = []

    if "ordinary_dividends" in fields:
        div_total, _, _ = _account_total(db, "Income:Dividends:%", year)
        inv_total, _, _ = _account_total(db, "Income:Investment:%", year)
        combined = div_total + inv_total
        comparisons.append(
            _make_comparison("ordinary_dividends", fields["ordinary_dividends"], combined)
        )

    if "qualified_dividends" in fields:
        comparisons.append(
            _make_comparison(
                "qualified_dividends",
                fields["qualified_dividends"],
                Decimal("0"),
                note="Qualified dividends not tracked separately in ledger",
            )
        )

    return _build_result("1099_div", year, comparisons)


def _reconcile_1099_b(db: Database, year: int, fields: dict) -> dict:
    comparisons: list[dict] = []

    row = db.fetchone(
        "SELECT * FROM s_yearly_capital_gains WHERE year = ? LIMIT 1",
        (year,),
    )

    rows = db.fetchall(
        "SELECT * FROM s_yearly_capital_gains WHERE year = ?",
        (year,),
    )

    total_proceeds = Decimal("0")
    total_cost_basis = Decimal("0")
    total_gain_loss = Decimal("0")
    for r in rows:
        total_proceeds += Decimal(str(r["total_proceeds"]))
        total_cost_basis += Decimal(str(r["total_cost_basis"]))
        total_gain_loss += Decimal(str(r["total_gain_loss"]))

    if "proceeds" in fields:
        comparisons.append(_make_comparison("proceeds", fields["proceeds"], total_proceeds))

    if "cost_basis" in fields:
        comparisons.append(_make_comparison("cost_basis", fields["cost_basis"], total_cost_basis))

    if "gain_loss" in fields:
        comparisons.append(_make_comparison("gain_loss", fields["gain_loss"], total_gain_loss))

    return _build_result("1099_b", year, comparisons)


def _reconcile_form16(db: Database, year: int, fields: dict) -> dict:
    comparisons: list[dict] = []

    if "gross_salary" in fields:
        total, _, _ = _account_total(db, "Income:Salary:%", year)
        comparisons.append(_make_comparison("gross_salary", fields["gross_salary"], total))

    if "tds" in fields:
        total, _, _ = _account_total(db, "Expenses:Taxes:IncomeTax%", year)
        comparisons.append(_make_comparison("tds", fields["tds"], total))

    return _build_result("form16", year, comparisons)


_DISPATCHERS = {
    "w2": _reconcile_w2,
    "1099_int": _reconcile_1099_int,
    "1099_div": _reconcile_1099_div,
    "1099_b": _reconcile_1099_b,
    "form16": _reconcile_form16,
}


def reconcile_tax_document(
    db: Database,
    form_type: str,
    year: int,
    fields: dict,
) -> dict:
    handler = _DISPATCHERS.get(form_type)
    if handler is None:
        raise ValueError(f"Unknown form type: {form_type}")
    return handler(db, year, fields)


def tax_readiness_report(
    db: Database,
    year: int,
    jurisdiction: str = "US",
) -> dict:
    # Income by category
    income_categories: dict[str, dict] = {}
    income_rows = db.fetchall(
        """
        SELECT a.name, COALESCE(SUM(ABS(CAST(p.amount AS REAL))), 0) as total,
               COUNT(DISTINCT t.id) as txn_count
        FROM postings p
        JOIN transactions t ON p.transaction_id = t.id
        JOIN accounts a ON p.account_id = a.id
        WHERE a.type = 'Income' AND t.date BETWEEN ? AND ?
        GROUP BY a.name
        ORDER BY a.name
        """,
        (f"{year}-01-01", f"{year}-12-31"),
    )

    category_groups: dict[str, dict] = {}
    for row in income_rows:
        acct_name = row["name"]
        parts = acct_name.split(":")
        cat_key = parts[1].lower() if len(parts) > 1 else "other"
        if cat_key not in category_groups:
            category_groups[cat_key] = {
                "total": Decimal("0"),
                "transaction_count": 0,
                "accounts": [],
            }
        category_groups[cat_key]["total"] += Decimal(str(row["total"]))
        category_groups[cat_key]["transaction_count"] += row["txn_count"]
        category_groups[cat_key]["accounts"].append(acct_name)

    income: dict[str, dict] = {}
    for cat_key, data in category_groups.items():
        income[cat_key] = {
            "total": str(data["total"]),
            "transaction_count": data["transaction_count"],
            "accounts": data["accounts"],
        }

    # Taxes paid
    if jurisdiction == "US":
        tax_map = {
            "federal": "Expenses:Taxes:Federal%",
            "state": "Expenses:Taxes:State%",
            "social_security": "Expenses:Taxes:SocialSecurity%",
            "medicare": "Expenses:Taxes:Medicare%",
        }
    else:
        tax_map = {
            "income_tax": "Expenses:Taxes:IncomeTax%",
            "professional_tax": "Expenses:Taxes:ProfessionalTax%",
        }

    taxes_paid: dict[str, str] = {}
    for key, pattern in tax_map.items():
        total, _, _ = _account_total(db, pattern, year)
        taxes_paid[key] = str(total)

    # Capital gains
    cap_rows = db.fetchall(
        "SELECT * FROM s_yearly_capital_gains WHERE year = ?",
        (year,),
    )
    short_term = Decimal("0")
    long_term = Decimal("0")
    for r in cap_rows:
        gain = Decimal(str(r["total_gain_loss"]))
        if r["term"] == "short":
            short_term += gain
        else:
            long_term += gain

    capital_gains = {
        "short_term": str(short_term),
        "long_term": str(long_term),
        "total": str(short_term + long_term),
    }

    # Deductible expenses
    deductible_patterns = [
        "Expenses:Medical%",
        "Expenses:Charity%",
        "Expenses:Education%",
        "Expenses:Donations%",
    ]
    deductible_expenses: list[dict] = []
    for pattern in deductible_patterns:
        total, _, accounts = _account_total(db, pattern, year)
        if total > Decimal("0"):
            category = pattern.replace("%", "")
            deductible_expenses.append({
                "category": category,
                "total": str(total),
            })

    # Gaps detection
    gaps: list[str] = []
    salary_total, salary_count, _ = _account_total(db, "Income:Salary:%", year)
    if salary_count > 0 and salary_count not in (12, 24, 26):
        gaps.append(
            f"Found {salary_count} salary transactions "
            f"— expected 12 for monthly, 24 for semi-monthly, or 26 for biweekly pay"
        )

    return {
        "year": year,
        "jurisdiction": jurisdiction,
        "income": income,
        "taxes_paid": taxes_paid,
        "capital_gains": capital_gains,
        "deductible_expenses": deductible_expenses,
        "gaps": gaps,
    }
