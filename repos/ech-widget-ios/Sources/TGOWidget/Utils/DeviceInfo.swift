import Foundation
#if canImport(UIKit)
import UIKit
#endif

/// Device information for visitor registration
enum DeviceInfo {
    static var osDescription: String {
        #if canImport(UIKit)
        let device = UIDevice.current
        return "\(device.systemName) \(device.systemVersion)"
        #else
        return "iOS"
        #endif
    }

    static var deviceModel: String {
        #if canImport(UIKit)
        return UIDevice.current.model
        #else
        return "iPhone"
        #endif
    }

    static var appVersion: String {
        Bundle.main.infoDictionary?["CFBundleShortVersionString"] as? String ?? "1.0"
    }

    static var bundleId: String {
        Bundle.main.bundleIdentifier ?? "unknown"
    }
}
