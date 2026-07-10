"""サーバー専用 clone と単一 writer（設計書 §6）。

- SoT = リモート main。ローカル commit は push 完了までは「耐久化された意図」
- 書き込みは asyncio.Lock で直列化し fetch→rebase→push リトライ
- 履歴書き換え検出時は自動 reset せず HistoryRewritten（人間介入待ち）
- flock による単一インスタンスガード（uvicorn 多重起動・二重デーモンの fail-fast）
"""

from __future__ import annotations

import asyncio
import fcntl
import re
import shutil
import subprocess

from plk_memory.settings import Settings

_NAMESPACE_LINE = re.compile(r"(?m)^namespace:[^\n]*$")


def rewrite_namespace_line(text: str, new_namespace: str = "plk.shared") -> str:
    """frontmatter の namespace 行 1 行だけを書き換え、他のバイトは一切変えない。

    以前は python-frontmatter の load→dumps 往復で書き換えていたが、dumps が
    キー順・クォート・datetime 表記・末尾改行まで正規化してしまい、昇格 PR の
    diff が「namespace 1 行のみの rename」にならず CI（check_promotion）が
    落ちるバグがあった（P2 Task 10 の実 PR #1 で発覚）。
    """
    new_text, n = _NAMESPACE_LINE.subn(f"namespace: {new_namespace}", text, count=1)
    if n != 1:
        raise ValueError("namespace 行が見つからない（昇格対象ファクトの frontmatter が不正）")
    return new_text


class WriteConflict(RuntimeError):
    pass


class HistoryRewritten(RuntimeError):
    pass


class AnotherInstanceRunning(RuntimeError):
    pass


class GitStore:
    def __init__(self, settings: Settings):
        self.settings = settings
        self._lock = asyncio.Lock()
        self._flock_fh = None

    def git(self, *args: str) -> str:
        r = subprocess.run(
            ["git", "-C", str(self.settings.data_repo_path), *args],
            capture_output=True, text=True, check=True,
        )
        return r.stdout

    def ensure_repo(self) -> None:
        self._acquire_instance_lock()
        path = self.settings.data_repo_path
        if not (path / ".git").exists():
            if not self.settings.data_repo_url:
                raise RuntimeError("PLK_DATA_REPO_URL が未設定で clone も存在しない")
            path.parent.mkdir(parents=True, exist_ok=True)
            subprocess.run(
                ["git", "clone", "-b", "main", self.settings.data_repo_url, str(path)],
                capture_output=True, text=True, check=True,
            )
            self.git("config", "user.email", self.settings.git_author_email)
            self.git("config", "user.name", self.settings.git_author_name)

    def _acquire_instance_lock(self) -> None:
        self.settings.lock_path.parent.mkdir(parents=True, exist_ok=True)
        fh = open(self.settings.lock_path, "w")
        try:
            fcntl.flock(fh, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as e:
            fh.close()
            raise AnotherInstanceRunning(
                "別の plk-memory インスタンスが writer ロックを保持している（単一レプリカ必須）"
            ) from e
        self._flock_fh = fh  # プロセス生存期間保持

    def head(self) -> str:
        return self.git("rev-parse", "HEAD").strip()

    def fetch_and_ff(self) -> bool:
        """fetch して fast-forward。履歴書き換えは HistoryRewritten。戻り値: 更新があったか。"""
        self.git("fetch", "origin", "main")
        local = self.head()
        remote = self.git("rev-parse", "origin/main").strip()
        if local == remote:
            return False
        try:
            base = self.git("merge-base", "HEAD", "origin/main").strip()
        except subprocess.CalledProcessError as e:
            # 共通祖先が無い = ルートコミットが書き換えられた（例: 唯一の commit を amend）
            raise HistoryRewritten(
                "リモート main の履歴が書き換えられている（自動 reset しない）"
            ) from e
        if base == local:
            self.git("merge", "--ff-only", "origin/main")
            return True
        if base != remote:
            # 双方に独自 commit（未 push あり）は commit_and_push の rebase に委ねる
            return False
        raise HistoryRewritten("リモート main の履歴が書き換えられている（自動 reset しない）")

    async def commit_and_push(self, rel_paths: list[str], message: str) -> str:
        async with self._lock:
            return await asyncio.to_thread(self._commit_and_push_sync, rel_paths, message)

    def _commit_and_push_sync(self, rel_paths: list[str], message: str) -> str:
        self.git("add", "--", *rel_paths)
        self.git("commit", "-m", message)
        for _ in range(3):
            try:
                self.git("push", "origin", "main")
                return self.head()
            except subprocess.CalledProcessError:
                self.git("fetch", "origin", "main")
                try:
                    self.git("rebase", "origin/main")
                except subprocess.CalledProcessError as e:
                    self.git("rebase", "--abort")
                    # rebase を諦めた自 commit を巻き戻し、SoT（リモート）に合わせる
                    self.git("reset", "--hard", "origin/main")
                    raise WriteConflict(
                        f"リモートと競合したため書き込みを破棄した（再試行が必要）: {message}"
                    ) from e
        # 呼び出し側は「WriteConflict 時は作業ツリーが SoT に戻っている」前提。
        # リトライ上限到達時もローカル commit を破棄してリモートに合わせる。
        self.git("reset", "--hard", "origin/main")
        raise WriteConflict(f"push リトライ上限超過: {message}")

    async def build_promotion_branch(self, *, old_rel: str, new_rel: str,
                                     branch: str, message: str) -> None:
        """昇格 PR 用ブランチを専用 worktree で作成し push する（メイン HEAD を動かさない）。"""
        async with self._lock:
            await asyncio.to_thread(self._build_promotion_branch_sync, old_rel, new_rel, branch, message)

    def _build_promotion_branch_sync(self, old_rel: str, new_rel: str, branch: str, message: str) -> None:
        self.git("fetch", "origin", "main")
        wt = self.settings.data_repo_path.parent / f"promote-{branch.replace('/', '_')}"
        if wt.exists():
            self.git("worktree", "remove", "--force", str(wt))
        # origin/main から新ブランチの worktree を作る
        self.git("worktree", "add", "-B", branch, str(wt), "origin/main")
        try:
            (wt / new_rel).parent.mkdir(parents=True, exist_ok=True)
            subprocess.run(["git", "-C", str(wt), "mv", old_rel, new_rel],
                           capture_output=True, text=True, check=True)
            new_path = wt / new_rel
            # namespace 行のみを書き換える（他バイト不変 — git が rename と認識し
            # CI の「namespace 1 行のみの rename」チェックを満たすため）
            new_path.write_text(
                rewrite_namespace_line(new_path.read_text(encoding="utf-8")),
                encoding="utf-8",
            )
            subprocess.run(["git", "-C", str(wt), "config", "user.email", self.settings.git_author_email], check=True)
            subprocess.run(["git", "-C", str(wt), "config", "user.name", self.settings.git_author_name], check=True)
            subprocess.run(["git", "-C", str(wt), "add", "-A"], check=True)
            subprocess.run(["git", "-C", str(wt), "commit", "-m", message], capture_output=True, text=True, check=True)
            subprocess.run(["git", "-C", str(wt), "push", "-f", "origin", branch], capture_output=True, text=True, check=True)
        finally:
            self.git("worktree", "remove", "--force", str(wt))
            # worktree ディレクトリが残存した場合の保険（--force でも稀に残る git の既知挙動対策）
            if wt.exists():
                shutil.rmtree(wt, ignore_errors=True)
