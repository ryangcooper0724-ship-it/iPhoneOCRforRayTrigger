import SwiftUI

@main
struct BibScannerApp: App {
    var body: some Scene {
        WindowGroup {
            CameraPreviewView()
                .ignoresSafeArea()
        }
    }
}
