from __future__ import annotations

from finkit.importers.pdf_parsers import (
    detect_institution,
    parse_marcus,
    parse_alliant,
    parse_chase_cc,
    parse_capitalone_cc,
    parse_citi_cc,
    parse_fidelity,
    parse_fidelity_holdings,
    parse_firsttech,
    parse_frost,
    parse_pdf_text,
)


class TestDetectInstitution:
    def test_marcus(self):
        assert detect_institution("Goldman Sachs Bank USA") == "marcus"
        assert detect_institution("Visit Marcus.com for details") == "marcus"

    def test_chase(self):
        assert detect_institution("visit chase.com/cardhelp") == "chase"

    def test_capitalone(self):
        assert detect_institution("Venture X Card details") == "capitalone"

    def test_citi(self):
        assert detect_institution("citicards.com info") == "citi"

    def test_fidelity(self):
        assert detect_institution("Fidelity.com account") == "fidelity"

    def test_alliant(self):
        assert detect_institution("alliantcreditunion.org") == "alliant"

    def test_unknown(self):
        assert detect_institution("Some random bank text") is None


class TestParseMarcus:
    SAMPLE = (
        "StatementPeriod 12/01/2025 to 12/31/2025\n"
        "ACCOUNT ACTIVITY\n"
        "Date Description Credits Debits Balance\n"
        "12/01/2025 BeginningBalance $22,055.27\n"
        "12/16/2025 ACHDepositInternettransfer $23,000.00 $45,055.27\n"
        "12/31/2025 InterestPaid $103.43 $45,158.70\n"
        "12/31/2025 EndingBalance $45,158.70\n"
    )

    def test_parses_transactions(self):
        rows = parse_marcus(self.SAMPLE, "Bank_-_Marcus_-_2026_01_01")
        assert len(rows) == 2

    def test_skips_beginning_ending(self):
        rows = parse_marcus(self.SAMPLE, "Bank_-_Marcus_-_2026_01_01")
        payees = [r["payee"] for r in rows]
        assert not any("Beginning" in p or "Ending" in p for p in payees)

    def test_dates_correct(self):
        rows = parse_marcus(self.SAMPLE, "Bank_-_Marcus_-_2026_01_01")
        assert rows[0]["date"] == "2025-12-16"
        assert rows[1]["date"] == "2025-12-31"

    def test_amounts(self):
        rows = parse_marcus(self.SAMPLE, "Bank_-_Marcus_-_2026_01_01")
        assert rows[0]["amount"] == "23000.00"
        assert rows[1]["amount"] == "103.43"


class TestParseAlliant:
    SAMPLE = (
        "01/31/26 DEPOSIT DIVIDEND 0.97 (cid:150)-------- 374.99\n"
        "02/28/26 DEPOSIT DIVIDEND 0.85 (cid:150)-------- 375.84\n"
        "03/31/26 DEPOSIT DIVIDEND 0.95 (cid:150)-------- 376.79\n"
    )

    def test_parses_dividends(self):
        rows = parse_alliant(self.SAMPLE, "Bank_-_Alliant_-_2026_03_31")
        assert len(rows) == 3

    def test_amounts(self):
        rows = parse_alliant(self.SAMPLE, "Bank_-_Alliant_-_2026_03_31")
        assert rows[0]["amount"] == "0.97"
        assert rows[2]["amount"] == "0.95"


class TestParseChaseCc:
    SAMPLE = (
        "AACCCCOOUUNNTT AACCTTIIVVIITTYY\n"
        "Date of\nTransaction Merchant Name $ Amount\n"
        "PAYMENTS AND OTHER CREDITS\n"
        "01/13 LYFT *1 RIDE HELP.LYFT.COM CA -.48\n"
        "01/16 AUTOMATIC PAYMENT - THANK YOU -141.94\n"
        "2026 Totals Year-to-Date\n"
    )

    def test_parses_transactions(self):
        rows = parse_chase_cc(self.SAMPLE, "CC_Chase_Freedom_xxx6689_-_2026_01_20")
        assert len(rows) == 2

    def test_negative_amounts(self):
        rows = parse_chase_cc(self.SAMPLE, "CC_Chase_Freedom_xxx6689_-_2026_01_20")
        assert rows[0]["amount"] == "-.48"
        assert rows[1]["amount"] == "-141.94"


class TestParseCapitaloneCc:
    SAMPLE = (
        "Transactions\nVisit capitalone.com to see detailed transactions.\n"
        "JOHN DOE #1234: Transactions\n"
        "Trans Date Post Date Description Amount\n"
        "Jan 15 Jan 17 DELTA AIR 0067463899129 $168.50\n"
        "Jan 15 Jan 17 SOUTHWES 5267463900081 $360.51\n"
        "Fees\n"
    )

    def test_parses_transactions(self):
        rows = parse_capitalone_cc(self.SAMPLE, "CC_CapitalOne_VentureX_xxx1234_-_2026_01")
        assert len(rows) == 2

    def test_post_dates_used(self):
        rows = parse_capitalone_cc(self.SAMPLE, "CC_CapitalOne_VentureX_xxx1234_-_2026_01")
        assert rows[0]["date"] == "2026-01-17"


class TestParseCitiCc:
    SAMPLE = (
        "Payments, Credits and Adjustments\n"
        "01/10 AUTOPAY 999990000028267RAUTOPAY -$426.06\n"
        "Standard Purchases\n"
        "12/14 12/14 COSTCO GAS #1152 ROUND ROCK TX $26.00\n"
        "12/14 12/14 COSTCO WHSE #1152 ROUND ROCK TX $155.88\n"
        "Fees Charged\n"
    )

    def test_parses_transactions(self):
        rows = parse_citi_cc(self.SAMPLE, "CC_Citi_costco_xxx5884_-_2026_01_14")
        assert len(rows) == 3

    def test_payment_negative(self):
        rows = parse_citi_cc(self.SAMPLE, "CC_Citi_costco_xxx5884_-_2026_01_14")
        assert rows[0]["amount"] == "-426.06"

    def test_purchase_positive(self):
        rows = parse_citi_cc(self.SAMPLE, "CC_Citi_costco_xxx5884_-_2026_01_14")
        assert rows[1]["amount"] == "26.00"


class TestParseFidelity:
    SAMPLE = (
        "Contributions\nDate Reference Description Amount\n"
        "01/06 Employer Cur Yr $750.00\n"
        "01/06 Participant Cur Yr 140.38\n"
        "01/20 Participant Cur Yr 140.38\n"
        "Total Contributions $1,030.76\n"
        "Distributions\nDate Reference Description Amount\n"
        "01/21 Normal Distr Partial -$154.00\n"
        "01/21 Normal Distr Partial -35.60\n"
        "Total Distributions -$189.60\n"
    )

    def test_parses_contributions(self):
        rows = parse_fidelity(self.SAMPLE, "HSA_-_Fidelity_JohnD_-_2026_Jan")
        contribs = [r for r in rows if r["amount"] and not r["amount"].startswith("-")]
        assert len(contribs) >= 1

    def test_parses_distributions(self):
        rows = parse_fidelity(self.SAMPLE, "HSA_-_Fidelity_JohnD_-_2026_Jan")
        dists = [r for r in rows if r["amount"].startswith("-")]
        assert len(dists) >= 1


class TestParseFidelityHoldings:
    SAMPLE = (
        "FIDELITY INT'L VALUE (FIVLX) unavailable 1,283.445 $14.8300 "
        "$19,033.49 $18,469.56 $563.93 $420.97\n"
    )

    def test_parses_holding(self):
        holdings = parse_fidelity_holdings(self.SAMPLE, "401k_-_Fidelity_-_2026_Jan")
        assert len(holdings) == 1
        assert holdings[0]["ticker"] == "FIVLX"
        assert holdings[0]["quantity"] == "1283.445"


class TestParseFrost:
    def test_returns_empty(self):
        assert parse_frost("Any text", "Frost") == []


class TestParseFirsttech:
    SAMPLE = (
        "DEPOSITS\n"
        "Trans Effect.\nDate Date Description Amount\n"
        "01/02 01/02 ACH Deposit META PP - PAYROLL 2,621.01\n"
        "01/08 01/08 ACH Deposit SCHWAB - MONEYLINK 1,500.00\n"
        "Total Deposits: 4,121.01\n"
        "MISCELLANEOUS DEBITS\n"
        "Trans Effect.\nDate Date Description Amount\n"
        "01/05 01/05 ACH Debit PAYPAL - INST XFER -23.09\n"
        "Total Miscellaneous Debits: 23.09\n"
    )

    def test_parses_deposits_and_debits(self):
        rows = parse_firsttech(self.SAMPLE, "Bank_-_Firsttech_combined_-_2026_01_31")
        assert len(rows) == 3

    def test_deposits_positive(self):
        rows = parse_firsttech(self.SAMPLE, "Bank_-_Firsttech_combined_-_2026_01_31")
        deposits = [r for r in rows if not r["amount"].startswith("-")]
        assert len(deposits) == 2

    def test_debits_negative(self):
        rows = parse_firsttech(self.SAMPLE, "Bank_-_Firsttech_combined_-_2026_01_31")
        debits = [r for r in rows if r["amount"].startswith("-")]
        assert len(debits) == 1


class TestParsePdfText:
    def test_auto_detect_and_parse(self):
        text = "Goldman Sachs Bank USA\nACCOUNT ACTIVITY\n12/31/2025 InterestPaid $5.00 $100.00\n"
        rows = parse_pdf_text(text, institution=None, filename="marcus.pdf")
        assert len(rows) == 1

    def test_explicit_institution(self):
        rows = parse_pdf_text("no keywords", institution="frost", filename="frost.pdf")
        assert rows == []

    def test_unknown_institution(self):
        rows = parse_pdf_text("no keywords", institution=None, filename="unknown.pdf")
        assert rows == []
