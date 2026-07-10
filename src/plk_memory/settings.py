"""plk-memory 全設定。環境変数 PLK_* で上書き（設計書 §3: Byteflare 固有値は設定へ）。"""

from __future__ import annotations

from pathlib import Path
from urllib.parse import urlparse

from pydantic_settings import BaseSettings, SettingsConfigDict

DOMAINS = ("tax", "legal", "shaho", "dev", "backoffice", "biz", "agent")


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="PLK_", env_file=".env", extra="ignore")

    # データリポジトリ（SoT = リモート main）
    data_repo_url: str = ""
    data_repo_path: Path = Path.home() / ".plk" / "data-repo"
    knowledge_subdir: str = "knowledge"

    # Persistence backend. Git remains the compatibility default while the
    # PostgreSQL reference path is rolled out and shadow-verified.
    storage_backend: str = "git"  # git | postgres
    database_url: str = ""
    database_schema: str = "plk_memory"
    default_organization_id: str = ""
    database_pool_size: int = 10
    outbox_poll_interval_seconds: float = 1.0
    outbox_batch_size: int = 100
    require_idempotency_key: bool = False
    require_expected_revision: bool = False

    # ローカル状態
    state_path: Path = Path.home() / ".plk" / "state.json"
    usage_log_path: Path = Path.home() / ".plk" / "usage.jsonl"
    lock_path: Path = Path.home() / ".plk" / "writer.lock"

    # 認証（token -> client 名）
    tokens: dict[str, str] = {}
    admin_token: str = ""

    # 認証モード（Phase 3: JWT 換装の実測用。既定 bearer のまま Mac 運用を継続する）
    auth_mode: str = "bearer"  # bearer | jwt
    jwt_issuer: str = "https://plk-memory.local/"
    jwt_audience: str = "plk-memory"
    # jwks_uri を設定するとその URI から公開鍵を取得（本番/ローカル JWKS 配信）。
    # 空なら jwt_public_key（PEM）を直接使う（テスト・オフライン検証）。
    jwks_uri: str = ""
    jwt_public_key: str = ""

    # group マッピング（Byteflare = single、組織展開 = per-namespace）
    # graphiti-core の validate_group_id は `^[a-zA-Z0-9_-]+$` のみ許可しドットを拒否するため、
    # namespace（ドット区切り）とは別に group_id はハイフン区切りにする。
    group_mode: str = "single"
    main_group: str = "plk-main"
    quarantine_group: str = "plk-quarantine"

    # ingest
    ingest_mode: str = "episode"  # episode | triplet
    anthropic_model: str = "claude-haiku-4-5-latest"

    # ingest LLM（graphiti のグラフ構築用）。既定はローカル Ollama（Anthropic API を消費しない）。
    # anthropic を選ぶ場合は llm_provider="anthropic" にし、上の anthropic_model を使う。
    llm_provider: str = "openai-compatible"  # anthropic | openai-compatible
    llm_base_url: str = "http://localhost:11434/v1"  # Ollama OpenAI 互換
    llm_model: str = "gpt-oss:20b"
    llm_api_key: str = "ollama"

    embedder_base_url: str = "http://localhost:11434/v1"  # Ollama OpenAI 互換
    embedder_model: str = "bge-m3"
    embedder_api_key: str = "ollama"
    embedding_dim: int = 1024

    # FalkorDB
    falkordb_host: str = "localhost"
    falkordb_port: int = 6379

    # 同期
    sync_interval_seconds: int = 600

    # サーバー
    bind_host: str = "127.0.0.1"
    bind_port: int = 8735

    # git identity（deferred fix: ハードコードを設定化）
    git_author_name: str = "plk-memory"
    git_author_email: str = "plk-memory@byteflare.co"

    # ドメイン（deferred fix: モジュール定数を設定化）
    domains: list[str] = list(DOMAINS)

    # 将来の実ホスト名 bind 時の DNS リバインディング保護（EC2/組織展開 期。ローカルは既定のまま）
    allowed_hosts: list[str] = ["*"]

    # Web UI（read 専用）
    ui_password: str = ""          # 空なら UI ログイン不可（本番のみ設定）
    ui_cookie_name: str = "plk_ui"

    @property
    def repo_slug(self) -> str:
        url = self.data_repo_url
        if url.startswith("git@"):
            # git@github.com:owner/repo.git
            path = url.split(":", 1)[1]
        else:
            path = urlparse(url).path.lstrip("/")
        return path.removesuffix(".git")

    def group_for(self, namespace: str) -> str:
        # graphiti の validate_group_id が `[a-zA-Z0-9_-]+` のみ許可するため、
        # namespace（ドット区切り）とは別に group_id はハイフン区切りで返す。
        if namespace == "plk.quarantine":
            return self.quarantine_group
        if self.group_mode == "per-namespace":
            return namespace.replace(".", "-")
        return self.main_group

    def all_groups(self) -> list[str]:
        # graphiti の validate_group_id が `[a-zA-Z0-9_-]+` のみ許可するため、
        # namespace（ドット区切り）とは別に group_id はハイフン区切りで返す。
        if self.group_mode == "per-namespace":
            return [f"plk-domain-{d}" for d in self.domains] + ["plk-shared", self.quarantine_group]
        return [self.main_group, self.quarantine_group]

    def path_for_namespace(self, namespace: str) -> str:
        if namespace == "plk.shared":
            return f"{self.knowledge_subdir}/shared"
        if namespace == "plk.quarantine":
            return f"{self.knowledge_subdir}/quarantine"
        domain = namespace.removeprefix("plk.domain.")
        return f"{self.knowledge_subdir}/domains/{domain}"

    @property
    def knowledge_dir(self) -> Path:
        return self.data_repo_path / self.knowledge_subdir
