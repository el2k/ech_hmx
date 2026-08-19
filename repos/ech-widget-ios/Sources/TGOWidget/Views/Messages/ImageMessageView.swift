import SwiftUI

/// Image message with async loading
struct ImageMessageView: View {
    let url: String
    let isMe: Bool
    let onTap: () -> Void

    var body: some View {
        if let imageURL = URL(string: url), !url.isEmpty {
            AsyncImage(url: imageURL) { phase in
                switch phase {
                case .success(let image):
                    image
                        .resizable()
                        .aspectRatio(contentMode: .fit)
                        .frame(maxWidth: 220, maxHeight: 220)
                        .clipShape(RoundedRectangle(cornerRadius: 12))
                        .onTapGesture(perform: onTap)

                case .failure:
                    HStack(spacing: 6) {
                        Image(systemName: "photo")
                            .foregroundColor(.secondary)
                        Text("Image failed to load")
                            .font(.caption)
                            .foregroundColor(.secondary)
                    }
                    .padding(12)
                    .background(Color(.systemGray6))
                    .clipShape(RoundedRectangle(cornerRadius: 12))

                case .empty:
                    ProgressView()
                        .frame(width: 120, height: 120)
                        .background(Color(.systemGray6))
                        .clipShape(RoundedRectangle(cornerRadius: 12))

                @unknown default:
                    EmptyView()
                }
            }
        } else {
            // Placeholder for uploading images
            RoundedRectangle(cornerRadius: 12)
                .fill(Color(.systemGray5))
                .frame(width: 120, height: 120)
                .overlay(ProgressView())
        }
    }
}
