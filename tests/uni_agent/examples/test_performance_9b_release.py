import json

import pytest

from examples.performance_9b.build_release import build, select_groups


def test_sampling_never_fills_missing_domains_with_other_tasks():
    groups = {"a": {"domain": "code", "split": "train", "teachers": {"qwen38"}}}
    chosen, deficits = select_groups(groups, {"code": 1, "office": 1})
    assert chosen == set()
    assert deficits == {"office": 1}


def test_general_retention_excludes_qwen_and_dev():
    groups = {
        "a": {"domain": "general", "split": "train", "teachers": {"qwen38"}},
        "b": {"domain": "general", "split": "dev", "teachers": {"fable"}},
        "c": {"domain": "general", "split": "train", "teachers": {"gpt56"}},
    }
    assert select_groups(groups, {"general": 1}) == ({"c"}, {})


def test_sampling_reproducible_and_excludes_dev():
    groups = {str(i): {"domain": "code", "split": "train", "teachers": {"gpt56"}} for i in range(20)}
    assert select_groups(groups, {"code": 5}) == select_groups(dict(reversed(list(groups.items()))), {"code": 5})


def write_source(tmp_path, rows):
    source = tmp_path / "source.jsonl"
    source.write_text("".join(json.dumps(row) + "\n" for row in rows))
    return {"sources": [{"path": str(source), "repo": "CodeFlame/test", "revision": "fixed"}], "quotas": {"code": 20}}


def example(teacher="gpt-5.6-sol", prompt="Create a calculator"):
    return {
        "teacher_model": teacher,
        "domain": "coding",
        "messages": [{"role": "user", "content": prompt}, {"role": "assistant", "content": "return 2"}],
    }


def test_build_conserves_rows_and_quarantines_unknown_and_gemini(tmp_path):
    row = example()
    config = write_source(tmp_path, [row, row, example(None), example("gemini-3.1-pro")])
    report = build(config, tmp_path / "out")
    counts = report["statistics"]["CodeFlame/test"]["counts"]
    assert counts["input_rows"] == 4
    assert sum(counts.get(k, 0) for k in ("screened", "excluded", "quarantine", "duplicate")) == 4
    assert not (tmp_path / "out" / "three_teacher-20k.jsonl").exists()
    decisions = [json.loads(x) for x in (tmp_path / "out" / "decisions.jsonl").read_text().splitlines()]
    assert decisions[2]["status"] == "quarantine"
    assert decisions[3]["status"] == "excluded"


def test_hash_mismatch_stops_release(tmp_path):
    config = write_source(tmp_path, [example()])
    config["sources"][0]["sha256"] = "incorrect"
    with pytest.raises(ValueError, match="hash mismatch"):
        build(config, tmp_path / "out")
    assert not (tmp_path / "out" / "manifest.json").exists()


def test_existing_release_cannot_be_overwritten(tmp_path):
    config = write_source(tmp_path, [example()])
    build(config, tmp_path / "out")
    with pytest.raises(FileExistsError):
        build(config, tmp_path / "out")


def test_source_task_variants_share_one_group_and_split(tmp_path):
    from examples.performance_9b.normalize import normalize_record

    variants = {}
    for index in range(1000):
        row = example(prompt=f"Task wording {index}")
        normalized = normalize_record(row, "CodeFlame/test", "fixed", index)
        split = "dev" if int(normalized["prompt_hash"][:8], 16) % 20 == 0 else "train"
        variants.setdefault(split, row)
        if len(variants) == 2:
            break
    assert set(variants) == {"train", "dev"}
    rows = [{**row, "source_trajectory_id": "same-original-task"} for row in variants.values()]
    config = write_source(tmp_path, rows)
    report = build(config, tmp_path / "out")
    screened = [json.loads(line) for line in (tmp_path / "out/screened.jsonl").read_text().splitlines()]
    assert len(screened) == 2
    assert len({row["release_task_group"] for row in screened}) == 1
    assert len({row["split"] for row in screened}) == 1
    assert report["sampling"]["screened"]["unique_prompt_groups"] == 1
    reversed_config = write_source(tmp_path, list(reversed(rows)))
    build(reversed_config, tmp_path / "reversed")
    reversed_rows = [json.loads(line) for line in (tmp_path / "reversed/screened.jsonl").read_text().splitlines()]
    assert {(row["release_task_group"], row["split"]) for row in reversed_rows} == {
        (row["release_task_group"], row["split"]) for row in screened
    }


def test_heldout_propagates_transitively_across_task_ids_and_source_prompts(tmp_path):
    # A1--A2 share a source task; A2--B1 share a prompt; B1--B2 share another task.
    rows = [
        {**example(prompt="First wording"), "task_id": "A"},
        {**example(prompt="Shared wording"), "task_id": "A"},
    ]
    config = write_source(tmp_path, rows)
    other = tmp_path / "other.jsonl"
    other.write_text(
        "".join(
            json.dumps(row) + "\n"
            for row in [
                {**example(prompt="Shared wording"), "task_id": "B"},
                {**example(prompt="Heldout wording"), "task_id": "B", "source_split": "test"},
            ]
        )
    )
    config["sources"].append({"path": str(other), "repo": "Other/test", "revision": "fixed"})
    report = build(config, tmp_path / "out")
    assert (tmp_path / "out/screened.jsonl").read_text() == ""
    assert (tmp_path / "out/three_teacher.jsonl").read_text() == ""
    decisions = [json.loads(line) for line in (tmp_path / "out/decisions.jsonl").read_text().splitlines()]
    assert len({row["task_group"] for row in decisions}) == 1
    assert decisions[0]["status"] == decisions[1]["status"] == decisions[3]["status"] == "excluded"
    for item in report["statistics"].values():
        counts = item["counts"]
        assert counts["input_rows"] == sum(
            counts.get(k, 0) for k in ("screened", "excluded", "quarantine", "duplicate")
        )
    assert report["sampling"]["screened"]["unique_prompt_groups"] == 0
