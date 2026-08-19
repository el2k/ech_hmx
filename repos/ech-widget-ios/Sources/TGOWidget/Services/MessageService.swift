import Foundation

/// Message history sync
final class MessageService {
    private let api: APIClient

    init(api: APIClient) {
        self.api = api
    }

    /// Sync messages for a channel
    func sync(
        channelId: String,
        channelType: Int,
        startMessageSeq: Int? = nil,
        endMessageSeq: Int? = nil,
        limit: Int = 30,
        pullMode: Int = 0
    ) async throws -> MessageSyncResponse {
        struct SyncRequest: Encodable {
            let platform_api_key: String?
            let channel_id: String
            let channel_type: Int
            let start_message_seq: Int?
            let end_message_seq: Int?
            let limit: Int?
            let pull_mode: Int?
        }

        let req = SyncRequest(
            platform_api_key: api.apiKey,
            channel_id: channelId,
            channel_type: channelType,
            start_message_seq: startMessageSeq,
            end_message_seq: endMessageSeq,
            limit: limit,
            pull_mode: pullMode
        )
        return try await api.post("/v1/visitors/messages/sync", body: req)
    }
}
