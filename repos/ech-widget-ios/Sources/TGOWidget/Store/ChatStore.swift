import Foundation
import Combine

/// Core chat state management
@MainActor
public final class ChatStore: ObservableObject {
    // MARK: - Published State

    @Published public var messages: [ChatMessage] = []
    @Published public var online = false
    @Published public var initializing = true
    @Published public var error: String?

    @Published public var historyLoading = false
    @Published public var historyHasMore = true

    @Published public var isStreaming = false
    @Published public var streamCanceling = false

    // MARK: - Internal State

    private(set) var myUid: String?
    private(set) var channelId: String?
    private(set) var channelType: Int = 251
    private(set) var visitorId: String?
    private var earliestSeq: Int?
    private var streamingClientMsgNo: String?

    // MARK: - Services

    private var api: APIClient?
    private var imService: IMService?
    private var visitorService: VisitorService?
    private var messageService: MessageService?
    private var chatService: ChatService?
    private var uploadService: UploadService?

    // MARK: - Init

    func setup(config: TGOConfig) {
        let client = APIClient(baseURL: config.baseURL, apiKey: config.apiKey)
        self.api = client
        self.visitorService = VisitorService(api: client)
        self.messageService = MessageService(api: client)
        self.chatService = ChatService(api: client)
        self.uploadService = UploadService(api: client)
        self.imService = IMService(api: client)

        imService?.onMessage = { [weak self] json in
            Task { @MainActor in
                self?.handleIncomingMessage(json)
            }
        }
        imService?.onCustomEvent = { [weak self] json in
            Task { @MainActor in
                self?.handleCustomEvent(json)
            }
        }
        imService?.onConnected = { [weak self] in
            Task { @MainActor in
                self?.online = true
            }
        }
        imService?.onDisconnected = { [weak self] reason in
            Task { @MainActor in
                self?.online = false
            }
        }
    }

    /// Returns the APIClient for use by PlatformStore
    var apiClient: APIClient? { api }
}

// MARK: - Initialization Flow

extension ChatStore {
    /// Full initialization: register visitor → connect IM → load history
    func initialize(config: TGOConfig) async {
        setup(config: config)
        initializing = true
        error = nil

        do {
            // 1. Register visitor
            let visitor = try await visitorService!.getOrRegister(info: config.visitorInfo)
            self.visitorId = visitor.id
            self.myUid = visitor.imUid
            self.channelId = visitor.channelId
            self.channelType = visitor.channelType ?? 251

            // 2. Connect IM
            if let token = visitor.imToken {
                try await imService?.connect(uid: visitor.imUid, token: token)
                imService?.startHeartbeat()
            }

            // 3. Load initial history
            await loadInitialHistory()

            initializing = false
            online = true
        } catch {
            self.error = error.localizedDescription
            initializing = false
        }
    }
}

// MARK: - Message History

extension ChatStore {
    func loadInitialHistory(limit: Int = 30) async {
        guard let channelId, let service = messageService else { return }
        historyLoading = true

        do {
            let resp = try await service.sync(
                channelId: channelId,
                channelType: channelType,
                limit: limit,
                pullMode: 0
            )
            let parsed = resp.messages.compactMap { parseWKMessage($0) }
            messages = parsed.sorted { ($0.messageSeq ?? 0) < ($1.messageSeq ?? 0) }
            earliestSeq = resp.startMessageSeq
            historyHasMore = resp.more == 1
            historyLoading = false
        } catch {
            historyLoading = false
        }
    }

    func loadMoreHistory(limit: Int = 30) async {
        guard let channelId, let service = messageService,
              !historyLoading, historyHasMore else { return }
        historyLoading = true

        do {
            let resp = try await service.sync(
                channelId: channelId,
                channelType: channelType,
                endMessageSeq: earliestSeq,
                limit: limit,
                pullMode: 0
            )
            let parsed = resp.messages.compactMap { parseWKMessage($0) }
            let sorted = parsed.sorted { ($0.messageSeq ?? 0) < ($1.messageSeq ?? 0) }
            messages.insert(contentsOf: sorted, at: 0)
            earliestSeq = resp.startMessageSeq
            historyHasMore = resp.more == 1
            historyLoading = false
        } catch {
            historyLoading = false
        }
    }
}

// MARK: - Send Message

extension ChatStore {
    func sendTextMessage(_ text: String) async {
        guard let channelId, let myUid else { return }
        let clientMsgNo = UUID().uuidString
        let trimmed = text.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !trimmed.isEmpty else { return }

        // Add optimistic message
        let msg = ChatMessage(
            id: clientMsgNo,
            role: .user,
            payload: .text(content: trimmed),
            time: Date(),
            clientMsgNo: clientMsgNo,
            fromUid: myUid,
            channelId: channelId,
            channelType: channelType,
            status: .sending
        )
        messages.append(msg)

        do {
            // Send via IM
            let payload: [String: Any] = ["type": 1, "content": trimmed]
            try await imService?.sendMessage(
                channelId: channelId,
                channelType: channelType,
                payload: payload,
                clientMsgNo: clientMsgNo
            )

            // Trigger AI completion
            try await chatService?.sendCompletion(
                message: trimmed,
                fromUid: myUid,
                channelId: channelId,
                channelType: channelType
            )

            // Update status
            if let idx = messages.firstIndex(where: { $0.id == clientMsgNo }) {
                messages[idx].status = .normal
            }
        } catch {
            if let idx = messages.firstIndex(where: { $0.id == clientMsgNo }) {
                messages[idx].status = .failed(error: error.localizedDescription)
            }
        }
    }

    func retryMessage(id: String) async {
        guard let idx = messages.firstIndex(where: { $0.id == id }),
              case .text(let content) = messages[idx].payload else { return }
        messages.remove(at: idx)
        await sendTextMessage(content)
    }

    func removeMessage(id: String) {
        messages.removeAll { $0.id == id }
    }
}

// MARK: - Upload

extension ChatStore {
    func uploadImage(data: Data, fileName: String) async {
        guard let channelId, let myUid, let uploadService else { return }
        let msgId = UUID().uuidString

        // Add placeholder
        var msg = ChatMessage(
            id: msgId,
            role: .user,
            payload: .image(url: "", width: 0, height: 0),
            time: Date(),
            clientMsgNo: msgId,
            fromUid: myUid,
            status: .uploading(progress: 0)
        )
        messages.append(msg)

        do {
            let resp = try await uploadService.upload(
                data: data,
                fileName: fileName,
                mimeType: "image/jpeg",
                channelId: channelId,
                channelType: channelType
            ) { [weak self] progress in
                Task { @MainActor in
                    if let idx = self?.messages.firstIndex(where: { $0.id == msgId }) {
                        self?.messages[idx].status = .uploading(progress: progress)
                    }
                }
            }

            let fileURL = uploadService.fileURL(fileId: resp.fileId)

            // Update message with real URL
            if let idx = messages.firstIndex(where: { $0.id == msgId }) {
                messages[idx].payload = .image(url: fileURL, width: 0, height: 0)
                messages[idx].status = .normal
            }

            // Send via IM
            let payload: [String: Any] = [
                "type": 2,
                "url": fileURL,
                "width": 0,
                "height": 0
            ]
            try await imService?.sendMessage(
                channelId: channelId,
                channelType: channelType,
                payload: payload,
                clientMsgNo: msgId
            )
        } catch {
            if let idx = messages.firstIndex(where: { $0.id == msgId }) {
                messages[idx].status = .failed(error: error.localizedDescription)
            }
        }
    }
}

// MARK: - Streaming

extension ChatStore {
    func cancelStreaming(reason: String = "user_cancel") async {
        guard let clientMsgNo = streamingClientMsgNo else { return }
        streamCanceling = true
        try? await chatService?.cancelStream(clientMsgNo: clientMsgNo, reason: reason)
        markStreamingEnd()
        streamCanceling = false
    }

    private func markStreamingStart(clientMsgNo: String) {
        isStreaming = true
        streamingClientMsgNo = clientMsgNo

        // Add AI loading placeholder
        let msg = ChatMessage(
            id: "stream-\(clientMsgNo)",
            role: .agent,
            payload: .aiLoading,
            time: Date(),
            clientMsgNo: clientMsgNo,
            streamData: ""
        )
        messages.append(msg)
    }

    private func markStreamingEnd(clientMsgNo: String? = nil) {
        isStreaming = false
        streamingClientMsgNo = nil
    }

    private func appendStreamDelta(clientMsgNo: String, content: String) {
        let streamId = "stream-\(clientMsgNo)"
        if let idx = messages.firstIndex(where: { $0.id == streamId }) {
            let current = messages[idx].streamData ?? ""
            let updated = current + content
            messages[idx].streamData = updated
            messages[idx].payload = .text(content: updated)
        }
    }

    private func finalizeStream(clientMsgNo: String, errorMessage: String? = nil) {
        let streamId = "stream-\(clientMsgNo)"
        if let idx = messages.firstIndex(where: { $0.id == streamId }) {
            if let err = errorMessage {
                messages[idx].errorMessage = err
            }
        }
        markStreamingEnd(clientMsgNo: clientMsgNo)
    }
}

// MARK: - Incoming Message Handling

extension ChatStore {
    private func handleIncomingMessage(_ json: [String: Any]) {
        guard let payloadData = json["payload"] else { return }

        var payloadDict: [String: Any]?
        if let dict = payloadData as? [String: Any] {
            payloadDict = dict
        } else if let str = payloadData as? String,
                  let data = str.data(using: .utf8),
                  let dict = try? JSONSerialization.jsonObject(with: data) as? [String: Any] {
            payloadDict = dict
        }

        guard let dict = payloadDict else { return }

        let fromUid = json["from_uid"] as? String ?? json["fromUid"] as? String ?? ""
        let msgSeq = json["message_seq"] as? Int ?? json["messageSeq"] as? Int
        let clientMsgNo = json["client_msg_no"] as? String ?? json["clientMsgNo"] as? String ?? UUID().uuidString
        let timestamp = json["timestamp"] as? Int

        // Skip own messages (already added optimistically)
        if fromUid == myUid { return }

        // Deduplicate by messageSeq
        if let seq = msgSeq, messages.contains(where: { $0.messageSeq == seq }) { return }

        let payload = MessagePayload.parse(from: dict)

        // Skip AI loading indicators
        if case .aiLoading = payload { return }

        let role: MessageRole = fromUid == myUid ? .user : .agent
        let time = timestamp.map { Date(timeIntervalSince1970: TimeInterval($0)) } ?? Date()
        let errorMsg = json["error"] as? String

        let msg = ChatMessage(
            id: clientMsgNo,
            role: role,
            payload: payload,
            time: time,
            messageSeq: msgSeq,
            clientMsgNo: clientMsgNo,
            fromUid: fromUid,
            errorMessage: errorMsg
        )
        messages.append(msg)
    }

    private func handleCustomEvent(_ json: [String: Any]) {
        guard let event = StreamParser.parse(eventData: json) else { return }

        switch event {
        case .delta(let clientMsgNo, let content):
            if !isStreaming {
                markStreamingStart(clientMsgNo: clientMsgNo)
            }
            if !content.isEmpty {
                appendStreamDelta(clientMsgNo: clientMsgNo, content: content)
            }

        case .close(let clientMsgNo, _):
            finalizeStream(clientMsgNo: clientMsgNo)

        case .error(let clientMsgNo, let message):
            finalizeStream(clientMsgNo: clientMsgNo, errorMessage: message)

        case .cancel(let clientMsgNo):
            finalizeStream(clientMsgNo: clientMsgNo)

        case .finish(let clientMsgNo):
            finalizeStream(clientMsgNo: clientMsgNo)
        }
    }
}

// MARK: - Welcome Message

extension ChatStore {
    func ensureWelcomeMessage(_ text: String) {
        guard !text.isEmpty else { return }
        let welcomeId = "welcome"
        guard !messages.contains(where: { $0.id == welcomeId }) else { return }
        let msg = ChatMessage(
            id: welcomeId,
            role: .agent,
            payload: .text(content: text),
            time: Date(timeIntervalSince1970: 0)
        )
        messages.insert(msg, at: 0)
    }
}

// MARK: - Parse WKMessage

extension ChatStore {
    private func parseWKMessage(_ wk: WKMessage) -> ChatMessage? {
        guard let payloadAny = wk.payload else { return nil }

        var dict: [String: Any]?
        if let d = payloadAny.value as? [String: Any] {
            dict = d
        }
        guard let dict else { return nil }

        let payload = MessagePayload.parse(from: dict)
        if case .aiLoading = payload { return nil }
        if case .command = payload { return nil }

        let fromUid = wk.fromUid ?? ""
        let role: MessageRole = fromUid == myUid ? .user : .agent
        let time = wk.timestamp.map { Date(timeIntervalSince1970: TimeInterval($0)) } ?? Date()

        return ChatMessage(
            id: wk.clientMsgNo ?? UUID().uuidString,
            role: role,
            payload: payload,
            time: time,
            messageSeq: wk.messageSeq,
            clientMsgNo: wk.clientMsgNo,
            fromUid: fromUid,
            errorMessage: wk.error
        )
    }
}
