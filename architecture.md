# architecture.md

ジムカーナ計測アプリ（RayTrigger）のファイル構成と依存関係のルール。

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
  └─ sensor ─┘
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
| `timer` | `common` | |
| すべての層 | `common` | `common`は依存される専用のハブ |

### 禁止されている依存（import-linterで強制）

- `storage` → `sheets` / `ui` / `sensor`
- `sensor` → `sheets` / `storage` / `ui` / `timer`
- `timer` → `sheets` / `storage` / `ui` / `sensor`
- `sheets` → `ui`
- `ui` → `sheets`
- `common` → `sheets` / `storage` / `ui` / `sensor` / `timer`

## 各レイヤーの責務

- **common**: どの層からも参照される定数・ヘルパーのみを置く。パス解決（`paths.py`）、スプレッドシートの列構成（`sheet_schema.py`）、タイム表示変換（`time_format.py`）。**ロジックを持つビジネス機能は置かない**。
- **sensor**: 光電管（YDCI.DLL）またはモックからのセンサー入力検知。`SensorDriverBase`が共通インターフェース。
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
