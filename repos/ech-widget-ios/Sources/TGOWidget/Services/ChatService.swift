import Foundation

/// Send messages + AI completion
final class ChatService {
    private let api: APIClient

    init(api: APIClient) {
        self.api = api
    }

    /// Send message and trigger AI completion
    func sendCompletion(
        message: String,
        fromUid: String,
        channelId: String,
        channelType: Int
    ) async throws {
        let req = CompletionRequest(
            apiKey: api.apiKey,
            message: message,
            fromUid: fromUid,
            wukongimOnly: true,
            forwardUserMessageToWukongim: false,
            stream: false,
            channelId: channelId,
            channelType: channelType
        )
        let data = try await api.postRaw("/v1/chat/completion", body: req)

        // Check for error in response
        if let json = try? JSONSerialization.jsonObject(with: data) as? [String: Any],
           let eventType = json["event_type"] as? String, eventType == "error" {
            let msg = json["message"] as? String ?? "Unknown error"
            throw TGOError.httpError(statusCode: -1)
        }
    }

    /// Cancel streaming response
    func cancelStream(clientMsgNo: String, reason: String = "user_cancel") async throws {
        let req = StreamCancelRequest(
            platformApiKey: api.apiKey,
            clientMsgNo: clientMsgNo,
            reason: reason
        )
        _ = try await api.postRaw("/v1/ai/runs/cancel-by-client", body: req)
    }

    /// Track visitor activity
    func trackActivity(
        visitorId: String,
        type: String,
        title: String,
        description: String? = nil
    ) async throws {
        let req = ActivityRequest(
            platformApiKey: api.apiKey,
            visitorId: visitorId,
            activityType: type,
            title: title,
            description: description
        )
        _ = try await api.postRaw("/v1/visitors/activities", body: req)
    }
}
