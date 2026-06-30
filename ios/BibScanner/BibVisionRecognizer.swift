import Vision
import CoreVideo

/// カメラフレーム1枚から1〜2桁の数字（ゼッケン番号）を認識する。
/// Apple Vision Frameworkの.accurateモードを使い、認識精度を優先する
/// （リアルタイム性より精度優先。停止中の車を対象としているため許容範囲）。
final class BibVisionRecognizer {
    private static let bibPattern = try! NSRegularExpression(pattern: "^\\d{1,2}$")

    /// 認識結果（ゼッケン候補, 信頼度0.0〜1.0）。見つからなければ(nil, 0.0)。
    func recognize(pixelBuffer: CVPixelBuffer, regionOfInterest: CGRect) -> (String?, Float) {
        let request = VNRecognizeTextRequest()
        request.recognitionLevel = .accurate
        request.recognitionLanguages = ["en"]
        request.usesLanguageCorrection = false
        request.regionOfInterest = regionOfInterest

        let handler = VNImageRequestHandler(cvPixelBuffer: pixelBuffer, options: [:])
        do {
            try handler.perform([request])
        } catch {
            return (nil, 0.0)
        }

        guard let results = request.results else { return (nil, 0.0) }

        var best: (String, Float)?
        for observation in results {
            guard let candidate = observation.topCandidates(1).first else { continue }
            let text = candidate.string.trimmingCharacters(in: .whitespaces)
            guard Self.bibPattern.firstMatch(
                in: text, range: NSRange(text.startIndex..., in: text)
            ) != nil else { continue }

            let confidence = candidate.confidence
            if best == nil || confidence > best!.1 {
                best = (text, confidence)
            }
        }

        return best.map { ($0.0, $0.1) } ?? (nil, 0.0)
    }
}
