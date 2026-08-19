import SwiftUI
#if canImport(UIKit)
import UIKit
#endif

/// Public API entry point for TGO Widget
public final class TGOWidget {
    /// Shared configuration (set via `configure`)
    private static var sharedConfig: TGOConfig?

    // MARK: - Configure

    /// Pre-configure the widget. Call before `show()`.
    public static func configure(
        apiKey: String,
        baseURL: String = TGOConfig.defaultBaseURL,
        theme: TGOTheme = .light,
        visitorInfo: VisitorInfo? = nil
    ) {
        sharedConfig = TGOConfig(
            apiKey: apiKey,
            baseURL: baseURL,
            theme: theme,
            visitorInfo: visitorInfo
        )
    }

    // MARK: - Show (UIKit)

    /// Present the chat as a modal from a UIViewController.
    /// If `configure()` was called, uses that config. Otherwise uses the provided apiKey.
    @MainActor
    public static func show(
        apiKey: String? = nil,
        baseURL: String = TGOConfig.defaultBaseURL,
        theme: TGOTheme = .light,
        from viewController: UIViewController,
        animated: Bool = true
    ) {
        let config: TGOConfig
        if let shared = sharedConfig {
            config = shared
        } else if let key = apiKey {
            config = TGOConfig(apiKey: key, baseURL: baseURL, theme: theme)
        } else {
            assertionFailure("TGOWidget: call configure() or provide apiKey")
            return
        }

        let chatView = TGOChatView(config: config, onDismiss: {
            viewController.dismiss(animated: animated)
        })

        let hostingController = UIHostingController(rootView: chatView)
        hostingController.modalPresentationStyle = .fullScreen
        viewController.present(hostingController, animated: animated)
    }

    /// Dismiss the currently presented chat
    @MainActor
    public static func hide(from viewController: UIViewController, animated: Bool = true) {
        viewController.dismiss(animated: animated)
    }

    /// Clear cached visitor data (forces re-registration)
    public static func clearCache() {
        guard let config = sharedConfig else { return }
        let storage = Storage(apiBase: config.baseURL, apiKey: config.apiKey)
        storage.remove(key: "visitor")
    }
}
