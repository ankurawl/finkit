from __future__ import annotations

import re


def classify_document(text: str, file_type: str) -> tuple[str, str]:
    lower = text.lower()
    length = len(text)

    # Each rule: (doc_type, checker_fn)
    # checker_fn returns the number of keyword matches, or 0 for no match.
    # Checked in priority order — most specific first.

    rules: list[tuple[str, int]] = [
        ("payslip", _check_payslip(lower)),
        ("tax_w2", _check_tax_w2(lower)),
        ("tax_1099", _check_tax_1099(lower)),
        ("tax_form16", _check_tax_form16(lower)),
        ("mortgage_statement", _check_mortgage_statement(lower)),
        ("loan_statement", _check_loan_statement(lower)),
        ("insurance_statement", _check_insurance_statement(lower)),
        ("receipt", _check_receipt(lower, length)),
        ("invoice", _check_invoice(lower)),
        ("brokerage_statement", _check_brokerage_statement(lower)),
        ("credit_card_statement", _check_credit_card_statement(lower)),
        ("bank_statement", _check_bank_statement(lower)),
        ("utility_bill", _check_utility_bill(lower)),
        ("property_tax", _check_property_tax(lower)),
    ]

    for doc_type, match_count in rules:
        if match_count > 0:
            confidence = _confidence_from_count(match_count, doc_type)
            return doc_type, confidence

    return "unknown", "low"


def _confidence_from_count(count: int, doc_type: str) -> str:
    # Very specific identifiers always get high confidence
    if doc_type in ("tax_w2", "tax_1099", "tax_form16") and count >= 1:
        return "high"
    if count >= 3:
        return "high"
    if count >= 2:
        return "medium"
    return "low"


def _check_payslip(lower: str) -> int:
    keywords = [
        "gross pay", "net pay", "deductions", "pay period",
        "earnings statement", "pay stub", "ytd",
    ]
    count = sum(1 for kw in keywords if kw in lower)
    return count if count >= 2 else 0


def _check_tax_w2(lower: str) -> int:
    # W-2 can appear with or without hyphen/space
    if re.search(r"\bw-2\b", lower) or "wage and tax statement" in lower:
        count = 0
        if re.search(r"\bw-2\b", lower):
            count += 1
        if "wage and tax statement" in lower:
            count += 1
        return max(count, 1)
    return 0


def _check_tax_1099(lower: str) -> int:
    forms = ["1099-int", "1099-div", "1099-b", "1099-misc", "1099-nec", "form 1099"]
    count = sum(1 for f in forms if f in lower)
    return count if count >= 1 else 0


def _check_tax_form16(lower: str) -> int:
    keywords = ["form no. 16", "form 16", "section 203", "certificate under section"]
    count = sum(1 for kw in keywords if kw in lower)
    return count if count >= 1 else 0


def _check_mortgage_statement(lower: str) -> int:
    if "mortgage" not in lower:
        return 0
    extras = ["escrow", "property tax", "homeowners insurance"]
    count = sum(1 for kw in extras if kw in lower)
    # "mortgage" itself counts as 1
    return (1 + count) if count >= 1 else 0


def _check_loan_statement(lower: str) -> int:
    has_loan = "loan" in lower or "promissory" in lower
    if not has_loan:
        return 0
    required = ["principal", "interest", "remaining balance"]
    count = sum(1 for kw in required if kw in lower)
    if count == len(required):
        # loan/promissory + all three required
        return 1 + count
    return 0


def _check_insurance_statement(lower: str) -> int:
    has_prefix = "premium" in lower or "policy" in lower
    if not has_prefix:
        return 0
    extras = ["coverage", "deductible", "claim"]
    count = sum(1 for kw in extras if kw in lower)
    return (1 + count) if count >= 1 else 0


def _check_receipt(lower: str, length: int) -> int:
    if length >= 3000:
        return 0
    if "receipt" in lower:
        return 1
    if "total" in lower and "subtotal" in lower:
        return 2
    return 0


def _check_invoice(lower: str) -> int:
    if "invoice" not in lower:
        return 0
    extras = ["bill to", "amount due", "due date"]
    count = sum(1 for kw in extras if kw in lower)
    return (1 + count) if count >= 1 else 0


def _check_brokerage_statement(lower: str) -> int:
    count = 0
    if "portfolio" in lower:
        count += 1
    if "holdings" in lower:
        count += 1
    if "securities" in lower and "dividends" in lower:
        count += 2
    return count


def _check_credit_card_statement(lower: str) -> int:
    keywords = ["minimum payment", "credit limit", "payment due"]
    count = sum(1 for kw in keywords if kw in lower)
    return count


def _check_bank_statement(lower: str) -> int:
    keywords = ["statement period", "beginning balance", "ending balance", "account activity"]
    count = sum(1 for kw in keywords if kw in lower)
    return count


def _check_utility_bill(lower: str) -> int:
    has_type = any(kw in lower for kw in ["electric", "gas", "water", "sewer"])
    if not has_type:
        return 0
    extras = ["usage", "meter", "utility"]
    count = sum(1 for kw in extras if kw in lower)
    return (1 + count) if count >= 1 else 0


def _check_property_tax(lower: str) -> int:
    if "property tax" not in lower:
        return 0
    extras = ["assessment", "parcel", "tax bill"]
    count = sum(1 for kw in extras if kw in lower)
    return (1 + count) if count >= 1 else 0


_HINTS: dict[str, dict] = {
    "payslip": {
        "expect": "single_multi_posting_transaction",
        "look_for": [
            "gross_pay", "federal_tax", "state_tax", "social_security", "medicare",
            "health_insurance", "dental", "vision", "401k", "hsa", "other_deductions", "net_pay",
            "pay_period_start", "pay_period_end", "pay_date", "employer",
        ],
        "typical_accounts": {
            "gross": "Income:Salary:{Employer}",
            "federal_tax": "Expenses:Taxes:Federal",
            "state_tax": "Expenses:Taxes:State",
            "social_security": "Expenses:Taxes:SocialSecurity",
            "medicare": "Expenses:Taxes:Medicare",
            "health_insurance": "Expenses:Benefits:Health",
            "401k": "Assets:Retirement:401k",
            "net_pay": "Assets:{Bank}:{Account}",
        },
        "note": "Gross pay is negative (income). All deductions and net pay are positive. Must sum to zero.",
    },
    "tax_w2": {
        "expect": "annual_summary",
        "look_for": [
            "wages", "federal_tax_withheld", "social_security_wages", "social_security_tax",
            "medicare_wages", "medicare_tax", "state_wages", "state_tax", "employer_name", "employer_ein",
        ],
        "typical_accounts": {"wages": "Income:Salary:*", "taxes": "Expenses:Taxes:*"},
        "note": "W-2 is an annual summary. Use reconcile_tax_document tool to compare against recorded payslip transactions rather than creating new transactions.",
    },
    "tax_1099": {
        "expect": "annual_summary",
        "look_for": [
            "interest_income", "ordinary_dividends", "qualified_dividends", "capital_gain_distributions",
            "proceeds", "cost_basis", "payer_name",
        ],
        "typical_accounts": {"interest": "Income:Interest:*", "dividends": "Income:Dividends:*"},
        "note": "1099 income may already be captured from bank/brokerage imports. Use reconcile_tax_document to check before creating duplicate transactions.",
    },
    "tax_form16": {
        "expect": "annual_summary",
        "look_for": [
            "gross_salary", "exemptions", "tds_deducted", "net_taxable_income", "employer_name", "pan",
        ],
        "typical_accounts": {"salary": "Income:Salary:*", "tds": "Expenses:Taxes:IncomeTax"},
        "note": "Indian tax certificate. Use reconcile_tax_document with form_type='form16' to compare against recorded salary transactions.",
    },
    "mortgage_statement": {
        "expect": "single_multi_posting_transaction",
        "look_for": [
            "payment_date", "principal", "interest", "escrow", "total_payment",
            "remaining_balance", "lender",
        ],
        "typical_accounts": {
            "principal": "Liabilities:Mortgage:{Lender}",
            "interest": "Expenses:Interest:Mortgage",
            "escrow": "Assets:Escrow:{Lender}",
            "payment": "Assets:{Bank}:{Account}",
        },
        "note": "Split payment into principal (reduces liability), interest (expense), and escrow (asset).",
    },
    "loan_statement": {
        "expect": "single_multi_posting_transaction",
        "look_for": [
            "payment_date", "principal", "interest", "total_payment", "remaining_balance", "lender",
        ],
        "typical_accounts": {
            "principal": "Liabilities:Loan:{Lender}",
            "interest": "Expenses:Interest:Loan",
            "payment": "Assets:{Bank}:{Account}",
        },
    },
    "insurance_statement": {
        "expect": "single_transaction",
        "look_for": ["premium_amount", "due_date", "policy_number", "coverage_period", "insurer"],
        "typical_accounts": {
            "premium": "Expenses:Insurance:{Type}",
            "payment": "Assets:{Bank}:{Account}",
        },
    },
    "receipt": {
        "expect": "single_transaction",
        "look_for": ["date", "merchant", "total", "subtotal", "tax", "items"],
        "typical_accounts": {
            "expense": "Expenses:{Category}",
            "payment": "Assets:{Bank}:{Account}",
        },
    },
    "invoice": {
        "expect": "single_transaction",
        "look_for": ["invoice_number", "date", "due_date", "amount_due", "vendor", "line_items"],
        "typical_accounts": {
            "expense": "Expenses:{Category}",
            "payable": "Liabilities:AccountsPayable",
        },
    },
    "brokerage_statement": {
        "expect": "multiple_transactions",
        "look_for": [
            "statement_period", "holdings", "transactions", "dividends",
            "interest", "fees", "account_value",
        ],
        "typical_accounts": {
            "holdings": "Assets:Investments:{Broker}:{Symbol}",
            "dividends": "Income:Dividends:{Symbol}",
            "fees": "Expenses:Fees:Investment",
        },
    },
    "credit_card_statement": {
        "expect": "multiple_transactions",
        "look_for": [
            "statement_period", "transactions", "previous_balance", "payments",
            "new_charges", "new_balance", "minimum_payment", "due_date",
        ],
        "typical_accounts": {
            "charges": "Expenses:{Category}",
            "card": "Liabilities:CreditCard:{Issuer}",
        },
    },
    "bank_statement": {
        "expect": "multiple_transactions",
        "look_for": [
            "statement_period", "beginning_balance", "ending_balance",
            "deposits", "withdrawals", "transactions",
        ],
        "typical_accounts": {
            "account": "Assets:{Bank}:{AccountType}",
            "transactions": "Expenses:{Category} or Income:{Category}",
        },
    },
    "utility_bill": {
        "expect": "single_transaction",
        "look_for": ["billing_period", "amount_due", "due_date", "usage", "rate", "provider"],
        "typical_accounts": {
            "expense": "Expenses:Utilities:{Type}",
            "payment": "Assets:{Bank}:{Account}",
        },
    },
    "property_tax": {
        "expect": "single_transaction",
        "look_for": ["tax_year", "assessed_value", "tax_amount", "due_date", "parcel_number"],
        "typical_accounts": {
            "tax": "Expenses:Taxes:Property",
            "payment": "Assets:{Bank}:{Account}",
        },
    },
    "unknown": {
        "expect": "unknown",
        "look_for": ["date", "amount", "description", "payee"],
        "typical_accounts": "Unable to determine — ask the user for account details.",
    },
}


def get_extraction_hints(document_type: str) -> dict:
    return _HINTS.get(document_type, _HINTS["unknown"])
