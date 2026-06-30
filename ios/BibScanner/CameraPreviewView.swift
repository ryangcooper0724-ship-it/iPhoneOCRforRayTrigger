import SwiftUI
import AVFoundation

/// 画面本体。カメラプレビュー＋ROI枠の重ね描画＋直近の認識・送信状況の表示。
struct CameraPreviewView: View {
    @StateObject private var viewModel = CameraPreviewViewModel()

    var body: some View {
        GeometryReader { geo in
            ZStack {
                CameraLayerView(session: viewModel.cameraSession.captureSessionForPreview)
                    .ignoresSafeArea()

                // ROI枠の可視化（CameraSession.regionOfInterestと同じ正規化座標）
                let roi = viewModel.cameraSession.regionOfInterest
                Rectangle()
                    .strokeBorder(Color.yellow, lineWidth: 2)
                    .frame(
                        width: roi.width * geo.size.width,
                        height: roi.height * geo.size.height
                    )
                    .position(
                        x: (roi.midX) * geo.size.width,
                        y: (1 - roi.midY) * geo.size.height // Vision座標系は左下原点なので反転
                    )

                VStack {
                    Spacer()
                    statusBar
                }
            }
        }
        .onAppear { viewModel.start() }
        .onDisappear { viewModel.stop() }
    }

    private var statusBar: some View {
        VStack(spacing: 4) {
            Text(viewModel.lastLockedBib.map { "ロック確定: \($0)" } ?? "認識待機中…")
                .font(.title2.bold())
            Text(viewModel.lastStatusMessage)
                .font(.caption)
                .foregroundColor(.secondary)
        }
        .padding()
        .frame(maxWidth: .infinity)
        .background(.ultraThinMaterial)
    }
}

/// AVCaptureVideoPreviewLayerをSwiftUIに橋渡しするだけのUIViewRepresentable。
struct CameraLayerView: UIViewRepresentable {
    let session: AVCaptureSession

    func makeUIView(context: Context) -> PreviewUIView {
        let view = PreviewUIView()
        view.videoPreviewLayer.session = session
        view.videoPreviewLayer.videoGravity = .resizeAspectFill
        return view
    }

    func updateUIView(_ uiView: PreviewUIView, context: Context) {}

    final class PreviewUIView: UIView {
        override class var layerClass: AnyClass { AVCaptureVideoPreviewLayer.self }
        var videoPreviewLayer: AVCaptureVideoPreviewLayer {
            layer as! AVCaptureVideoPreviewLayer
        }
    }
}
