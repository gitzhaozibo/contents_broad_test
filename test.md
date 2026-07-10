# Azure OpenAI (GPT-5.4) → ローカルvLLM 移行整理

作成日: 2026-07-10

## 1. 移行概要

| 項目 | 移行前(Azure OpenAI) | 移行後(ローカルvLLM) |
|---|---|---|
| モデル | GPT-5.4(デプロイメント名で指定) | オープンモデル(Qwen3系 / gpt-oss 等) |
| 推論基盤 | Azureマネージドサービス | vLLM(自社GPU、オンプレ/閉域) |
| API | /v1/chat/completions(OpenAI互換) | 同左(OpenAI互換、SDKのbase_url差し替え) |
| ルーティング/認証 | Azure AD / APIキー + api-version | LiteLLM Proxy(仮想キー、レート制御) |
| コンテンツフィルター | Azure標準搭載(4カテゴリ+Prompt Shields) | 標準機能なし → 自前構築が必要 |
| データの所在 | Azure(閉域構成でも外部送信) | 完全社内(外部送信なし) |
| 品質・速度 | フロンティア級 | 低下前提(許容済み)、タスク別モデル使い分けで補完 |

## 2. API・コード改修点

| No | 対象 | 改修要否 | 内容 |
|---|---|---|---|
| 1 | エンドポイント/認証 | 要 | base_urlをLiteLLM Proxyに変更。api-version廃止。Azure ADキー→仮想キー管理 |
| 2 | model | 要(軽微) | デプロイメント名→モデル名。LiteLLMのエイリアスで吸収可 |
| 3 | messages | 不要 | role構造そのまま。chat templateはvLLMが自動適用 |
| 4 | temperature | 不要(要調整) | 互換。ただし推奨値がモデル依存(例:Qwen3は0.6〜0.7)。temperature=0で劣化するモデルあり |
| 5 | verbosity | 要 | GPT-5系固有で非対応。除去し、システムプロンプト指示に変換(LiteLLM hookで吸収推奨) |
| 6 | reasoning_effort | 要(利用時) | 固有パラメータ。思考モード切替(enable_thinking等)にモデル固有の方法で置換 |
| 7 | max_tokens | 不要 | 両形式受付。新規はmax_completion_tokens推奨 |
| 8 | Structured Outputs | 不要(要検証) | guided decodingで対応。スキーマ通り出るか実データで検証 |
| 9 | Function Calling | 要(設定) | vLLM起動フラグ(--enable-auto-tool-choice、パーサー指定)が必要。安定性はモデル依存 |
| 10 | レスポンス処理 | 要(参照時) | prompt_filter_results / content_filter_results が消滅。finish_reason=content_filterも発生しない |
| 11 | エラー処理 | 要 | Azureの429/Retry-After前提のリトライ設計を、LiteLLM側レート制御に合わせ見直し |
| 12 | usage/コスト計算 | 要(利用時) | トークナイザーが変わるため件数がずれる。見積ロジック再調整 |

## 3. 非機能・インフラの注意点

| No | 項目 | 注意点・対応 |
|---|---|---|
| 1 | 並列実行 | vLLMのContinuous Batchingで同時受付可。max-num-seqs / gpu-memory-utilizationで調整 |
| 2 | 性能特性 | 同時数増でスループット向上・個別レイテンシ悪化。ピーク同時接続を見積りvllm bench serveで実測 |
| 3 | レート制御 | vLLM単体にクォータ機能なし。LiteLLMでrate limit・同時実行制限・タイムアウト設定 |
| 4 | GPUサイジング | モデルVRAM+KVキャッシュ分を確保。量子化(Q4等)の品質影響をタスク別に検証 |
| 5 | 可用性 | Azure SLAの代替として、vLLM複数インスタンス+LiteLLMフェイルオーバー、障害時のAzure退避経路を設計 |
| 6 | モデル調達 | Hugging Face取得はハッシュ検証・safetensorsのみ許可・社内レジストリ管理(サプライチェーン対策) |

## 4. セキュリティ・ガバナンス改修点

| No | 項目 | 対応内容 |
|---|---|---|
| 1 | コンテンツフィルター | ガードモデル(Llama Guard / ShieldGemma等)を別サーブし入出力二段判定。LiteLLM hookに組込 |
| 2 | 日本語判定精度 | 汎用ガードモデルは日本語で精度低下。実際のリスク(PII・目的外利用)に合わせ設計 |
| 3 | PII/顧客情報検出 | 有害判定より優先度高。検出+マスキング層をpre-call hookに実装 |
| 4 | 監査ログ | 入出力全量を改ざん耐性ある形で保存(社内不正利用の統制が自社責任になる) |
| 5 | 規程整合 | FISC安全対策基準・社内AI利用規程とのマッピングを設計書段階で作成 |
| 6 | フィルター互換 | 自前フィルター結果をAzure形式(content_filter_results)で付与するとアプリ互換維持可 |

## 5. 移行の進め方(推奨ステップ)

| フェーズ | 内容 | 完了条件 |
|---|---|---|
| 1. 評価準備 | 実タスクの匿名化ゴールデンデータセット作成(タスク別20〜50件) | Azure出力を正解基準として保存 |
| 2. モデル選定 | 候補モデルをOllama/vLLMでPoC、ベンチ比較 | タスク別採用モデル決定 |
| 3. 互換層構築 | LiteLLMにverbosity変換・フィルター・監査ログ集約 | アプリ無改修で疎通 |
| 4. 並行稼働 | 同一リクエストをAzureとvLLMに並行送信し比較 | 品質・性能が許容範囲と確認 |
| 5. 段階切替 | 機密データ案件からローカルへルーティング切替 | データ分類ルールで自動振り分け稼働 |
| 6. 運用定着 | モデル更新時の再評価パイプライン、GPU監視(Prometheus流用可) | 定期評価が回る体制 |
