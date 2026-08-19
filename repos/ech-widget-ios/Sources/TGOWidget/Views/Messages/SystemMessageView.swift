import SwiftUI

/// System message (centered, muted)
struct SystemMessageView: View {
    let content: String

    var body: some View {
        Text(content)
            .font(.caption)
            .foregroundColor(.secondary)
            .multilineTextAlignment(.center)
            .padding(.horizontal, 16)
            .padding(.vertical, 6)
            .frame(maxWidth: .infinity)
    }
}
