import Foundation
import AVFoundation

/// 画面とCameraSessionを仲介し、カメラ権限の要求・直近の認識状況をUIに反映する。
@MainActor
final class CameraPreviewViewModel: ObservableObject {
    @Published var lastLockedBib: String?
    @Published var lastStatusMessage: String = "カメラ権限を確認しています…"

    let cameraSession = CameraSession()

    init() {
        cameraSession.onLocked = { [weak self] bib in
            Task { @MainActor in
                self?.lastLockedBib = bib
                self?.lastStatusMessage = "送信しました（\(Date().formatted(date: .omitted, time: .standard))）"
            }
        }
        cameraSession.onUploadError = { [weak self] message in
            Task { @MainActor in
                self?.lastStatusMessage = "送信失敗: \(message)"
            }
        }
    }

    func start() {
        AVCaptureDevice.requestAccess(for: .video) { [weak self] granted in
            Task { @MainActor in
                guard let self else { return }
                if granted {
                    self.lastStatusMessage = "認識待機中…"
                    self.cameraSession.start()
                } else {
                    self.lastStatusMessage = "カメラ権限が許可されていません（設定アプリから許可してください）"
                }
            }
        }
    }

    func stop() {
        cameraSession.stop()
    }
}
