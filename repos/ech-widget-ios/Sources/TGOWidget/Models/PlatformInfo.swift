import Foundation

/// Platform configuration from server
public struct PlatformInfo: Codable {
    public let id: String?
    public let name: String?
    public let config: PlatformConfig?
}

public struct PlatformConfig: Codable {
    public let position: String?
    public let themeColor: String?
    public let widgetTitle: String?
    public let welcomeMessage: String?
    public let logoUrl: String?
    public let displayMode: String?

    enum CodingKeys: String, CodingKey {
        case position
        case themeColor = "theme_color"
        case widgetTitle = "widget_title"
        case welcomeMessage = "welcome_message"
        case logoUrl = "logo_url"
        case displayMode = "display_mode"
    }

    public var resolvedThemeColor: String { themeColor ?? "#2f80ed" }
    public var resolvedTitle: String { widgetTitle ?? "Tgo" }
}

/// Channel info
public struct ChannelInfo: Codable {
    public let name: String?
    public let avatar: String?
    public let channelId: String?
    public let channelType: Int?
    public let entityType: String?

    enum CodingKeys: String, CodingKey {
        case name, avatar
        case channelId = "channel_id"
        case channelType = "channel_type"
        case entityType = "entity_type"
    }
}

/// Upload response
public struct UploadResponse: Codable {
    public let fileId: String
    public let fileName: String
    public let fileSize: Int
    public let fileType: String
    public let fileUrl: String
    public let channelId: String
    public let channelType: Int
    public let uploadedAt: String

    enum CodingKeys: String, CodingKey {
        case fileId = "file_id"
        case fileName = "file_name"
        case fileSize = "file_size"
        case fileType = "file_type"
        case fileUrl = "file_url"
        case channelId = "channel_id"
        case channelType = "channel_type"
        case uploadedAt = "uploaded_at"
    }
}

/// Message sync response
public struct MessageSyncResponse: Codable {
    public let startMessageSeq: Int
    public let endMessageSeq: Int
    public let more: Int
    public let messages: [WKMessage]

    enum CodingKeys: String, CodingKey {
        case startMessageSeq = "start_message_seq"
        case endMessageSeq = "end_message_seq"
        case more, messages
    }
}

/// WuKongIM message from sync API
public struct WKMessage: Codable {
    public let messageId: Int?
    public let messageIdStr: String?
    public let clientMsgNo: String?
    public let messageSeq: Int?
    public let fromUid: String?
    public let channelId: String?
    public let channelType: Int?
    public let timestamp: Int?
    public let payload: AnyCodable?
    public let error: String?

    enum CodingKeys: String, CodingKey {
        case messageId = "message_id"
        case messageIdStr = "message_id_str"
        case clientMsgNo = "client_msg_no"
        case messageSeq = "message_seq"
        case fromUid = "from_uid"
        case channelId = "channel_id"
        case channelType = "channel_type"
        case timestamp, payload, error
    }
}

/// WuKongIM route response
struct WKRouteResponse: Codable {
    let wssAddr: String?
    let wsAddr: String?
    let ws: String?
    let wsUrl: String?
    let wsAddrTls: String?

    enum CodingKeys: String, CodingKey {
        case wssAddr = "wss_addr"
        case wsAddr = "ws_addr"
        case ws
        case wsUrl = "ws_url"
        case wsAddrTls = "ws_addr_tls"
    }

    /// Resolve best WebSocket address
    var resolvedAddress: String? {
        if let addr = wssAddr, !addr.isEmpty { return addr }
        if let addr = wsAddr, !addr.isEmpty { return addr }
        if let addr = ws, !addr.isEmpty { return addr }
        if let addr = wsUrl, !addr.isEmpty { return addr }
        if let addr = wsAddrTls, !addr.isEmpty { return addr }
        return nil
    }
}

/// Completion request
struct CompletionRequest: Encodable {
    let apiKey: String
    let message: String
    let fromUid: String
    let wukongimOnly: Bool
    let forwardUserMessageToWukongim: Bool
    let stream: Bool
    let channelId: String?
    let channelType: Int?

    enum CodingKeys: String, CodingKey {
        case apiKey = "api_key"
        case message
        case fromUid = "from_uid"
        case wukongimOnly = "wukongim_only"
        case forwardUserMessageToWukongim = "forward_user_message_to_wukongim"
        case stream
        case channelId = "channel_id"
        case channelType = "channel_type"
    }
}

/// Stream cancel request
struct StreamCancelRequest: Encodable {
    let platformApiKey: String
    let clientMsgNo: String
    let reason: String?

    enum CodingKeys: String, CodingKey {
        case platformApiKey = "platform_api_key"
        case clientMsgNo = "client_msg_no"
        case reason
    }
}

/// Activity tracking request
struct ActivityRequest: Encodable {
    let platformApiKey: String?
    let visitorId: String
    let activityType: String
    let title: String
    let description: String?

    enum CodingKeys: String, CodingKey {
        case platformApiKey = "platform_api_key"
        case visitorId = "visitor_id"
        case activityType = "activity_type"
        case title, description
    }
}
