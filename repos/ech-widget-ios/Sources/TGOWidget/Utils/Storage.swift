import Foundation

/// UserDefaults wrapper with namespaced keys
final class Storage {
    private let prefix: String
    private let defaults = UserDefaults.standard
    private let decoder = JSONDecoder()
    private let encoder = JSONEncoder()

    init(apiBase: String, apiKey: String) {
        // Match JS pattern: tgo:{type}:{apiBase}:{apiKey}
        self.prefix = "tgo:\(apiBase):\(apiKey)"
    }

    func save<T: Encodable>(key: String, value: T) {
        let fullKey = "\(prefix):\(key)"
        if let data = try? encoder.encode(value) {
            defaults.set(data, forKey: fullKey)
        }
    }

    func load<T: Decodable>(key: String) -> T? {
        let fullKey = "\(prefix):\(key)"
        guard let data = defaults.data(forKey: fullKey) else { return nil }
        return try? decoder.decode(T.self, from: data)
    }

    func remove(key: String) {
        let fullKey = "\(prefix):\(key)"
        defaults.removeObject(forKey: fullKey)
    }

    func saveBool(key: String, value: Bool) {
        defaults.set(value, forKey: "\(prefix):\(key)")
    }

    func loadBool(key: String) -> Bool {
        defaults.bool(forKey: "\(prefix):\(key)")
    }
}
