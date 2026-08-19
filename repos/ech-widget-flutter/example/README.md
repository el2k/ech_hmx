# TGO Widget Example

This example demonstrates how to integrate the TGO Widget into a Flutter application.

## Getting Started

1. Replace `'your-api-key'` in `lib/main.dart` with your actual platform API key.

2. Run the example:

```bash
cd example
flutter run
```

## Features Demonstrated

- Widget initialization with configuration
- Floating launcher button with unread badge
- Opening chat as bottom sheet
- Opening chat as full screen page
- Connection status monitoring
- Unread count listening

## Integration Steps

### 1. Add Dependency

```yaml
dependencies:
  tgo_widget: ^1.0.0
```

### 2. Initialize

```dart
await TgoWidget.init(
  apiKey: 'your-api-key',
  apiBase: 'https://api.tgo.ai',
  config: TgoWidgetConfig(
    title: 'Customer Service',
    themeColor: Color(0xFF2F80ED),
    position: WidgetPosition.bottomRight,
    welcomeMessage: 'Hello! How can I help you?',
  ),
);
```

### 3. Add Launcher

```dart
Stack(
  children: [
    YourAppContent(),
    TgoWidgetLauncher(),
  ],
)
```

## API Reference

See the main package [README](../README.md) for complete API documentation.

