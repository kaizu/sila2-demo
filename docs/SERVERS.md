# サーバー実装メモ

## 概要

`servers/` 配下の各 SiLA2 サーバーは、生成コードを土台にした最小限の feature 実装を持つ。実機制御そのものよりも、
**実機と同一の Feature 定義を保ったまま**、SiLA2 経由の接続・コマンド実行・状態遷移を確認しやすくすることを狙う。

**`specs/` の Feature XML は編集しない。** 実機と同一でなければ drop-in 置換テストにならないため、
多 spot 化などの改修もコマンド署名と Feature を変えずサーバー内部で行う。

## Ardea サーバー（実在機器のモック）

`servers/ardea_server/` は**実在する機器 Ardea のモック**であり、他の 5 台とは性格が違う。実機の
`ardea-sila2` は DENSO ロボット（ORiN b-CAP）と KEYENCE PLC（KV COM+）を同時に駆動し、
**Feature を 9 本公開する**。モックもその 9 本を配信する。

| Feature | 出自 | モックの実装 |
|---|---|---|
| `LabwareService` | Ardea 固有 | **`Transfer` を実装**。`LightIsOn` を実装。他 5 コマンドは未実装 |
| `CarriageService` | Ardea 固有 | `StationNames` / `CarriagePosition` を実装。`MoveCarriage` は未実装 |
| `RobotPoseService` | Ardea 固有 | 全 4 コマンド未実装 |
| `RobotOrientationService` | Ardea 固有 | 全 2 コマンド未実装 |
| `VariableService` / `TaskService` / `RobotService` | `bcap-sila2`（b-CAP プロバイダ） | 全コマンド未実装 |
| `DeviceService` / `ConnectionService` | `kvcomplus-sila2`（KV COM+ プロバイダ） | 全コマンド未実装 |

**Feature 定義の 2 つのコピー。** `specs/ardea_server/` にあるのは**ソース** XML（実機リポジトリからの
コピー・読むためのもの）。実際に配信されるのは `servers/ardea_server/ardea_server/generated/<feature>/`
にある codegen 正規化版で、これも実機の生成物からコピーしたものなので**実機が配信するバイト列と同一**である。
両者が同じ Feature を表しているかは `servers/ardea_server/tests/test_feature_definitions.py` が検査する。
**生成コードは再生成せずコピーする**（それが同一性を構造的に保証する唯一の方法）。出典と手順は
`specs/ardea_server/README.md`。

**未実装コマンドは `NotImplementedError`** を投げる。クライアントには
`UndefinedExecutionError: Method is not implemented by the server` が届く（**この文言は sila2 が用意するもので、
実装側のメッセージは破棄される**）。理由の説明はサーバーログに `INFO` で出るので、
`docker compose logs ardea-server-1` で読む。declared error を新設しないのは、そのために Feature XML を
編集すれば drop-in 置換が壊れるからである。
実装しないのは手抜きではなく方針で、これらのコマンドは世界モデルに対応物の無いハードウェアを動かすもの
（アーム姿勢・PLC アドレス・PacScript のタスク名）であり、成功したふりをすればワークフローが
**このラボでは通るが実機では通らない**依存を持ってしまう。「実装済みは Transfer だけ」を保つ検査は
上記の単体テストに入っている。

**実装する 3 プロパティの導出**（世界モデルに素直に対応するものだけを実装した）:

| プロパティ | 導出 |
|---|---|
| `CarriageService.StationNames` | `GET /state` の全 `device.spot` から arm 自身の spot（`ardea.gripper`）を除いてソート。**`Transfer` が受け付ける名前と完全に一致する**。実機は motion 設定から読む |
| `CarriageService.CarriagePosition` | 合成レール位置 = 上記リスト内の index × 100 mm。**実機の座標ではない**。目的は「動かない間は安定し、動けば変わる」という観測可能性で、`Transfer` が到達のたびに publish する |
| `LabwareService.LightIsOn` | `ardea` device の opaque state の `light` キー（`GET /devices/ardea/state`）。実機ではロボットコントローラの変数なので世界モデルに対応物が無く、seed が宣言し運用者が `PUT /devices/ardea/state/light` で変える |

**station 名は暫定で `device.spot` そのもの。** 実機の station 名は motion 設定由来（`Base2`..`Base5` 等）
なので、この点だけは実機とモックでワークフローの引数が違う。**次段で mock 専用の station マップを入れる**
予定であり、そのとき `StationNames` / `CarriagePosition` / `InvalidStation` はその設定を読む形に変わる。

**世界モデルの失敗は declared error に分かれない。** 未宣言 location・item 不在・扉が閉じている、は
どれも undefined execution error として届く（実機なら `NoStationAtPosition` / `GraspFailed` 等に分かれる）。
`laboratory-client` がエラーコードを機械可読な形で返さないため。既知のギャップである。

## 世界モデルとの連携

- 各サーバーが作用する location は **`LABORATORY_MODEL_LOCATION`（`device.spot` 形式）で環境変数から**受け取る。
  **シードが宣言した spot でなければならない**（未宣言なら `unknown_location` / 404 で失敗する）。
- HTTP アクセス（URL 組み立て・JSON・タイムアウト・エラー変換）と設定の読み取りは共有パッケージ
  `laboratory-client` に集約する。**ただし世界の意味づけ**（回転にはプレートが要る、開いた扉は到達可能を意味する）
  **は各サーバーの実装に残す** — world state の解釈は、それを行うコマンドに属する。
- 現在 item の存在を前提とするコマンド: `SpinCycle` / `StartCycle` / `Peel` / `StartRun`。
- 現在 access 状態を更新するコマンド: centrifuge の `OpenDoor` / `CloseDoor`、thermal cycler の `OpenLid` / `CloseLid`。
- `LabwareService.Transfer`（Ardea）は世界モデル上の **2 hop の `move`** として扱う。
  - source から arm の spot（`ardea.gripper`）へ、続いて arm の spot から destination へ。
  - 保持中 item を表す独自の内部変数は持たない。搬送中のプレートが arm 上にあるのは実機でも実際の状態である。
  - **実機は 1 コマンドで経路全体を走る**（carriage を source へ → pick → destination へ → put）ので、
    モックも 1 コマンドで両 hop を行う。旧 trolley arm の `Pick` + `Place` の 2 呼び出しは無くなった。

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
| `Status` プロパティ（**Ardea 以外の 5 台**） | 0=Not Connected, 1=Idle, 2=Running, 3=Error |
| `InstrumentState`（thermal cycler の `GetInstrumentState` 応答のみ） | 0=IDLE, 1=STANDBY, 2=RUNNING, 3=ERROR, 4=DIAGNOSTICS |

**Ardea の Feature には `Status` プロパティが無い**（実機の Feature 定義にそもそも無く、編集もしない）。
進捗は `Transfer` の intermediate response と `progress` で報告する。Idle/Running のブラケットは持たない。

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
- `LabwareService.Transfer` は intermediate response で phase を報告する。所要時間を phase 数で等分し、
  1 phase ごとに待つので、ポーリングするクライアントには経路の進行が見える。
  **`progress` も phase 単位で更新する**（最後の phase で 1.0 になる）。

## ログ方針

- feature 実装はコマンド入口で `logging` の `INFO` ログを出す。
- 引数を持つコマンドは、確認に必要な主要パラメータをログへ含める。
- Docker Compose では各サーバーを `--verbose` 付きで起動し、これらの `INFO` ログが見えるようにする。

## 確認方法

- `samples/` に各サーバーへ直接接続する確認スクリプトを置く。`samples/run_all_smoke_tests.py` が 6 台分を束ねる。
- `samples/run_roundabout.py` は `station.slot1` の item を Ardea で
  `seal-remover.stage -> plateloc.stage -> thermal-cycler.block -> centrifuge.deck -> station.slot1` と一周させる。
  1 区間 = `Transfer` 1 回。初期化と最終確認には世界モデルを使うが、装置間の移動そのものは SiLA2 サーバーを
  直接呼び出して行う。
- `samples/ardea_server_smoke.py` は Transfer に加えて**未実装コマンドが即座に拒否されること**も確認する
  （`MoveCarriage`）。無応答で待たされるのではなくエラーで返るのが仕様である。
- 手順は `docs/OPERATIONS.md`。
