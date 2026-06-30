import Foundation

/// ロック確定したゼッケン値をESP32へHTTP POSTする。
/// タイムアウトしても複雑な再送制御はしない（次のロックで自然に再送されるため）。
final class BibUploader {
    private let session: URLSession

    init() {
        let config = URLSessionConfiguration.ephemeral
        config.timeoutIntervalForRequest = BibScannerConfig.requestTimeoutSeconds
        session = URLSession(configuration: config)
    }

    func send(bib: String, confidence: Float, onError: ((String) -> Void)? = nil) {
        var request = URLRequest(url: BibScannerConfig.esp32BaseURL)
        request.httpMethod = "POST"
        request.setValue("application/json", forHTTPHeaderField: "Content-Type")
        request.setValue(BibScannerConfig.bibToken, forHTTPHeaderField: "X-Bib-Token")

        let payload: [String: Any] = [
            "bib": bib,
            "confidence": confidence * 100.0,
            "ts": Int(Date().timeIntervalSince1970),
        ]
        request.httpBody = try? JSONSerialization.data(withJSONObject: payload)

        let task = session.dataTask(with: request) { _, response, error in
            if let error = error {
                onError?(error.localizedDescription)
                return
            }
            if let http = response as? HTTPURLResponse, http.statusCode != 200 {
                onError?("HTTP \(http.statusCode)")
            }
        }
        task.resume()
    }
}
