# BibScanner Web版（iPhone Safari + PWA）

Mac・Xcode・AltStoreを一切使わず、**Safariで開いてホーム画面に追加するだけ**で
動くゼッケン認識アプリ。OCRはブラウザ内で完結するTesseract.js（純JavaScript）
を使う。Apple Visionより精度・速度は落ちるが、1〜2桁の数字限定なので実用範囲。

## 仕組み

- カメラ映像をROI（画面中央の黄枠）だけ`<canvas>`に切り出し→グレースケール＋
  簡易二値化→3倍拡大して`Tesseract.js`に渡す
- 認識結果の安定化（`confirmCount`回連続一致・`minConfidence`以上）はPC側の
  `BibStabilizer`（旧`BibReader._observe()`）と同じロジックを`app.js`に実装済み
- ロックが確定した瞬間だけESP32へ`fetch()`でJSON POST（既存のPython/Arduino側と
  互換のリクエスト形式: `{"bib": "42", "confidence": 87.5, "ts": ...}`）
- `service-worker.js`が全アセット（Tesseract.jsのコア・wasm・英語学習データ込み）を
  キャッシュするので、**一度オンラインで読み込めば以降はオフラインで動く**

## セットアップ手順

### 1. GitHub Pagesでホスティング（推奨）

PWAとして"ホーム画面に追加"するにはHTTPS配信が必要（HTTPだとService Workerが
登録できない）。`web/bib_scanner/`をGitHub Pagesで公開するのが最も簡単。

```
git init   # gymkhana_v2フォルダ全体、または web/bib_scanner だけでも可
git add .
git commit -m "BibScanner web app"
git remote add origin <あなたのGitHubリポジトリURL>
git push -u origin main
```

GitHubリポジトリの **Settings → Pages** で、Source を該当ブランチ・
`/web/bib_scanner`（または`docs`フォルダにコピーして配信）に設定すると
`https://<ユーザー名>.github.io/<リポジトリ名>/`で公開される。

### 2. iPhoneで初回読み込み（自宅などインターネットがある環境で）

1. 公開したURLをSafari（**必ずSafari。Chrome等はPWAのオフライン動作が不安定**）で開く
2. カメラ権限を許可
3. 初回はTesseract.jsの学習データ（約2MB）読み込みのため少し待つ
4. 共有ボタン → **「ホーム画面に追加」**
5. これでService Workerが全アセットをキャッシュし、オフラインでも起動できる状態になる

### 3. 現地での使用

1. iPhoneのWi-FiをESP32のAP（`firmware/esp32_bib_bridge`参照）に切り替える
   （インターネットには繋がらなくなるが、キャッシュ済みなのでアプリは動く）
2. ホーム画面のアイコンからアプリを起動
3. 右上の「設定」ボタンでESP32のURL（デフォルト`http://192.168.4.1/bib`）と
   トークン（`firmware`側`EXPECTED_TOKEN`と一致させる）を設定
4. 黄色いROI枠にゼッケンを収めて待機。安定して認識されると画面下部に
   「ロック確定: XX」と表示されESP32へ自動送信される

## 既知の制約・チューニングポイント

- **精度・速度はApple Visionより劣る**。特に低照度・斜め角度・ボケに弱い。
  実車・実際の照明で試して`minConfidence`・ROI範囲を現地調整すること
- ROIサイズ・送信先URL・confirmCount・minConfidenceは「設定」画面から
  その場で変更可能（`localStorage`に保存され次回起動時も保持される）
- Service Workerのキャッシュは`CACHE_NAME`（`bib-scanner-v1`）のバージョンを
  上げない限り更新されない。コード修正後に再配信する場合は
  `service-worker.js`内の`CACHE_NAME`を変更してから再度オンラインで開き直す
- `icon-192.png`は仮アイコン。差し替えたい場合は同名で192x192のPNGを置き換える
- iOSのSafariでは画面ロック中・バックグラウンドだとカメラストリームが止まるため、
  自動ロックはオフにしておくこと

