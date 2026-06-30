# architecture.md

ジムカーナ計測アプリ（RayTrigger）のファイル構成と依存関係のルール。
アプリ自体の機能・セットアップ手順は[README.md](README.md)を参照。

## 処理の流れ（main.pyが何をしているか）

`main.py`の`main()`がアプリ全体を起動・結線するエントリーポイントで、概ね以下の順で進む。

1. **起動**：`config.json`を読み、`build_driver()`で実機（`sensor.ydci_driver.YdciDriver`）への接続を試みる。失敗時は自動的に`sensor.mock_driver.MockDriver`にフォールバックする。
2. **Sheets接続・セッション開始**：`sheets.manager.build_client()`でGoogle認証し、`sheets.manager.start_session()`で大会セッションを開始する。再接続確認・フォーマット選択・大会名入力のダイアログは`ui.session_dialogs.prompt_session_start`がコールバックとして渡され、そこで表示される。失敗（認証ファイル無し・ネット不通等）してもローカル保存のみで起動を継続する。
3. **画面表示**：`ui.main_window.MainWindow`を生成し、センサー監視スレッド（`sensor.monitor.SensorMonitor`）を開始する。ゼッケン自動入力が有効な場合は`serial_input.bib_source.SerialBibSource`（ESP32からのUSBシリアル受信）も同様にバックグラウンドスレッドで開始する。
4. **計測中**：センサーがSTART/GOALを検知すると`main.py`内の`PendingResultQueue`に積まれ、画面に確認パネルが表示される。操作者がPT・脱輪件数を入力して確定（または自動確定）すると、`save_and_upload()`が呼ばれる。ゼッケン自動入力モードがONの場合、STARTを検知した瞬間に`SerialBibSource`が保持している直近の確定値（iPhone側で安定化判定済みのゼッケン候補）がその枠のゼッケン欄へ自動入力され、画面表示とブザーで操作者に通知される。確定（最終確認）は通常通りGOAL確認パネルで行う。
5. **保存・送信**：`save_and_upload()`はまず`storage.local_store.LocalStore`へ同期で保存し（ここで失われない）、続いて`storage.csv_mirror`でローカルCSVミラーを更新する。その後`_submit_record_to_sheets()`がバックグラウンドスレッドで`sheets.uploader.write_result()`を呼び、Googleスプレッドシートへ書き込む。
6. **送信失敗時の復旧**：Sheets書き込みが失敗してもローカルDBには残っており、`sync_pending_records()`（「未送信を同期」ボタン）で未送信レコードだけをまとめて再送できる。`sheets_client`が起動時に確立できていなかった場合は、このボタンが`connect_sheets()`を再実行して接続からやり直す。

## プロジェクト構造

```
gymkhana/
├── main.py                      エントリーポイント（起動・各層の結線）
├── version.py                   アプリ名・バージョン定数
├── common/                      共通層（ハブ。他のどの層にも依存しない）
│   ├── paths.py                 exe実行時/ソース実行時のパス解決
│   ├── sheet_schema.py          スプレッドシートの列構成・シート名の定義
│   └── time_format.py           タイム文字列⇄秒数の変換、DNF/MCセンチネル値
├── sensor/                      センサー層（完全に独立）
│   ├── driver_base.py           共通インターフェース（SensorDriverBase）
│   ├── mock_driver.py           モックドライバ
│   ├── ydci_driver.py           実機（YDCI.DLL）ドライバ
│   └── monitor.py               センサー監視スレッド
├── ocr/                         OCRゼッケン認識層（完全に独立／現在は本番運用では無効化）
│   ├── engine_base.py           共通インターフェース（OcrEngineBase）
│   ├── mock_engine.py           モックエンジン（テスト用エミュレーター）
│   ├── tesseract_engine.py      Tesseract＋OpenCVによる実エンジン
│   ├── camera_capture.py        カメラ映像の継続取得スレッド
│   └── bib_reader.py            認識結果の安定化（ロック）・取得
├── serial_input/                ゼッケン受信層（完全に独立。iPhone+ESP32方式の入口）
│   └── bib_source.py            ESP32からのUSBシリアル受信・確定値の保持（SerialBibSource）
├── timer/                       計時ロジック層（完全に独立）
│   ├── lap_timer.py             タイム計測の状態機械
│   ├── run_manager.py           枠A/枠Bの出走管理
│   └── waiting_list.py          待機リスト
├── storage/                     ローカル保存層（timerにのみ依存可）
│   ├── local_store.py           SQLiteへの記録保存
│   └── csv_mirror.py            ローカルCSVへの自動書き出し
├── sheets/                      Googleスプレッドシート連携層
│   ├── manager.py                セッション管理（大会の開始/再接続）
│   ├── uploader.py              Sheetsへのタイム書き込み
│   └── template_setup.py        テンプレートスプレッドシートの新規構築
├── ui/                          画面層（Tkinter）
│   ├── main_window.py           メインウィンドウ
│   └── session_dialogs.py       大会開始時のダイアログ（再接続確認等）
└── tests/                       番犬テスト（pytest）
```

## 依存関係のルール

依存方向は **上ほど上位・具体的、下ほど基盤的**：

```
main（エントリーポイント。全層を結線してよい）
  └─ ui ─┐
  └─ sheets ─┤
  └─ storage ┤→ timer
  └─ sensor ─┤
  └─ ocr ────┤
  └─ serial_input ┘
       └─ common（最も基盤。誰からも参照されるが、何も参照しない）
```

`.importlinter`（import-linterの設定）でこれを自動チェックしている。実行コマンド：

```
lint-imports
```

### 許可されている依存

| From | To | 備考 |
|---|---|---|
| `main` | すべて | エントリーポイントなので全層を結線してよい |
| `ui` | `sensor`, `storage`, `timer`, `common`, `version` | `sensor.mock_driver.MockDriver`への直接参照は例外的に許可（後述） |
| `sheets` | `storage`, `common` | |
| `storage` | `timer`, `common` | |
| `sensor` | `common` | |
| `ocr` | `common` | |
| `serial_input` | `common` | |
| `timer` | `common` | |
| すべての層 | `common` | `common`は依存される専用のハブ |

### 禁止されている依存（import-linterで強制）

- `storage` → `sheets` / `ui` / `sensor` / `ocr`
- `sensor` → `sheets` / `storage` / `ui` / `timer` / `ocr`
- `ocr` → `sheets` / `storage` / `ui` / `timer` / `sensor`
- `serial_input` → `sheets` / `storage` / `ui` / `timer` / `sensor` / `ocr`
- `timer` → `sheets` / `storage` / `ui` / `sensor` / `ocr`
- `sheets` → `ui`
- `ui` → `sheets`
- `common` → `sheets` / `storage` / `ui` / `sensor` / `timer` / `ocr` / `serial_input`

## 各レイヤーの責務

- **common**: どの層からも参照される定数・ヘルパーのみを置く。パス解決（`paths.py`）、スプレッドシートの列構成（`sheet_schema.py`）、タイム表示変換（`time_format.py`）。**ロジックを持つビジネス機能は置かない**。
- **sensor**: 光電管（YDCI.DLL）またはモックからのセンサー入力検知。`SensorDriverBase`が共通インターフェース。
- **ocr**: 固定カメラ映像からのゼッケン番号（OCR）認識。`OcrEngineBase`が共通インターフェースで、`TesseractOcrEngine`（実エンジン）・`MockOcrEngine`（テスト用エミュレーター）を差し替え可能。`BibReader`が「停止中に安定して読み取れた値」をロックして保持し、次の車の認識が安定するまで上書きしない（START発火の瞬間のブレた値を拾わないため）。**現在は本番運用では`serial_input`層に置き換えられて無効化されているが、コードは保持している（config.jsonの`ocr.enabled`で切替）。**
- **serial_input**: iPhone（Vision Frameworkで認識・安定化判定）→ ESP32（Wi-Fi受信→USBシリアル転送）経由で届く、確定済みのゼッケン値を受信・保持する層。安定化判定は送信元（iPhone）側で完結しているため、`SerialBibSource`は受信した最新の有効値をそのまま保持するだけでよい（再デバウンスしない）。`get_locked_candidate()` / `get_locked_frame()`を`BibReader`と同名にして、`main.py`側の呼び出しコードを共通化している。
- **timer**: タイム計測の状態機械・出走枠管理・待機リスト。Tkinterにも他層にも依存しない純粋ロジック。
- **storage**: SQLiteへの確定記録の保存、ローカルCSVの自動書き出し（Sheets書き込み失敗時のバックアップ）。
- **sheets**: Googleスプレッドシートとの連携（認証・セッション管理・書き込み・テンプレート構築）。ダイアログ表示はuiに委譲する（コールバック注入）。
- **ui**: Tkinterによる画面表示とユーザー操作のハンドリング。`session_dialogs.py`はsheets層からコールバックとして呼ばれるダイアログ群。
- **main.py**: 上記すべてを結線し、アプリを起動するエントリーポイント。

## やってはいけないこと（禁止パターン）

1. **storage/sensor/timerからsheets/uiをimportしない**: これらは基盤層であり、上位層の事情（Googleスプレッドシートの都合、画面の都合）を知ってはならない。
2. **sheets層にTkinterを直接書かない**: ダイアログが必要な場合は、呼び出し側（main.pyまたはui層）からコールバック関数として注入する（`sheets/manager.py`の`start_session(..., prompt_session_start, ...)`を参照）。
3. **commonに業務ロジックを増やさない**: commonは「誰にも依存しない定数・ヘルパー」のみ。Google APIを呼ぶ・Tkinterを使う・ファイルI/Oをする等の副作用を持つコードはcommonに置かない。
4. **新しいモジュール間の横断importを追加する前に`lint-imports`を実行する**: 依存方向を誤ると`storageはsheets/ui/sensorに依存してはならない`等の契約違反として検知される。

## 既知の残課題（今回は対応を見送ったもの）

- `main.py`の`main()`関数は約400行・約25個のネスト関数を含む「神関数」のままです。内部の関数群が`session`/`sheets_client`/`local_store`等の可変な共有状態をクロージャで持っているため、単純なファイル分割では済まず、状態を保持するクラスへの再設計が必要になります。ユーザー判断により今回はスコープ外としました。
- `ui/main_window.py`は`sensor.mock_driver.MockDriver`を直接import しています（モック専用の手動トリガーボタンのため）。実害が小さいため意図的に許容しています。
