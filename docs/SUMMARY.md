# プロジェクト概要

このプロジェクトは、SiLA2 ベースの機器サーバー群と、それらを補助的に操作・探索する FastAPI アプリケーションをまとめたリポジトリである。

`servers/` には、Station、Trolley Arm、Microplate Centrifuge、PlateLoc、Automated Plate Seal Remover、Automated Thermal Cycler などの SiLA2 サーバーパッケージがあり、各サーバーは生成コードと最小限の feature 実装を持つ。

`fastapi_app/` には、ヘルスチェック、SiLA2 サーバー探索、Reset 実行、feature 定義取得、Trolley position の取得・設定を行う API がある。ローカル実行の基本形は `docker-compose.yml` にまとまっており、複数の SiLA2 サーバーと FastAPI をまとめて起動できる。

`laboratory_model/` には、Docker Compose 上で共有される簡易な世界状態サービスがあり、場所ごとの item の有無と access 状態を管理する。起動時初期状態や各サーバーとの連携方針は `docs/LABORATORY_MODEL.md` に整理する。

`specs/` には各サーバーの SiLA 定義 XML があり、`external/` には直接の開発対象ではない参考用の外部実装や依存ライブラリのソースコードが配置されている。

`samples/` には、FastAPI を介さず `sila-python` で各 SiLA2 サーバーへ直接接続して動作確認するための Python スクリプトを置く。単体の smoke test に加えて、`samples/run_roundabout.py` では `station:1` から各装置を一周して再び `station:1` へ戻す統合確認を行う。

現在の Docker Compose 設定では、各 SiLA2 サーバーは `--verbose` 付きで起動し、コマンド呼び出し時の `INFO` ログを `docker compose logs` で確認できる。
