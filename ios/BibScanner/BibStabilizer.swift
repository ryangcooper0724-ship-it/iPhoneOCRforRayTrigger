import Foundation

/// PC側 ocr/bib_reader.py の BibReader._observe() と同じロジックをSwiftに移植したもの。
///
/// 同一値が confirmCount 回連続、かつ信頼度が minConfidence 以上のときだけ
/// 「ロック」とみなし、ロックが新たに確定した瞬間にのみ true を返す
/// （= 送信トリガーとして使う）。低信頼度の読み取りは「読めなかった」扱いにし、
/// 連続カウントを途切れさせる。
final class BibStabilizer {
    private let confirmCount: Int
    private let minConfidence: Float

    private var lockedCandidate: String?
    private var lastRawValue: String?
    private var streakCount: Int = 0

    init(confirmCount: Int = BibScannerConfig.confirmCount,
         minConfidence: Float = BibScannerConfig.minConfidence) {
        self.confirmCount = max(1, confirmCount)
        self.minConfidence = minConfidence
    }

    /// 1件の生の認識結果を処理する。新たにロックが確定した場合のみそのゼッケン値を返す。
    @discardableResult
    func observe(rawValue: String?, confidence: Float) -> String? {
        var value = rawValue
        if value != nil && confidence < minConfidence {
            value = nil
        }

        if value == nil || value != lastRawValue {
            lastRawValue = value
            streakCount = value != nil ? 1 : 0
            return nil
        }

        streakCount += 1
        if streakCount >= confirmCount && value != lockedCandidate {
            lockedCandidate = value
            return value
        }
        return nil
    }
}
