import SwiftUI

/// Input bar with text field, send button, and image picker
struct MessageInputView: View {
    @Binding var text: String
    let isStreaming: Bool
    let themeColor: String
    let onSend: () -> Void
    let onCancelStream: () -> Void
    let onImagePick: () -> Void

    @FocusState private var isFocused: Bool

    var body: some View {
        VStack(spacing: 0) {
            Divider()
            HStack(alignment: .bottom, spacing: 8) {
                // Image picker button
                Button(action: onImagePick) {
                    Image(systemName: "photo")
                        .font(.system(size: 20))
                        .foregroundColor(.secondary)
                }
                .accessibilityLabel("Attach image")
                .frame(width: 36, height: 36)

                // Text input
                if #available(iOS 16.0, *) {
                    TextField("Type a message...", text: $text, axis: .vertical)
                        .textFieldStyle(.plain)
                        .lineLimit(1...5)
                        .focused($isFocused)
                        .padding(.horizontal, 12)
                        .padding(.vertical, 8)
                        .background(Color(.systemGray6))
                        .clipShape(RoundedRectangle(cornerRadius: 18))
                } else {
                    TextField("Type a message...", text: $text)
                        .textFieldStyle(.plain)
                        .focused($isFocused)
                        .padding(.horizontal, 12)
                        .padding(.vertical, 8)
                        .background(Color(.systemGray6))
                        .clipShape(RoundedRectangle(cornerRadius: 18))
                }

                // Send / Cancel button
                if isStreaming {
                    Button(action: onCancelStream) {
                        Image(systemName: "stop.circle.fill")
                            .font(.system(size: 28))
                            .foregroundColor(.red)
                    }
                    .accessibilityLabel("Stop generating")
                    .frame(width: 36, height: 36)
                } else {
                    Button(action: onSend) {
                        Image(systemName: "arrow.up.circle.fill")
                            .font(.system(size: 28))
                            .foregroundColor(
                                text.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty
                                    ? Color(.systemGray4)
                                    : Color(hex: themeColor)
                            )
                    }
                    .disabled(text.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty)
                    .accessibilityLabel("Send message")
                    .frame(width: 36, height: 36)
                }
            }
            .padding(.horizontal, 12)
            .padding(.vertical, 8)
        }
        .background(Color(.systemBackground))
    }
}
