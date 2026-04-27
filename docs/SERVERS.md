# サーバー実装メモ

## 概要

`servers/` 配下の各 SiLA2 サーバーは、生成コードを土台にした最小限の feature 実装を持つ。現在の実装は、実機制御そのものよりも、SiLA2 経由の接続確認、コマンド実行、状態遷移確認をしやすくするためのモック寄りの構成である。

## 直接確認用スクリプト

- `samples/` 配下に、各サーバーへ `sila-python` で直接接続する smoke test スクリプトを配置している。
- `samples/run_all_smoke_tests.py` を実行すると、各サーバーの代表的なコマンドを順に呼び出して疎通確認できる。
- この確認では FastAPI は使用しない。

## 実装上の前提

- observable command の終了処理は `sila2` 側の manager に任せる前提とし、feature 実装側で `instance.complete()` は呼ばない。
- PlateLoc の sealing temperature や cycle count などは内部状態として保持し、getter 経由で参照する。
- Automated Thermal Cycler の `StartRun` 実行後は、`StopRun` が呼ばれるまで running 状態を維持する。
- Trolley Arm には `Pick` / `Place` を追加しており、laboratory model 上の item を自サーバー location 経由で移動させる。
  - `Pick` は指定場所から trolley arm の location へ移す。
  - `Place` は trolley arm の location から指定場所へ移す。
  - 保持中 item を表す独自の内部変数は持たない。

## ログ方針

- 各サーバーの feature 実装では、コマンド入口で `logging` を使った `INFO` ログを出す。
- 引数を持つコマンドは、確認に必要な主要パラメータをログへ含める。
- Docker Compose では各サーバーを `--verbose` 付きで起動し、これらの `INFO` ログが確認できるようにする。

## 統合確認

- `samples/run_roundabout.py` では、`station:1` の item を trolley arm で `seal-remover -> plateloc -> thermal-cycler -> centrifuge -> station:1` と順に移動させる。
- 初期状態の投入と最終状態の確認には laboratory model を使うが、装置間の移動そのものは FastAPI を介さず SiLA2 サーバーを直接呼び出して行う。
