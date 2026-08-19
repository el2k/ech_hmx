import Foundation

/// Visitor model returned from registration API
public struct Visitor: Codable {
    public let id: String
    public let platformOpenId: String?
    public let projectId: String?
    public let platformId: String?
    public let createdAt: String?
    public let updatedAt: String?
    public let channelId: String
    public let channelType: Int?
    public let imToken: String?
    public let name: String?
    public let nickname: String?
    public let avatarUrl: String?
    public let isOnline: Bool?

    enum CodingKeys: String, CodingKey {
        case id
        case platformOpenId = "platform_open_id"
        case projectId = "project_id"
        case platformId = "platform_id"
        case createdAt = "created_at"
        case updatedAt = "updated_at"
        case channelId = "channel_id"
        case channelType = "channel_type"
        case imToken = "im_token"
        case name, nickname
        case avatarUrl = "avatar_url"
        case isOnline = "is_online"
    }

    /// IM uid = "{visitor_id}-vtr"
    public var imUid: String { "\(id)-vtr" }
}

/// Registration request body
struct VisitorRegisterRequest: Encodable {
    let platformApiKey: String
    let name: String?
    let nickname: String?
    let avatarUrl: String?
    let phoneNumber: String?
    let email: String?
    let company: String?
    let jobTitle: String?
    let source: String?
    let note: String?
    let customAttributes: [String: String?]?
    let systemInfo: SystemInfo?
    let timezone: String?

    enum CodingKeys: String, CodingKey {
        case platformApiKey = "platform_api_key"
        case name, nickname
        case avatarUrl = "avatar_url"
        case phoneNumber = "phone_number"
        case email, company
        case jobTitle = "job_title"
        case source, note
        case customAttributes = "custom_attributes"
        case systemInfo = "system_info"
        case timezone
    }
}

struct SystemInfo: Encodable {
    let sourceDetail: String?
    let browser: String?
    let operatingSystem: String?

    enum CodingKeys: String, CodingKey {
        case sourceDetail = "source_detail"
        case browser
        case operatingSystem = "operating_system"
    }
}
