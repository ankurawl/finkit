from __future__ import annotations

from decimal import Decimal

from finkit.db import Database
from finkit.operations import open_account


_US_ACCOUNTS: list[tuple[str, str, str]] = [
    # (name_template, type, currency)
    ("Income:Salary:{employer}", "Income", "USD"),
    ("Expenses:Taxes:Federal", "Expenses", "USD"),
    ("Expenses:Taxes:State", "Expenses", "USD"),
    ("Expenses:Taxes:SocialSecurity", "Expenses", "USD"),
    ("Expenses:Taxes:Medicare", "Expenses", "USD"),
    ("Expenses:Benefits:Health", "Expenses", "USD"),
    ("Expenses:Benefits:Dental", "Expenses", "USD"),
    ("Expenses:Benefits:Vision", "Expenses", "USD"),
    ("Expenses:Benefits:Life", "Expenses", "USD"),
    ("Assets:Retirement:401k", "Assets", "USD"),
    ("Assets:Retirement:HSA", "Assets", "USD"),
    ("Assets:Retirement:FSA", "Assets", "USD"),
]

_US_ROLE_MAP: dict[str, str] = {
    "gross": "Income:Salary:{employer}",
    "federal_tax": "Expenses:Taxes:Federal",
    "state_tax": "Expenses:Taxes:State",
    "social_security": "Expenses:Taxes:SocialSecurity",
    "medicare": "Expenses:Taxes:Medicare",
    "health_insurance": "Expenses:Benefits:Health",
    "dental": "Expenses:Benefits:Dental",
    "vision": "Expenses:Benefits:Vision",
    "life_insurance": "Expenses:Benefits:Life",
    "retirement_401k": "Assets:Retirement:401k",
    "hsa": "Assets:Retirement:HSA",
    "fsa": "Assets:Retirement:FSA",
}

_IN_ACCOUNTS: list[tuple[str, str, str]] = [
    ("Income:Salary:{employer}", "Income", "INR"),
    ("Expenses:Taxes:IncomeTax", "Expenses", "INR"),
    ("Expenses:Taxes:ProfessionalTax", "Expenses", "INR"),
    ("Expenses:Benefits:PF", "Expenses", "INR"),
    ("Expenses:Benefits:Health", "Expenses", "INR"),
    ("Assets:Retirement:EPF", "Assets", "INR"),
    ("Assets:Retirement:NPS", "Assets", "INR"),
]

_IN_ROLE_MAP: dict[str, str] = {
    "gross": "Income:Salary:{employer}",
    "income_tax": "Expenses:Taxes:IncomeTax",
    "professional_tax": "Expenses:Taxes:ProfessionalTax",
    "pf": "Expenses:Benefits:PF",
    "health_insurance": "Expenses:Benefits:Health",
    "epf": "Assets:Retirement:EPF",
    "nps": "Assets:Retirement:NPS",
}


def setup_payroll_accounts(
    db: Database,
    employer: str,
    jurisdiction: str = "US",
) -> dict[str, str]:
    if jurisdiction == "US":
        account_defs = _US_ACCOUNTS
        role_map = _US_ROLE_MAP
    elif jurisdiction == "IN":
        account_defs = _IN_ACCOUNTS
        role_map = _IN_ROLE_MAP
    else:
        raise ValueError(f"Unsupported jurisdiction: {jurisdiction}")

    with db.transaction():
        for name_template, acct_type, currency in account_defs:
            name = name_template.format(employer=employer)
            existing = db.fetchone("SELECT id FROM accounts WHERE name = ?", (name,))
            if existing:
                continue
            open_account(db, name=name, type=acct_type, currency=currency)

    return {
        role: name_template.format(employer=employer)
        for role, name_template in role_map.items()
    }


def build_payslip_transaction(
    date: str,
    pay_period: str,
    employer: str,
    line_items: list[dict],
    net_pay_account: str,
    currency: str = "USD",
) -> dict:
    gross_amount: Decimal | None = None
    gross_account: str | None = None
    deductions: list[dict] = []

    for item in line_items:
        if "gross" in item["label"].lower():
            gross_amount = Decimal(item["amount"])
            gross_account = item["account"]
        else:
            deductions.append(item)

    if gross_amount is None or gross_account is None:
        raise ValueError("No gross pay item found (label must contain 'gross')")

    deduction_total = sum(Decimal(d["amount"]) for d in deductions)
    net_pay = gross_amount - deduction_total

    postings: list[dict] = [
        {"account": gross_account, "amount": str(-gross_amount), "currency": currency},
    ]
    for d in deductions:
        postings.append({
            "account": d["account"],
            "amount": d["amount"],
            "currency": currency,
        })
    postings.append({
        "account": net_pay_account,
        "amount": str(net_pay),
        "currency": currency,
    })

    total = sum(Decimal(p["amount"]) for p in postings)
    if abs(total) > Decimal("0.01"):
        raise ValueError(
            f"Payslip postings do not balance: sum is {total} (tolerance 0.01)"
        )

    return {
        "date": date,
        "payee": employer,
        "narration": f"Payroll {pay_period}",
        "postings": postings,
        "tags": ["payroll"],
    }


def get_payroll_account_map(db: Database, employer: str) -> dict[str, str]:
    role_patterns: dict[str, str] = {
        "gross": f"Income:Salary:{employer}",
        "federal_tax": "Expenses:Taxes:Federal",
        "state_tax": "Expenses:Taxes:State",
        "social_security": "Expenses:Taxes:SocialSecurity",
        "medicare": "Expenses:Taxes:Medicare",
        "health_insurance": "Expenses:Benefits:Health",
        "dental": "Expenses:Benefits:Dental",
        "vision": "Expenses:Benefits:Vision",
        "life_insurance": "Expenses:Benefits:Life",
        "retirement_401k": "Assets:Retirement:401k",
        "hsa": "Assets:Retirement:HSA",
        "fsa": "Assets:Retirement:FSA",
        "income_tax": "Expenses:Taxes:IncomeTax",
        "professional_tax": "Expenses:Taxes:ProfessionalTax",
        "pf": "Expenses:Benefits:PF",
        "epf": "Assets:Retirement:EPF",
        "nps": "Assets:Retirement:NPS",
    }

    result: dict[str, str] = {}
    for role, name in role_patterns.items():
        row = db.fetchone("SELECT name FROM accounts WHERE name = ?", (name,))
        if row:
            result[role] = row["name"]
    return result
