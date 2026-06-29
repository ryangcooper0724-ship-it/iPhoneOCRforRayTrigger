# RayTrigger（TPGarage）

光電管×2台（START/GOAL）とY2 Corporation製UBシリーズDIOボード（DIO-8/8B-UBT）を使ったジムカーナタイム計測アプリ。計測結果はローカルDB（バックアップ）とGoogleスプレッドシートの両方に記録される。

開発の経緯・設計判断の詳細は[architecture.md](architecture.md)を参照。

## 機能

- UBボード（YDCI.DLL）への接続。DLLが無い/見つからない場合は自動的にモックモードで起動（画面上のボタンでセンサー発火をシミュレート可能）
- 枠A/枠B 2台同時出走対応。START/GOALセンサーのポーリング監視（デバウンスでチャタリング除去）
- GOAL確定後、PT（パイロンタッチ）・脱輪のペナルティ件数を確認パネルで入力してから確定（一定時間で自動確定）
- ゼッケン番号入力（+1ボタン付き）、待機リスト
- リアルタイムタイム表示（`0:12.345` 形式）
- 確定タイムは必ずローカルSQLite DBに保存してから、Googleスプレッドシートへ非同期で書き込む。Sheets書き込みが失敗してもタイムは失われず、「未送信を同期」ボタンで後から再送できる
- 大会フォーマット（通常大会用/阪名戦用/練習会用）ごとにテンプレートスプレッドシートを使い分け
- 当日タイム履歴の確認・修正、CSVへの自動ミラーリング（Sheetsのバックアップ）
- DNF / MC（マシン故障）/ 全体リセット

## 処理の流れ（概要）

1. 起動時、`config.json`の認証情報でGoogleスプレッドシートに接続し、大会セッションを開始する（前回大会への再接続 or 新規大会名・フォーマット入力）。失敗してもローカル保存のみで起動を継続する。
2. センサー（実機またはモック）がSTART/GOALの通過を検知すると、確定待ちキューに積まれ、画面に確認パネルが表示される。
3. 操作者がPT・脱輪の件数を確認し、確定（または一定時間で自動確定）するとローカルDBに即保存される。
4. 保存と同時にバックグラウンドでGoogleスプレッドシートへ書き込みを試みる。失敗時はローカルには残るが「未送信」のまま。
5. 通信が不安定でも、「未送信を同期」ボタンを押せばその時点の未送信レコードだけをまとめて再送できる（成功した分だけ「済」になる、まだら状態でも問題ない）。

## セットアップ

### 1. Python環境

Python 3.10以上が必要。

```bash
cd gymkhana
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
```

### 2. UBボードのDLL配置

`Ydci.dll` をこの `gymkhana` フォルダ（`main.py` と同じ階層、exe化した場合はexe本体と同じ階層）に配置する。
配置されていない場合や読み込みに失敗した場合は、自動的にモックモードで起動する（画面に「センサー: ...モックモードで起動しました」と表示される）。

### 3. Googleサービスアカウントの作成

1. [Google Cloud Console](https://console.cloud.google.com/) で新規プロジェクトを作成（または既存プロジェクトを使用）
2. 「APIとサービス」→「ライブラリ」から以下の2つを有効化する
   - **Google Sheets API**
   - **Google Drive API**（テンプレートのコピー・新規スプレッドシート作成に必要）
3. 「APIとサービス」→「認証情報」→「認証情報を作成」→「サービスアカウント」でサービスアカウントを作成
4. 作成したサービスアカウントの「鍵」タブから JSON形式の鍵を作成・ダウンロード
5. ダウンロードしたJSONファイルを `credentials.json` としてこの `gymkhana` フォルダに配置する（`.gitignore` 対象なのでGit管理には含まれない）
6. 使用するテンプレートスプレッドシートを開き、「共有」からサービスアカウントのメールアドレス（JSON内の `client_email`）を編集者として共有する

テンプレートスプレッドシートの新規作成手順は[README_sheets.md](README_sheets.md)を参照。

### 4. config.json の設定

```json
{
  "board_model": "DIO-8/8B-UBT",
  "board_id_switch": 0,
  "start_channel": 0,
  "goal_channel": 1,
  "debounce_ms": 300,
  "poll_interval_ms": 10,
  "credentials_path": "credentials.json",
  "templates": {
    "format1": { "name": "通常大会用", "template_spreadsheet_id": "..." },
    "format2": { "name": "阪名戦用", "template_spreadsheet_id": "..." },
    "format3": { "name": "練習会用", "template_spreadsheet_id": "..." }
  },
  "pt_penalty_seconds": 5,
  "datsurin_penalty_seconds": 5
}
```

- `templates`配下の各`template_spreadsheet_id`は、コピー元となるテンプレートスプレッドシートのURL `https://docs.google.com/spreadsheets/d/【ここ】/edit` の部分。起動時にフォーマットを選ぶと、このテンプレートが大会ごとにコピーされる（サービスアカウントがDrive容量を持たない場合はコピーせずテンプレート自体を使い回す）
- `pt_penalty_seconds` / `datsurin_penalty_seconds` はPT・脱輪1件あたりの加算秒数
- `start_channel` / `goal_channel` は実機確認後にチャンネルがずれていれば変更する

### 5. 起動

```bash
python main.py
```

## モックモードでの動作確認

DLLが見つからない開発PCでは自動的にモックモードになり、画面に「STARTセンサー発火」「GOALセンサー発火」ボタンが表示される。これをクリックすることで実機なしに一連の動作を確認できる。

## 実機での動作確認時の注意

- `start_channel` / `goal_channel` が実際の配線と一致しているか確認する（光電管の遮断でその値が0→1になることを確認）
- `debounce_ms` はノイズで誤検知する場合は大きくする（デフォルト300ms）
- `poll_interval_ms` は推奨5〜10ms。下げすぎるとCPU負荷が上がる

## テスト・依存関係チェック

```bash
python -m pytest
lint-imports
```

ファイル構成・依存関係のルールは[architecture.md](architecture.md)を参照。

## 実行ファイル化（配布用exe）

PyInstallerで単体exeにビルドできる。バージョン情報・アイコンは`version.py`・`file_version_info.txt`・`app_icon.ico`で管理。

```bash
python -m PyInstaller --onefile --windowed --name "RayTrigger_TPGarage_v1.01" --version-file file_version_info.txt --icon app_icon.ico --add-data "app_icon.ico;." main.py
```

配布時は`dist/`内のexeに加えて、`config.json`・`credentials.json`・`Ydci.dll`・USBドライバインストーラーを同じフォルダに置く（exeは自分と同じフォルダからこれらを読む。PyInstaller onefile展開時の一時フォルダではなく、exe本体の場所を基準に解決している）。

## ディレクトリ構成

```
gymkhana/
├── main.py                エントリーポイント
├── version.py              アプリ名・バージョン
├── config.json
├── credentials.json        各自配置（.gitignore対象）
├── Ydci.dll                 各自配置
├── common/                  共通層（パス解決・列構成・タイム変換）
├── sensor/                  センサー層（実機/モックドライバ）
├── timer/                   計時ロジック層
├── storage/                 ローカル保存層（SQLite・CSVミラー）
├── sheets/                  Googleスプレッドシート連携層
├── ui/                      画面層（Tkinter）
└── tests/                   pytestによる番犬テスト
```

詳細な依存関係のルールは[architecture.md](architecture.md)を参照。
