# Sheets連携モジュール セットアップ手順

ジムカーナ計測アプリのGoogleスプレッドシート連携部分（`sheets/`配下）のセットアップ手順。

## 構成

```
sheets/
├── formatter.py        # タイム表示形式の変換（秒 ⇔ "1:13.123"、DNF/MC判定）
├── manager.py           # セッション管理（大会の新規開始・再接続）、スプレッドシート生成
├── uploader.py          # タイム書き込み（CSV先書き・Sheets非同期書き込み）
└── template_setup.py    # テンプレートスプレッドシートをゼロから構築するスクリプト
session.json              # 起動時に自動生成・読み込み（.gitignore対象）
gymkhana_*.csv             # 大会ごとのローカルCSV（.gitignore対象）
```

## 1. Googleサービスアカウントの作成

1. [Google Cloud Console](https://console.cloud.google.com/) で新規プロジェクトを作成（または既存プロジェクトを使用）
2. 「APIとサービス」→「ライブラリ」から以下の2つを有効化する
   - **Google Sheets API**
   - **Google Drive API**（テンプレートのコピー・新規スプレッドシート作成に必要）
3. 「APIとサービス」→「認証情報」→「認証情報を作成」→「サービスアカウント」でサービスアカウントを作成
4. 作成したサービスアカウントの「鍵」タブから JSON形式の鍵を作成・ダウンロードし、`credentials.json` としてプロジェクトルートに配置する（`.gitignore`対象）

## 2. テンプレートスプレッドシートの準備（任意）

テンプレートを使い回したい場合は、以下のいずれかの方法でテンプレート用スプレッドシートを用意する。

### 方法A: 既存のスプレッドシートをテンプレート化する

1. 空のGoogleスプレッドシートを作成
2. サービスアカウントのメールアドレス（`credentials.json`内の`client_email`）を編集者として共有
3. 以下のコマンドでシート構成（タイム表・リザルト・エントリーリスト＋数式）を自動構築する

```bash
python -m sheets.template_setup credentials.json <スプレッドシートID>
```

4. 作成されたスプレッドシートの「エントリーリスト」シートに、参加者情報（ゼッケン・氏名・車種・参加車両名・所属クラブ）を事前入力する
5. そのスプレッドシートのIDを `config.json` の `template_spreadsheet_id` に設定する

### 方法B: テンプレートを使わない（毎回ゼロから自動生成）

`config.json` の `template_spreadsheet_id` を空文字 `""` のままにしておくと、新規大会開始時に毎回 `template_setup.setup_workbook()` が自動で呼ばれ、ゼロからシート構成を作る。
この場合、大会ごとに「エントリーリスト」シートへ参加者情報を入力する必要がある。

## 3. config.json の設定

```json
{
  "credentials_path": "credentials.json",
  "template_spreadsheet_id": "（テンプレートのスプレッドシートID、無ければ空文字）"
}
```

## 4. スプレッドシートの構成

### シート1: タイム表（アプリが書き込む）

| 列 | 項目 | 内容 |
|---|---|---|
| A | 順位 | 数式（ベストタイムのRANK。DNF/MCは末尾、未走行は空欄） |
| B | ゼッケン | エントリーリストから手入力 |
| C | 氏名 | エントリーリストからVLOOKUP |
| D | 参加車両名 | エントリーリストからVLOOKUP（列幅 約15文字分） |
| E | 所属クラブ | エントリーリストからVLOOKUP |
| F | 1本目 | アプリが書き込む（数値の秒数、またはDNF/MC） |
| G | 2本目 | アプリが書き込む（数値の秒数、またはDNF/MC） |
| H | ベスト | 数式（F・Gの速い方を `1:13.123` 形式で表示。DNF/MCのみならその文字を表示） |

J・K・L列は順位計算用の隠し列（ランキング用の数値キー）。通常は触らなくてよい。

### シート2: リザルト（数式のみ・アプリは書き込まない）

タイム表をベストタイム昇順に並べ替えたもの。未走行者は最下段で順位なし。

### シート3: エントリーリスト（事前に手入力）

| 列 | 項目 |
|---|---|
| A | ゼッケン |
| B | 氏名 |
| C | 車種 |
| D | 参加車両名 |
| E | 所属クラブ |

**注意**: アプリは「タイム表」のB列（ゼッケン）に対応する行を探してF/G列に書き込む。エントリーリストに無い（タイム表にゼッケン行が無い）ゼッケン番号のタイムを書き込もうとするとエラーになる。大会前に必ずエントリーリストとタイム表のB列を入力しておくこと。

## 5. 計測アプリ本体からの呼び出し方

```python
# アプリ起動時にセッションを開始（新規 or 再接続をダイアログで確認）
from sheets.manager import start_session, build_client

config = load_config()  # config.jsonを読む
client = build_client(config, base_dir=BASE_DIR)
session = start_session(config, base_dir=BASE_DIR, client=client)

# タイム確定時
from sheets.uploader import record_time
from sheets.formatter import DNF_SECONDS, MC_SECONDS

record_time(session, bib=42, time_sec=73.123, client=client)       # 通常タイム
record_time(session, bib=15, time_sec=DNF_SECONDS, client=client)  # DNF
record_time(session, bib=8,  time_sec=MC_SECONDS, client=client)   # MC
```

`record_time()` は必ずローカルCSV（`session.csv_path`）へ同期で先に書き込み、Sheetsへは別スレッドで非同期に書き込む。Sheets書き込みに失敗してもCSVには記録済みなので計測は止まらない。失敗を検知したい場合は `on_sheets_error` コールバックを渡す。

## 既知の制約・注意点

- Sheets APIのレート制限（100リクエスト/100秒）に配慮し、1回の計測で1回の`update_cell`に収めている。短時間に多数の確定が連続する場合は間隔を空けることを推奨
- 「タイム表」のH列（ベスト）・J/K/L列（隠し列）の数式は`template_setup.py`が一括生成したもの。手動で行を挿入・削除すると数式がずれるので、行の挿入・削除はテンプレート構築後は避けること
- `session.json`・`gymkhana_*.csv`・`credentials.json` はいずれも`.gitignore`対象（大会ごとの個人情報・認証情報を含むため）

## 既存main.pyとの統合について

このモジュールは現行の`main.py`/`sheets/uploader.py`（ゼッケンごとの1行追記・「計測結果」シート方式）とは異なる設計（ゼッケン行を更新するタイム表方式・大会セッション管理）になっている。`main.py`を新しい`session`/`record_time()`インターフェースに合わせて配線し直す作業は別タスクとして残っている。
