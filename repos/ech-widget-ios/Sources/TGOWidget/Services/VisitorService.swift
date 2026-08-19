import Foundation

/// Visitor registration + caching
final class VisitorService {
    private let api: APIClient
    private let storage: Storage

    init(api: APIClient) {
        self.api = api
        self.storage = Storage(apiBase: api.baseURL, apiKey: api.apiKey)
    }

    /// Register or return cached visitor
    func getOrRegister(info: VisitorInfo? = nil) async throws -> Visitor {
        if let cached: Visitor = storage.load(key: "visitor") {
            return cached
        }
        let visitor = try await register(info: info)
        storage.save(key: "visitor", value: visitor)
        return visitor
    }

    private func register(info: VisitorInfo?) async throws -> Visitor {
        let sysInfo = SystemInfo(
            sourceDetail: nil,
            browser: nil,
            operatingSystem: DeviceInfo.osDescription
        )
        let req = VisitorRegisterRequest(
            platformApiKey: api.apiKey,
            name: info?.name,
            nickname: info?.nickname,
            avatarUrl: info?.avatarURL,
            phoneNumber: info?.phone,
            email: info?.email,
            company: info?.company,
            jobTitle: info?.jobTitle,
            source: info?.source ?? "ios_sdk",
            note: info?.note,
            customAttributes: info?.customAttributes?.mapValues { Optional($0) },
            systemInfo: sysInfo,
            timezone: TimeZone.current.identifier
        )
        return try await api.post("/v1/visitors/register", body: req)
    }

    /// Clear cached visitor
    func clearCache() {
        storage.remove(key: "visitor")
    }
}
