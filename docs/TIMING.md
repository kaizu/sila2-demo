# コマンド所要時間と同時実行

## 概要

各モックコマンドが「どれだけ時間をかけるか」を、実装中のリテラルではなく**設定として**持つ仕組み。
目的は、labcode のポーリング周期で `dispatch -> running -> completed` の遷移が観測できる速度で
ラボを動かし、**labcode の見積りと意図的にずらす**ことで replan や running-task margin を実地に叩くこと。

## ファイルと経路

| ファイル | 役割 |
|---|---|
| `config/command_durations.yaml` | **既定プロファイル**。全コマンド 0.05 秒＝設定化する前の挙動そのまま。sample が速いまま保たれる |
| `config/command_durations.realistic.yaml` | 秒〜数十秒。labcode を回すときに使う |
| `tools/slice_durations.py` | ビルド時に device 1 台分を切り出す |
| `tools/tests/test_command_durations.py` | 設定ファイルと実装の齟齬を検出する |

```
config/command_durations.yaml   （ラボ全体・YAML・コメント可）
        │  docker build（builder ステージ）
        ▼
/app/command_durations.json     （その device 1 台分・JSON・イメージに焼き込み）
        │  Server.__init__ が読む
        ▼
Server.sleep_for("OpenDoor")    （各コマンドが自分の名前で引く）
```

- **入力が YAML なのは人が読んで書くため、出力が JSON なのはプログラムしか読まないため。**
  この分担のおかげで **PyYAML は builder ステージだけに入り、5 つのランタイムイメージには増えません**。
- **焼き込みなので、値を変えるにはリビルドが必要**です（マウントではありません）。
- プロファイルの切り替えは build arg 1 つ:

```bash
DURATIONS_FILE=command_durations.realistic.yaml docker compose build
docker compose up -d --force-recreate
```

> `docker compose up -d --build` はソース変更を反映しないことがあります。確実に入れ替えるには
> `docker compose build` と `--force-recreate` を明示してください。

## 書式

```yaml
devices:
  centrifuge:
    commands:
      SpinCycle: { duration: 20 }
      OpenDoor:  { duration: 3 }
```

- device 名は `laboratory_model.seed.yaml` と一致させる。コマンド名は feature 接頭辞を除いた素の SiLA2 コマンド名。
- **各コマンドの値をスカラーではなく mapping にしてある**のは、将来 jitter のような設定を
  `{ duration: 3, jitter: 0.15 }` と**足すだけ**にするため。スカラー略記も許すと、両形式を受けるパーサを
  恒久的に抱えることになる。device 単位の設定は `commands:` の隣に置ける。
- **切り出しスクリプトは知らないキーをそのまま通す**ので、ラボ全体のファイルに設定を足せば
  スクリプトを教育しなくてもサーバーまで届く。

## 既定は「待たない」— これは罠でもある

**ファイルに記述が無いコマンドは一切待ちません。** device のキーが無ければそのサーバーの全コマンドが待ちません。

これは意図した既定ですが、同時に危険でもあります。**待たないコマンドは Running の窓が潰れるので、
ポーリングするクライアントから Status 遷移が観測できなくなります。**「書き忘れ」が静かに効きます。

そのため **`tools/tests/test_command_durations.py` が実装（AST）を読んで、両プロファイルと
コードの齟齬を双方向に検出します**。
- 待つのに未記述 → 失敗（観測性を失う）
- 記述があるのに待たない → 失敗（コマンド名の typo・不要になった項目）

コマンドを追加・変更したら、この 2 つのファイルも更新してください。テストが教えてくれます。

## 同時実行ガード

長い所要時間により、1 サーバーに 2 つのコマンドが重なることが現実的になります。モックの内部状態
（protocol loaded / validated、開いている bucket など）はロック無しの素の属性なので、重なると静かに壊れます。

そこで **`Server.executing()` が 1 コマンドの実行中はサーバーを占有し、後から来たコマンドを拒否します**。

```
CloseDoor cannot start because OpenDoor is still executing on this server
```

**判定は「コマンドが実行中か」であって Status ではありません。** ここが重要な点です。`StartRun` は
契約上 `StopRun` まで Status を Running のまま残すので、**Status で判定すると、その run を終わらせるための
コマンドが必ず拒否されます**。

- ガードは `_one_at_a_time` デコレータで各コマンドに付ける（本体を `with` で囲まない。
  sila2 は実装メソッドのシグネチャを検査せずに呼ぶので安全）。
- **`Stop*` コマンドには付けない。** 止めるためのコマンドを、止めたい対象の完了まで待たせるのは本末転倒。
  なお現状のモックでは stop が実行中コマンドを実際に中断することはできない（別の制限であり、ガードとは無関係）。
- `TrolleyArmProvider.SetTrolleyPosition` は**これとは別に** Status ベースのガードを持っている
  （Idle 以外では実行できない）。こちらは feature 固有の規則で、上記の同時実行ガードとは目的が違う。

## 観測可能コマンドのエラーは poll しないと見えない

ガードの拒否は**呼び出し時ではなく、コマンドインスタンスを poll したときに現れます**。
observable command の呼び出しはインスタンスを即座に返すので、`instance.get_responses()` まで
到達しないと `UndefinedExecutionError` は観測できません。手で確認するときの落とし穴です。

## realistic プロファイルを使うときの注意

`samples/common.py` の `DEFAULT_TIMEOUT_SECONDS` は 10 秒で、realistic の一部コマンドはこれを超えます。

```bash
uv run python samples/run_all_smoke_tests.py --timeout 120
```

既定プロファイルでは 10 秒のままで十分です（全コマンド 0.05 秒なので、ハングを速く失敗として報告できる）。

## 未実装・先送り

- **jitter（ランダムなぶれ）は入っていません。** 書式は上記のとおり受け入れる準備ができています。
- **`TrolleyArmProvider.Pick` / `Place` には所要時間がありません**（現在そもそも待たない）。
  搬送時間は搬送のマイルストーンで扱います。両プロファイルに記述が無いのは意図的です。
- **station には時間を要するコマンドがありません。** 切り出したファイルは空（`{"commands": {}}`）で焼かれ、
  サーバー側は読みません。将来コマンドが増えたら設定と読み取りを足すだけで済みます。
