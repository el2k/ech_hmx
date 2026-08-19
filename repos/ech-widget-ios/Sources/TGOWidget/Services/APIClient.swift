import Foundation

/// Unified HTTP client for TGO API
final class APIClient {
    let baseURL: String
    let apiKey: String
    private let session: URLSession
    private let decoder: JSONDecoder
    private let encoder: JSONEncoder
    private let timeout: TimeInterval = 10

    init(baseURL: String, apiKey: String) {
        self.baseURL = baseURL.hasSuffix("/") ? String(baseURL.dropLast()) : baseURL
        self.apiKey = apiKey
        self.session = URLSession.shared
        self.decoder = JSONDecoder()
        self.encoder = JSONEncoder()
    }

    // MARK: - GET

    func get<T: Decodable>(
        _ path: String,
        query: [String: String] = [:]
    ) async throws -> T {
        var components = URLComponents(string: "\(baseURL)\(path)")!
        var items = query.map { URLQueryItem(name: $0.key, value: $0.value) }
        items.append(URLQueryItem(name: "platform_api_key", value: apiKey))
        components.queryItems = items

        var request = URLRequest(url: components.url!)
        request.httpMethod = "GET"
        request.setValue(apiKey, forHTTPHeaderField: "X-Platform-API-Key")
        request.timeoutInterval = timeout

        let (data, response) = try await session.data(for: request)
        try validateResponse(response)
        return try decoder.decode(T.self, from: data)
    }

    // MARK: - POST JSON

    func post<T: Decodable>(
        _ path: String,
        body: some Encodable
    ) async throws -> T {
        let url = URL(string: "\(baseURL)\(path)")!
        var request = URLRequest(url: url)
        request.httpMethod = "POST"
        request.setValue("application/json", forHTTPHeaderField: "Content-Type")
        request.setValue(apiKey, forHTTPHeaderField: "X-Platform-API-Key")
        request.timeoutInterval = timeout
        request.httpBody = try encoder.encode(body)

        let (data, response) = try await session.data(for: request)
        try validateResponse(response)
        return try decoder.decode(T.self, from: data)
    }

    /// POST that returns raw Data (for completion endpoint)
    func postRaw(
        _ path: String,
        body: some Encodable
    ) async throws -> Data {
        let url = URL(string: "\(baseURL)\(path)")!
        var request = URLRequest(url: url)
        request.httpMethod = "POST"
        request.setValue("application/json", forHTTPHeaderField: "Content-Type")
        request.setValue(apiKey, forHTTPHeaderField: "X-Platform-API-Key")
        request.timeoutInterval = 60
        request.httpBody = try encoder.encode(body)

        let (data, response) = try await session.data(for: request)
        try validateResponse(response)
        return data
    }

    // MARK: - Multipart Upload

    func upload(
        _ path: String,
        fileData: Data,
        fileName: String,
        mimeType: String,
        fields: [String: String],
        onProgress: ((Double) -> Void)? = nil
    ) async throws -> UploadResponse {
        let boundary = "TGO-\(UUID().uuidString)"
        let url = URL(string: "\(baseURL)\(path)")!
        var request = URLRequest(url: url)
        request.httpMethod = "POST"
        request.setValue(
            "multipart/form-data; boundary=\(boundary)",
            forHTTPHeaderField: "Content-Type"
        )
        request.setValue(apiKey, forHTTPHeaderField: "X-Platform-API-Key")
        request.timeoutInterval = 120

        var body = Data()
        for (key, val) in fields {
            body.appendMultipart(boundary: boundary, name: key, value: val)
        }
        body.appendMultipart(
            boundary: boundary, name: "file",
            fileName: fileName, mimeType: mimeType, data: fileData
        )
        body.append("--\(boundary)--\r\n".data(using: .utf8)!)

        request.httpBody = body

        let (data, response) = try await session.data(for: request)
        try validateResponse(response)
        return try decoder.decode(UploadResponse.self, from: data)
    }

    // MARK: - Helpers

    private func validateResponse(_ response: URLResponse) throws {
        guard let http = response as? HTTPURLResponse else {
            throw TGOError.invalidResponse
        }
        guard (200...299).contains(http.statusCode) else {
            throw TGOError.httpError(statusCode: http.statusCode)
        }
    }
}

// MARK: - Errors

public enum TGOError: LocalizedError {
    case invalidResponse
    case httpError(statusCode: Int)
    case missingConfig
    case imConnectionFailed(String)
    case uploadFailed(String)

    public var errorDescription: String? {
        switch self {
        case .invalidResponse: return "Invalid server response"
        case .httpError(let code): return "HTTP error \(code)"
        case .missingConfig: return "TGOWidget not configured"
        case .imConnectionFailed(let msg): return "IM connection failed: \(msg)"
        case .uploadFailed(let msg): return "Upload failed: \(msg)"
        }
    }
}

// MARK: - Data helpers

extension Data {
    mutating func appendMultipart(boundary: String, name: String, value: String) {
        let field = "--\(boundary)\r\nContent-Disposition: form-data; name=\"\(name)\"\r\n\r\n\(value)\r\n"
        append(field.data(using: .utf8)!)
    }

    mutating func appendMultipart(
        boundary: String, name: String,
        fileName: String, mimeType: String, data: Data
    ) {
        var header = "--\(boundary)\r\n"
        header += "Content-Disposition: form-data; name=\"\(name)\"; filename=\"\(fileName)\"\r\n"
        header += "Content-Type: \(mimeType)\r\n\r\n"
        append(header.data(using: .utf8)!)
        append(data)
        append("\r\n".data(using: .utf8)!)
    }
}
