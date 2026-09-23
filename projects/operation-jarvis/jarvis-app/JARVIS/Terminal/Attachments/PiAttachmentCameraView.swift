import SwiftUI
import UIKit
import UniformTypeIdentifiers

/// Camera-only capture. Never writes to the user's photo library.
struct PiAttachmentCameraView: UIViewControllerRepresentable {
    let completion: (Result<UIImage?, Error>) -> Void

    func makeCoordinator() -> Coordinator { Coordinator(completion: completion) }

    func makeUIViewController(context: Context) -> UIImagePickerController {
        let picker = UIImagePickerController()
        picker.sourceType = .camera
        picker.mediaTypes = [UTType.image.identifier]
        picker.cameraCaptureMode = .photo
        picker.allowsEditing = false
        picker.delegate = context.coordinator
        return picker
    }

    func updateUIViewController(_ controller: UIImagePickerController, context: Context) {}

    final class Coordinator: NSObject, UIImagePickerControllerDelegate, UINavigationControllerDelegate {
        private let completion: (Result<UIImage?, Error>) -> Void
        private var completed = false

        init(completion: @escaping (Result<UIImage?, Error>) -> Void) {
            self.completion = completion
        }

        private func finish(_ result: Result<UIImage?, Error>) {
            guard !completed else { return }
            completed = true
            completion(result)
        }

        func imagePickerControllerDidCancel(_ picker: UIImagePickerController) {
            finish(.success(nil))
        }

        func imagePickerController(
            _ picker: UIImagePickerController,
            didFinishPickingMediaWithInfo info: [UIImagePickerController.InfoKey: Any]
        ) {
            guard let image = info[.originalImage] as? UIImage else {
                finish(.failure(PiAttachmentTransportError.rejected("The camera photo could not be read.")))
                return
            }
            finish(.success(image))
        }
    }
}

enum PiAttachmentCameraStore {
    static func prepare(_ image: UIImage, maxBytes: Int64) throws -> PiAttachmentPhotoTransfer {
        guard let data = image.jpegData(compressionQuality: 0.9), !data.isEmpty else {
            throw PiAttachmentTransportError.rejected("The camera photo could not be encoded.")
        }
        guard Int64(data.count) <= maxBytes else {
            throw PiAttachmentTransportError.rejected("The camera photo exceeds the attachment size limit.")
        }
        let manager = FileManager.default
        let directory = manager.temporaryDirectory
            .appendingPathComponent("JARVIS-Pi-Photo-\(UUID().uuidString)", isDirectory: true)
        try manager.createDirectory(at: directory, withIntermediateDirectories: false, attributes: [
            .posixPermissions: 0o700,
            .protectionKey: FileProtectionType.complete,
        ])
        do {
            var values = URLResourceValues()
            values.isExcludedFromBackup = true
            var protectedDirectory = directory
            try protectedDirectory.setResourceValues(values)
            var url = directory.appendingPathComponent("camera-\(UUID().uuidString.lowercased()).jpg")
            try data.write(to: url, options: [.atomic, .completeFileProtection])
            try manager.setAttributes([.posixPermissions: 0o600], ofItemAtPath: url.path)
            try url.setResourceValues(values)
            return PiAttachmentPhotoTransfer(url: url, displayName: "Camera Photo.jpg")
        } catch {
            try? manager.removeItem(at: directory)
            throw error
        }
    }
}
