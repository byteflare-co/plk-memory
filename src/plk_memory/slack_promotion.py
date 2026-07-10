"""Slack 承認アダプタのスタブ（設計書 §2・§10: 境界の実在を一度通す）。

PromotionBackend Protocol の非 GitHub 実装。Block Kit ペイロード生成と
承認コールバック → transition の『形だけ』を提供する。実 Slack 接続・slack-bolt 依存はない。
組織展開 逆輸入時にここへ実 chat.postMessage / interactivity エンドポイントを差し込む。
"""

from __future__ import annotations

from plk_memory.promotions import PromotionRequest

ACTION_APPROVE = "plk_promote_approve"
ACTION_REJECT = "plk_promote_reject"


def build_approval_blocks(pr: PromotionRequest) -> list[dict]:
    """昇格リクエストの承認メッセージ（Slack Block Kit）。
    button の value に promotion id を載せ、interactivity callback で回収する。"""
    return [
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": (
                    "*plk-memory 昇格リクエスト*\n"
                    f"・fact_id: `{pr.fact_id}`\n"
                    f"・from: `{pr.from_namespace}` → to: `{pr.to_namespace}`\n"
                    f"・rename: `{pr.old_path}` → `{pr.new_path}`"
                ),
            },
        },
        {
            "type": "actions",
            "block_id": pr.id,
            "elements": [
                {
                    "type": "button",
                    "action_id": ACTION_APPROVE,
                    "style": "primary",
                    "text": {"type": "plain_text", "text": "承認"},
                    "value": pr.id,
                },
                {
                    "type": "button",
                    "action_id": ACTION_REJECT,
                    "style": "danger",
                    "text": {"type": "plain_text", "text": "却下"},
                    "value": pr.id,
                },
            ],
        },
    ]


def parse_action_callback(payload: dict) -> tuple[str, str]:
    """Slack interactivity callback を (promotion_id, merged_state) に写像する。
    approve → APPROVED / reject → CLOSED（poll_promotions が解釈する merged_state 語彙に合わせる）。
    Slack backend では承認と適用が分離するため、承認は中間状態 APPROVED であり、
    MERGED は record_applied（適用完了）で初めて到達する。"""
    action = payload["actions"][0]
    promotion_id = action["value"]
    if action["action_id"] == ACTION_APPROVE:
        return promotion_id, "APPROVED"
    if action["action_id"] == ACTION_REJECT:
        return promotion_id, "CLOSED"
    raise ValueError(f"未知の action_id: {action['action_id']}")


class SlackPromotionBackend:
    """PromotionBackend Protocol（create_pr / merged_state）の Slack 実装スケルトン。

    実 Slack 接続はしない。create_pr = 承認メッセージ投稿の代わりに Block Kit を記録し
    合成 (message_id, permalink) を返す。merged_state = record_decision / record_applied で
    記録された状態を返す（実運用では interactivity エンドポイントが record_decision を、
    適用処理が record_applied を呼ぶ）。

    状態遷移（4 値語彙）: OPEN →（承認 callback）APPROVED →（適用）MERGED、
    または OPEN →（却下 callback）CLOSED。GitHub と違い承認と適用が分離する。
    """

    def __init__(self) -> None:
        self.posted: dict[int, list[dict]] = {}   # message_id -> blocks
        self._decisions: dict[int, str] = {}       # message_id -> "APPROVED"|"MERGED"|"CLOSED"
        self._next_id = 1000

    async def create_pr(self, pr: PromotionRequest) -> tuple[int, str]:
        self._next_id += 1
        message_id = self._next_id
        self.posted[message_id] = build_approval_blocks(pr)
        # 実運用では chat.postMessage の permalink。スタブでは合成 URL。
        return message_id, f"https://slack.example/archives/C000/p{message_id}"

    def record_decision(self, message_id: int, state: str) -> None:
        """interactivity callback → merged_state へ橋渡し（承認 APPROVED / 却下 CLOSED の記録）。"""
        self._decisions[message_id] = state

    def record_applied(self, message_id: int) -> None:
        """適用完了の記録 — 以後 merged_state は MERGED を返す。

        実装（組織展開 逆輸入時）ではここが承認済みリクエストの実適用点:
        knowledge リポジトリで old_path → new_path の git 移動＋commit＋push を行い、
        成功後に MERGED を記録する。スタブでは状態記録のみ。
        """
        self._decisions[message_id] = "MERGED"

    async def merged_state(self, message_id: int) -> str:
        return self._decisions.get(message_id, "OPEN")
