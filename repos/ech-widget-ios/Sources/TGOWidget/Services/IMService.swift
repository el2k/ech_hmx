import Foundation

/// WuKongIM WebSocket wrapper
/// Note: This is a protocol-based abstraction. The actual WuKongEasySDK
/// integration requires the native SDK. This provides the interface and
/// a URLSession-based WebSocket fallback.
final class IMService: NSObject {
    private let api: APIClient
    private var webSocket: URLSessionWebSocketTask?
    private var session: URLSession?
    private(set) var isConnected = false
    private var uid: String = ""
    private var token: String = ""

    var onMessage: (([String: Any]) -> Void)?
    var onCustomEvent: (([String: Any]) -> Void)?
    var onConnected: (() -> Void)?
    var onDisconnected: ((String?) -> Void)?

    init(api: APIClient) {
        self.api = api
    }

    // MARK: - Connection

    /// Fetch WS route and connect
    func connect(uid: String, token: String) async throws {
        self.uid = uid
        self.token = token

        let route: WKRouteResponse = try await api.get(
            "/v1/wukongim/route",
            query: ["uid": uid]
        )

        guard let wsAddr = route.resolvedAddress else {
            throw TGOError.imConnectionFailed("No WebSocket address")
        }

        // Convert http(s) to ws(s) if needed
        let wsURL = Self.normalizeWSURL(wsAddr)

        guard let url = URL(string: wsURL) else {
            throw TGOError.imConnectionFailed("Invalid WebSocket URL: \(wsURL)")
        }

        let config = URLSessionConfiguration.default
        session = URLSession(configuration: config, delegate: self, delegateQueue: nil)
        webSocket = session?.webSocketTask(with: url)
        webSocket?.resume()

        // Send auth after connection
        try await sendAuth()
        isConnected = true
        onConnected?()
        startReceiving()
    }

    func disconnect() {
        webSocket?.cancel(with: .normalClosure, reason: nil)
        webSocket = nil
        session?.invalidateAndCancel()
        session = nil
        isConnected = false
    }

    // MARK: - Send

    /// Send a message payload via WuKongIM
    func sendMessage(
        channelId: String,
        channelType: Int,
        payload: [String: Any],
        clientMsgNo: String
    ) async throws {
        let msg: [String: Any] = [
            "type": "send",
            "channel_id": channelId,
            "channel_type": channelType,
            "payload": payload,
            "client_msg_no": clientMsgNo,
            "from_uid": uid
        ]
        try await sendJSON(msg)
    }

    // MARK: - Private

    private func sendAuth() async throws {
        let auth: [String: Any] = [
            "type": "auth",
            "uid": uid,
            "token": token
        ]
        try await sendJSON(auth)
    }

    private func sendJSON(_ dict: [String: Any]) async throws {
        let data = try JSONSerialization.data(withJSONObject: dict)
        guard let str = String(data: data, encoding: .utf8) else { return }
        try await webSocket?.send(.string(str))
    }

    private func startReceiving() {
        webSocket?.receive { [weak self] result in
            guard let self else { return }
            switch result {
            case .success(let message):
                self.handleMessage(message)
                self.startReceiving()
            case .failure:
                self.isConnected = false
                self.onDisconnected?("Connection lost")
            }
        }
    }

    private func handleMessage(_ message: URLSessionWebSocketTask.Message) {
        var data: Data?
        switch message {
        case .string(let text):
            data = text.data(using: .utf8)
        case .data(let d):
            data = d
        @unknown default:
            return
        }

        guard let data,
              let json = try? JSONSerialization.jsonObject(with: data) as? [String: Any]
        else { return }

        let type = json["type"] as? String ?? ""

        switch type {
        case "message", "msg":
            onMessage?(json)
        case "custom_event", "event":
            onCustomEvent?(json)
        case "pong":
            break // heartbeat response
        default:
            // Could be a message or event in different format
            if json["payload"] != nil {
                onMessage?(json)
            } else if json["dataJson"] != nil || json["event_type"] != nil {
                onCustomEvent?(json)
            }
        }
    }

    /// Start heartbeat ping
    func startHeartbeat() {
        Task { [weak self] in
            while self?.isConnected == true {
                try? await Task.sleep(nanoseconds: 30_000_000_000) // 30s
                guard self?.isConnected == true else { break }
                try? await self?.sendJSON(["type": "ping"])
            }
        }
    }

    static func normalizeWSURL(_ addr: String) -> String {
        var url = addr
        if url.hasPrefix("http://") {
            url = "ws://" + url.dropFirst(7)
        } else if url.hasPrefix("https://") {
            url = "wss://" + url.dropFirst(8)
        } else if !url.hasPrefix("ws://") && !url.hasPrefix("wss://") {
            url = "wss://" + url
        }
        return url
    }
}

// MARK: - URLSessionDelegate

extension IMService: URLSessionWebSocketDelegate {
    func urlSession(
        _ session: URLSession,
        webSocketTask: URLSessionWebSocketTask,
        didOpenWithProtocol protocol: String?
    ) {
        // Connected
    }

    func urlSession(
        _ session: URLSession,
        webSocketTask: URLSessionWebSocketTask,
        didCloseWith closeCode: URLSessionWebSocketTask.CloseCode,
        reason: Data?
    ) {
        isConnected = false
        let reasonStr = reason.flatMap { String(data: $0, encoding: .utf8) }
        onDisconnected?(reasonStr)
    }
}
