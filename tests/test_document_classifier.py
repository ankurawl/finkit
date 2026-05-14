from __future__ import annotations

import pytest

from finkit.importers.document_classifier import classify_document, get_extraction_hints


# ---------------------------------------------------------------------------
# classify_document tests
# ---------------------------------------------------------------------------


class TestPayslip:
    def test_basic_payslip(self):
        text = "Your Earnings Statement for pay period ending 01/15/2026. Gross Pay: $5,000. Deductions: $1,200. Net Pay: $3,800."
        doc_type, confidence = classify_document(text, "pdf")
        assert doc_type == "payslip"

    def test_high_confidence_many_keywords(self):
        text = "Pay Stub — Gross Pay $5000, Net Pay $3800, Deductions $1200, Pay Period 01/01–01/15, YTD earnings $10000"
        doc_type, confidence = classify_document(text, "pdf")
        assert doc_type == "payslip"
        assert confidence == "high"

    def test_medium_confidence_two_keywords(self):
        text = "Gross Pay: $5,000. Net Pay: $3,800."
        doc_type, confidence = classify_document(text, "pdf")
        assert doc_type == "payslip"
        assert confidence == "medium"

    def test_one_keyword_not_enough(self):
        text = "Your gross pay for the period."
        doc_type, _ = classify_document(text, "pdf")
        assert doc_type != "payslip"


class TestTaxW2:
    def test_w2_keyword(self):
        text = "Form W-2 Wage and Tax Statement 2025"
        doc_type, confidence = classify_document(text, "pdf")
        assert doc_type == "tax_w2"
        assert confidence == "high"

    def test_w2_alone(self):
        text = "This is your W-2 for the tax year."
        doc_type, confidence = classify_document(text, "pdf")
        assert doc_type == "tax_w2"
        assert confidence == "high"

    def test_wage_and_tax_statement(self):
        text = "Wage and Tax Statement for calendar year 2025"
        doc_type, confidence = classify_document(text, "pdf")
        assert doc_type == "tax_w2"
        assert confidence == "high"


class TestTax1099:
    def test_1099_int(self):
        doc_type, confidence = classify_document("1099-INT Interest Income", "pdf")
        assert doc_type == "tax_1099"
        assert confidence == "high"

    def test_1099_div(self):
        doc_type, _ = classify_document("Form 1099-DIV Dividends and Distributions", "pdf")
        assert doc_type == "tax_1099"

    def test_form_1099_generic(self):
        doc_type, _ = classify_document("Form 1099 information return", "pdf")
        assert doc_type == "tax_1099"

    def test_multiple_1099_forms(self):
        text = "1099-INT and 1099-DIV combined statement"
        doc_type, confidence = classify_document(text, "pdf")
        assert doc_type == "tax_1099"
        assert confidence == "high"


class TestTaxForm16:
    def test_form_16(self):
        text = "Form 16 Certificate under section 203 of the Income Tax Act"
        doc_type, confidence = classify_document(text, "pdf")
        assert doc_type == "tax_form16"
        assert confidence == "high"

    def test_form_no_16(self):
        text = "Form No. 16 issued by employer"
        doc_type, confidence = classify_document(text, "pdf")
        assert doc_type == "tax_form16"
        assert confidence == "high"


class TestMortgageStatement:
    def test_mortgage_with_escrow(self):
        text = "Your mortgage payment. Escrow analysis shows property tax increase."
        doc_type, _ = classify_document(text, "pdf")
        assert doc_type == "mortgage_statement"

    def test_mortgage_with_property_tax(self):
        text = "Mortgage statement. Property tax portion of your payment."
        doc_type, _ = classify_document(text, "pdf")
        assert doc_type == "mortgage_statement"

    def test_mortgage_with_insurance(self):
        text = "Mortgage details. Homeowners insurance premium included."
        doc_type, _ = classify_document(text, "pdf")
        assert doc_type == "mortgage_statement"

    def test_mortgage_alone_no_match(self):
        text = "Mortgage rates are rising in the current market."
        doc_type, _ = classify_document(text, "pdf")
        assert doc_type != "mortgage_statement"


class TestMortgagePriorityOverLoan:
    def test_mortgage_not_classified_as_loan(self):
        text = "Mortgage loan statement. Principal $800, Interest $600, Remaining balance $250,000. Escrow $400."
        doc_type, _ = classify_document(text, "pdf")
        assert doc_type == "mortgage_statement"


class TestLoanStatement:
    def test_loan_with_all_required(self):
        text = "Personal loan statement. Principal: $500, Interest: $50, Remaining balance: $9,450."
        doc_type, _ = classify_document(text, "pdf")
        assert doc_type == "loan_statement"

    def test_loan_missing_required(self):
        text = "Loan amount $10,000. Principal payment due."
        doc_type, _ = classify_document(text, "pdf")
        assert doc_type != "loan_statement"

    def test_promissory_note(self):
        text = "Promissory note. Principal $1000, Interest $50, Remaining balance $9000."
        doc_type, _ = classify_document(text, "pdf")
        assert doc_type == "loan_statement"


class TestInsuranceStatement:
    def test_premium_with_coverage(self):
        text = "Insurance premium notice. Your coverage details for the policy period."
        doc_type, _ = classify_document(text, "pdf")
        assert doc_type == "insurance_statement"

    def test_policy_with_deductible(self):
        text = "Policy summary. Your deductible is $500."
        doc_type, _ = classify_document(text, "pdf")
        assert doc_type == "insurance_statement"

    def test_premium_alone_no_match(self):
        text = "Premium quality products available now."
        doc_type, _ = classify_document(text, "pdf")
        assert doc_type != "insurance_statement"


class TestReceipt:
    def test_receipt_keyword_short_text(self):
        text = "Receipt #12345. Thank you for your purchase."
        doc_type, _ = classify_document(text, "pdf")
        assert doc_type == "receipt"

    def test_total_and_subtotal_short(self):
        text = "Items purchased. Subtotal: $45.00. Tax: $3.60. Total: $48.60."
        doc_type, confidence = classify_document(text, "pdf")
        assert doc_type == "receipt"
        assert confidence == "medium"

    def test_receipt_long_text_no_match(self):
        text = "Receipt " + "x" * 3000
        doc_type, _ = classify_document(text, "pdf")
        assert doc_type != "receipt"

    def test_total_subtotal_long_text_no_match(self):
        text = "Subtotal and Total " + "y" * 3000
        doc_type, _ = classify_document(text, "pdf")
        assert doc_type != "receipt"


class TestInvoice:
    def test_invoice_with_bill_to(self):
        text = "Invoice #1001. Bill To: John Doe. Amount Due: $500."
        doc_type, _ = classify_document(text, "pdf")
        assert doc_type == "invoice"

    def test_invoice_with_due_date(self):
        text = "Invoice for services rendered. Due Date: 02/15/2026."
        doc_type, _ = classify_document(text, "pdf")
        assert doc_type == "invoice"

    def test_invoice_alone_no_match(self):
        text = "The invoice was lost in the mail."
        doc_type, _ = classify_document(text, "pdf")
        assert doc_type != "invoice"


class TestBrokerageStatement:
    def test_portfolio(self):
        doc_type, _ = classify_document("Your portfolio summary as of December 31.", "pdf")
        assert doc_type == "brokerage_statement"

    def test_holdings(self):
        doc_type, _ = classify_document("Account holdings as of quarter end.", "pdf")
        assert doc_type == "brokerage_statement"

    def test_securities_and_dividends(self):
        text = "Securities held in your account. Dividends earned this quarter."
        doc_type, confidence = classify_document(text, "pdf")
        assert doc_type == "brokerage_statement"
        assert confidence == "medium"


class TestCreditCardStatement:
    def test_minimum_payment(self):
        doc_type, _ = classify_document("Minimum payment due: $25.00", "pdf")
        assert doc_type == "credit_card_statement"

    def test_credit_limit(self):
        doc_type, _ = classify_document("Your credit limit is $10,000", "pdf")
        assert doc_type == "credit_card_statement"

    def test_multiple_keywords(self):
        text = "Minimum payment $25. Credit limit $10,000. Payment due by 02/15."
        doc_type, confidence = classify_document(text, "pdf")
        assert doc_type == "credit_card_statement"
        assert confidence == "high"


class TestBankStatement:
    def test_statement_period(self):
        doc_type, _ = classify_document("Statement period: 01/01/2026 to 01/31/2026", "pdf")
        assert doc_type == "bank_statement"

    def test_beginning_ending_balance(self):
        text = "Beginning balance: $5,000. Ending balance: $5,500."
        doc_type, confidence = classify_document(text, "pdf")
        assert doc_type == "bank_statement"
        assert confidence == "medium"

    def test_all_keywords(self):
        text = "Statement period 01/01-01/31. Beginning balance $5000. Ending balance $5500. Account activity below."
        doc_type, confidence = classify_document(text, "pdf")
        assert doc_type == "bank_statement"
        assert confidence == "high"


class TestUtilityBill:
    def test_electric_with_usage(self):
        text = "Electric bill. Usage this month: 850 kWh."
        doc_type, _ = classify_document(text, "pdf")
        assert doc_type == "utility_bill"

    def test_water_with_meter(self):
        text = "Water service. Meter reading: 12345."
        doc_type, _ = classify_document(text, "pdf")
        assert doc_type == "utility_bill"

    def test_gas_alone_no_match(self):
        text = "Gas prices are high this winter."
        doc_type, _ = classify_document(text, "pdf")
        assert doc_type != "utility_bill"


class TestPropertyTax:
    def test_property_tax_with_assessment(self):
        text = "Property tax bill. Assessment value: $350,000."
        doc_type, _ = classify_document(text, "pdf")
        assert doc_type == "property_tax"

    def test_property_tax_with_parcel(self):
        text = "Property tax notice. Parcel #123-456-789."
        doc_type, _ = classify_document(text, "pdf")
        assert doc_type == "property_tax"

    def test_property_tax_alone_no_match(self):
        text = "Property tax might increase next year."
        doc_type, _ = classify_document(text, "pdf")
        assert doc_type != "property_tax"


class TestUnknown:
    def test_no_keywords(self):
        text = "This is a random document with no financial keywords."
        doc_type, confidence = classify_document(text, "pdf")
        assert doc_type == "unknown"
        assert confidence == "low"

    def test_empty_text(self):
        doc_type, confidence = classify_document("", "pdf")
        assert doc_type == "unknown"
        assert confidence == "low"


class TestCaseInsensitive:
    def test_uppercase_w2(self):
        doc_type, _ = classify_document("WAGE AND TAX STATEMENT", "pdf")
        assert doc_type == "tax_w2"

    def test_mixed_case_payslip(self):
        text = "GROSS PAY: $5000. Net Pay: $3800. Deductions: $1200."
        doc_type, _ = classify_document(text, "pdf")
        assert doc_type == "payslip"

    def test_uppercase_bank_statement(self):
        text = "STATEMENT PERIOD: JAN 2026. BEGINNING BALANCE $5000."
        doc_type, _ = classify_document(text, "pdf")
        assert doc_type == "bank_statement"


# ---------------------------------------------------------------------------
# get_extraction_hints tests
# ---------------------------------------------------------------------------


class TestGetExtractionHints:
    ALL_TYPES = [
        "payslip", "tax_w2", "tax_1099", "tax_form16",
        "mortgage_statement", "loan_statement", "insurance_statement",
        "receipt", "invoice", "brokerage_statement",
        "credit_card_statement", "bank_statement",
        "utility_bill", "property_tax", "unknown",
    ]

    @pytest.mark.parametrize("doc_type", ALL_TYPES)
    def test_has_required_keys(self, doc_type):
        hints = get_extraction_hints(doc_type)
        assert "expect" in hints
        assert "look_for" in hints
        assert "typical_accounts" in hints

    @pytest.mark.parametrize("doc_type", ALL_TYPES)
    def test_expect_is_valid(self, doc_type):
        hints = get_extraction_hints(doc_type)
        valid = {
            "single_transaction", "single_multi_posting_transaction",
            "multiple_transactions", "annual_summary", "unknown",
        }
        assert hints["expect"] in valid

    @pytest.mark.parametrize("doc_type", ALL_TYPES)
    def test_look_for_is_list(self, doc_type):
        hints = get_extraction_hints(doc_type)
        assert isinstance(hints["look_for"], list)
        assert len(hints["look_for"]) > 0

    def test_payslip_hints(self):
        hints = get_extraction_hints("payslip")
        assert hints["expect"] == "single_multi_posting_transaction"
        assert "gross_pay" in hints["look_for"]
        assert "net_pay" in hints["look_for"]
        assert "note" in hints

    def test_w2_hints(self):
        hints = get_extraction_hints("tax_w2")
        assert hints["expect"] == "annual_summary"
        assert "wages" in hints["look_for"]
        assert "note" in hints

    def test_1099_hints(self):
        hints = get_extraction_hints("tax_1099")
        assert hints["expect"] == "annual_summary"
        assert "interest_income" in hints["look_for"]

    def test_form16_hints(self):
        hints = get_extraction_hints("tax_form16")
        assert hints["expect"] == "annual_summary"
        assert "tds_deducted" in hints["look_for"]

    def test_unknown_type_returns_fallback(self):
        hints = get_extraction_hints("nonexistent_type")
        assert hints["expect"] == "unknown"

    def test_mortgage_hints(self):
        hints = get_extraction_hints("mortgage_statement")
        assert hints["expect"] == "single_multi_posting_transaction"
        assert "escrow" in hints["look_for"]

    def test_bank_statement_hints(self):
        hints = get_extraction_hints("bank_statement")
        assert hints["expect"] == "multiple_transactions"
