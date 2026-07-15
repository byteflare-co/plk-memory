from __future__ import annotations

import importlib.util
import json
import re
import sys
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace

import pytest


@pytest.fixture
def run_eval_module():
    path = Path(__file__).parents[1] / "scripts" / "eval" / "run_eval.py"
    spec = importlib.util.spec_from_file_location("plk_run_eval_for_test", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _queries() -> list[dict]:
    return [
        {"query": "alpha", "expected": ["fact-a"]},
        {"query": "beta", "expected": ["fact-b"]},
    ]


def test_compute_summary_matches_rendered_aggregate(run_eval_module) -> None:
    queries = _queries()
    results = {
        "rg": {
            "alpha": ["other", "fact-a"],
            "beta": ["other"],
        },
        "embed": {
            "alpha": ["fact-a"],
            "beta": ["x", "y", "z", "fact-b"],
        },
    }

    summary = run_eval_module.compute_summary(queries, results)

    assert summary == {
        "rg": {"hit5": 1, "hit5_rate": 0.5, "mrr": 0.25},
        "embed": {"hit5": 2, "hit5_rate": 1.0, "mrr": 0.625},
    }
    rendered = run_eval_module.render_markdown(queries, results, {})
    assert "| rg | 1/2 | 0.50 | 0.250 |" in rendered
    assert "| embed | 2/2 | 1.00 | 0.625 |" in rendered


def test_history_records_include_shared_provenance(run_eval_module, tmp_path, monkeypatch) -> None:
    settings = SimpleNamespace(
        data_repo_path=tmp_path / "repo",
        embedder_model="bge-m3",
        llm_model="gpt-oss:20b",
    )
    facts = [SimpleNamespace(status="active"), SimpleNamespace(status="invalidated")]
    results = {
        "rg": {"alpha": ["fact-a"], "beta": []},
        "embed": {"alpha": ["fact-a"], "beta": ["fact-b"]},
        "graph(triplet)": {"alpha": [], "beta": ["fact-b"]},
    }
    monkeypatch.setattr(run_eval_module, "corpus_revision", lambda _path: "354d0f8")

    records = run_eval_module.build_history_records(
        settings=settings,
        queries=_queries(),
        facts=facts,
        runner_results=results,
    )

    assert [record["runner"] for record in records] == ["rg", "embed", "graph(triplet)"]
    assert len({record["run_id"] for record in records}) == 1
    assert re.fullmatch(r"[0-9A-HJKMNP-TV-Z]{26}", records[0]["run_id"])
    assert len({record["queries_hash"] for record in records}) == 1
    assert re.fullmatch(r"sha256:[0-9a-f]{64}", records[0]["queries_hash"])
    assert len({record["ts"] for record in records}) == 1
    assert datetime.fromisoformat(records[0]["ts"]).tzinfo is not None
    for record in records:
        assert record["queries"] == 2
        assert record["corpus_active"] == 1
        assert record["corpus_total"] == 2
        assert record["corpus_revision"] == "354d0f8"
        assert record["corpus_scope"] == "domains"
    assert records[0]["hit5"] == 1
    assert records[0]["hit5_rate"] == 0.5
    assert records[0]["mrr"] == 0.5
    assert records[0]["embed_model"] is None
    assert records[0]["llm_model"] is None
    assert records[0]["graph_mode"] is None
    assert records[1]["embed_model"] == "bge-m3"
    assert records[1]["llm_model"] is None
    assert records[2]["embed_model"] is None
    assert records[2]["llm_model"] == "gpt-oss:20b"
    assert records[2]["graph_mode"] == "triplet"

    path = tmp_path / "nested" / "eval-history.jsonl"
    run_eval_module.append_history(path, records)
    assert [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()] == records


def _stub_main(monkeypatch, module, tmp_path: Path):
    history_path = tmp_path / "eval-history.jsonl"
    settings = SimpleNamespace(
        data_repo_path=tmp_path / "repo",
        knowledge_dir=tmp_path / "knowledge",
        embedder_model="bge-m3",
        llm_model="gpt-oss:20b",
        eval_history_path=history_path,
    )
    facts = [SimpleNamespace(status="active")]
    monkeypatch.setattr(module, "Settings", lambda: settings)
    monkeypatch.setattr(module, "load_queries", lambda _path: _queries())
    monkeypatch.setattr(module, "load_facts", lambda _settings: facts)
    monkeypatch.setattr(module.shutil, "which", lambda _name: None)
    monkeypatch.setattr(
        module,
        "run_rg",
        lambda query, _facts, _settings, _use_rg: ["fact-a"] if query == "alpha" else [],
    )
    monkeypatch.setattr(module, "corpus_revision", lambda _path: "abc1234")
    return history_path


def test_main_appends_history_without_changing_stdout_or_out(
    run_eval_module, tmp_path, monkeypatch, capsys
) -> None:
    history_path = _stub_main(monkeypatch, run_eval_module, tmp_path)
    out_path = tmp_path / "result.md"
    monkeypatch.setattr(
        sys,
        "argv",
        ["run_eval.py", "--runners", "rg", "--out", str(out_path)],
    )

    run_eval_module.main()

    captured = capsys.readouterr()
    assert captured.err == ""
    assert captured.out == out_path.read_text(encoding="utf-8")
    records = [json.loads(line) for line in history_path.read_text(encoding="utf-8").splitlines()]
    assert len(records) == 1
    assert records[0]["runner"] == "rg"
    assert records[0]["corpus_revision"] == "abc1234"


def test_no_history_skips_provenance_and_file_creation(
    run_eval_module, tmp_path, monkeypatch
) -> None:
    history_path = _stub_main(monkeypatch, run_eval_module, tmp_path)
    monkeypatch.setattr(
        run_eval_module,
        "corpus_revision",
        lambda _path: pytest.fail("--no-history では provenance を収集しない"),
    )
    monkeypatch.setattr(sys, "argv", ["run_eval.py", "--runners", "rg", "--no-history"])

    run_eval_module.main()

    assert not history_path.exists()


def test_history_append_failure_is_stderr_warning_only(
    run_eval_module, tmp_path, monkeypatch, capsys
) -> None:
    _stub_main(monkeypatch, run_eval_module, tmp_path)
    out_path = tmp_path / "result.md"
    monkeypatch.setattr(
        run_eval_module,
        "append_history",
        lambda _path, _records: (_ for _ in ()).throw(PermissionError("read-only")),
    )
    monkeypatch.setattr(
        sys,
        "argv",
        ["run_eval.py", "--runners", "rg", "--out", str(out_path)],
    )

    run_eval_module.main()

    captured = capsys.readouterr()
    assert captured.out == out_path.read_text(encoding="utf-8")
    assert captured.err == "warning: eval-history の追記に失敗しました: read-only\n"
