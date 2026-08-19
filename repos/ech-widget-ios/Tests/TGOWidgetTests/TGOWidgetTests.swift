import XCTest
import SwiftUI
@testable import TGOWidget

final class TGOWidgetTests: XCTestCase {

    // MARK: - Message Payload Parsing

    func testParseTextPayload() {
        let dict: [String: Any] = ["type": 1, "content": "Hello world"]
        let payload = MessagePayload.parse(from: dict)
        if case .text(let content) = payload {
            XCTAssertEqual(content, "Hello world")
        } else {
            XCTFail("Expected text payload")
        }
    }

    func testParseImagePayload() {
        let dict: [String: Any] = ["type": 2, "url": "https://example.com/img.png", "width": 200, "height": 150]
        let payload = MessagePayload.parse(from: dict)
        if case .image(let url, let w, let h) = payload {
            XCTAssertEqual(url, "https://example.com/img.png")
            XCTAssertEqual(w, 200)
            XCTAssertEqual(h, 150)
        } else {
            XCTFail("Expected image payload")
        }
    }

    func testParseFilePayload() {
        let dict: [String: Any] = ["type": 3, "content": "doc.pdf", "url": "https://example.com/doc.pdf", "name": "doc.pdf", "size": 1024]
        let payload = MessagePayload.parse(from: dict)
        if case .file(_, let url, let name, let size) = payload {
            XCTAssertEqual(url, "https://example.com/doc.pdf")
            XCTAssertEqual(name, "doc.pdf")
            XCTAssertEqual(size, 1024)
        } else {
            XCTFail("Expected file payload")
        }
    }

    func testParseMixedPayload() {
        let dict: [String: Any] = [
            "type": 12,
            "content": "Check this out",
            "images": [["url": "https://example.com/1.png", "width": 100, "height": 100]],
            "file": ["url": "https://example.com/f.pdf", "name": "f.pdf", "size": 512]
        ]
        let payload = MessagePayload.parse(from: dict)
        if case .mixed(let content, let images, let file) = payload {
            XCTAssertEqual(content, "Check this out")
            XCTAssertEqual(images.count, 1)
            XCTAssertNotNil(file)
        } else {
            XCTFail("Expected mixed payload")
        }
    }

    func testParseSystemPayload() {
        let dict: [String: Any] = ["type": 1001, "content": "Agent joined"]
        let payload = MessagePayload.parse(from: dict)
        if case .system(let type, let content) = payload {
            XCTAssertEqual(type, 1001)
            XCTAssertEqual(content, "Agent joined")
        } else {
            XCTFail("Expected system payload")
        }
    }

    func testParseAILoadingPayload() {
        let dict: [String: Any] = ["type": 100]
        let payload = MessagePayload.parse(from: dict)
        if case .aiLoading = payload {
            // pass
        } else {
            XCTFail("Expected aiLoading payload")
        }
    }

    func testParseUnknownPayload() {
        let dict: [String: Any] = ["type": 999, "data": "something"]
        let payload = MessagePayload.parse(from: dict)
        if case .unknown(let type, _) = payload {
            XCTAssertEqual(type, 999)
        } else {
            XCTFail("Expected unknown payload")
        }
    }

    // MARK: - Visitor

    func testVisitorImUid() {
        let visitor = Visitor(
            id: "v123", platformOpenId: nil, projectId: nil, platformId: nil,
            createdAt: nil, updatedAt: nil, channelId: "ch1", channelType: 251,
            imToken: "tok", name: nil, nickname: nil, avatarUrl: nil, isOnline: true
        )
        XCTAssertEqual(visitor.imUid, "v123-vtr")
    }

    // MARK: - Config

    func testConfigDefaults() {
        let config = TGOConfig(apiKey: "pk_test")
        XCTAssertEqual(config.baseURL, "https://api.tgo.ai")
    }

    func testConfigTrailingSlash() {
        let config = TGOConfig(apiKey: "pk_test", baseURL: "https://api.tgo.ai/")
        XCTAssertEqual(config.baseURL, "https://api.tgo.ai")
    }

    // MARK: - Stream Parser

    func testStreamParserV2Delta() {
        let data: [String: Any] = [
            "type": "stream.delta",
            "id": "msg-123",
            "payload": ["delta": "Hello "]
        ]
        if let event = StreamParser.parse(eventData: data) {
            if case .delta(let id, let content) = event {
                XCTAssertEqual(id, "msg-123")
                XCTAssertEqual(content, "Hello ")
            } else {
                XCTFail("Expected delta event")
            }
        } else {
            XCTFail("Failed to parse")
        }
    }

    func testStreamParserV2Close() {
        let data: [String: Any] = [
            "type": "stream.close",
            "id": "msg-123",
            "payload": ["end_reason": 0]
        ]
        if let event = StreamParser.parse(eventData: data) {
            if case .close(let id, let reason) = event {
                XCTAssertEqual(id, "msg-123")
                XCTAssertEqual(reason, 0)
            } else {
                XCTFail("Expected close event")
            }
        } else {
            XCTFail("Failed to parse")
        }
    }

    func testStreamParserLegacy() {
        let data: [String: Any] = [
            "type": "___TextMessageContent",
            "id": "msg-456",
            "data": "world"
        ]
        if let event = StreamParser.parse(eventData: data) {
            if case .delta(let id, let content) = event {
                XCTAssertEqual(id, "msg-456")
                XCTAssertEqual(content, "world")
            } else {
                XCTFail("Expected delta event")
            }
        } else {
            XCTFail("Failed to parse")
        }
    }

    // MARK: - TimeFormatter

    func testTimeFormatterToday() {
        let now = Date()
        let result = TimeFormatter.format(now)
        XCTAssertFalse(result.contains("/"))
    }

    func testShouldShowTime() {
        let now = Date()
        XCTAssertTrue(TimeFormatter.shouldShowTime(previous: nil, current: now))
        XCTAssertFalse(TimeFormatter.shouldShowTime(previous: now, current: now.addingTimeInterval(60)))
        XCTAssertTrue(TimeFormatter.shouldShowTime(previous: now, current: now.addingTimeInterval(600)))
    }

    // MARK: - IMService URL normalization

    func testWSURLNormalization() {
        XCTAssertEqual(IMService.normalizeWSURL("http://example.com"), "ws://example.com")
        XCTAssertEqual(IMService.normalizeWSURL("https://example.com"), "wss://example.com")
        XCTAssertEqual(IMService.normalizeWSURL("ws://example.com"), "ws://example.com")
        XCTAssertEqual(IMService.normalizeWSURL("example.com"), "wss://example.com")
    }

    // MARK: - AnyCodable

    func testAnyCodableRoundTrip() throws {
        let original = AnyCodable(["key": "value", "num": 42] as [String: Any])
        let data = try JSONEncoder().encode(original)
        let decoded = try JSONDecoder().decode(AnyCodable.self, from: data)
        if let dict = decoded.value as? [String: Any] {
            XCTAssertEqual(dict["key"] as? String, "value")
            XCTAssertEqual(dict["num"] as? Int, 42)
        } else {
            XCTFail("Expected dictionary")
        }
    }

    // MARK: - Color Hex

    func testColorHexInit() {
        // Just verify it doesn't crash
        let _ = Color(hex: "#2f80ed")
        let _ = Color(hex: "2f80ed")
        let _ = Color(hex: "#fff")
        let _ = Color(hex: "invalid")
    }
}
