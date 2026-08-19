import SwiftUI

/// Text message with basic Markdown support (iOS 15+)
struct TextMessageView: View {
    let content: String
    let isMe: Bool
    let themeColor: String

    var body: some View {
        if #available(iOS 15.0, *) {
            let attributed = (try? AttributedString(markdown: content, options: .init(interpretedSyntax: .inlineOnlyPreservingWhitespace))) ?? AttributedString(content)
            Text(attributed)
                .font(.body)
                .foregroundColor(isMe ? .white : .primary)
                .textSelection(.enabled)
                .padding(.horizontal, 14)
                .padding(.vertical, 10)
                .background(isMe ? Color(hex: themeColor) : Color(.systemGray6))
                .clipShape(RoundedRectangle(cornerRadius: 16))
        }
    }
}
