import copy
import json
from pathlib import Path

import pytest

pytestmark = [pytest.mark.cpu, pytest.mark.level0]


def test_filters_redacts_and_preserves_order_without_mutation():
    from examples.dsh.capability_tasks.log_tool.oracle import evaluate

    records = [
        dict(timestamp="z", service="api", severity="ERROR", message="Ping Ada+ops@Sub.Example.com!", extra=3),
        dict(timestamp="a", service="api", severity="INFO", message="ok"),
        dict(timestamp="b", service="api", severity="ERROR", message="x@y.io and z@z.org"),
    ]
    before = copy.deepcopy(records)
    assert evaluate(records, severity="ERROR", service="api") == [
        dict(timestamp="z", service="api", severity="ERROR", message="Ping [REDACTED_EMAIL]!"),
        dict(timestamp="b", service="api", severity="ERROR", message="[REDACTED_EMAIL] and [REDACTED_EMAIL]"),
    ]
    assert records == before


def test_missing_invalid_empty_and_no_matching():
    from examples.dsh.capability_tasks.log_tool.oracle import evaluate

    valid = dict(timestamp="", service="", severity="", message="unchanged")
    assert evaluate([None, {}, dict(valid, message=None), valid, valid], service="") == [valid, valid]
    assert evaluate([valid], severity="ERROR") == []
    assert evaluate([], severity=None) == []


@pytest.mark.parametrize("records,filters", [({}, {}), ([], {"severity": []}), ([], {"service": 1})])
def test_invalid_contract_refused(records, filters):
    from examples.dsh.capability_tasks.log_tool.oracle import evaluate

    with pytest.raises(ValueError):
        evaluate(records, **filters)


@pytest.mark.parametrize(
    "message,expected",
    [
        ("bad..local@example.com foo@bad_domain.com x@y.c", "bad..local@example.com foo@bad_domain.com x@y.c"),
        ("(a.b+tag@sub-domain.example.co.uk), next", "([REDACTED_EMAIL]), next"),
        ("Contact Z_1@EXAMPLE.COM. Another a@b.io!", "Contact [REDACTED_EMAIL]. Another [REDACTED_EMAIL]!"),
    ],
)
def test_email_grammar(message, expected):
    from examples.dsh.capability_tasks.log_tool.oracle import evaluate

    record = dict(timestamp="a@b.io", service="a@b.io", severity="INFO", message=message)
    assert evaluate([record]) == [dict(record, message=expected)]


def test_public_fixture_contract_and_split_independence():
    from examples.dsh.capability_tasks.log_tool.oracle import evaluate

    root = Path(__file__).resolve().parents[3] / "examples/dsh/capability_tasks/log_tool/fixtures"
    files = sorted(root.glob("*.json"))
    assert len(files) == 6
    cases = [json.loads(path.read_text()) for path in files]
    assert sum(case["split"] == "train" for case in cases) == 4
    assert sum(case["split"] == "dev" for case in cases) == 2
    assert len({case["case_id"] for case in cases}) == 6
    all_inputs = set()
    for case in cases:
        assert case["schema"] == "dsh.t2-log-tool-case.v1" and case["public"] is True
        assert len(case["calls"]) >= 2
        signatures = [json.dumps(call, sort_keys=True) for call in case["calls"]]
        assert len(set(signatures)) == len(signatures)
        assert not all_inputs.intersection(signatures)
        all_inputs.update(signatures)
        outputs = [evaluate(**call) for call in case["calls"]]
        assert len({json.dumps(output, sort_keys=True) for output in outputs}) > 1
        assert outputs[-1] == []


def test_service_and_severity_are_exact_and_combined():
    from examples.dsh.capability_tasks.log_tool.oracle import evaluate

    target = dict(timestamp="1", service="api", severity="ERROR", message="target")
    records = [dict(target, service="API"), dict(target, severity="error"), target]
    assert evaluate(records, service="api", severity="ERROR") == [target]
    assert evaluate(records, service="api") == records[1:]
    assert evaluate(records, severity="ERROR") == [records[0], target]
