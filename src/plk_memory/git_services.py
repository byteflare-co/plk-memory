"""Git backend の REST/MCP ファサード（旧 app.AppServices）。

REST/MCP 双方から呼ばれる実体関数を `AppServices` にまとめている（テスト容易性の
ため薄いラッパから分離 — 設計書 §8, Task 9 brief）。
"""

from __future__ import annotations

import asyncio
import hashlib
import posixpath
import time

import frontmatter
from ulid import ULID

from plk_memory.auth import current_client
from plk_memory.admission import CodexAdmissionRunner
from plk_memory.facts import SKIP_NAMES, FactError, FactNotFound, FactService
from plk_memory.feedback import FeedbackCoordinator, FeedbackState
from plk_memory.gitstore import GitStore, WriteConflict
from plk_memory.promotions import PromotionState, PromotionStore, new_promotion, transition
from plk_memory.settings import Settings
from plk_memory.state import StateStore
from plk_memory.sync import SyncEngine
from plk_memory.usage_log import UsageLog


class AppServices:
    """REST/MCP 双方から呼ばれる実体関数のコンテナ（テスト容易性のため薄いラッパから分離）。"""

    def __init__(
        self,
        *,
        settings: Settings,
        store: GitStore,
        facts: FactService,
        graph,
        sync: SyncEngine,
        state_store: StateStore,
        usage: UsageLog,
        promotion_store: PromotionStore,
        feedback: FeedbackCoordinator,
        admission: CodexAdmissionRunner,
        promotion_backend=None,
    ):
        self.settings = settings
        self.store = store
        self.facts = facts
        self.graph = graph
        self.sync = sync
        self.state_store = state_store
        self.usage = usage
        self.promotion_store = promotion_store
        self.feedback = feedback
        self.admission = admission
        self.promotion_backend = promotion_backend
        self._bg_tasks: set[asyncio.Task] = set()

    # --- 内部ヘルパー ---

    def _require_client(self) -> str:
        client = current_client.get()
        if client is None:
            raise PermissionError(
                "認証されていない呼び出し（current_client 未設定 — 認証レイヤ外からの直接呼び出しは不可）"
            )
        return client

    def _spawn_sync(self) -> None:
        task = asyncio.create_task(self.sync.sync())
        self._bg_tasks.add(task)
        task.add_done_callback(self._bg_tasks.discard)

    def _group_ids_for(self, namespaces: list[str] | None) -> list[str]:
        quarantine = self.settings.quarantine_group
        if namespaces:
            include_quarantine = "plk.quarantine" in namespaces
            groups = {
                self.settings.group_for(ns)
                for ns in namespaces
                if ns != "plk.quarantine" or include_quarantine
            }
            if include_quarantine:
                groups.add(quarantine)
            return sorted(groups) if groups else [self.settings.main_group]
        return [g for g in self.settings.all_groups() if g != quarantine]

    # --- ツール実体 ---

    async def tool_search(
        self,
        query: str,
        namespaces: list[str] | None = None,
        kind: str | None = None,
        status: str = "active",
        limit: int = 10,
        reason: str | None = None,
        log_usage: bool = True,
    ) -> dict:
        client = current_client.get()
        start = time.monotonic()
        search_id = str(ULID())
        allow_quarantine = bool(namespaces and "plk.quarantine" in namespaces)

        def log_search(outcome: str, results: list[dict]) -> int:
            latency_ms = int((time.monotonic() - start) * 1000)
            if log_usage:
                self.usage.log(
                    client, "plk_search", query=query, hits=len(results),
                    latency_ms=latency_ms, reason=reason,
                    fact_ids=[str(result["fact_id"]) for result in results],
                    search_id=search_id, outcome=outcome,
                )
            return latency_ms

        if not self.graph.ready:
            latency_ms = log_search("degraded", [])
            return {
                "degraded": True,
                "message": "graph index が未接続（degraded モード）",
                "hits": [],
                "search_id": search_id,
                "latency_ms": latency_ms,
            }

        try:
            group_ids = self._group_ids_for(namespaces)
            state = self.state_store.load()
            uuid_to_fact = {
                uuid: fact_id
                for fact_id, entry in state.facts.items()
                for uuid in entry.episode_uuids
            }
            pool = max(limit * 5, 50)
            raw_hits = await self.graph.search(query, group_ids, uuid_to_fact, limit=pool)
            results = []
            for hit in raw_hits:
                try:
                    post, rel = self.facts.get(hit.fact_id)
                except FactNotFound:
                    continue
                ns = post.get("namespace")
                if ns == "plk.quarantine" and not allow_quarantine:
                    continue
                if kind is not None and post.get("kind") != kind:
                    continue
                if status is not None and post.get("status") != status:
                    continue
                if namespaces and ns not in namespaces:
                    continue
                results.append(
                    {
                        "fact_id": hit.fact_id,
                        "statement": post.get("statement"),
                        "namespace": ns,
                        "kind": post.get("kind"),
                        "status": post.get("status"),
                        "path": rel,
                        "fact_text": hit.fact_text,
                        "created_at": post.get("created_at"),
                    }
                )
                if len(results) >= limit:
                    break
        except Exception as error:  # noqa: BLE001 - search failures remain degraded reads
            latency_ms = log_search("error", [])
            return {
                "degraded": True,
                "message": f"search 失敗: {error}",
                "hits": [],
                "search_id": search_id,
                "latency_ms": latency_ms,
            }

        latency_ms = log_search("ok", results)
        return {
            "hits": results,
            "degraded": False,
            "search_id": search_id,
            "latency_ms": latency_ms,
        }

    async def tool_add(
        self,
        *,
        namespace: str,
        kind: str,
        statement: str,
        why: str,
        how_to_apply: str,
        source: str,
        tags: list[str] | None = None,
        body: str = "",
        slug: str | None = None,
        source_type: str = "agent",
        supersedes: list[str] | None = None,
        idempotency_key: str | None = None,
        expected_revision: int | None = None,
        expected_superseded_revisions: dict[str, int] | None = None,
    ) -> dict:
        del idempotency_key, expected_revision, expected_superseded_revisions
        client = self._require_client()
        if self.sync.maintenance:
            return {"error": "maintenance 中（reindex 実行中）", "retry": True}
        try:
            fact_id = await self.facts.add(
                client=client, namespace=namespace, kind=kind, statement=statement,
                why=why, how_to_apply=how_to_apply, source=source, tags=tags, body=body,
                slug=slug, source_type=source_type, supersedes=supersedes,
            )
        except FactError as e:
            return {"error": str(e)}
        except WriteConflict as e:
            return {"error": str(e), "retry": True}
        self._spawn_sync()
        return {"fact_id": fact_id, "note": "索引は非同期で更新される"}

    async def tool_invalidate(
        self,
        fact_id: str,
        reason: str,
        *,
        idempotency_key: str | None = None,
        expected_revision: int | None = None,
    ) -> dict:
        del idempotency_key, expected_revision
        client = self._require_client()
        if self.sync.maintenance:
            return {"error": "maintenance 中（reindex 実行中）", "retry": True}
        try:
            await self.facts.invalidate(fact_id, reason, client=client)
        except (FactError, FactNotFound) as e:
            return {"error": str(e)}
        except WriteConflict as e:
            return {"error": str(e), "retry": True}
        self._spawn_sync()
        return {"fact_id": fact_id, "note": "索引は非同期で更新される"}

    async def tool_history(self, fact_id: str) -> dict:
        try:
            return self.facts.history(fact_id)
        except FactNotFound:
            return {"error": f"fact が存在しない: {fact_id}"}

    async def tool_status(self) -> dict:
        status = await self.sync.status()
        pending = self.promotion_store.by_state(PromotionState.proposed) + \
            self.promotion_store.by_state(PromotionState.approved)
        status["pending_promotions"] = [
            {"promotion_id": p.id, "fact_id": p.fact_id, "state": p.state.value, "pr_url": p.pr_url}
            for p in pending
        ]
        return status

    async def ui_list_facts(
        self,
        *,
        namespace: str | None,
        kind: str | None,
        status: str,
    ) -> list[dict]:
        facts = []
        for post, rel in self.facts.list_posts():
            if not post.get("id"):
                continue
            if namespace and post.get("namespace") != namespace:
                continue
            if kind and post.get("kind") != kind:
                continue
            if status and post.get("status") != status:
                continue
            facts.append(
                {
                    "fact_id": post.get("id"),
                    "statement": post.get("statement"),
                    "namespace": post.get("namespace"),
                    "kind": post.get("kind"),
                    "status": post.get("status"),
                    "path": rel,
                    "created_at": post.get("created_at"),
                }
            )
        return facts

    async def ui_metrics_posts(self) -> tuple[list[dict], int]:
        posts: list[dict] = []
        skipped = 0
        for path in sorted(self.settings.knowledge_dir.rglob("*.md")):
            if path.name in SKIP_NAMES:
                continue
            try:
                post = frontmatter.load(path)
            except Exception:  # noqa: BLE001 - one malformed fact must not hide healthy metrics
                skipped += 1
                continue
            posts.append(dict(post.metadata))
        return posts, skipped

    async def ui_fact_detail(self, fact_id: str) -> dict | None:
        try:
            post, rel = self.facts.get(fact_id)
        except FactNotFound:
            return None
        return {
            "fact_id": fact_id,
            "path": rel,
            "meta": {
                **dict(post.metadata),
                "_content_hash": self._fact_content_hash(rel),
            },
            "body": post.content,
            "history": self.facts.history(fact_id),
        }

    def _fact_content_hash(self, rel: str) -> str:
        return hashlib.sha256(
            (self.settings.data_repo_path / rel).read_bytes()
        ).hexdigest()

    async def ui_submit_feedback(self, fact_id: str, feedback: str) -> dict:
        async with self.store.write_lock():
            try:
                post, rel = self.facts.get(fact_id)
            except FactNotFound:
                return {"error": f"fact が存在しない: {fact_id}"}
            if post.get("status") != "active":
                return {"error": "active な fact のみ改善できます"}
            base_content_hash = self._fact_content_hash(rel)
            original = {
                "statement": post.get("statement", ""),
                "why": post.get("why", ""),
                "how_to_apply": post.get("how_to_apply", ""),
                "tags": post.get("tags", []),
                "body": post.content,
                "namespace": post.get("namespace", ""),
                "kind": post.get("kind", ""),
                "source": post.get("source", ""),
            }
        try:
            request = await self.feedback.submit(
                fact_id=fact_id,
                base_content_hash=base_content_hash,
                namespace=str(post.get("namespace", "")),
                kind=str(post.get("kind", "")),
                source=str(post.get("source", "")),
                original=original,
                feedback=feedback,
            )
        except ValueError as error:
            return {"error": str(error)}
        return request.model_dump(mode="json")

    async def ui_feedback_requests(self, fact_id: str) -> list[dict]:
        return [
            item.model_dump(mode="json") for item in self.feedback.store.by_fact(fact_id)
        ]

    async def ui_apply_feedback(self, request_id: str) -> dict:
        try:
            request = await self.feedback.claim_apply(request_id)
        except KeyError:
            return {"error": f"feedback request が存在しない: {request_id}"}
        except ValueError as error:
            return {"error": str(error)}
        if request.proposal is None:  # claim_apply guarantees this; narrows the type.
            return {"error": "proposal がありません"}
        try:
            post, rel = self.facts.get(request.fact_id)
        except FactNotFound:
            await self.feedback.transition(
                request_id, FeedbackState.stale, error="元factが存在しません"
            )
            return {"error": "元factが存在しないためstaleになりました", "stale": True}
        marker = f"PLK-Change-Ref: feedback/{request_id}"
        applied_commit = self.store.git(
            "log", "-1", "--format=%H", f"--grep={marker}"
        ).strip()
        if applied_commit and post.get("superseded_by"):
            replacement_id = str(post.get("superseded_by"))
            await self.feedback.transition(
                request_id,
                FeedbackState.applied,
                replacement_fact_id=replacement_id,
            )
            return {"fact_id": replacement_id, "state": FeedbackState.applied.value}
        if (
            post.get("status") != "active"
            or self._fact_content_hash(rel) != request.base_content_hash
        ):
            await self.feedback.transition(
                request_id, FeedbackState.stale, error="元factが依頼後に変更されました"
            )
            return {"error": "元factが変更されたためstaleになりました", "stale": True}
        proposal = request.proposal
        try:
            replacement_id = await self.facts.add(
                client="plk-web-ui",
                namespace=request.namespace,
                kind=request.kind,
                statement=proposal.statement,
                why=proposal.why,
                how_to_apply=proposal.how_to_apply,
                source=request.source,
                tags=proposal.tags,
                body=proposal.body,
                source_type="agent",
                supersedes=[request.fact_id],
                expected_superseded_hashes={
                    request.fact_id: request.base_content_hash
                },
                change_ref=f"feedback/{request_id}",
            )
        except FactError as error:
            if "変更されています" in str(error):
                await self.feedback.transition(
                    request_id, FeedbackState.stale, error=str(error)
                )
                return {"error": str(error), "stale": True}
            await self.feedback.transition(
                request_id, FeedbackState.proposed, error=str(error)
            )
            return {"error": str(error)}
        except FactNotFound as error:
            await self.feedback.transition(
                request_id, FeedbackState.proposed, error=str(error)
            )
            return {"error": str(error)}
        except WriteConflict as error:
            await self.feedback.transition(
                request_id, FeedbackState.proposed, error=str(error)
            )
            return {"error": str(error), "retry": True}
        await self.feedback.transition(
            request_id,
            FeedbackState.applied,
            replacement_fact_id=replacement_id,
        )
        self._spawn_sync()
        return {"fact_id": replacement_id, "state": FeedbackState.applied.value}

    async def ui_reject_feedback(self, request_id: str) -> dict:
        try:
            updated = await self.feedback.reject(request_id)
        except KeyError:
            return {"error": f"feedback request が存在しない: {request_id}"}
        except ValueError as error:
            return {"error": str(error)}
        return updated.model_dump(mode="json")

    async def ui_invalidate_fact(
        self, fact_id: str, reason: str, expected_hash: str
    ) -> dict:
        if self.sync.maintenance:
            return {"error": "maintenance 中（reindex 実行中）", "retry": True}
        try:
            await self.facts.invalidate(
                fact_id,
                reason,
                client="plk-web-ui",
                expected_hash=expected_hash,
            )
        except (FactError, FactNotFound) as error:
            return {"error": str(error)}
        except WriteConflict as error:
            return {"error": str(error), "retry": True}
        self._spawn_sync()
        return {"fact_id": fact_id, "status": "invalidated"}

    async def tool_propose_promotion(
        self,
        fact_id: str,
        reason: str | None = None,
        *,
        idempotency_key: str | None = None,
    ) -> dict:
        del idempotency_key
        self._require_client()
        if self.promotion_backend is None:
            return {"error": "promotion backend が未設定（enable_github_promotion=True の常駐プロセスのみ有効）"}
        try:
            post, rel = self.facts.get(fact_id)
        except FactNotFound:
            return {"error": f"fact が存在しない: {fact_id}"}
        if post.get("status") != "active":
            return {"error": "active な fact のみ昇格できる"}
        ns = post.get("namespace")
        if not isinstance(ns, str) or not ns.startswith("plk.domain."):
            return {"error": f"昇格できるのは plk.domain.* のみ（現在: {ns}）"}
        # push 完了がプリコンディション（設計書 §5）。
        # ここで先に await（to_thread）を消化しておくことで、以降の
        # 「重複チェック → upsert」を event loop 上で await 無しの不可分区間にする
        # （同一 fact への並行 propose が重複レコードを作るレースの防止）。
        unpushed = (
            await asyncio.to_thread(self.store.git, "rev-list", "--count", "origin/main..HEAD")
        ).strip()
        if unpushed != "0":
            return {"error": f"未 push の commit が {unpushed} 件ある（push 完了後に再試行）"}
        # 既存の未処理昇格があれば再作成しない（ここから upsert まで await を挟まない）
        for existing in self.promotion_store.by_fact(fact_id):
            if existing.state in (PromotionState.proposed, PromotionState.approved):
                return {"error": "既に昇格リクエストが存在する", "promotion_id": existing.id}

        # domains/<d>/<file> -> shared/<file>（CI の check_promotion が要求する rename 形）
        new_rel = f"{self.settings.knowledge_subdir}/shared/" + posixpath.basename(rel)
        pr = new_promotion(
            fact_id=fact_id, from_namespace=ns, old_path=rel, new_path=new_rel,
            branch=f"promote/{fact_id}", reason=reason,
        )
        self.promotion_store.upsert(pr)
        try:
            number, url = await self.promotion_backend.create_pr(pr)
        except Exception as e:  # noqa: BLE001
            # ロールバック: proposed のまま pr_number=None のレコードが残ると、
            # ①再 propose が重複チェックで永久拒否 ②poll が pr_number=None で永久スキップ、
            # の復旧不能状態になる。削除して再 propose で自己回復させる
            # （PR が作られていた場合も backend の already-exists 再利用で回収できる）。
            self.promotion_store.delete(pr.id)
            return {"error": f"PR 作成に失敗: {e}"}
        pr = pr.model_copy(update={"pr_number": number, "pr_url": url})
        self.promotion_store.upsert(pr)
        return {"promotion_id": pr.id, "pr_url": url, "state": pr.state.value}

    async def tool_decide_promotion(
        self,
        request_id: str,
        decision: str,
        rationale: str,
        expected_revision: int,
        *,
        idempotency_key: str | None = None,
    ) -> dict:
        del request_id, decision, rationale, expected_revision, idempotency_key
        return {"error": "Git-primaryではGitHub PR上で承認・mergeする"}

    async def poll_promotions(self) -> dict:
        if self.promotion_backend is None:
            return {"applied": 0, "rejected": 0, "checked": 0}
        applied = rejected = checked = 0
        for pr in self.promotion_store.by_state(PromotionState.proposed) + \
                self.promotion_store.by_state(PromotionState.approved):
            if pr.pr_number is None:
                continue
            checked += 1
            try:
                state = await self.promotion_backend.merged_state(pr.pr_number)
            except Exception:  # noqa: BLE001 - 照会失敗は次回に回す
                continue
            # 冪等性: transition() は許可されない遷移で PromotionError を送出するため、
            # 既に applied/rejected な PromotionRequest を再取得した場合（同じ merge の
            # 二重検知）はここで静かにスキップする。
            current = self.promotion_store.get(pr.id)
            if current.state not in (PromotionState.proposed, PromotionState.approved):
                continue
            if state == "MERGED":
                self.promotion_store.upsert(transition(current, PromotionState.applied))
                await self.sync.sync()  # level-triggered が rename を拾い shared へ再 ingest
                applied += 1
            elif state == "APPROVED":
                # 承認と適用が分離するバックエンド（Slack 等）の中間状態。
                # 承認の記録のみ行い、sync はしない（適用は MERGED 検知時）。
                # GitHub backend は APPROVED を返さないため既存経路への影響はない。
                if current.state is PromotionState.proposed:
                    self.promotion_store.upsert(transition(current, PromotionState.approved))
            elif state == "CLOSED":
                self.promotion_store.upsert(transition(current, PromotionState.rejected))
                rejected += 1
        return {"applied": applied, "rejected": rejected, "checked": checked}
