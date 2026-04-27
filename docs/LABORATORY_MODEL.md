# Laboratory Model

## 概要

`laboratory_model` は、Docker Compose 上の各 SiLA2 サーバーから共有参照される簡易な世界状態サービスである。初期実装では、場所ごとの item の有無と、場所がアクセス可能かどうかだけを管理する。

## 状態モデル

- location は文字列で表す。
- 1 location には 0 個または 1 個の item を置ける。
- item の `item_id` は `laboratory_model` 内部で `uuid4` により生成する。
- 各 location は `accessible: bool` を持ち、`true` のときだけその場所への操作を許可する。
- location が未登録の場合、既定値は `occupied: false` かつ `accessible: true` とする。

## API 方針

- item の追加・削除・移動は location ベースで行い、外部から `item_id` は指定しない。
- `add`, `remove`, `move` は、関係する location が `accessible=true` のときだけ成功する。
- `move` は `source` と `destination` の両方が accessible である必要がある。
- `lock` / `unlock` は location ごとの access 状態を切り替える。
- `lock` 済みの location に再度 `lock`、`unlock` 済みの location に再度 `unlock` してもエラーにはしない。

## 起動時初期状態

- `LABORATORY_MODEL_INITIAL_STATE_FILE` を指定すると、起動時に JSON ファイルから初期状態を読み込む。
- 初期状態ファイルは `config/laboratory_model.initial_state.json` を標準とし、`docker-compose.yml` から mount する。
- JSON では `location` を必須とし、`occupied` の既定値は `false`、`accessible` の既定値は `true` とする。
- `occupied: true` の場合、起動時に内部で item を生成する。
- 初期状態ファイルが未指定なら空状態で起動し、不正な内容なら起動失敗とする。

## サーバー連携

- 各 SiLA2 サーバーは `--laboratory-model-url` と `--laboratory-model-location` をオプションで受け取る。
- 対応する値は `LABORATORY_MODEL_URL` と `LABORATORY_MODEL_LOCATION` に反映し、`Server` 実装から参照する。
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
  - `Pick(location)` は `location -> trolley arm 自身の location`
  - `Place(location)` は `trolley arm 自身の location -> location`
  - trolley arm サーバー自身は item ID を内部保持しない。

## テスト方針

- `samples/laboratory_model_smoke.py` は `laboratory_model` 単体の smoke test である。
- 各 SiLA2 サーバー用の smoke test は、必要な location に item を投入してから対象コマンドを呼ぶ。
- `samples/run_roundabout.py` は laboratory model を初期化にだけ使い、その後の移動は SiLA2 サーバーと trolley arm だけで進める。
- これらの smoke test は `reset` を使って状態を作り直すため、並列実行すると互いに干渉しうる。
