import pytest

from deployment.checks.harbor_cleanup_scripted_smoke import TruncatedPolicy, check_terminal


def test_truncation_comes_from_model_protocol_not_artifact_rewrite():
    result = TruncatedPolicy().respond({})
    assert result[0]["choices"][0]["finish_reason"] == "length"


def test_clean_rejection_never_becomes_zero_reward():
    value = dict(
        status="cancelled",
        manifest=dict(status="cancelled", artifacts=[], error_code="evidence-rejected-after-cleanup"),
    )
    check_terminal("truncated", value)
    value["manifest"]["artifacts"] = [{"kind": "reward"}]
    with pytest.raises(RuntimeError):
        check_terminal("truncated", value)
