# contents_broad_test — 社内ポータル コンテンツ配信・管理システム

Azure App Service 上で動作する社内ポータル。動画・PDF・お知らせ等のコンテンツを
Azure Blob Storage に保存し、Entra ID（Easy Auth）認証のもとで配信・管理する。

## 構成
単一コンテナ内で **nginx + FastAPI(uvicorn)** を **supervisor** が管理する。
コンテンツは Blob Storage と nginx の `/var/www/html/content` に同じ相対パスで
保存する。画面からの再アップロード（更新）と削除は両方の保存先に反映される。

| ファイル | 役割 |
|---|---|
| `Dockerfile` | イメージ定義（nginx＋supervisor＋FastAPI、ビルド時検証） |
| `supervisord.conf` | nginx と FastAPI のプロセス管理 |
| `nginx.conf` | 静的配信と `/app01/api/` のリバースプロキシ |
| `src/api.py` | FastAPI 本体（health / me / admin） |
| `index.html` | 管理タブ付きポータル画面 |
| `health_check.html` | 稼働状態表示ページ |
| `requirements.txt` | Python 依存関係 |

## ポート
nginx listen 80 / EXPOSE 80 / WEBSITES_PORT=80 を一致。uvicorn は 127.0.0.1:8000 固定。

## API
- `GET /api/health` 認証済 — API + Blob 接続性（正常200／異常503）
- `GET /api/me` 認証済 — ユーザー名と `is_admin`
- `GET /api/admin/files` 管理者 — ファイル一覧
- `POST /api/admin/upload?name=...` 管理者 — リクエストボディを nginx と Blob に保存・更新
- `POST /api/admin/delete` 管理者 — nginx と Blob から削除

## App Service 設定
`WEBSITES_PORT=80`, `STORAGE_ACCOUNT_NAME`, `BLOB_CONTAINER_NAME`,
`STORAGE_MODE=azure`。ローカル保存先は `CONTENT_ROOT` で変更できる
（既定 `/var/www/html/content`）。
ストレージはマネージドID＋RBAC（読取/共同作成者）でアクセスし、キーは保持しない。

nginx は 2 GB までのリクエストを許可し、アップロードをバッファリングせず API に
ストリーミングする。再起動後も nginx 側のコピーを維持する必要がある環境では、
`/var/www/html/content` に永続ボリュームをマウントする。

ローカル開発では Easy Auth が無く `X-MS-CLIENT-PRINCIPAL` が付かないため管理者判定は常に偽。

### Blob を作成しないテスト・検証

`STORAGE_MODE=dummy` を設定すると Azure SDK を呼ばず、nginx 側のローカル保存だけで
一覧・アップロード・削除を検証できる。`local` と `ci` のテスト環境ではこのモードを
既定で使用する。

## テスト
`pytest` と `Playwright` による単体・結合・E2E テストを `tests/` に用意している。

| 種別 | 場所 | 内容 |
|---|---|---|
| 単体 (unit) | `tests/unit/` | 認証ヘッダ解析・管理者判定など純粋ロジック |
| 結合 (integration) | `tests/integration/` | FastAPI TestClient で各APIを検証（Blobはモック） |
| E2E | `tests/e2e/` | Playwright でポータルUI（タブ/一覧/検索/削除/稼働状態）を検証 |

### 環境切り替え
`TEST_ENV` 環境変数でテスト環境（`local`/`ci`/`staging`）を切り替える。
定義は `tests/environments.py`。未指定時は `local`。

```bash
pip install -r requirements-dev.txt
python -m playwright install chromium      # E2E用
python -m pytest                            # 既定(local)で全テスト
TEST_ENV=ci python -m pytest -m integration # 環境を切り替えて結合のみ
python -m pytest -m unit                    # 種別で絞り込み
```
