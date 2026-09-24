"""Selection policy keeps provenance and evaluation contamination explicit."""

import pytest

from examples.performance_9b.policy import ability_domain, policy_flags


def flags(raw=None, source="codeflame", **changes):
    normalized = {"teacher_claimed": "gpt-5.6", "teacher_evidence": {"conflict": False}}
    normalized.update(changes)
    return policy_flags(raw or {}, normalized, source)


def test_gemini_is_explicitly_excluded():
    assert "excluded_gemini31" in flags(teacher_claimed="gemini-3.1-pro")
    assert "excluded_gemini31" not in flags(teacher_claimed="gemini-3.0")


def test_unknown_teacher_and_conflicting_claims():
    assert "unknown_teacher" in flags(teacher_claimed=None)
    assert "teacher_conflict" in flags(teacher_evidence={"conflict": True})
    assert "teacher_conflict" not in flags(teacher_evidence={"conflict": False})


@pytest.mark.parametrize("source", ["premium", "saidutta69/fable-5-premium-v2"])
def test_premium_requires_mixed_provenance_resolution(source):
    assert "mixed_teacher_provenance_unresolved" in flags(source=source)


def test_helio_license():
    assert "unknown_source_license" in flags(source="helio")


@pytest.mark.parametrize("split", ["test", "validation", "val", "dev", "test/main"])
def test_heldout(split):
    assert "heldout_source" in flags({"source_split": split})
    assert "heldout_source" not in flags({"split": "train"})


@pytest.mark.parametrize("field", ["source", "repo", "domain"])
def test_benchmarks(field):
    assert "benchmark_source" in flags({field: "openai/humaneval"})
    assert "benchmark_source" not in flags({field: "my-training"})


@pytest.mark.parametrize("license_name", ["unknown", "other", "CC-BY-NC-4.0", ""])
def test_license_review(license_name):
    assert "source_license_review" in flags({"source_license": license_name})
    assert "source_license_review" not in flags({"source_license": "Apache-2.0"})


def test_attestation_boolean_false_only():
    assert "teacher_unattested" in flags({"metadata": {"model_attested": False}})
    assert "teacher_unattested" not in flags({"metadata": {"model_attested": ""}})
    assert "teacher_unattested" not in flags({"metadata": {"model_attested": True}})
    assert "teacher_unattested" not in flags()


@pytest.mark.parametrize(
    ("domain", "expected"),
    [
        ("coding", "code"),
        ("terminal_agent", "code"),
        ("math_formal", "reasoning"),
        ("science_logic_data", "reasoning"),
        ("strict_instruction", "general"),
        ("office", "office"),
        ("writing", "writing"),
        ("new-domain", "unknown"),
    ],
)
def test_explicit_domains(domain, expected):
    assert ability_domain({"domain": domain}, "source") == expected


def test_no_prompt_keyword_inference():
    assert ability_domain({"prompt": "Write an office memo"}, "source") == "unknown"
    assert ability_domain({}, "FineEnvs/data-agent-sft") == "data"
    assert "not_sft_source" in flags(source="Spreadsheet-RL/Spreadsheet-RL")


def test_gemini_scope_and_mixed_claim():
    assert "excluded_gemini31" not in flags(source="other", teacher_claimed="gemini-3.1")
    assert "excluded_gemini31" in flags(teacher_claimed="Qwen3.8+Gemini3.1")
    assert "mixed_teacher_provenance_unresolved" in flags(source="premium", teacher_claimed="Gemini3.1")


def test_provenance_alias_and_license_prefixes():
    assert "benchmark_source" in flags({"source_repository": "humaneval"})
    for value in ["unknown-see-provenance", "other;synthetic"]:
        assert "source_license_review" in flags({"source_license": value})


def test_same_level_teacher_conflict_cannot_hide_gemini():
    from examples.performance_9b.normalize import normalize_record

    raw = {"teacher_model": "gpt-5.6", "model": "gemini-3.1", "prompt": "hi", "answer": "hello"}
    record = normalize_record(raw, "CodeFlame/test", "rev", 0)
    result = policy_flags(raw, record, "CodeFlame/test")
    assert "teacher_conflict" in result
    assert "excluded_gemini31" in result


def test_metadata_val_is_heldout():
    assert "heldout_source" in flags({"metadata": {"source_split": "val"}})
