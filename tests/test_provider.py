"""Provider chain and quota tests.

The cost claim in this project is a design property, not a promise, so the tests that matter most
are the ones asserting the paid backend cannot be reached by accident and that a spent budget
degrades rather than crashes.
"""

from __future__ import annotations

import pytest

from rag.provider import (
    DEFAULT_CHAIN,
    AnthropicBackend,
    Completion,
    FakeBackend,
    GeminiBackend,
    GroqBackend,
    LLMProvider,
    OllamaBackend,
    ProviderUnavailable,
)
from rag.quota import QuotaExceeded, QuotaLedger


@pytest.fixture
def ledger(tmp_path) -> QuotaLedger:
    return QuotaLedger(path=tmp_path / "quota.json", daily_limit=5)


@pytest.fixture
def clean_env(monkeypatch):
    for key in (
        "OLLAMA_HOST",
        "GEMINI_API_KEY",
        "GROQ_API_KEY",
        "ANTHROPIC_API_KEY",
        "ANTHROPIC_ENABLED",
        "LLM_PROVIDER",
    ):
        monkeypatch.delenv(key, raising=False)
    return monkeypatch


class TestChainOrder:
    def test_free_tiers_come_first_and_local_before_remote(self):
        assert DEFAULT_CHAIN[0] == "ollama"
        assert DEFAULT_CHAIN.index("gemini") < DEFAULT_CHAIN.index("groq")
        assert "anthropic" not in DEFAULT_CHAIN

    def test_naming_a_backend_starts_there_and_keeps_the_fallbacks(self, clean_env):
        clean_env.setenv("LLM_PROVIDER", "gemini")
        assert LLMProvider.from_env().chain == ("gemini", "groq", "fake")

    def test_fake_pins_the_chain_so_ci_cannot_reach_the_network(self, clean_env):
        clean_env.setenv("LLM_PROVIDER", "fake")
        assert LLMProvider.from_env().chain == ("fake",)

    def test_an_unknown_provider_falls_back_to_the_default_chain(self, clean_env):
        clean_env.setenv("LLM_PROVIDER", "something-else")
        assert LLMProvider.from_env().chain == DEFAULT_CHAIN


class TestPaidBackendIsOff:
    def test_it_is_not_in_the_default_chain(self):
        assert "anthropic" not in DEFAULT_CHAIN

    def test_a_key_alone_does_not_enable_it(self, clean_env):
        """Two switches, so the zero-cost claim is not one stray variable from being false."""
        clean_env.setenv("ANTHROPIC_API_KEY", "sk-not-a-real-key")
        ok, reason = AnthropicBackend().available()
        assert ok is False
        assert "switched off by policy" in reason

    def test_the_opt_in_alone_does_not_enable_it(self, clean_env):
        clean_env.setenv("ANTHROPIC_ENABLED", "true")
        ok, reason = AnthropicBackend().available()
        assert ok is False
        assert "ANTHROPIC_API_KEY" in reason

    def test_even_fully_configured_it_refuses_to_spend(self, clean_env):
        clean_env.setenv("ANTHROPIC_ENABLED", "true")
        clean_env.setenv("ANTHROPIC_API_KEY", "sk-not-a-real-key")
        assert AnthropicBackend().available()[0] is True
        with pytest.raises(ProviderUnavailable, match="free tiers only"):
            AnthropicBackend().generate("hello")


class TestAvailability:
    def test_ollama_reports_why_it_cannot_be_used(self, clean_env):
        ok, reason = OllamaBackend().available()
        if not ok:
            assert "ollama" in reason.lower()

    def test_gemini_needs_a_key(self, clean_env):
        assert GeminiBackend().available() == (False, "GEMINI_API_KEY is not set")

    def test_groq_needs_a_key(self, clean_env):
        assert GroqBackend().available() == (False, "GROQ_API_KEY is not set")

    def test_the_offline_backend_needs_nothing(self):
        assert FakeBackend().available()[0] is True


class TestFallthrough:
    def test_skips_unavailable_backends_and_records_every_hop(self, clean_env, ledger):
        provider = LLMProvider(chain=DEFAULT_CHAIN, ledger=ledger)
        completion = provider.generate("what is the median price in JVC?")
        assert isinstance(completion, Completion)
        outcomes = {h["backend"]: h["outcome"] for h in provider.hops}
        assert outcomes["fake"] == "answered"
        assert outcomes["gemini"] == "skipped"

    def test_an_answer_from_the_offline_backend_is_marked_degraded(self, clean_env, ledger):
        provider = LLMProvider(chain=DEFAULT_CHAIN, ledger=ledger)
        completion = provider.generate("anything")
        assert completion.degraded is True
        assert "offline fixture backend" in completion.note

    def test_a_pinned_offline_chain_is_not_treated_as_degraded(self, ledger):
        """Running deliberately offline is a choice, not a failure."""
        provider = LLMProvider(chain=("fake",), ledger=ledger)
        assert provider.generate("anything").degraded is False

    def test_describe_explains_each_backend(self, clean_env, ledger):
        rows = {d["backend"]: d for d in LLMProvider(ledger=ledger).describe()}
        assert rows["gemini"]["available"] is False
        assert rows["fake"]["available"] is True
        assert rows["fake"]["requests_remaining"] == 5

    def test_raises_only_when_nothing_at_all_can_answer(self, clean_env, ledger):
        provider = LLMProvider(chain=("gemini", "groq"), ledger=ledger)
        with pytest.raises(ProviderUnavailable, match="no backend in the chain"):
            provider.generate("anything")


class TestFixtures:
    def test_a_recorded_fixture_is_used_when_one_exists(self, tmp_path):
        backend = FakeBackend(fixture_dir=tmp_path)
        prompt = "what is the net yield in JVC?"
        (tmp_path / f"{FakeBackend._key(prompt)}.txt").write_text("A recorded answer.")
        assert backend.generate(prompt) == "A recorded answer."

    def test_a_prompt_with_no_fixture_still_answers_deterministically(self, tmp_path):
        backend = FakeBackend(fixture_dir=tmp_path)
        first = backend.generate("an unrecorded prompt")
        second = backend.generate("an unrecorded prompt")
        assert first == second
        assert "carries no factual claims" in first

    def test_changing_a_prompt_does_not_silently_reuse_another_answer(self, tmp_path):
        backend = FakeBackend(fixture_dir=tmp_path)
        (tmp_path / f"{FakeBackend._key('prompt A')}.txt").write_text("answer A")
        assert backend.generate("prompt A") == "answer A"
        assert backend.generate("prompt B") != "answer A"

    def test_offline_embeddings_are_deterministic_and_the_right_width(self):
        backend = FakeBackend()
        first = backend.embed(["dubai marina"])
        second = backend.embed(["dubai marina"])
        assert first == second
        assert len(first[0]) == 768

    def test_offline_embeddings_are_marked_degraded_by_the_provider(self, clean_env, ledger):
        result = LLMProvider(chain=("fake",), ledger=ledger).embed(["a", "b"])
        assert result.degraded is True
        assert result.dimensions == 768
        assert len(result.vectors) == 2

    def test_embedding_nothing_is_not_a_request(self, ledger):
        result = LLMProvider(chain=("fake",), ledger=ledger).embed([])
        assert result.vectors == []
        assert ledger.used("fake") == 0


class TestQuota:
    def test_counts_requests_not_tokens(self, ledger):
        """The free tiers this project uses meter requests, so that is what is counted."""
        ledger.record("gemini")
        ledger.record("gemini")
        assert ledger.used("gemini") == 2

    def test_backends_are_counted_separately(self, ledger):
        ledger.record("gemini")
        assert ledger.used("groq") == 0

    def test_refuses_to_spend_past_the_daily_allowance(self, ledger):
        for _ in range(5):
            ledger.spend("gemini")
        with pytest.raises(QuotaExceeded, match="requests for today"):
            ledger.spend("gemini")

    def test_remaining_never_goes_negative(self, ledger):
        for _ in range(5):
            ledger.record("gemini")
        ledger.record("gemini")
        assert ledger.remaining("gemini") == 0

    def test_the_ledger_survives_a_restart(self, tmp_path):
        """A nightly job and an interactive session share one daily allowance."""
        path = tmp_path / "quota.json"
        QuotaLedger(path=path, daily_limit=10).record("gemini")
        assert QuotaLedger(path=path, daily_limit=10).used("gemini") == 1

    def test_a_corrupt_ledger_does_not_stop_the_application(self, tmp_path):
        path = tmp_path / "quota.json"
        path.write_text("{not json")
        assert QuotaLedger(path=path).used("gemini") == 0

    def test_a_spent_budget_makes_the_chain_move_on_rather_than_fail(self, clean_env, tmp_path):
        ledger = QuotaLedger(path=tmp_path / "q.json", daily_limit=1)
        provider = LLMProvider(chain=("fake",), ledger=ledger)
        provider.generate("first")
        with pytest.raises(ProviderUnavailable):
            provider.generate("second")
        assert any(h["outcome"] == "skipped" and "budget" in h["reason"] for h in provider.hops)

    def test_the_report_states_the_cost(self, ledger):
        ledger.record("gemini")
        report = ledger.report()
        assert report["spend_aed"] == 0.0
        assert report["today"]["gemini"] == 1
        assert "free tier" in report["note"]

    def test_usage_is_broken_down_by_kind(self, ledger):
        ledger.record("gemini", kind="embed")
        ledger.record("gemini", kind="generate")
        assert ledger.report()["today"]["_by_kind"]["gemini:embed"] == 1
