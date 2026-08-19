import SwiftUI

/// Top navigation bar
struct HeaderView: View {
    let title: String
    let themeColor: String
    let online: Bool
    var onDismiss: (() -> Void)?

    var body: some View {
        HStack {
            VStack(alignment: .leading, spacing: 2) {
                Text(title)
                    .font(.headline)
                    .foregroundColor(.white)
                HStack(spacing: 4) {
                    Circle()
                        .fill(online ? Color.green : Color.gray)
                        .frame(width: 6, height: 6)
                    Text(online ? "Online" : "Connecting...")
                        .font(.caption2)
                        .foregroundColor(.white.opacity(0.8))
                }
            }

            Spacer()

            if let onDismiss {
                Button(action: onDismiss) {
                    Image(systemName: "xmark")
                        .font(.system(size: 16, weight: .medium))
                        .foregroundColor(.white)
                        .frame(width: 32, height: 32)
                }
                .accessibilityLabel("Close")
            }
        }
        .padding(.horizontal, 16)
        .padding(.vertical, 12)
        .background(Color(hex: themeColor))
    }
}
