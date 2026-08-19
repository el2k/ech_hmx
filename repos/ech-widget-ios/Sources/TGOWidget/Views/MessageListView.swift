import SwiftUI

/// Scrollable message list
struct MessageListView: View {
    let messages: [ChatMessage]
    let myUid: String?
    let isStreaming: Bool
    let historyLoading: Bool
    let historyHasMore: Bool
    let themeColor: String
    let onLoadMore: () -> Void
    let onImageTap: (String) -> Void
    let onRetry: (String) -> Void

    var body: some View {
        ScrollViewReader { proxy in
            ScrollView {
                LazyVStack(spacing: 0) {
                    // Load more button
                    if historyHasMore {
                        Button(action: onLoadMore) {
                            if historyLoading {
                                ProgressView()
                                    .progressViewStyle(.circular)
                                    .scaleEffect(0.8)
                            } else {
                                Text("Load earlier messages")
                                    .font(.caption)
                                    .foregroundColor(.secondary)
                            }
                        }
                        .frame(maxWidth: .infinity)
                        .padding(.vertical, 8)
                        .disabled(historyLoading)
                    }

                    ForEach(Array(messages.enumerated()), id: \.element.id) { index, message in
                        let prevTime = index > 0 ? messages[index - 1].time : nil
                        let showTime = TimeFormatter.shouldShowTime(previous: prevTime, current: message.time)

                        VStack(spacing: 0) {
                            if showTime {
                                Text(TimeFormatter.format(message.time))
                                    .font(.caption2)
                                    .foregroundColor(.secondary)
                                    .padding(.vertical, 8)
                            }

                            MessageBubbleView(
                                message: message,
                                isMe: message.role == .user,
                                themeColor: themeColor,
                                onImageTap: onImageTap,
                                onRetry: { onRetry(message.id) }
                            )
                        }
                    }

                    // Streaming indicator
                    if isStreaming {
                        HStack {
                            TypingIndicator()
                                .padding(.leading, 16)
                            Spacer()
                        }
                        .padding(.vertical, 4)
                    }
                }
                .padding(.vertical, 8)
            }
            .onChange(of: messages.count) { _ in
                if let last = messages.last {
                    withAnimation(.easeOut(duration: 0.2)) {
                        proxy.scrollTo(last.id, anchor: .bottom)
                    }
                }
            }
        }
    }
}

// MARK: - Typing Indicator

struct TypingIndicator: View {
    @State private var phase = 0

    var body: some View {
        HStack(spacing: 4) {
            ForEach(0..<3) { i in
                Circle()
                    .fill(Color.secondary.opacity(0.5))
                    .frame(width: 6, height: 6)
                    .offset(y: phase == i ? -4 : 0)
            }
        }
        .onAppear {
            withAnimation(.easeInOut(duration: 0.4).repeatForever(autoreverses: true)) {
                phase = (phase + 1) % 3
            }
        }
    }
}
