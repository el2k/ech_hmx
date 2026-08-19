import Foundation
import Combine

/// Platform configuration state
@MainActor
public final class PlatformStore: ObservableObject {
    @Published public var loading = false
    @Published public var error: String?
    @Published public var config: PlatformConfig?
    @Published public var isExpanded = false

    private var platformService: PlatformService?

    func setup(api: APIClient) {
        self.platformService = PlatformService(api: api)
    }

    func fetchConfig() async {
        guard let service = platformService else { return }
        loading = true
        error = nil
        do {
            let info = try await service.fetchInfo()
            config = info.config
            loading = false
        } catch {
            self.error = error.localizedDescription
            loading = false
        }
    }

    var themeColor: String {
        config?.resolvedThemeColor ?? "#2f80ed"
    }

    var title: String {
        config?.resolvedTitle ?? "Tgo"
    }

    var welcomeMessage: String? {
        config?.welcomeMessage
    }
}
