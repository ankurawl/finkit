from __future__ import annotations

import re
from datetime import datetime
from typing import Any


PDF_STANDARD_MAPPING: dict[str, Any] = {
    "date_col": "date",
    "payee_col": "payee",
    "narration_col": "narration",
    "amount_col": "amount",
    "amount_sign": "negative_is_debit",
    "date_format": "%Y-%m-%d",
}

_MONTHS = {
    "Jan": 1, "Feb": 2, "Mar": 3, "Apr": 4, "May": 5, "Jun": 6,
    "Jul": 7, "Aug": 8, "Sep": 9, "Oct": 10, "Nov": 11, "Dec": 12,
}

_INSTITUTION_KEYWORDS: list[tuple[str, list[str]]] = [
    ("marcus", ["Goldman Sachs Bank", "Marcus.com", "marcus.com"]),
    ("alliant", ["alliantcreditunion.org", "Alliant Credit Union", "ALLIANT"]),
    ("firsttech", ["firsttechfed.com", "First Tech Federal", "FIRST TECHNOLOGY FCU"]),
    ("frost", ["frostbank.com", "Frost Bank", "FROST PERSONAL"]),
    ("chase", ["chase.com/cardhelp", "CHASE FREEDOM", "CHASE PRIME", "CHASE UNITED"]),
    ("capitalone", ["capitalone.com", "Capital One", "Venture X Card"]),
    ("citi", ["citicards.com", "Costco Anywhere Visa", "Citi Double Cash", "CITI CARD"]),
    ("fidelity", ["Fidelity.com", "Fidelity Brokerage", "FIDELITY", "BrokerageLink"]),
]


def detect_institution(text: str) -> str | None:
    for slug, keywords in _INSTITUTION_KEYWORDS:
        for kw in keywords:
            if kw in text:
                return slug
    return None


def _clean_amount(s: str) -> str:
    s = s.strip().replace(",", "").replace("$", "")
    if s.startswith("(") and s.endswith(")"):
        s = "-" + s[1:-1]
    return s


def _infer_year(month: int, stmt_year: int, stmt_month: int) -> int:
    if month > stmt_month:
        return stmt_year - 1
    return stmt_year


def _extract_stmt_date_from_filename(filename: str) -> tuple[int, int]:
    m = re.search(r"(\d{4})\s+(\d{2})", filename)
    if m:
        return int(m.group(1)), int(m.group(2))
    m = re.search(r"(\d{4})\s+(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)", filename)
    if m:
        return int(m.group(1)), _MONTHS[m.group(2)]
    return 2026, 1


# ---- Marcus (Goldman Sachs) ------------------------------------------------

def parse_marcus(text: str, filename: str) -> list[dict]:
    rows: list[dict] = []

    period_match = re.search(
        r"(?:StatementPeriod|Statement Period)\s+(\d{2}/\d{2}/\d{4})\s*to\s*(\d{2}/\d{2}/\d{4})",
        text,
    )
    year = "2025"
    if period_match:
        year = period_match.group(2).split("/")[-1]

    activity_idx = text.find("ACCOUNT ACTIVITY")
    if activity_idx == -1:
        return rows

    section = text[activity_idx:]
    for m in re.finditer(
        r"(\d{2}/\d{2}/\d{4})\s+(.+?)\s+\$([0-9,.]+)\s+\$([0-9,.]+)",
        section,
    ):
        date_str, desc, amount_str, _ = m.group(1), m.group(2).strip(), m.group(3), m.group(4)
        if "BeginningBalance" in desc or "EndingBalance" in desc:
            continue

        date = datetime.strptime(date_str, "%m/%d/%Y").strftime("%Y-%m-%d")
        amt = _clean_amount(amount_str)

        if "Withdrawal" in desc or "Debit" in desc:
            amt = "-" + amt

        rows.append({"date": date, "payee": desc, "narration": desc, "amount": amt})

    return rows


# ---- Alliant Credit Union ---------------------------------------------------

def parse_alliant(text: str, filename: str) -> list[dict]:
    rows: list[dict] = []
    for m in re.finditer(
        r"(\d{2}/\d{2}/\d{2})\s+(DEPOSIT DIVIDEND)\s+(\d+\.\d{2})",
        text,
    ):
        date = datetime.strptime(m.group(1), "%m/%d/%y").strftime("%Y-%m-%d")
        rows.append({
            "date": date,
            "payee": "Alliant Dividend",
            "narration": m.group(2),
            "amount": _clean_amount(m.group(3)),
        })
    return rows


# ---- FirstTech (combined PDF) -----------------------------------------------

def parse_firsttech(text: str, filename: str) -> list[dict]:
    rows: list[dict] = []
    stmt_year, stmt_month = _extract_stmt_date_from_filename(filename)

    deposit_section = re.search(r"DEPOSITS\n(.*?)Total Deposits", text, re.DOTALL)
    if deposit_section:
        for m in re.finditer(
            r"(\d{2}/\d{2})\s+\d{2}/\d{2}\s+(.+?)\s+([\d,.]+(?:\.\d{2}))\s*$",
            deposit_section.group(1),
            re.MULTILINE,
        ):
            mm, dd = int(m.group(1)[:2]), int(m.group(1)[3:5])
            yr = _infer_year(mm, stmt_year, stmt_month)
            date = f"{yr}-{mm:02d}-{dd:02d}"
            rows.append({
                "date": date,
                "payee": m.group(2).strip(),
                "narration": m.group(2).strip(),
                "amount": _clean_amount(m.group(3)),
            })

    debit_section = re.search(r"MISCELLANEOUS DEBITS\n(.*?)Total Miscellaneous Debits", text, re.DOTALL)
    if debit_section:
        for m in re.finditer(
            r"(\d{2}/\d{2})\s+\d{2}/\d{2}\s+(.+?)\s+(-?[\d,.]+(?:\.\d{2}))\s*$",
            debit_section.group(1),
            re.MULTILINE,
        ):
            mm, dd = int(m.group(1)[:2]), int(m.group(1)[3:5])
            yr = _infer_year(mm, stmt_year, stmt_month)
            date = f"{yr}-{mm:02d}-{dd:02d}"
            amt = _clean_amount(m.group(3))
            if not amt.startswith("-"):
                amt = "-" + amt
            rows.append({
                "date": date,
                "payee": m.group(2).strip(),
                "narration": m.group(2).strip(),
                "amount": amt,
            })

    return rows


# ---- Chase Credit Cards -----------------------------------------------------

def parse_chase_cc(text: str, filename: str) -> list[dict]:
    rows: list[dict] = []
    stmt_year, stmt_month = _extract_stmt_date_from_filename(filename)

    for start_marker in [
        "AACCCCOOUUNNTT AACCTTIIVVIITTYY",
        "PAYMENTS AND OTHER CREDITS",
        "ACCOUNT ACTIVITY",
    ]:
        idx = text.find(start_marker)
        if idx >= 0:
            break
    else:
        return rows

    section = text[idx:]
    for end_marker in ["IINNTTEERREESSTT", "2026 Totals", "2025 Totals", "Interest Charge"]:
        end_idx = section.find(end_marker)
        if end_idx > 0:
            section = section[:end_idx]
            break

    for m in re.finditer(
        r"^(\d{2}/\d{2})\s+(.+?)\s+(-?[\d,.]*\.\d{2})\s*$",
        section,
        re.MULTILINE,
    ):
        date_short = m.group(1)
        desc = m.group(2).strip()
        amt = _clean_amount(m.group(3))

        skip_words = ["ORDER NUMBER", "PAYMENTS AND", "DATE OF", "MERCHANT", "TRANSACTION"]
        if any(w in desc.upper() for w in skip_words):
            continue

        mm = int(date_short[:2])
        dd = int(date_short[3:5])
        yr = _infer_year(mm, stmt_year, stmt_month)
        date = f"{yr}-{mm:02d}-{dd:02d}"

        rows.append({"date": date, "payee": desc, "narration": desc, "amount": amt})

    return rows


# ---- Capital One Credit Cards -----------------------------------------------

def parse_capitalone_cc(text: str, filename: str) -> list[dict]:
    rows: list[dict] = []
    stmt_year, stmt_month = _extract_stmt_date_from_filename(filename)

    txn_idx = text.find("Transactions\nVisit capitalone.com")
    if txn_idx == -1:
        txn_idx = text.find("Transactions")
    if txn_idx == -1:
        return rows

    section = text[txn_idx:]
    end_idx = section.find("\nFees\n")
    if end_idx == -1:
        end_idx = section.find("Total Transactions for This Period")
    if end_idx > 0:
        section = section[:end_idx]

    month_pat = "|".join(_MONTHS.keys())
    for m in re.finditer(
        rf"({month_pat})\s+(\d{{1,2}})\s+({month_pat})\s+(\d{{1,2}})\s+(.+?)\s+\$([0-9,.]+)\s*$",
        section,
        re.MULTILINE,
    ):
        post_month = _MONTHS[m.group(3)]
        post_day = int(m.group(4))
        desc = m.group(5).strip()
        amt = _clean_amount(m.group(6))

        yr = _infer_year(post_month, stmt_year, stmt_month)
        date = f"{yr}-{post_month:02d}-{post_day:02d}"

        rows.append({"date": date, "payee": desc, "narration": desc, "amount": amt})

    fee_match = re.search(
        rf"({month_pat})\s+(\d{{1,2}})\s+({month_pat})\s+(\d{{1,2}})\s+CAPITAL ONE MEMBER FEE\s+\$([0-9,.]+)",
        text,
    )
    if fee_match:
        post_month = _MONTHS[fee_match.group(3)]
        post_day = int(fee_match.group(4))
        amt = _clean_amount(fee_match.group(5))
        yr = _infer_year(post_month, stmt_year, stmt_month)
        date = f"{yr}-{post_month:02d}-{post_day:02d}"
        rows.append({
            "date": date,
            "payee": "Capital One Member Fee",
            "narration": "Annual membership fee",
            "amount": amt,
        })

    return rows


# ---- Citi Credit Cards ------------------------------------------------------

def parse_citi_cc(text: str, filename: str) -> list[dict]:
    rows: list[dict] = []
    stmt_year, stmt_month = _extract_stmt_date_from_filename(filename)

    in_txn_section = False
    for line in text.split("\n"):
        line = line.strip()

        if any(h in line for h in [
            "Payments, Credits and Adjustments",
            "Standard Purchases",
        ]):
            in_txn_section = True
            continue

        if in_txn_section and any(s in line for s in [
            "Fees Charged", "TOTAL FEES", "Interest Charged",
            "No Activity", "Costco Cash Back",
        ]):
            in_txn_section = False
            continue

        if not in_txn_section:
            continue

        m = re.match(
            r"(\d{2}/\d{2})\s+(?:(\d{2}/\d{2})\s+)?(.+?)\s+(-?\$?[\d,.]+\.\d{2})\s*$",
            line,
        )
        if not m:
            continue

        date1, date2, desc, amt_str = m.group(1), m.group(2), m.group(3).strip(), m.group(4)
        use_date = date2 if date2 else date1
        mm, dd = int(use_date[:2]), int(use_date[3:5])

        skip_words = ["CARD ENDING", "SPEND LIMIT", "NEW CHARGES"]
        if any(w in desc.upper() for w in skip_words):
            continue

        yr = _infer_year(mm, stmt_year, stmt_month)
        date = f"{yr}-{mm:02d}-{dd:02d}"
        amt = _clean_amount(amt_str)

        rows.append({"date": date, "payee": desc, "narration": desc, "amount": amt})

    return rows


# ---- Fidelity (Investment accounts) -----------------------------------------

def parse_fidelity(text: str, filename: str) -> list[dict]:
    rows: list[dict] = []
    stmt_year, _ = _extract_stmt_date_from_filename(filename)

    contrib_section = re.search(
        r"Contributions\nDate\s+Reference\s+Description\s+Amount\n(.*?)Total Contributions",
        text,
        re.DOTALL,
    )
    if contrib_section:
        for m in re.finditer(r"(\d{2}/\d{2})\s+(.+?)\s+\$([0-9,.]+)", contrib_section.group(1)):
            mm, dd = int(m.group(1)[:2]), int(m.group(1)[3:5])
            date = f"{stmt_year}-{mm:02d}-{dd:02d}"
            rows.append({
                "date": date,
                "payee": "Fidelity Contribution",
                "narration": m.group(2).strip(),
                "amount": _clean_amount(m.group(3)),
            })

    dist_section = re.search(
        r"Distributions\nDate\s+Reference\s+Description\s+Amount\n(.*?)Total Distributions",
        text,
        re.DOTALL,
    )
    if dist_section:
        for m in re.finditer(r"(\d{2}/\d{2})\s+(.+?)\s+-?\$([0-9,.]+)", dist_section.group(1)):
            mm, dd = int(m.group(1)[:2]), int(m.group(1)[3:5])
            date = f"{stmt_year}-{mm:02d}-{dd:02d}"
            rows.append({
                "date": date,
                "payee": "Fidelity Distribution",
                "narration": m.group(2).strip(),
                "amount": "-" + _clean_amount(m.group(3)),
            })

    div_section = re.search(
        r"Dividends, Interest & Other Income.*?\n(.*?)Total Dividends",
        text,
        re.DOTALL,
    )
    if div_section:
        for m in re.finditer(
            r"(\d{2}/\d{2})\s+(.+?)\s+\d+\s+(?:Dividend Received|Interest).*?\$([0-9,.]+)",
            div_section.group(1),
        ):
            mm, dd = int(m.group(1)[:2]), int(m.group(1)[3:5])
            date = f"{stmt_year}-{mm:02d}-{dd:02d}"
            rows.append({
                "date": date,
                "payee": f"Dividend - {m.group(2).strip()}",
                "narration": f"Dividend from {m.group(2).strip()}",
                "amount": _clean_amount(m.group(3)),
            })

    return rows


def parse_fidelity_holdings(text: str, filename: str) -> list[dict]:
    holdings: list[dict] = []
    stmt_year, _ = _extract_stmt_date_from_filename(filename)

    for m in re.finditer(
        r"([A-Z][A-Z\s'\-&]+?)\s*\(([A-Z]{2,10})\)\s+"
        r"(?:unavailable|\$[0-9,.]+)\s+"
        r"([0-9,.]+)\s+"
        r"\$([0-9,.]+)\s+"
        r"\$([0-9,.]+)\s+"
        r"\$([0-9,.]+)\s+"
        r"(?:\$|-)?([0-9,.]+)",
        text,
    ):
        holdings.append({
            "name": m.group(1).strip(),
            "ticker": m.group(2),
            "quantity": _clean_amount(m.group(3)),
            "price": _clean_amount(m.group(4)),
            "market_value": _clean_amount(m.group(5)),
            "cost_basis": _clean_amount(m.group(6)),
            "gain_loss": _clean_amount(m.group(7)),
        })

    for m in re.finditer(
        r"BERKSHIRE HATHAWAY.*?CLASS B \(BRKB\).*?"
        r"\$([0-9,.]+)\s+([0-9,.]+)\s+\$([0-9,.]+)\s+\$([0-9,.]+)\s+\$([0-9,.]+)\s+\$([0-9,.]+)",
        text,
        re.DOTALL,
    ):
        if not any(h["ticker"] == "BRKB" for h in holdings):
            holdings.append({
                "name": "BERKSHIRE HATHAWAY INC CLASS B",
                "ticker": "BRKB",
                "quantity": _clean_amount(m.group(2)),
                "price": _clean_amount(m.group(3)),
                "market_value": _clean_amount(m.group(4)),
                "cost_basis": _clean_amount(m.group(5)),
                "gain_loss": _clean_amount(m.group(6)),
            })

    acct_value = re.search(
        r"(?:Ending Account Value|Your Account Value)[:\s]+\$([0-9,.]+)", text
    )
    if acct_value:
        for h in holdings:
            h["account_value"] = _clean_amount(acct_value.group(1))

    return holdings


# ---- Frost Bank (balance only) ----------------------------------------------

def parse_frost(text: str, filename: str) -> list[dict]:
    return []


# ---- Registry ---------------------------------------------------------------

PARSERS: dict[str, Any] = {
    "marcus": parse_marcus,
    "alliant": parse_alliant,
    "firsttech": parse_firsttech,
    "frost": parse_frost,
    "chase": parse_chase_cc,
    "capitalone": parse_capitalone_cc,
    "citi": parse_citi_cc,
    "fidelity": parse_fidelity,
}


def parse_pdf_text(
    text: str,
    institution: str | None,
    filename: str,
) -> list[dict]:
    if institution is None:
        institution = detect_institution(text)

    if institution is None:
        return []

    parser = PARSERS.get(institution)
    if parser is None:
        return []

    return parser(text, filename)
