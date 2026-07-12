import subprocess
from pathlib import Path

import pytest

from plk_memory.gitstore import GitStore
from plk_memory.settings import Settings

# git-sync 専用ヘルパー（write_valid_fact 等）を別モジュールに分離しつつ、
# fixture（write_valid_fact）を従来どおり全テストから暗黙に使えるようにするための登録。
pytest_plugins = ["tests.gitsync_helpers"]


def sh(cwd: Path, *args: str) -> str:
    return subprocess.run(["git", "-C", str(cwd), *args], capture_output=True, text=True, check=True).stdout


@pytest.fixture
def remote(tmp_path):
    origin = tmp_path / "origin.git"
    subprocess.run(["git", "init", "--bare", "-b", "main", str(origin)], check=True, capture_output=True)
    seed = tmp_path / "seed"
    subprocess.run(["git", "clone", str(origin), str(seed)], check=True, capture_output=True)
    sh(seed, "config", "user.email", "t@t")
    sh(seed, "config", "user.name", "t")
    (seed / "knowledge").mkdir()
    (seed / "knowledge" / "a.md").write_text("a", encoding="utf-8")
    sh(seed, "add", "-A")
    sh(seed, "commit", "-m", "init")
    sh(seed, "push", "origin", "main")
    return origin, seed


def make_settings(tmp_path, origin, *, tokens=None, admin_token="a", **overrides) -> Settings:
    return Settings(
        data_repo_url=str(origin),
        data_repo_path=tmp_path / "server-clone",
        lock_path=tmp_path / "writer.lock",
        state_path=tmp_path / "state.json",
        usage_log_path=tmp_path / "usage.jsonl",
        tokens=tokens if tokens is not None else {"t": "c"}, admin_token=admin_token,
        _env_file=None,  # pyright: ignore[reportCallIssue]
        **overrides,
    )


def make_store(tmp_path, origin) -> GitStore:
    s = make_settings(tmp_path, origin)
    store = GitStore(s)
    store.ensure_repo()
    return store
