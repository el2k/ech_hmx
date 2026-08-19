import Foundation

/// Platform configuration fetching
final class PlatformService {
    private let api: APIClient

    init(api: APIClient) {
        self.api = api
    }

    func fetchInfo() async throws -> PlatformInfo {
        try await api.get("/v1/platforms/info")
    }

    func fetchChannelInfo(channelId: String, channelType: Int) async throws -> ChannelInfo {
        try await api.get("/v1/channels/info", query: [
            "channel_id": channelId,
            "channel_type": String(channelType)
        ])
    }
}
