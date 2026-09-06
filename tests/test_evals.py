"""Eval harness tests.

The eval is a gate, so it has to be trustworthy in both directions: it must fail when retrieval is
genuinely broken, and it must not pass a system that answered from nothing. The multilingual cases
earn their place — they caught two real bugs that every English case missed.
"""

from __future__ import annotations

import pytest

from rag.evals.run import (
    CASES_PATH,
    FAITHFULNESS_TARGET,
    RECALL_TARGET,
    load_cases,
    run,
    score_case,
)
from rag.indexer import build_index, load_index
from rag.provider import LLMProvider
from rag.quota import QuotaLedger
from rag.retriever import Retriever, tokenize


@pytest.fixture(scope="module")
def cases() -> list[dict]:
    return load_cases()


@pytest.fixture
def provider(tmp_path) -> LLMProvider:
    return LLMProvider(chain=("fake",), ledger=QuotaLedger(path=tmp_path / "q.json"))


class TestCaseSet:
    def test_there_are_thirty_cases(self, cases):
        assert len(cases) == 30

    def test_case_ids_are_unique(self, cases):
        assert len({c["id"] for c in cases}) == len(cases)

    def test_all_three_languages_are_covered(self, cases):
        langs = {c["lang"] for c in cases}
        assert langs == {"en", "hi", "ar"}

    def test_each_language_has_more_than_one_case(self, cases):
        from collections import Counter

        counts = Counter(c["lang"] for c in cases)
        assert all(n >= 2 for n in counts.values()), counts

    def test_both_documents_and_registry_facts_are_tested(self, cases):
        assert any("expect_doc" in c for c in cases)
        assert any("expect_area" in c for c in cases)

    def test_every_case_states_a_question(self, cases):
        for case in cases:
            assert case["question"].strip()
            assert case["lang"] in {"en", "hi", "ar"}

    def test_the_file_is_the_one_the_harness_reads(self):
        assert CASES_PATH.exists()


class TestTokenisationAcrossScripts:
    """Both bugs the eval caught were here, and both were invisible to the English cases."""

    def test_arabic_words_survive_tokenisation(self):
        tokens = tokenize("ما هي رسوم نقل الملكية في دبي")
        assert "رسوم" in tokens
        assert len(tokens) >= 5

    def test_hindi_words_are_not_split_at_their_vowel_marks(self):
        """A Latin-only pattern shatters सर्विस into six single characters."""
        tokens = tokenize("सर्विस चार्ज क्या होता है")
        assert "सर्विस" in tokens
        assert "चार्ज" in tokens

    def test_english_is_unaffected(self):
        assert tokenize("What is the transfer fee?") == ["what", "is", "the", "transfer", "fee"]

    def test_punctuation_and_underscores_are_not_tokens(self):
        assert tokenize("a_b, c!") == ["a", "b", "c"]


class TestScoring:
    def _retriever(self, provider):
        chunks = load_index()
        if not chunks:
            build_index()
            chunks = load_index()
        return Retriever(chunks, provider=provider)

    def test_a_case_whose_source_is_retrieved_counts_as_recalled(self, provider):
        result = score_case(
            {
                "id": "t",
                "lang": "en",
                "question": "What is a service charge and what does it pay for?",
                "expect_doc": "service_charges",
            },
            self._retriever(provider),
            provider,
        )
        assert result.recalled is True
        assert result.hit_rank is not None

    def test_a_case_whose_source_is_missed_counts_as_not_recalled(self, provider):
        result = score_case(
            {
                "id": "t",
                "lang": "en",
                "question": "What is a service charge?",
                "expect_doc": "a_document_that_does_not_exist",
            },
            self._retriever(provider),
            provider,
        )
        assert result.recalled is False
        assert result.hit_rank is None

    def test_an_area_case_matches_on_the_area_key(self, provider):
        result = score_case(
            {
                "id": "t",
                "lang": "en",
                "question": "What is the median price per square metre in JVC?",
                "expect_area": "jumeirah village circle",
            },
            self._retriever(provider),
            provider,
        )
        assert result.recalled is True

    def test_an_answer_asserting_nothing_is_faithful(self, provider):
        """A refusal makes no claims, so it cannot be unfaithful."""
        result = score_case(
            {"id": "t", "lang": "en", "question": "what is a service charge"},
            Retriever([], provider=provider),
            provider,
        )
        assert result.faithful is True

    def test_the_broken_tokeniser_would_have_failed_the_gate(self, provider):
        """Regression guard: with Latin-only tokens, Arabic retrieved nothing relevant."""
        import regex

        from rag import retriever as retriever_module

        original = retriever_module.TOKEN
        try:
            retriever_module.TOKEN = regex.compile(r"[a-z0-9']+")
            broken = self._retriever(provider)
            result = score_case(
                {
                    "id": "ar",
                    "lang": "ar",
                    "question": "ما هي رسوم نقل الملكية في دائرة الأراضي والأملاك بدبي؟",
                    "expect_doc": "dld_fees",
                },
                broken,
                provider,
            )
            assert result.recalled is False
        finally:
            retriever_module.TOKEN = original


@pytest.fixture(scope="module")
def report():
    """Scored once: running thirty cases through the whole stack is not cheap."""
    build_index()
    return run(k=5, out=None)


class TestGate:
    def test_the_whole_set_is_scored(self, report):
        assert report["n_cases"] == 30
        assert len(report["cases"]) == 30

    def test_recall_meets_its_target(self, report):
        assert report["recall_at_k"] >= RECALL_TARGET, report["failures"]

    def test_faithfulness_meets_its_target(self, report):
        assert report["faithfulness"] >= FAITHFULNESS_TARGET, report["failures"]

    def test_every_language_is_scored_separately(self, report):
        assert set(report["by_language"]) == {"en", "hi", "ar"}
        for lang, row in report["by_language"].items():
            assert row["cases"] >= 2, lang

    def test_no_language_is_carried_by_the_others(self, report):
        """An aggregate can hide a language failing completely, which is what happened."""
        for lang, row in report["by_language"].items():
            assert row["recall"] >= RECALL_TARGET, f"{lang}: {row}"

    def test_the_report_declares_its_provenance(self, report):
        assert report["provenance"] in {"REAL", "SYNTHETIC"}

    def test_a_degraded_run_says_so_rather_than_claiming_a_clean_score(self, report):
        if report["degraded"]:
            assert report["caveat"]
            assert "GEMINI_API_KEY" in report["caveat"]

    def test_the_verdict_combines_both_gates(self, report):
        assert report["passed"] == (report["recall_met"] and report["faithfulness_met"])
