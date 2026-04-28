"""Tests for fuzzy account matching — exact, prefix, substring, edit distance, confidence gate."""

import pytest

from personalfinance.matching import (
    CONFIDENCE_THRESHOLD,
    MatchResult,
    match_account,
    resolve_account,
)

ACCOUNTS = [
    "Assets:Checking",
    "Assets:Savings",
    "Assets:Brokerage",
    "Expenses:Food:Groceries",
    "Expenses:Food:DiningOut",
    "Expenses:Food:GrubHub",
    "Expenses:Transport:Gas",
    "Expenses:Subscriptions",
    "Income:Salary",
    "Liabilities:CreditCard",
]


class TestMatchAccount:
    def test_exact_match(self):
        results = match_account("Assets:Checking", ACCOUNTS)
        assert len(results) > 0
        assert results[0].account == "Assets:Checking"
        assert results[0].score == 1.0
        assert results[0].method == "exact"

    def test_prefix_match(self):
        results = match_account("Checking", ACCOUNTS)
        assert len(results) > 0
        assert results[0].account == "Assets:Checking"
        assert results[0].method == "prefix"

    def test_substring_match(self):
        results = match_account("Grocer", ACCOUNTS)
        assert len(results) > 0
        assert results[0].account == "Expenses:Food:Groceries"
        assert results[0].method == "substring"

    def test_edit_distance_match(self):
        results = match_account("Chekking", ACCOUNTS)
        assert len(results) > 0
        top = results[0]
        assert top.account == "Assets:Checking"
        assert top.method == "edit_distance"

    def test_top_n_limit(self):
        results = match_account("Food", ACCOUNTS, top_n=2)
        assert len(results) <= 2

    def test_empty_accounts(self):
        results = match_account("anything", [])
        assert results == []

    def test_no_match(self):
        results = match_account("xyzzyplugh", ACCOUNTS)
        assert len(results) == 0 or results[0].score < 0.5


class TestResolveAccount:
    def test_confident_match(self):
        account, candidates = resolve_account("Assets:Checking", ACCOUNTS)
        assert account == "Assets:Checking"
        assert len(candidates) == 1

    def test_confident_prefix(self):
        account, candidates = resolve_account("Salary", ACCOUNTS)
        assert account == "Income:Salary"

    def test_ambiguous_below_threshold(self):
        account, candidates = resolve_account("Food", ACCOUNTS)
        if account is None:
            assert len(candidates) > 0
            assert all(c.score < CONFIDENCE_THRESHOLD for c in candidates)

    def test_no_match_returns_none(self):
        account, candidates = resolve_account("NonexistentAccount", ACCOUNTS)
        assert account is None

    def test_threshold_boundary(self):
        assert CONFIDENCE_THRESHOLD == 0.85
