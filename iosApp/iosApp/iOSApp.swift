import SwiftUI
import ComposeApp

@main
struct iOSApp: App {
    init() {
        IosQrBridge.shared.scanner = SwiftQrScanner()
    }

    var body: some Scene {
        WindowGroup {
            ContentView()
        }
    }
}
