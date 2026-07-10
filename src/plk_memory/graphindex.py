"""Graphiti (graphiti-core 0.29.2) ラッパー（設計書 §4-5）。

graphiti 実 API への適応内容（group_id 制約・cross_encoder 回避等）は
docs/LESSONS.md を参照。
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from typing import Any

import frontmatter
from graphiti_core import Graphiti
from graphiti_core.cross_encoder.client import CrossEncoderClient
from graphiti_core.driver.falkordb_driver import FalkorDriver
from graphiti_core.edges import Edge, EntityEdge, create_entity_edge_embeddings
from graphiti_core.embedder.openai import OpenAIEmbedder, OpenAIEmbedderConfig
from graphiti_core.llm_client.anthropic_client import AnthropicClient
from graphiti_core.llm_client.client import LLMClient
from graphiti_core.llm_client.config import LLMConfig
from graphiti_core.llm_client.openai_generic_client import OpenAIGenericClient
from graphiti_core.nodes import EntityNode, create_entity_node_embeddings
from graphiti_core.utils.bulk_utils import add_nodes_and_edges_bulk
from graphiti_core.utils.maintenance.graph_data_operations import clear_data
from pydantic import BaseModel

from plk_memory.rendering import content_hash, episode_name, render_episode
from plk_memory.settings import Settings
from plk_memory.state import FactIndexEntry

logger = logging.getLogger(__name__)


class SearchHit(BaseModel):
    fact_id: str
    fact_text: str
    score: float | None = None


class _NullCrossEncoder(CrossEncoderClient):
    """Graphiti() のデフォルト cross_encoder（OpenAIRerankerClient）の代替。

    OpenAIRerankerClient() はコンストラクタ内で AsyncOpenAI(api_key=None) を
    生成し、OPENAI_API_KEY 未設定の環境ではその場で openai.OpenAIError を
    送出する（Graphiti.__init__ が cross_encoder 未指定時に無条件でこれを
    構築するため、search を一度も呼ばなくても Graphiti() 自体が失敗する）。
    本 GraphIndex は search() を EDGE_HYBRID_SEARCH_RRF 相当（RRF リランキ
    ング、cross_encoder 不使用）で行うため rank() は実際には呼ばれない想定
    だが、念のため no-op 実装を渡して構築時エラーを回避する。
    """

    async def rank(self, query: str, passages: list[str]) -> list[tuple[str, float]]:
        return [(p, 0.0) for p in passages]


def _build_llm_client(settings: Settings) -> LLMClient:
    """ingest LLM のクライアントを settings.llm_provider に応じて構築する（純粋関数）。

    - anthropic: 現行どおり AnthropicClient（組織展開 逆輸入用に温存）。
    - openai-compatible: ローカル Ollama 等の OpenAI 互換 /chat/completions エンドポイント
      向け OpenAIGenericClient（graphiti-core 0.29.2 時点。json_schema 構造化出力に既定対応
      しており Ollama もターゲットとして明記されている。DEFAULT_MODEL フォールバックを避け
      るため model は必ず settings.llm_model を渡す）。
    - それ以外: 起動時に明示エラー。
    """
    if settings.llm_provider == "anthropic":
        return AnthropicClient(LLMConfig(model=settings.anthropic_model))
    if settings.llm_provider == "openai-compatible":
        return OpenAIGenericClient(
            LLMConfig(
                model=settings.llm_model,
                base_url=settings.llm_base_url,
                api_key=settings.llm_api_key,
            )
        )
    raise ValueError(
        f"未知の llm_provider: {settings.llm_provider!r}（'anthropic' か 'openai-compatible' を指定）"
    )


def _resolve_hits(edges: list[Any], uuid_to_fact: dict[str, str], limit: int) -> list[SearchHit]:
    """検索で得た edge 群を fact_id に解決し、重複除去・件数制限する（純粋関数）。

    帰属は 2 経路:
    - triplet モード: edge.uuid そのもの → fact_id。state.facts の episode_uuids には
      add_triplet が返した edge uuid を格納しており、triplet の EntityEdge は
      episodes が空。Task 14 実測で「episodes のみ参照だと triplet 検索が
      恒久 0 ヒット（正解 edge が rank1 で返っていても帰属で全部捨てる）」
      というバグとして発見・修正。
    - episode モード: edge.episodes（episode uuid のリスト）→ fact_id。
    """
    hits: list[SearchHit] = []
    seen_fact_ids: set[str] = set()
    skipped = 0
    for edge in edges:
        fact_id: str | None = uuid_to_fact.get(getattr(edge, "uuid", ""))
        if fact_id is None:
            episode_uuids = getattr(edge, "episodes", None) or []
            for ep_uuid in episode_uuids:
                if ep_uuid in uuid_to_fact:
                    fact_id = uuid_to_fact[ep_uuid]
                    break
        if fact_id is None:
            skipped += 1
            continue
        if fact_id in seen_fact_ids:
            continue
        seen_fact_ids.add(fact_id)
        hits.append(SearchHit(fact_id=fact_id, fact_text=edge.fact, score=getattr(edge, "score", None)))
        if len(hits) >= limit:
            break
    if skipped:
        logger.info("graphindex: skipped %d edges with no fact attribution", skipped)
    return hits


class GraphIndex:
    def __init__(self, settings: Settings):
        self.settings = settings
        self._graphiti: Graphiti | None = None
        self._ready = False
        # group_id -> clone 済みドライバのキャッシュ。プロセス生存期間中解放しないが、
        # キーは settings.all_groups() の group に限られるため有界（数個）。
        self._group_drivers: dict[str, Any] = {}
        # route-then-operate の相互排他ロック。_route_group は graphiti の共有状態
        # （Graphiti.driver / Graphiti.clients.driver）を書き換えるため、公開メソッド
        # 全体を直列化しないと、await 境界で別コルーチンが別 group へ付け替えた
        # ドライバを読み書きしてしまう（plk-quarantine の隔離境界も破れ得る）。
        # 検索の並行性は失われるが Phase 1 の規模（単一レプリカ・少数クライアント）
        # では許容。組織展開 規模では graphiti の driver= 引数スレッディング
        # （操作ごとにドライバを引数で渡す方式）への移行を検討する。
        self._op_lock = asyncio.Lock()

    @property
    def ready(self) -> bool:
        return self._ready

    def _graph(self) -> Graphiti:
        if self._graphiti is None:
            raise RuntimeError("GraphIndex.start() をまだ呼び出していません")
        return self._graphiti

    def _route_group(self, group_id: str) -> None:
        """graphiti のドライバを group_id 用の FalkorDB グラフへ切り替える。

        graphiti-core 0.29.2 の FalkorDriver はマルチテナント（group_id ごとに
        別グラフ）。`add_episode` だけは内部で driver / clients.driver を
        `clone(database=group_id)` へ付け替えるが、`search`（単一 group_id）・
        `add_triplet`・`remove_episode`・`clear_data` は自前で付け替えない。
        そのため (1) 新規プロセス（新規 Graphiti インスタンス）は default_db を
        向いたままで、初回 search がデータの入った group グラフを読めず 0 件になる
        （Task 13 live 実測で判明: measure_ingest プロセスは plk-main へ書き、
        別プロセスの検索が default_db を読んだ）、(2) triplet upsert・削除・clear も
        default_db に向いてしまう。よって全操作の前に両参照を揃えて付け替える。
        clone はイベントループ上で対象グラフの索引構築も予約する。

        注意: 共有状態の書き換えなので、呼び出し側は必ず _op_lock を保持していること。
        """
        graphiti = self._graph()
        driver = self._group_drivers.get(group_id)
        if driver is None:
            driver = graphiti.driver.clone(database=group_id)
            self._group_drivers[group_id] = driver
        graphiti.driver = driver
        graphiti.clients.driver = driver

    async def start(self) -> None:
        driver = FalkorDriver(
            host=self.settings.falkordb_host,
            port=self.settings.falkordb_port,
        )
        llm_client = _build_llm_client(self.settings)
        embedder = OpenAIEmbedder(
            OpenAIEmbedderConfig(
                api_key=self.settings.embedder_api_key,
                base_url=self.settings.embedder_base_url,
                embedding_model=self.settings.embedder_model,
                embedding_dim=self.settings.embedding_dim,
            )
        )
        graphiti = Graphiti(
            graph_driver=driver,
            llm_client=llm_client,
            embedder=embedder,
            cross_encoder=_NullCrossEncoder(),
        )
        await graphiti.build_indices_and_constraints()
        self._graphiti = graphiti
        self._ready = True

    # --- 書き込み ---

    async def upsert_fact(
        self, post: frontmatter.Post, old: FactIndexEntry | None
    ) -> FactIndexEntry:
        # route→操作を原子化する（_op_lock の理由は __init__ のコメント参照）
        async with self._op_lock:
            if old is not None and old.episode_uuids:
                await self._delete_entry(old)

            if post["status"] == "invalidated":
                return FactIndexEntry()

            group_id = self.settings.group_for(post["namespace"])
            self._route_group(group_id)

            if self.settings.ingest_mode == "triplet":
                return await self._upsert_curated_triplet(post, group_id)
            return await self._upsert_episode(post, group_id)

    async def _upsert_episode(self, post: frontmatter.Post, group_id: str) -> FactIndexEntry:
        graphiti = self._graph()
        created_at = post["created_at"]
        if isinstance(created_at, str):
            created_at = datetime.fromisoformat(created_at)

        result = await graphiti.add_episode(
            name=episode_name(post),
            episode_body=render_episode(post),
            source_description=f"plk:{post['id']}",
            reference_time=created_at,
            group_id=group_id,
        )
        return FactIndexEntry(
            episode_uuids=[result.episode.uuid],
            content_hash=content_hash(post),
            group_id=group_id,
        )

    async def _upsert_curated_triplet(self, post: frontmatter.Post, group_id: str) -> FactIndexEntry:
        graphiti = self._graph()
        statement = post["statement"]
        tags: list[str] = list(post.get("tags") or []) or [post["namespace"]]
        now = datetime.now(timezone.utc)

        edge_uuids: list[str] = []
        for tag in tags:
            fact_node = EntityNode(name=statement, group_id=group_id, labels=["Entity"])
            tag_node = EntityNode(name=tag, group_id=group_id, labels=["Entity"])
            edge = EntityEdge(
                name="RELATES_TO",
                fact=statement,
                source_node_uuid=fact_node.uuid,
                target_node_uuid=tag_node.uuid,
                group_id=group_id,
                created_at=now,
            )
            nodes = [fact_node, tag_node]
            edges = [edge]
            # Curated PLK facts are already reviewed. Graphiti.add_triplet() routes even
            # explicit triplets through LLM duplicate resolution, which can hang local
            # Ollama ingest; store the explicit relation directly instead.
            await create_entity_node_embeddings(graphiti.embedder, nodes)
            await create_entity_edge_embeddings(graphiti.embedder, edges)
            await add_nodes_and_edges_bulk(graphiti.driver, [], [], nodes, edges, graphiti.embedder)
            edge_uuids.append(edge.uuid)

        return FactIndexEntry(
            episode_uuids=edge_uuids,
            content_hash=content_hash(post),
            group_id=group_id,
        )

    async def delete_fact(self, old: FactIndexEntry) -> None:
        if not old.episode_uuids:
            return
        # route→操作を原子化する（_op_lock の理由は __init__ のコメント参照）
        async with self._op_lock:
            await self._delete_entry(old)

    async def _delete_entry(self, entry: FactIndexEntry) -> None:
        graphiti = self._graph()
        self._route_group(entry.group_id or self.settings.main_group)
        if self.settings.ingest_mode == "triplet":
            # triplet モードでは episode_uuids に edge（もしくは node）の uuid を格納している。
            await Edge.delete_by_uuids(graphiti.driver, entry.episode_uuids)
        else:
            for ep_uuid in entry.episode_uuids:
                await graphiti.remove_episode(ep_uuid)

    # --- 読み取り ---

    async def search(
        self,
        query: str,
        group_ids: list[str],
        uuid_to_fact: dict[str, str],
        limit: int = 10,
    ) -> list[SearchHit]:
        graphiti = self._graph()
        # group_id ごとに専用グラフへルーティングして検索し、結果を結合する
        # （単一 group_id では graphiti 側がドライバを付け替えないため — _route_group 参照）。
        # route→検索を原子化する（_op_lock の理由は __init__ のコメント参照）。
        edges: list[Any] = []
        async with self._op_lock:
            for gid in group_ids:
                self._route_group(gid)
                edges.extend(
                    await graphiti.search(query, group_ids=[gid], num_results=limit * 3)
                )
        return _resolve_hits(edges, uuid_to_fact, limit)

    async def clear(self, group_ids: list[str]) -> None:
        graphiti = self._graph()
        # route→clear を原子化する（_op_lock の理由は __init__ のコメント参照）
        async with self._op_lock:
            for gid in group_ids:
                self._route_group(gid)
                await clear_data(graphiti.driver, [gid])
                await graphiti.build_indices_and_constraints()
