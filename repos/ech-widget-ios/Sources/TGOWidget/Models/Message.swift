import Foundation

// MARK: - Message Payload Types

public enum MessagePayloadType: Int, Codable {
    case text = 1
    case image = 2
    case file = 3
    case mixed = 12
    case command = 99
    case aiLoading = 100
    // 1000-2000 range = system messages
}

public enum MessagePayload: Equatable {
    case text(content: String)
    case image(url: String, width: Int, height: Int)
    case file(content: String, url: String, name: String, size: Int)
    case mixed(content: String, images: [ImageInfo], file: FileInfo?)
    case command(cmd: String, param: [String: AnyCodable])
    case aiLoading
    case system(type: Int, content: String)
    case unknown(type: Int, raw: [String: AnyCodable])
}

public struct ImageInfo: Codable, Equatable {
    public let url: String
    public let width: Int
    public let height: Int
}

public struct FileInfo: Codable, Equatable {
    public let url: String
    public let name: String
    public let size: Int
}

// MARK: - Chat Message

public enum MessageRole: String {
    case user
    case agent
}

public enum MessageStatus: Equatable {
    case normal
    case uploading(progress: Double)
    case sending
    case failed(error: String)
}

public struct ChatMessage: Identifiable, Equatable {
    public let id: String
    public var role: MessageRole
    public var payload: MessagePayload
    public var time: Date
    public var messageSeq: Int?
    public var clientMsgNo: String?
    public var fromUid: String?
    public var channelId: String?
    public var channelType: Int?
    public var streamData: String?
    public var status: MessageStatus
    public var errorMessage: String?

    public init(
        id: String = UUID().uuidString,
        role: MessageRole,
        payload: MessagePayload,
        time: Date = Date(),
        messageSeq: Int? = nil,
        clientMsgNo: String? = nil,
        fromUid: String? = nil,
        channelId: String? = nil,
        channelType: Int? = nil,
        streamData: String? = nil,
        status: MessageStatus = .normal,
        errorMessage: String? = nil
    ) {
        self.id = id
        self.role = role
        self.payload = payload
        self.time = time
        self.messageSeq = messageSeq
        self.clientMsgNo = clientMsgNo
        self.fromUid = fromUid
        self.channelId = channelId
        self.channelType = channelType
        self.streamData = streamData
        self.status = status
        self.errorMessage = errorMessage
    }
}

// MARK: - AnyCodable (lightweight type-erased wrapper)

public struct AnyCodable: Codable, Equatable {
    public let value: Any

    public init(_ value: Any) { self.value = value }

    public init(from decoder: Decoder) throws {
        let container = try decoder.singleValueContainer()
        if container.decodeNil() {
            value = NSNull()
        } else if let b = try? container.decode(Bool.self) {
            value = b
        } else if let i = try? container.decode(Int.self) {
            value = i
        } else if let d = try? container.decode(Double.self) {
            value = d
        } else if let s = try? container.decode(String.self) {
            value = s
        } else if let arr = try? container.decode([AnyCodable].self) {
            value = arr.map(\.value)
        } else if let dict = try? container.decode([String: AnyCodable].self) {
            value = dict.mapValues(\.value)
        } else {
            value = NSNull()
        }
    }

    public func encode(to encoder: Encoder) throws {
        var container = encoder.singleValueContainer()
        switch value {
        case is NSNull:
            try container.encodeNil()
        case let b as Bool:
            try container.encode(b)
        case let i as Int:
            try container.encode(i)
        case let d as Double:
            try container.encode(d)
        case let s as String:
            try container.encode(s)
        case let arr as [Any]:
            try container.encode(arr.map { AnyCodable($0) })
        case let dict as [String: Any]:
            try container.encode(dict.mapValues { AnyCodable($0) })
        default:
            try container.encodeNil()
        }
    }

    public static func == (lhs: AnyCodable, rhs: AnyCodable) -> Bool {
        String(describing: lhs.value) == String(describing: rhs.value)
    }
}

// MARK: - Payload Parsing

extension MessagePayload {
    public static func parse(from dict: [String: Any]) -> MessagePayload {
        guard let typeRaw = dict["type"] as? Int else {
            return .unknown(type: 0, raw: dict.mapValues { AnyCodable($0) })
        }

        switch typeRaw {
        case 1:
            let content = dict["content"] as? String ?? ""
            return .text(content: content)

        case 2:
            let url = dict["url"] as? String ?? ""
            let w = dict["width"] as? Int ?? 0
            let h = dict["height"] as? Int ?? 0
            return .image(url: url, width: w, height: h)

        case 3:
            let content = dict["content"] as? String ?? ""
            let url = dict["url"] as? String ?? ""
            let name = dict["name"] as? String ?? ""
            let size = dict["size"] as? Int ?? 0
            return .file(content: content, url: url, name: name, size: size)

        case 12:
            let content = dict["content"] as? String ?? ""
            var images: [ImageInfo] = []
            if let imagesArr = dict["images"] as? [[String: Any]] {
                images = imagesArr.compactMap { img in
                    guard let url = img["url"] as? String else { return nil }
                    return ImageInfo(
                        url: url,
                        width: img["width"] as? Int ?? 0,
                        height: img["height"] as? Int ?? 0
                    )
                }
            }
            var fileInfo: FileInfo?
            if let f = dict["file"] as? [String: Any], let furl = f["url"] as? String {
                fileInfo = FileInfo(
                    url: furl,
                    name: f["name"] as? String ?? "",
                    size: f["size"] as? Int ?? 0
                )
            }
            return .mixed(content: content, images: images, file: fileInfo)

        case 99:
            let cmd = dict["cmd"] as? String ?? ""
            let param = (dict["param"] as? [String: Any]) ?? [:]
            return .command(cmd: cmd, param: param.mapValues { AnyCodable($0) })

        case 100:
            return .aiLoading

        case 1000...2000:
            let content = dict["content"] as? String ?? ""
            return .system(type: typeRaw, content: content)

        default:
            return .unknown(type: typeRaw, raw: dict.mapValues { AnyCodable($0) })
        }
    }
}
