"""自己発行 JWT ＋ローカル JWKS の生成（Phase 3 認証換装の 4 クライアント接続確認用）。

verify-and-adapt: RSAKeyPair / JsonWebKey の API は fastmcp 3.4.2 / authlib 1.7.2 で
実機確認済み。brief 記載からの差分（実装時に判明したもの）:
  - `RSAKeyPair.private_key` は素の str ではなく pydantic `SecretStr`。
    `.get_secret_value()` で PEM 文字列を取り出す必要がある（brief はプレーン str を想定）。
  - `JsonWebKey.import_key(...).as_dict()` は kid を自動生成する（RFC7638 サムプリント）。
    `create_token(..., kid=...)` にはその kid をそのまま渡せる。

使い方:
    uv run python -m scripts.auth.issue_jwt
出力:
    ~/.plk/jwt/  … private.pem / public.pem / jwks.json / tokens.env（4 クライアント分）
戻し方（実測後）: PLK_AUTH_MODE を消す（既定 bearer に戻る）。鍵は破棄してよい。
"""

from __future__ import annotations

import json
from pathlib import Path

from authlib.jose import JsonWebKey
from fastmcp.server.auth.providers.jwt import RSAKeyPair

ISSUER = "https://plk-memory.local/"
AUDIENCE = "plk-memory"
CLIENTS = ["claude-code", "codex", "hermes", "custom-agent"]
OUT = Path.home() / ".plk" / "jwt"


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    pair = RSAKeyPair.generate()
    # private_key は SecretStr（brief は str を想定していたが実際は pydantic SecretStr）。
    (OUT / "private.pem").write_text(pair.private_key.get_secret_value(), encoding="utf-8")
    (OUT / "public.pem").write_text(pair.public_key, encoding="utf-8")

    jwk = JsonWebKey.import_key(pair.public_key, {"kty": "RSA", "use": "sig", "alg": "RS256"})
    jwk_dict = jwk.as_dict()
    (OUT / "jwks.json").write_text(
        json.dumps({"keys": [jwk_dict]}, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    lines = []
    for client in CLIENTS:
        token = pair.create_token(
            subject=client, issuer=ISSUER, audience=AUDIENCE,
            kid=jwk_dict.get("kid"), expires_in_seconds=30 * 24 * 3600,
        )
        lines.append(f"# {client}\nPLK_JWT_{client.replace('-', '_').upper()}={token}")
    (OUT / "tokens.env").write_text("\n".join(lines) + "\n", encoding="utf-8")

    print(f"生成完了: {OUT}")
    print("サーバー起動（jwt モード）例:")
    print('  PLK_AUTH_MODE=jwt PLK_JWKS_URI=http://127.0.0.1:8735/.well-known/jwks.json \\')
    print(f'  PLK_JWT_PUBLIC_KEY="$(cat {OUT}/public.pem)" \\')
    print("  uv run uvicorn plk_memory.app:create_app --factory --host 127.0.0.1 --port 8735")
    print(f"各クライアントの Bearer には {OUT}/tokens.env の JWT を使う")


if __name__ == "__main__":
    main()
