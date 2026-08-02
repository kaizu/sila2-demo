# サーバー実装メモ

## 概要

`servers/` 配下の各 SiLA2 サーバーは、生成コードを土台にした最小限の feature 実装を持つ。実機制御そのものよりも、
**実機と同一の Feature 定義を保ったまま**、SiLA2 経由の接続・コマンド実行・状態遷移を確認しやすくすることを狙う。

**`specs/` の Feature XML は編集しない。** 実機と同一でなければ drop-in 置換テストにならないため、
多 spot 化などの改修もコマンド署名と Feature を変えずサーバー内部で行う。

## 世界モデルとの連携

- 各サーバーが作用する location は **`LABORATORY_MODEL_LOCATION`（`device.spot` 形式）で環境変数から**受け取る。
  **シードが宣言した spot でなければならない**（未宣言なら `unknown_location` / 404 で失敗する）。
- HTTP アクセス（URL 組み立て・JSON・タイムアウト・エラー変換）と設定の読み取りは共有パッケージ
  `laboratory-client` に集約する。**ただし世界の意味づけ**（回転にはプレートが要る、開いた扉は到達可能を意味する）
  **は各サーバーの実装に残す** — world state の解釈は、それを行うコマンドに属する。
- 現在 item の存在を前提とするコマンド: `SpinCycle` / `StartCycle` / `Peel` / `StartRun`。
- 現在 access 状態を更新するコマンド: centrifuge の `OpenDoor` / `CloseDoor`、thermal cycler の `OpenLid` / `CloseLid`。
- `TrolleyArmProvider.Pick` / `Place` は世界モデル上の `move` として扱う。
  - `Pick` は指定場所から arm の spot（`trolley-arm.gripper`）へ、`Place` はその逆。
  - 保持中 item を表す独自の内部変数は持たない。

## コマンド所要時間と同時実行

- 各コマンドの待ち時間は `Server.sleep_for(<コマンド名>)` で引く。値はビルド時にイメージへ焼き込まれた
  `/app/command_durations.json`（ラボ全体の `config/command_durations.yaml` から切り出したもの）にある。
  **記述が無いコマンドは待たない。**
- **1 サーバーで 2 つのコマンドが同時に実行されることは `Server.executing()` が拒否する**
  （`_one_at_a_time` デコレータ）。判定は Status ではなく「実行中か」で行う。`Stop*` には付けない。
- 詳細と理由は `docs/TIMING.md`。

## Status の扱い

**2 つの異なる enum があるので混同しない。**

| | 値 |
|---|---|
| `Status` プロパティ（全機器共通） | 0=Not Connected, 1=Idle, 2=Running, 3=Error |
| `InstrumentState`（thermal cycler の `GetInstrumentState` 応答のみ） | 0=IDLE, 1=STANDBY, 2=RUNNING, 3=ERROR, 4=DIAGNOSTICS |

各コマンドの遷移は **Feature XML の記述が契約**である。

- actuating コマンドは実行中 Running、正常終了で Idle、失敗で Error。
- read / set / stop / reset は開始時の status を維持する。
- **thermal cycler の `OpenLid` / `CloseLid` は Idle を維持する**（同系の centrifuge の `OpenDoor` / `CloseDoor` は
  Running になる）。これは XML 側の意図的な feature 固有の例外であり、モックのバグではない。
- `StartRun` は Running にしたまま返り、`StopRun` まで Running が続く。
- station は起動時 Error(3) を意図的に維持する（デバッグ用途）。

## その他の実装上の前提

- observable command の終了処理は `sila2` 側の manager に任せ、feature 実装で `instance.complete()` は呼ばない。
- PlateLoc の sealing temperature や cycle count などは内部状態として保持し、getter 経由で参照する。
- `TrolleyArmProvider.SetTrolleyPosition` は Idle 以外では実行できない（Status ベースのガード）。
  上記の同時実行ガードとは目的が別なので、両方が存在する。

## ログ方針

- feature 実装はコマンド入口で `logging` の `INFO` ログを出す。
- 引数を持つコマンドは、確認に必要な主要パラメータをログへ含める。
- Docker Compose では各サーバーを `--verbose` 付きで起動し、これらの `INFO` ログが見えるようにする。

## 確認方法

- `samples/` に各サーバーへ直接接続する確認スクリプトを置く。`samples/run_all_smoke_tests.py` が 6 台分を束ねる。
- `samples/run_roundabout.py` は `station.slot1` の item を trolley arm で
  `seal-remover.stage -> plateloc.stage -> thermal-cycler.block -> centrifuge.deck -> station.slot1` と一周させる。
  初期化と最終確認には世界モデルを使うが、装置間の移動そのものは SiLA2 サーバーを直接呼び出して行う。
- 手順は `docs/OPERATIONS.md`。
