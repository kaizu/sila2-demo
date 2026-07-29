# 運用手順

## 起動

プロジェクトルートで以下を実行する。

```bash
docker compose up -d
```

イメージの再ビルドも必要な場合は以下を使う。

```bash
docker compose up --build -d
```

現在の `docker-compose.yml` では、各 SiLA2 サーバーは `--verbose` 付きで起動する。

## 停止

```bash
docker compose down
```

## 起動確認

まず、コンテナが起動していることを確認する。

```bash
docker compose ps
```

正常時は `laboratory-model` と SiLA2 サーバー群が `Up` になる。

次に、`laboratory_model` のヘルスチェックを確認する。

```bash
curl -sS http://localhost:8001/health
```

正常時の応答:

```json
{"status":"healthy"}
```

SiLA2 サーバー群への疎通は、下記「直接接続の確認」の smoke スクリプトで行う。

## 直接接続の確認

`sila-python` で各 SiLA2 サーバーへ直接接続する確認スクリプトは `samples/` 配下に置く。

全件実行:

```bash
uv run python samples/run_all_smoke_tests.py
```

正常時は `All smoke tests passed.` と表示される。

## ログ確認

SiLA2 サーバー側の `INFO` ログを確認するには以下を使う。

```bash
docker compose logs --tail=200 sila2-server-1 sila2-server-2 sila2-server-3 sila2-server-4 sila2-server-5 trolley-arm-server-1
```

samples 実行後は、各サーバーの feature 実装からコマンド呼び出しを示す `INFO` ログが出る。たとえば `Reset called` や `StartRun called` のようなメッセージを確認できる。

## 注意事項

- ホスト側からは、公開ポート `50052`〜`50057` で各 SiLA2 サーバーへ、`8001` で `laboratory_model` へ直接アクセスする。
- Docker Compose ネットワーク内でコンテナ間接続する場合は、各サービスのコンテナ名と内部ポート `50052`（SiLA2 サーバー）／`8001`（laboratory-model）を使う。ホスト側の公開ポート `50053`〜`50057` はホストマシンからの直接アクセス用であり、コンテナ内部からそのまま使う前提ではない。
