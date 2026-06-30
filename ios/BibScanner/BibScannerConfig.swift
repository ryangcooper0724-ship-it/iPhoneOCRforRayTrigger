import Foundation

/// 現場ごとに調整する固定設定値。本番では設定画面化も検討可。
enum BibScannerConfig {
    static let esp32BaseURL = URL(string: "http://192.168.4.1/bib")!
    static let bibToken = "change_me_too" // firmware側のEXPECTED_TOKENと一致させる

    static let confirmCount = 3
    static let minConfidence: Float = 0.6 // VNRecognizedTextのconfidenceは0.0〜1.0

    static let requestTimeoutSeconds: TimeInterval = 1.5
}
