import Foundation

/// File upload with progress
final class UploadService {
    private let api: APIClient

    init(api: APIClient) {
        self.api = api
    }

    /// Upload file data
    func upload(
        data: Data,
        fileName: String,
        mimeType: String,
        channelId: String,
        channelType: Int,
        onProgress: ((Double) -> Void)? = nil
    ) async throws -> UploadResponse {
        try await api.upload(
            "/v1/chat/upload",
            fileData: data,
            fileName: fileName,
            mimeType: mimeType,
            fields: [
                "channel_id": channelId,
                "channel_type": String(channelType)
            ],
            onProgress: onProgress
        )
    }

    /// Build file URL from file ID
    func fileURL(fileId: String) -> String {
        "\(api.baseURL)/v1/chat/files/\(fileId)?platform_api_key=\(api.apiKey)"
    }
}
