import AVFoundation

/// カメラ映像を継続取得し、フレームごとにOCR→安定化判定→送信のパイプラインへ流す。
/// ROI（ゼッケンが映る範囲）は固定矩形で指定する想定（現場の設置角度に応じて調整）。
final class CameraSession: NSObject, AVCaptureVideoDataOutputSampleBufferDelegate {
    private let captureSession = AVCaptureSession()
    private let videoOutputQueue = DispatchQueue(label: "bibscanner.video.output")

    private let recognizer = BibVisionRecognizer()
    private let stabilizer = BibStabilizer()
    private let uploader = BibUploader()

    /// カメラ画角に対するゼッケン想定領域（正規化座標 0.0〜1.0、Visionの座標系に準拠）。
    /// 現場の設置角度・距離に応じて要調整。
    var regionOfInterest = CGRect(x: 0.25, y: 0.25, width: 0.5, height: 0.5)

    /// 画面表示用にAVCaptureVideoPreviewLayerへそのまま渡せるセッション参照。
    var captureSessionForPreview: AVCaptureSession { captureSession }

    /// ロックが新たに確定した瞬間に呼ばれる（UI更新用）。
    var onLocked: ((String) -> Void)?
    /// 送信に失敗した際に呼ばれる（UI更新用）。
    var onUploadError: ((String) -> Void)?

    func start() {
        configureSession()
        captureSession.startRunning()
    }

    func stop() {
        captureSession.stopRunning()
    }

    private func configureSession() {
        captureSession.beginConfiguration()
        captureSession.sessionPreset = .high

        if let device = AVCaptureDevice.default(.builtInWideAngleCamera, for: .video, position: .back),
           let input = try? AVCaptureDeviceInput(device: device),
           captureSession.canAddInput(input) {
            captureSession.addInput(input)
        }

        let output = AVCaptureVideoDataOutput()
        output.setSampleBufferDelegate(self, queue: videoOutputQueue)
        if captureSession.canAddOutput(output) {
            captureSession.addOutput(output)
        }

        captureSession.commitConfiguration()
    }

    func captureOutput(
        _ output: AVCaptureOutput,
        didOutput sampleBuffer: CMSampleBuffer,
        from connection: AVCaptureConnection
    ) {
        guard let pixelBuffer = CMSampleBufferGetImageBuffer(sampleBuffer) else { return }

        let (value, confidence) = recognizer.recognize(
            pixelBuffer: pixelBuffer, regionOfInterest: regionOfInterest
        )
        if let lockedBib = stabilizer.observe(rawValue: value, confidence: confidence) {
            onLocked?(lockedBib)
            uploader.send(bib: lockedBib, confidence: confidence) { [weak self] message in
                self?.onUploadError?(message)
            }
        }
    }
}
