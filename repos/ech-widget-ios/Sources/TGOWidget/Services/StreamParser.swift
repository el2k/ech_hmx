import Foundation

/// Parse AI streaming events from WuKongIM custom events
final class StreamParser {

    enum StreamEvent {
        case delta(clientMsgNo: String, content: String)
        case close(clientMsgNo: String, endReason: Int?)
        case error(clientMsgNo: String, message: String)
        case cancel(clientMsgNo: String)
        case finish(clientMsgNo: String)
    }

    /// Parse a custom event JSON into a StreamEvent
    static func parse(eventData: [String: Any]) -> StreamEvent? {
        guard let type = eventData["type"] as? String else { return nil }

        // Legacy format: types start with "___"
        if type.hasPrefix("___") {
            return parseLegacy(type: type, data: eventData)
        }

        // v2 format
        if let id = eventData["id"] as? String {
            return parseV2(type: type, id: id, data: eventData)
        }

        // v2 via dataJson
        if let dataJson = eventData["dataJson"] as? [String: Any],
           let id = eventData["id"] as? String {
            return parseV2(type: type, id: id, data: dataJson)
        }

        return nil
    }

    private static func parseV2(type: String, id: String, data: [String: Any]) -> StreamEvent? {
        let payload = data["payload"] as? [String: Any]

        switch type {
        case "stream.delta":
            let delta = payload?["delta"] as? String ?? ""
            return .delta(clientMsgNo: id, content: delta)

        case "stream.close":
            let endReason = payload?["end_reason"] as? Int
            return .close(clientMsgNo: id, endReason: endReason)

        case "stream.error":
            let error = payload?["error"] as? String ?? "Unknown error"
            return .error(clientMsgNo: id, message: error)

        case "stream.cancel":
            return .cancel(clientMsgNo: id)

        case "stream.finish":
            return .finish(clientMsgNo: id)

        default:
            return nil
        }
    }

    private static func parseLegacy(type: String, data: [String: Any]) -> StreamEvent? {
        let id = data["id"] as? String ?? ""

        switch type {
        case "___TextMessageStart":
            return .delta(clientMsgNo: id, content: "")

        case "___TextMessageContent":
            let content = data["data"] as? String ?? ""
            return .delta(clientMsgNo: id, content: content)

        case "___TextMessageEnd":
            let errorMsg = data["data"] as? String
            if let err = errorMsg, !err.isEmpty {
                return .error(clientMsgNo: id, message: err)
            }
            return .close(clientMsgNo: id, endReason: nil)

        default:
            return nil
        }
    }
}
