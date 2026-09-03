# contents_broad_test — 社内ポータル コンテンツ配信・管理システム

Azure App Service 上で動作する社内ポータル。動画・PDF・お知らせ等のコンテンツを
Azure Blob Storage に保存し、Entra ID（Easy Auth）認証のもとで配信・管理する。

## アプリの説明

社員向けの単一ページ（`index.html`）のポータルで、次の 3 タブで構成される。
「管理」タブは Entra ID のアプリロール **FileAdmin** を持つユーザーにのみ表示される。

### ホーム
動画・マニュアル等のコンテンツを閲覧する入口。コンテンツは nginx の
`/content/` 配下から配信される。

### お知らせ
`release_notes/` フォルダに置かれたテキストファイル（`.txt`）を新しい順に表示する。
ファイル名の接頭辞でカテゴリを判定し、サブタブで切り替えて表示する。

| カテゴリ | ファイル名 | 表示スタイル |
|---|---|---|
| リリース | 接頭辞なし（例 `2026-08-25_v1.3.0.txt`） | 青系カード。ファイル名がタイトル、本文全体を表示 |
| アップデート | `update_*.txt` | 緑系のコンパクトなカード |
| ニュース | `news_*.txt` | 黄系カード。本文 1 行目をタイトル、2 行目以降を本文として表示 |

### 管理（FileAdmin のみ）
フォルダ（`manuals/` `videos/` `release_notes/` `announcements/`）を選び、
ファイルの一覧・検索・ソート・ページング（50 件/頁）ができる。
ドラッグ＆ドロップまたはファイル選択でアップロード（進捗バー付き、同名は上書き確認）、
チェックボックスで複数選択して削除できる。削除は 5 秒間の「元に戻す」猶予付き。
アップロード・削除は nginx ローカルと Blob Storage の両方に反映される。

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
| `index.html` | 管理タブ付きポータル画面（マークアップ） |
| `static/js/app.js` | ポータル画面のフロントエンドロジック（素の JavaScript） |
| `static/css/style.css` | ポータル画面のスタイルシート |
| `portal-content/` | dummy モードで使うローカルコンテンツ（開発・テスト用） |
| `health_check.html` | 稼働状態表示ページ |
| `requirements.txt` | Python 依存関係 |

## ポート
nginx listen 80 / EXPOSE 80 / WEBSITES_PORT=80 を一致。uvicorn は 127.0.0.1:8000 固定。

## API
- `GET /api/health` 認証済 — API + Blob 接続性（正常200／異常503）
- `GET /api/me` 認証済 — ユーザー名と `is_admin`
- `GET /api/release-notes` 認証済 — `release_notes/` 配下の `.txt` をカテゴリ・本文付きで新しい順に返す
- `GET /api/admin/files` 管理者 — ファイル一覧
- `POST /api/admin/upload?name=...` 管理者 — リクエストボディを一時ファイルへストリーミングし、nginx と Blob に保存・更新
- `POST /api/admin/delete` 管理者 — nginx と Blob から削除

ファイル名は相対パスとして検証され、絶対パス、`..`、`.`、空のパス要素、バックスラッシュ、
NULL 文字を含む名前は拒否される。これにより、ローカル保存先のディレクトリ外へ書き込まない。

## App Service 設定
`WEBSITES_PORT=80`, `STORAGE_ACCOUNT_NAME`, `BLOB_CONTAINER_NAME`,
`STORAGE_MODE=azure`。ローカル保存先は `CONTENT_ROOT` で変更できる
（既定 `/var/www/html/content`）。
ストレージはマネージドID＋RBAC（読取/共同作成者）でアクセスし、キーは保持しない。

nginx は 2 GB までのリクエストを許可し、アップロードをバッファリングせず API に
ストリーミングする。再起動後も nginx 側のコピーを維持する必要がある環境では、
`/var/www/html/content` に永続ボリュームをマウントする。

## ローカル開発

Azure と Easy Auth を使わずに、FastAPI と開発用プロキシを別々に起動する。
開発用プロキシは nginx の代わりに UI 配信と API プロキシを行い、既定では
`FileAdmin` ロールを含む `X-MS-CLIENT-PRINCIPAL` ヘッダを API に付与する。

```bash
# ターミナル 1: API（リポジトリ直下で実行）
STORAGE_MODE=dummy python -m uvicorn src.api:app --host 127.0.0.1 --port 8000

# ターミナル 2: UI + API プロキシ
python scripts/dev_server.py
```

ブラウザで http://127.0.0.1:8080/app01/ を開く。稼働確認ページは
http://127.0.0.1:8080/app01/health_check、API 直接確認先は
http://127.0.0.1:8000 である。一般ユーザーの表示を確認する場合は、プロキシを
`DEV_ADMIN=0 python scripts/dev_server.py` で起動する。

dummy モードでは `CONTENT_ROOT` 未指定時にリポジトリ内の `portal-content/` を使う。
別のコンテンツを使う場合は、API と開発用プロキシの両方に同じ `CONTENT_ROOT` を指定する。
テストデータは `python scripts/generate_test_data.py` で生成でき、動画を省略する場合は
`--skip-videos` を付ける。

### Blob を作成しないテスト・検証

`STORAGE_MODE=dummy` を設定すると Azure SDK を呼ばず、nginx 側のローカル保存だけで
一覧・アップロード・削除を検証できる。`local` と `ci` のテスト環境ではこのモードを
既定で使用する。

## Lint / フォーマット
Python コードは [Ruff](https://docs.astral.sh/ruff/) で検査・整形する。
VS Code では Ruff 拡張機能の同梱版を使用し、Python ファイルの保存時フォーマットと
明示的な import 整理を有効にしている。Python 環境へ Ruff パッケージをインストールする
必要はない。ルール設定は `pyproject.toml`（行長 120、pycodestyle/pyflakes/isort/pyupgrade/bugbear/simplify）。

```bash
uvx ruff check .          # 一時実行で lint（--fix で自動修正）
uvx ruff format .         # 一時実行でフォーマット（--check で差分確認のみ）
```

`uvx` を使わずにコマンドラインで実行する場合は、開発用仮想環境などへ Ruff を別途
インストールする。プロジェクトの `requirements-dev.txt` には含めない。

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
