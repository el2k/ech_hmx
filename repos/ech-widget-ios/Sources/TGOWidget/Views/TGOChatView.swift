import SwiftUI

/// Main chat view — can be used standalone in SwiftUI
public struct TGOChatView: View {
    @StateObject private var chatStore = ChatStore()
    @StateObject private var platformStore = PlatformStore()
    @State private var inputText = ""
    @State private var showImagePicker = false
    @State private var previewImageURL: String?

    private let config: TGOConfig
    public var onDismiss: (() -> Void)?

    public init(apiKey: String, baseURL: String = TGOConfig.defaultBaseURL, theme: TGOTheme = .light) {
        self.config = TGOConfig(apiKey: apiKey, baseURL: baseURL, theme: theme)
    }

    init(config: TGOConfig, onDismiss: (() -> Void)? = nil) {
        self.config = config
        self.onDismiss = onDismiss
    }

    public var body: some View {
        VStack(spacing: 0) {
            HeaderView(
                title: platformStore.title,
                themeColor: platformStore.themeColor,
                online: chatStore.online,
                onDismiss: onDismiss
            )

            if chatStore.initializing {
                Spacer()
                ProgressView()
                    .progressViewStyle(.circular)
                Spacer()
            } else if let error = chatStore.error {
                Spacer()
                VStack(spacing: 12) {
                    Image(systemName: "wifi.slash")
                        .font(.system(size: 40))
                        .foregroundColor(.secondary)
                    Text(error)
                        .font(.subheadline)
                        .foregroundColor(.secondary)
                        .multilineTextAlignment(.center)
                    Button("Retry") {
                        Task { await chatStore.initialize(config: config) }
                    }
                    .buttonStyle(.bordered)
                }
                .padding()
                Spacer()
            } else {
                MessageListView(
                    messages: chatStore.messages,
                    myUid: chatStore.myUid,
                    isStreaming: chatStore.isStreaming,
                    historyLoading: chatStore.historyLoading,
                    historyHasMore: chatStore.historyHasMore,
                    themeColor: platformStore.themeColor,
                    onLoadMore: {
                        Task { await chatStore.loadMoreHistory() }
                    },
                    onImageTap: { url in
                        previewImageURL = url
                    },
                    onRetry: { id in
                        Task { await chatStore.retryMessage(id: id) }
                    }
                )
            }

            MessageInputView(
                text: $inputText,
                isStreaming: chatStore.isStreaming,
                themeColor: platformStore.themeColor,
                onSend: {
                    let text = inputText
                    inputText = ""
                    Task { await chatStore.sendTextMessage(text) }
                },
                onCancelStream: {
                    Task { await chatStore.cancelStreaming() }
                },
                onImagePick: {
                    showImagePicker = true
                }
            )
        }
        .background(Color(.systemBackground))
        .task {
            await initialize()
        }
        .fullScreenCover(item: $previewImageURL) { url in
            ImagePreviewView(url: url, onDismiss: { previewImageURL = nil })
        }
    }

    private func initialize() async {
        await chatStore.initialize(config: config)
        if let api = chatStore.apiClient {
            platformStore.setup(api: api)
            await platformStore.fetchConfig()
        }
        if let welcome = platformStore.welcomeMessage {
            chatStore.ensureWelcomeMessage(welcome)
        }
    }
}

// Make String identifiable for fullScreenCover
extension String: @retroactive Identifiable {
    public var id: String { self }
}
