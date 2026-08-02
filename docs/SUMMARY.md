# プロジェクト概要

このプロジェクトは、SiLA2 ベースの機器サーバー群と、それらが共有する世界状態サービス `laboratory_model` をまとめたリポジトリである。

`servers/` には、Station、Trolley Arm、Microplate Centrifuge、PlateLoc、Automated Plate Seal Remover、Automated Thermal Cycler などの SiLA2 サーバーパッケージがあり、各サーバーは生成コードと最小限の feature 実装を持つ。

ローカル実行の基本形は `docker-compose.yml` にまとまっており、複数の SiLA2 サーバーと `laboratory_model` をまとめて起動できる。

`laboratory_model/` には、Docker Compose 上で共有される簡易な世界状態サービスがある。**device 中心**の世界を持ち、各 device が固定の spot 集合（item の有無と access 状態）と、無解釈の state（key-value）を持つ。location は常に `device.spot` で、**トポロジはシードが宣言し、未宣言の場所への操作は 404 になる**。シードの形式や各サーバーとの連携方針は `docs/LABORATORY_MODEL.md` に整理する。

`laboratory-client/` には、各 SiLA2 サーバーが laboratory model に到達するための共有パッケージ（HTTP 転送層と環境変数からの設定読み取り）がある。世界の意味づけは共有せず、各サーバーの実装に残す。

`specs/` には各サーバーの SiLA 定義 XML があり、`external/` には直接の開発対象ではない参考用の外部実装や依存ライブラリのソースコードが配置されている。

`samples/` には、`sila-python` で各 SiLA2 サーバーへ直接接続して動作確認するための Python スクリプトを置く。単体の smoke test に加えて、`samples/run_roundabout.py` では `station.slot1` から各装置を一周して再び `station.slot1` へ戻す統合確認を行う。

各モックコマンドの所要時間は実装中のリテラルではなく設定として持ち、`config/command_durations.yaml` に
ラボ全体を記述してビルド時に device ごとに切り出してイメージへ焼き込む。既定プロファイルは従来どおりの
0.05 秒、realistic プロファイルは labcode のポーリング周期で遷移が観測できる秒〜数十秒。同時実行ガードと
あわせて `docs/TIMING.md` に整理する。

現在の Docker Compose 設定では、各 SiLA2 サーバーは `--verbose` 付きで起動し、コマンド呼び出し時の `INFO` ログを `docker compose logs` で確認できる。
