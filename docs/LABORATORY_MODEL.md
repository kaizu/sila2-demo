# Laboratory Model

## 概要

`laboratory_model` は、Docker Compose 上の各 SiLA2 サーバーから共有参照される簡易な世界状態サービスである。
**device 中心**の世界を持ち、各 device が固定の **spot**（item が置ける場所）集合と、無解釈の **state**（key-value）を持つ。

## 状態モデル

```
device
 ├─ spots: { <spot>: { occupied, item_id, accessible } }
 └─ state: { <key>: <value> }
```

- **location は常に `device.spot`**（ドットちょうど 1 個）。device 名だけで「その device の唯一の spot」を指す省略形は無い。
  暗黙 spot の特別扱いを作ると、ストア・API・シード・各サーバー・全テストがその例外を理解しなければならなくなるため。
  旧世代の名前（`centrifuge:1`）はドットが無いので**解釈されずに拒否される** — 改名漏れが静かに通らない。
- **トポロジは宣言済み**。どの device が存在し、それぞれどの spot を持つかはシード（`config/laboratory_model.seed.yaml`）が決め、
  実行中に増えない。**宣言されていない device / spot への操作は 404（`unknown_location`）**。
  これは意図した設計で、ワークフローが物理的に存在しない場所へプレートを動かそうとしたとき、
  リクエスト自身がその場所を作ってしまうのではなく、その場で誤りが露見する。
- 1 spot には 0 個または 1 個の item を置ける。`item_id` は `laboratory_model` 内部で `uuid4` により生成する。
- **`accessible` は spot 単位で、モデルが強制する第一級の属性**。`accessible=false` の spot への add / remove / move は拒否される。
  これがこのモジュールが持つ唯一の物理的意味論である。
  複数 spot を覆う lid を持つ device は、**そのサーバーが各 spot を明示的に lock する**ことで表現する
  （「その lid が何を覆うか」の判断は、装置を知っているサーバー側に置く）。
- **`state` は完全に無解釈**。key と value はそのまま保存され、このサービスのどのルールも読まない。
  `lid` / `door` / `up` などは、それを書いたサーバーにとってのみ意味を持つ。値は JSON スカラー（str / int / float / bool / null）に限る。

## API 方針

- item の追加・削除・移動は location ベースで行い、外部から `item_id` は指定しない。
- `add`, `remove`, `move` は、関係する location が `accessible=true` のときだけ成功する。
- `move` は `source` と `destination` の両方が accessible である必要がある。
- **チェック順**: 存在（404）→ accessibility（409）→ occupancy（409）。
  この順序のおかげで、`source_empty` が返ったときは「両端の扉は問題なかった」と信じられる。
- `lock` / `unlock` は spot ごとの access 状態を切り替える。
- `lock` 済みの spot に再度 `lock`、`unlock` 済みの spot に再度 `unlock` してもエラーにはしない。
- HTTP ステータスの意味は **400 = リクエストが不正**、**404 = その場所は存在しない**、**409 = 世界が拒否した**。

### エンドポイント

| エンドポイント | 用途 |
|---|---|
| `GET /health` | liveness |
| `POST /items/add` / `POST /items/move` / `DELETE /items/remove` | item の配置・移動・除去（body は `location` / `source` / `destination`） |
| `POST /locations/lock` / `POST /locations/unlock` | spot 単位の access 切り替え |
| `GET /locations/{location}` | 1 spot の状態（`device` / `spot` / `location` / `occupied` / `item_id` / `accessible`） |
| `GET /state` | 全世界のスナップショット（宣言済み device を全列挙） |
| `GET /devices` | 宣言済み device の一覧 |
| `GET /devices/{device}` | 1 device の state と spots |
| `GET /devices/{device}/state` | 無解釈な state の dict |
| `PUT /devices/{device}/state/{key}` | state の 1 key を設定（body は `{"value": <scalar>}`） |
| `DELETE /devices/{device}/state/{key}` | state の 1 key を外す |
| `POST /reset` / `POST /reseed` | 下記「ライフサイクル」 |

`GET /state` はトポロジが宣言済みなので sparse ではなく全 device を列挙する。`location` を併記するので、
1 文字列で assertion できる。

```json
{"devices": [
  {"device": "thermal-cycler",
   "state": {"lid": "open"},
   "spots": [{"spot": "block", "location": "thermal-cycler.block",
              "occupied": true, "item_id": "...", "accessible": true}]}
]}
```

## 起動時初期状態（シード）

- `LABORATORY_MODEL_SEED_FILE` で YAML のシードファイルを指定する。標準は `config/laboratory_model.seed.yaml` で、
  `docker-compose.yml` から read-only で mount する。未指定なら **device が 1 つも無い世界**で起動し、不正な内容なら起動失敗とする。
- シードは 4 つを 1 ファイルで表す。

```yaml
devices:
  - id: thermal-cycler
    spots: [block]                 # トポロジ（labcode env.yaml と同じリスト形）
    state: { lid: open }           # 無解釈・t=0 の静止状態
    closed_spots: [block]          # 任意。既定は「全 spot が accessible」
boundary:
  inputs:
    plate: { spot: station.slot1 }  # occupancy（labcode boundary.yaml と同じ形）
```

- **`devices` / `boundary` は labcode の `env.yaml` / `boundary.yaml` と同じ形**にしてあるので、
  正常系ではワークフローが信じている世界の忠実な写しになる。**ただしこのファイルはそれらの文書そのものではない** —
  別立てにしてあるのは、**意図的に齟齬を注入できる**ようにするため（ワークフローが期待する spot を reality が持たない、等）。
  二重の世界モデルを走らせる理由そのものがこれである。
- **静止状態（`state`）はシードが持ち、各サーバーが起動時に書き込む方式は採らない**。理由は 2 つ:
  サーバーが書いた値は次の `/reset`・`/reseed` で失われ、誰も戻さない。また起動時に書く設計はサーバーが
  laboratory model の起動完了を待つ必要を生む（compose の `depends_on` は readiness を待たない。現状サーバーは遅延アクセスのみで依存ゼロ）。
- `boundary.inputs` の port に `spot` が無い場合は labcode の Pure Data（物理オブジェクトを持たない値）なので、
  occupancy には寄与せず読み飛ばす。
- 適用順は **item を置いてから spot を閉じる**。`add` は閉じた spot を拒否するので、逆順だと
  「閉じていて、かつ item が入っている」状態が表現できなくなる。

## ライフサイクル（`/reset` と `/reseed` は別物）

| 操作 | 効果 | 主な利用者 |
|---|---|---|
| `POST /reseed` | シードファイルを**ディスクから読み直し** t=0 を再構築（トポロジ＋occupancy＋device state＋closed_spots） | 連続 run。run 間の再シード |
| `POST /reset` | **トポロジは維持**し、全 spot を空・accessible に、device state をクリア | 単体テスト／sample の白紙化 |

`/reset` がトポロジまで消すと全 location が未知になり何も動かなくなる。だから reset は「空の世界」であって「無い世界」ではない。
`/reseed` がファイルを読み直す（起動時のスナップショットを再生するのではない）のは意図的で、run の合間にファイルを編集したら次の reseed でそれが効く。

## サーバー連携

- 各 SiLA2 サーバーは `LABORATORY_MODEL_URL` と `LABORATORY_MODEL_LOCATION` を環境変数で受け取る
  （`docker-compose.yml` の各サービスの `environment:` で設定する。`SILA_SERVER_NAME` / `SILA_SERVER_TYPE` と同じ経路）。
  **`LABORATORY_MODEL_LOCATION` はシードが宣言した spot を指していなければならない**。さもなくばそのサーバーの
  world 呼び出しは `unknown_location` で失敗する。
- 読み取りと検証は共有パッケージ `laboratory-client` の `load_laboratory_model_config()` に集約し、
  各サーバーの `Server.__init__` から呼ぶ。未設定は「world model なしで動かす」正当な構成として許容するが、
  **設定されていて空・前後に空白がある場合は起動時エラー**とする（黙って trim しない）。
- HTTP の機構（URL 組み立て・JSON・タイムアウト・エラー変換）も `laboratory-client` にある。
  **世界の意味づけ（回転にはプレートが要る、開いた扉は到達可能を意味する）は各サーバーに残す** —
  world state の解釈は、それを行うコマンドに属する。
- 以前は各サーバーの `__main__.py` に `--laboratory-model-url` / `--laboratory-model-location` オプションを
  手書きで足し、そこから `os.environ` に書き戻していた。環境変数が実際の経路である点は変わらないため、
  純粋な生成物である `__main__.py` を手で触る必要をなくす形に整理した（`docs/RULES.md`「静的チェック方針」参照）。
- 現在は次のコマンドが laboratory model の item presence を参照する。
  - `MicroplateCentrifugeController.SpinCycle`
  - `PlateLocController.StartCycle`
  - `AutomatedPlateSealRemoverController.Peel`
  - `AutomatedThermalCyclerController.StartRun`
- 現在は次のコマンドが laboratory model の access 状態を更新する。
  - `MicroplateCentrifugeController.OpenDoor` で `unlock`
  - `MicroplateCentrifugeController.CloseDoor` で `lock`
  - `AutomatedThermalCyclerController.OpenLid` で `unlock`
  - `AutomatedThermalCyclerController.CloseLid` で `lock`
- `TrolleyArmProvider.Pick` / `Place` は laboratory model 上の `move` として扱う。
  - `Pick(location)` は `location -> trolley arm 自身の spot`
  - `Place(location)` は `trolley arm 自身の spot -> location`
  - trolley arm サーバー自身は item ID を内部保持しない。
- **labcode との差分（記録）**: labcode は transporter（`arm`）に spots を持たせない（`transporters: [{id: arm}]`）。
  本 repo は搬送中の item が物理的にどこにあるかを表現する必要があるため、**transporter も spot を持つ device として宣言する**
  （`trolley-arm.gripper`）。これは backend 側のモデリング選択である。

## テスト方針

- `samples/laboratory_model_smoke.py` は `laboratory_model` 単体の smoke test である。
- 各 SiLA2 サーバー用の smoke test は、必要な location に item を投入してから対象コマンドを呼ぶ。
- `samples/run_roundabout.py` は laboratory model を初期化にだけ使い、その後の移動は SiLA2 サーバーと trolley arm だけで進める。
- これらの smoke test は `reset` を使って状態を作り直すため、並列実行すると互いに干渉しうる。
- docker 非依存の単体テストは `laboratory_model/tests/` にある（`uv run pytest`）。詳細は `docs/RULES.md`「テスト方針」。

### 既知の先送り

`/reset` は device state もクリアする。将来コマンドが `lid == closed` のような静止状態を前提にするようになったら、
`/reset` 後の sample はその前提を失う。そのときに「`/reset` をシードの device state まで戻す」のか
「sample が明示的に set する」のかを決める。現時点では state に依存するルールが無いので無害。
