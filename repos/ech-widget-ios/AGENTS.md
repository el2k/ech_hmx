# AGENTS.md — tgo-widget-ios

## Project Overview

iOS (Swift) SDK for TGO customer service widget. SwiftUI-based chat UI with UIKit bridging via UIHostingController.

## Tech Stack

- Swift 5.9+, iOS 15+
- SwiftUI for UI, ObservableObject for state
- URLSession + async/await for networking
- URLSessionWebSocketTask for WuKongIM
- Swift Package Manager for distribution

## Key Files

- `TGOWidget.swift` — Public API (`configure`, `show`, `hide`)
- `TGOConfig.swift` — Configuration model
- `ChatStore.swift` — Core state (messages, streaming, upload)
- `APIClient.swift` — Unified HTTP client
- `IMService.swift` — WebSocket IM connection
- `StreamParser.swift` — AI streaming event parser
- `TGOChatView.swift` — Main SwiftUI chat view

## API Contract

All endpoints mirror `tgo-widget-js`. Auth via `X-Platform-API-Key` header.

## Conventions

- Models use `CodingKeys` with `snake_case` mapping
- Visitor UID format: `{visitor_id}-vtr`
- Cache keys: `tgo:{apiBase}:{apiKey}:{type}`
- Message types: 1=text, 2=image, 3=file, 12=mixed, 99=cmd, 100=aiLoading, 1000-2000=system
