import pytest

from deployment.checks.work_state_runtime_canary import validate_probe


def test_real_tool_contract_distinguishes_missing_from_denied():
    calls = [
        dict(label="missing", error=True, denied=False),
        dict(label="create", error=False, denied=False),
        dict(label="denied", error=True, denied=True),
    ]
    results = [
        dict(label=c["label"], isError=c["error"], expectedTextPresent=c["denied"], forbiddenTextPresent=False)
        for c in calls
    ]
    report = dict(tools=["str_replace_editor"], results=results)
    validate_probe(report, calls)
    results[0]["expectedTextPresent"] = True
    with pytest.raises(ValueError, match="missing"):
        validate_probe(report, calls)


def test_hidden_text_and_missing_calls_cannot_pass():
    calls = [dict(label="deny", error=True, denied=True)]
    report = dict(tools=["str_replace_editor"], results=[])
    with pytest.raises(ValueError):
        validate_probe(report, calls)
    report["results"] = [dict(label="deny", isError=True, expectedTextPresent=True, forbiddenTextPresent=True)]
    with pytest.raises(ValueError):
        validate_probe(report, calls)
