import AVFoundation
import UIKit
import ComposeApp

/// Native QR scanner used by the shared Compose UI (Vibe-Code import).
final class SwiftQrScanner: NativeQrScanner {
    func scan(callback: QrScanCallback) {
        DispatchQueue.main.async {
            switch AVCaptureDevice.authorizationStatus(for: .video) {
            case .authorized:
                Self.present(callback)
            case .notDetermined:
                AVCaptureDevice.requestAccess(for: .video) { granted in
                    DispatchQueue.main.async { granted ? Self.present(callback) : callback.onResult(value: nil) }
                }
            default:
                callback.onResult(value: nil)
            }
        }
    }

    private static func present(_ callback: QrScanCallback) {
        guard let root = UIApplication.shared.connectedScenes
            .compactMap({ ($0 as? UIWindowScene)?.keyWindow?.rootViewController }).first else {
            callback.onResult(value: nil); return
        }
        var top = root
        while let presented = top.presentedViewController { top = presented }
        let vc = QrScannerViewController { value in callback.onResult(value: value) }
        top.present(vc, animated: true)
    }
}

final class QrScannerViewController: UIViewController, AVCaptureMetadataOutputObjectsDelegate {
    private let session = AVCaptureSession()
    private var onResult: ((String?) -> Void)?

    init(onResult: @escaping (String?) -> Void) {
        self.onResult = onResult
        super.init(nibName: nil, bundle: nil)
        modalPresentationStyle = .fullScreen
    }

    required init?(coder: NSCoder) { fatalError("not supported") }

    override func viewDidLoad() {
        super.viewDidLoad()
        view.backgroundColor = .black
        guard let device = AVCaptureDevice.default(for: .video),
              let input = try? AVCaptureDeviceInput(device: device),
              session.canAddInput(input) else { finish(nil); return }
        session.addInput(input)
        let output = AVCaptureMetadataOutput()
        guard session.canAddOutput(output) else { finish(nil); return }
        session.addOutput(output)
        output.setMetadataObjectsDelegate(self, queue: .main)
        output.metadataObjectTypes = [.qr]

        let preview = AVCaptureVideoPreviewLayer(session: session)
        preview.frame = view.layer.bounds
        preview.videoGravity = .resizeAspectFill
        view.layer.addSublayer(preview)

        let close = UIButton(type: .system)
        close.setTitle("Abbrechen", for: .normal)
        close.setTitleColor(.white, for: .normal)
        close.titleLabel?.font = .preferredFont(forTextStyle: .headline)
        close.translatesAutoresizingMaskIntoConstraints = false
        close.addTarget(self, action: #selector(cancel), for: .touchUpInside)
        view.addSubview(close)
        NSLayoutConstraint.activate([
            close.centerXAnchor.constraint(equalTo: view.centerXAnchor),
            close.bottomAnchor.constraint(equalTo: view.safeAreaLayoutGuide.bottomAnchor, constant: -24),
        ])
        DispatchQueue.global(qos: .userInitiated).async { [session] in session.startRunning() }
    }

    func metadataOutput(_ output: AVCaptureMetadataOutput, didOutput metadataObjects: [AVMetadataObject], from connection: AVCaptureConnection) {
        guard let code = (metadataObjects.first as? AVMetadataMachineReadableCodeObject)?.stringValue else { return }
        finish(code)
    }

    @objc private func cancel() { finish(nil) }

    private func finish(_ value: String?) {
        session.stopRunning()
        let callback = onResult
        onResult = nil
        dismiss(animated: true) { callback?(value) }
        if presentingViewController == nil { callback?(value) }
    }
}
