import Foundation

/// SDK configuration
public struct TGOConfig {
    public var apiKey: String
    public var baseURL: String
    public var theme: TGOTheme
    public var visitorInfo: VisitorInfo?

    public static let defaultBaseURL = "https://api.tgo.ai"

    public init(
        apiKey: String,
        baseURL: String = TGOConfig.defaultBaseURL,
        theme: TGOTheme = .light,
        visitorInfo: VisitorInfo? = nil
    ) {
        self.apiKey = apiKey
        self.baseURL = baseURL.hasSuffix("/") ? String(baseURL.dropLast()) : baseURL
        self.theme = theme
        self.visitorInfo = visitorInfo
    }
}

// MARK: - Theme

public enum TGOTheme {
    case light
    case dark
    case custom(TGOThemeColors)
}

public struct TGOThemeColors {
    public var primary: String       // hex color
    public var background: String
    public var text: String
    public var bubbleUser: String
    public var bubbleAgent: String

    public init(
        primary: String = "#2f80ed",
        background: String = "#ffffff",
        text: String = "#1a1a1a",
        bubbleUser: String = "#2f80ed",
        bubbleAgent: String = "#f0f0f0"
    ) {
        self.primary = primary
        self.background = background
        self.text = text
        self.bubbleUser = bubbleUser
        self.bubbleAgent = bubbleAgent
    }
}

// MARK: - Visitor Info (optional pre-fill)

public struct VisitorInfo {
    public var name: String?
    public var nickname: String?
    public var avatarURL: String?
    public var phone: String?
    public var email: String?
    public var company: String?
    public var jobTitle: String?
    public var source: String?
    public var note: String?
    public var customAttributes: [String: String]?

    public init(
        name: String? = nil,
        nickname: String? = nil,
        avatarURL: String? = nil,
        phone: String? = nil,
        email: String? = nil,
        company: String? = nil,
        jobTitle: String? = nil,
        source: String? = nil,
        note: String? = nil,
        customAttributes: [String: String]? = nil
    ) {
        self.name = name
        self.nickname = nickname
        self.avatarURL = avatarURL
        self.phone = phone
        self.email = email
        self.company = company
        self.jobTitle = jobTitle
        self.source = source
        self.note = note
        self.customAttributes = customAttributes
    }
}
