import json
import time

import pytest

from examples.performance_9b.background import read_status, start, verify
from examples.performance_9b.build_release import file_hash


def launch(tmp_path, bad_hash=False):
    source = tmp_path / "source.jsonl"
    source.write_text(
        json.dumps({"prompt": "hello", "answer": "hi", "teacher_model": "gpt-5.6", "domain": "coding"}) + "\n"
    )
    config = tmp_path / "config.json"
    config.write_text(
        json.dumps(
            {
                "sources": [
                    {
                        "repo": "test",
                        "revision": "fixed",
                        "path": str(source),
                        "sha256": "bad" if bad_hash else file_hash(source),
                    }
                ],
                "quotas": {"office": 1},
            }
        )
    )
    folder = tmp_path / "run"
    start(config, folder)
    deadline = time.monotonic() + 20
    while time.monotonic() < deadline:
        status = read_status(folder)
        if status["state"] in ("SUCCEEDED", "FAILED"):
            return folder, status, config
        time.sleep(0.05)
    pytest.fail((folder / "process.log").read_text())


def test_detached_success_immutable_run_and_report(tmp_path):
    folder, status, config = launch(tmp_path)
    assert status["state"] == "SUCCEEDED", (folder / "process.log").read_text()
    assert status["training_ready"] is False
    assert (folder / "report.md").exists()
    assert (folder / "code-manifest.json").exists()
    assert status["sampling"]["three_teacher"]["quota_deficits"] == {"office": 1}
    with pytest.raises(FileExistsError):
        start(config, folder)
    output = folder / "output"
    with (output / "screened.jsonl").open("a") as f:
        f.write("tamper")
    with pytest.raises(ValueError, match="verification failed"):
        verify(output)


def test_detached_hash_failure_keeps_diagnostic(tmp_path):
    folder, status, _ = launch(tmp_path, bad_hash=True)
    assert status["state"] == "FAILED"
    assert "SHA256" in status["error"]
    assert "Traceback" in (folder / "process.log").read_text()
    assert not (folder / "output").exists()
