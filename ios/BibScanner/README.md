# BibScanner（iPhone側アプリ）

## Macを持っていない場合（推奨：GitHub Actionsでクラウドビルド）

Xcodeのビルド自体はGitHub Actionsの無料macOSランナー上で行い、生成された
**無署名の.ipa**をWindows上の**AltServer**でiPhoneにインストールする。
Mac本体やXcodeをローカルに持つ必要は一切ない。

### 1. リポジトリをGitHubにpushする

このプロジェクト（`gymkhana_v2`）をGitHubリポジトリにする（プライベートでも可。
ただしプライベートリポジトリはmacOSランナーの無料分数が少ないので、頻繁に
ビルドする場合はpublicにするか有料プランを検討）。

```
git init
git add .
git commit -m "iPhone bib scanner app"
git remote add origin <あなたのGitHubリポジトリURL>
git push -u origin main
```

`.github/workflows/ios-build.yml`が含まれていれば、push時に自動でビルドが走る
（`ios/BibScanner/`配下を変更した時のみ）。手動で起動したい場合はGitHubの
"Actions"タブ→"Build BibScanner (unsigned IPA)"→"Run workflow"。

### 2. ビルド成果物（.ipa）をダウンロード

GitHub Actionsの実行結果ページ→"Artifacts"→`BibScanner-unsigned-ipa`を
ダウンロードしてWindows PC上に展開する（中に`BibScanner-unsigned.ipa`が入っている）。

### 3. Windows PCにAltServerをインストール

1. https://altstore.io から **Windows版AltServer** をダウンロード・インストール
2. インストール時に**iTunes（またはApple Devices）**が必要と案内されるので、
   Microsoft Store版の「Apple Devices」アプリ、もしくは公式iTunesを先に入れておく
3. AltServerはタスクトレイに常駐する

### 4. iPhoneとペアリング

1. iPhoneをUSBでWindows PCに接続し、「このコンピュータを信頼」を許可
2. タスクトレイのAltServerアイコンを右クリック→自分のApple IDでログイン
   （無料のApple IDで可。2要素認証が必要）

### 5. .ipaをインストール

1. AltServerのタスクトレイアイコンを右クリック→ **Install .ipa**
2. 接続中のiPhoneを選択し、ダウンロードした`BibScanner-unsigned.ipa`を指定
3. インストールが完了するとiPhoneのホーム画面にBibScannerアイコンが現れる
4. 初回起動時は「設定→一般→VPNとデバイス管理」で開発元（自分のApple ID）を信頼する操作が必要

### 6. 7日ごとの再署名について

無料Apple IDで署名したアプリは**7日間で期限切れ**になる（有料Apple Developer
Program、年額12,000円程度に加入すれば1年間有効になる）。期限切れ前に
iPhone側の**AltStoreアプリ**（AltServerインストール時に同時に入る）を開き、
Wi-FiでAltServerが起動しているWindows PCと同じネットワークに繋がっていれば
自動/手動で再署名できる。現場運用で7日を跨ぐ場合は、大会前にAltStoreアプリを
開いて「Refresh」しておくこと。

## Macが使える場合（通常のXcode手順）

以下の手順でXcode上に取り込んでください（Mac＋Xcodeが必要）。

1. Xcodeで **File → New → Project → iOS → App** を選択
   - Product Name: `BibScanner`
   - Interface: **SwiftUI**
   - Language: Swift
2. Xcodeが自動生成する `BibScannerApp.swift`・`ContentView.swift`・`Assets.xcassets`等のうち、
   `BibScannerApp.swift`はこのフォルダの同名ファイルで**上書き**し、`ContentView.swift`は削除してよい
3. このフォルダ内の以下のファイルをFinderからXcodeのプロジェクトナビゲータへドラッグ＆ドロップ
   （"Copy items if needed"にチェック）
   - `CameraPreviewView.swift`
   - `CameraPreviewViewModel.swift`
   - `CameraSession.swift`
   - `BibVisionRecognizer.swift`
   - `BibStabilizer.swift`
   - `BibUploader.swift`
   - `BibScannerConfig.swift`
4. `Info.plist`の内容をプロジェクトの`Info.plist`（またはXcode 13以降ならTargetの
   "Info"タブ）にマージする。最低限 `NSCameraUsageDescription` と
   `NSAppTransportSecurity`(ATS例外)が必要
5. `BibScannerConfig.swift`の`bibToken`を`firmware/esp32_bib_bridge/esp32_bib_bridge.ino`の
   `EXPECTED_TOKEN`と同じ値に変更
6. 実機（Simulatorはカメラ非対応）をXcodeに接続し、Signing & Capabilitiesで
   開発チームを設定してビルド・実行

## 画面の動き

- 起動するとカメラ権限を要求 → 許可後にカメラプレビューが全画面表示される
- 黄色い枠（ROI）の中だけを認識対象にする。`CameraSession.regionOfInterest`を
  実際のゼッケン位置に合わせて調整する
- 同じ数字が`confirmCount`回連続・`minConfidence`以上の信頼度で安定すると
  画面下部に「ロック確定: XX」と表示され、ESP32へ自動送信される
- 送信に失敗した場合は「送信失敗: ...」と表示されるが、自動リトライはしない
  （次に車が停止してロックが確定すれば自然に再送される）

## 既知の制約・要調整事項

- ROIは固定矩形。設置角度・距離が変わるたびにコード上の数値を調整して再ビルドが必要
  （現場で頻繁に動かす場合は将来的に画面上でドラッグ調整できるUIを追加すると良い）
- 画面ロック・自動スリープは設定アプリ側でオフにしておくこと
- Wi-Fi接続はESP32のAPへ手動で切り替える必要がある（自動再接続の仕組みは未実装）
