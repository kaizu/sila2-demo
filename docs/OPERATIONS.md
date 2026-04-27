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

正常時は `fastapi` と SiLA2 サーバー群が `Up` になる。

次に、FastAPI のヘルスチェックを確認する。

```bash
curl -sS http://localhost:8000/health
```

正常時の応答:

```json
{"status":"healthy"}
```

続いて、FastAPI 経由で SiLA2 サーバー探索を行う。

```bash
curl -sS "http://localhost:8000/sila/discover?timeout=1&insecure=true"
```

正常時は、検出されたサーバー一覧と `count` が返る。

## 直接接続の確認

FastAPI を使わず、`sila-python` で各 SiLA2 サーバーへ直接接続する確認スクリプトは `samples/` 配下に置く。

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

- FastAPI コンテナ経由で `/sila/reset` や `/sila/trolley-position` を呼ぶ場合、`127.0.0.1` は FastAPI コンテナ自身を指す。
- FastAPI から他の SiLA2 サーバーへ接続するには、`/sila/discover` で得られるコンテナ内 IP アドレスと内部ポート `50052` を使う。
- ホスト側の公開ポート `50053` から `50057` は、ホストマシンから直接アクセスするためのものであり、FastAPI コンテナ内部からそのまま使う前提ではない。
