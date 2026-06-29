# ジムカーナ計測アプリ

光電管×2台（START/GOAL）とY2 Corporation製UBシリーズDIOボード（DIO-8/8B-UBT）を使ったジムカーナタイム計測アプリ。計測結果はGoogleスプレッドシートに自動記入される。

## 機能（フェーズ1）

- UBボード（YDCI.DLL）への接続。DLLが無い/見つからない場合は自動的にモックモードで起動（画面上のボタンでセンサー発火をシミュレート可能）
- START/GOALセンサーのポーリング監視（チャタリング除去あり）
- GOALは2回通過でタイム確定（コースレイアウト対応）。GOALカウントのみのリセットも可能
- ゼッケン番号入力（+1ボタン付き）
- リアルタイムタイム表示（`0:12.345` 形式）
- タイム確定時にGoogleスプレッドシートへ自動書き込み（ゼッケン番号・タイム・日時）
- DNF / 全体リセットボタン

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

`Ydci.dll` をこの `gymkhana` フォルダ（`main.py` と同じ階層）に配置する。
配置されていない場合や読み込みに失敗した場合は、自動的にモックモードで起動する（画面に「センサー: ...モックモードで起動しました」と表示される）。

### 3. Googleサービスアカウントの作成

1. [Google Cloud Console](https://console.cloud.google.com/) で新規プロジェクトを作成（または既存プロジェクトを使用）
2. 「APIとサービス」→「ライブラリ」から **Google Sheets API** を有効化
3. 「APIとサービス」→「認証情報」→「認証情報を作成」→「サービスアカウント」でサービスアカウントを作成
4. 作成したサービスアカウントの「鍵」タブから JSON形式の鍵を作成・ダウンロード
5. ダウンロードしたJSONファイルを `credentials.json` としてこの `gymkhana` フォルダに配置する（`.gitignore` 対象なのでGit管理には含まれない）
6. 書き込み先のスプレッドシートを開き、「共有」からサービスアカウントのメールアドレス（JSON内の `client_email`）を編集者として共有する

### 4. config.json の設定

```json
{
  "board_model": "DIO-8/8B-UBT",
  "board_id_switch": 0,
  "start_channel": 0,
  "goal_channel": 1,
  "debounce_ms": 300,
  "poll_interval_ms": 10,
  "spreadsheet_id": "（スプレッドシートのURL中のID部分）",
  "sheet_name": "計測結果",
  "credentials_path": "credentials.json"
}
```

- `spreadsheet_id` はスプレッドシートのURL `https://docs.google.com/spreadsheets/d/【ここ】/edit` の部分
- `sheet_name` で指定したシートが存在しない場合は自動作成され、ヘッダー行（ゼッケン番号・タイム(秒)・日時）が追加される
- `start_channel` / `goal_channel` は実機確認後にチャンネルがずれていれば変更する

### 5. 起動

```bash
python main.py
```

## モックモードでの動作確認

DLLが見つからない開発PCでは自動的にモックモードになり、画面下部に「STARTセンサー発火」「GOALセンサー発火」ボタンが表示される。これをクリックすることで実機なしに一連の動作（START→GOAL1回目→GOAL2回目→タイム確定→Sheets書き込み）を確認できる。

## 実機での動作確認時の注意

- `start_channel` / `goal_channel` が実際の配線と一致しているか確認する（光電管の遮断でその値が0→1になることを確認）
- `debounce_ms` はノイズで誤検知する場合は大きくする（デフォルト300ms）
- `poll_interval_ms` は推奨5〜10ms。下げすぎるとCPU負荷が上がる

## ディレクトリ構成

```
gymkhana/
├── main.py
├── config.json
├── credentials.json     # 各自配置（.gitignore対象）
├── Ydci.dll              # 各自配置
├── sensor/
│   ├── driver_base.py
│   ├── ydci_driver.py
│   └── mock_driver.py
│   └── monitor.py
├── timer/
│   └── lap_timer.py
├── sheets/
│   └── uploader.py
└── ui/
    └── main_window.py
```

## 今後（フェーズ2予定）

- タイム履歴リスト（当日分）
- CSVエクスポート
- オフライン時のローカル保存と後でSheets同期
