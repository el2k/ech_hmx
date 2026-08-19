import SwiftUI

/// Message bubble container — routes to specific message type views
struct MessageBubbleView: View {
    let message: ChatMessage
    let isMe: Bool
    let themeColor: String
    let onImageTap: (String) -> Void
    let onRetry: () -> Void

    var body: some View {
        HStack(alignment: .bottom, spacing: 8) {
            if isMe { Spacer(minLength: 60) }

            VStack(alignment: isMe ? .trailing : .leading, spacing: 4) {
                // Message content
                Group {
                    switch message.payload {
                    case .text(let content):
                        let displayText = message.streamData ?? content
                        TextMessageView(
                            content: displayText,
                            isMe: isMe,
                            themeColor: themeColor
                        )

                    case .image(let url, _, _):
                        ImageMessageView(
                            url: url,
                            isMe: isMe,
                            onTap: { onImageTap(url) }
                        )

                    case .file(let content, let url, let name, let size):
                        FileMessageView(
                            name: name.isEmpty ? content : name,
                            size: size,
                            url: url,
                            isMe: isMe,
                            themeColor: themeColor
                        )

                    case .mixed(let content, let images, let file):
                        VStack(alignment: .leading, spacing: 8) {
                            if !content.isEmpty {
                                TextMessageView(content: content, isMe: isMe, themeColor: themeColor)
                            }
                            ForEach(images, id: \.url) { img in
                                ImageMessageView(url: img.url, isMe: isMe, onTap: { onImageTap(img.url) })
                            }
                            if let f = file {
                                FileMessageView(name: f.name, size: f.size, url: f.url, isMe: isMe, themeColor: themeColor)
                            }
                        }

                    case .system(_, let content):
                        SystemMessageView(content: content)

                    case .aiLoading:
                        TypingIndicator()
                            .padding(.horizontal, 16)
                            .padding(.vertical, 12)
                            .background(Color(.systemGray6))
                            .clipShape(RoundedRectangle(cornerRadius: 16))

                    default:
                        EmptyView()
                    }
                }

                // Status indicators
                if case .uploading(let progress) = message.status {
                    ProgressView(value: progress)
                        .progressViewStyle(.linear)
                        .frame(width: 120)
                }

                if case .sending = message.status {
                    HStack(spacing: 4) {
                        ProgressView()
                            .scaleEffect(0.6)
                        Text("Sending...")
                            .font(.caption2)
                            .foregroundColor(.secondary)
                    }
                }

                if case .failed(let error) = message.status {
                    HStack(spacing: 4) {
                        Image(systemName: "exclamationmark.circle.fill")
                            .foregroundColor(.red)
                            .font(.caption)
                        Text("Failed")
                            .font(.caption2)
                            .foregroundColor(.red)
                        Button("Retry", action: onRetry)
                            .font(.caption2)
                    }
                }

                if let err = message.errorMessage {
                    Text(err)
                        .font(.caption2)
                        .foregroundColor(.red)
                        .padding(.horizontal, 4)
                }
            }

            if !isMe { Spacer(minLength: 60) }
        }
        .padding(.horizontal, 12)
        .padding(.vertical, 2)
    }
}

// MARK: - File Message

struct FileMessageView: View {
    let name: String
    let size: Int
    let url: String
    let isMe: Bool
    let themeColor: String

    var body: some View {
        HStack(spacing: 10) {
            Image(systemName: "doc.fill")
                .font(.title2)
                .foregroundColor(Color(hex: themeColor))
            VStack(alignment: .leading, spacing: 2) {
                Text(name)
                    .font(.subheadline)
                    .lineLimit(2)
                if size > 0 {
                    Text(formatSize(size))
                        .font(.caption2)
                        .foregroundColor(.secondary)
                }
            }
        }
        .padding(12)
        .background(isMe ? Color(hex: themeColor).opacity(0.1) : Color(.systemGray6))
        .clipShape(RoundedRectangle(cornerRadius: 12))
    }

    private func formatSize(_ bytes: Int) -> String {
        let kb = Double(bytes) / 1024
        if kb < 1024 { return String(format: "%.1f KB", kb) }
        return String(format: "%.1f MB", kb / 1024)
    }
}
