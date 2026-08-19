# TGO Widget for Flutter

A Flutter package for integrating TGO customer service chat widget into your app. Easy to use, customizable, and feature-rich.

## Features

- 💬 Real-time messaging via WuKongIM
- 📷 Support for text, image, and file messages
- 🤖 Streaming message support for AI responses
- 📜 Message history loading
- 📎 File and image upload
- 🔔 Floating launcher button with unread badge
- 🌓 Dark/Light theme support
- 🌍 Internationalization (English and Chinese)
- 👤 Visitor identity management
- ⚙️ Highly customizable

## Installation

Add this to your package's `pubspec.yaml` file:

```yaml
dependencies:
  tgo_widget: ^1.0.0
```

## Quick Start

### 1. Initialize the Widget

```dart
import 'package:tgo_widget/tgo_widget.dart';

void main() async {
  WidgetsFlutterBinding.ensureInitialized();
  
  // Initialize TGO Widget
  await TgoWidget.init(
    apiKey: 'your-platform-api-key',
    apiBase: 'https://api.tgo.ai', // Optional, defaults to https://api.tgo.ai
    config: TgoWidgetConfig(
      title: 'Customer Service',
      themeColor: Color(0xFF2F80ED),
      position: WidgetPosition.bottomRight,
      welcomeMessage: 'Hello! How can I help you?',
    ),
  );
  
  runApp(MyApp());
}
```

### 2. Add the Launcher Button

The easiest way to integrate is using the floating launcher button:

```dart
class MyHomePage extends StatelessWidget {
  @override
  Widget build(BuildContext context) {
    return Scaffold(
      body: Stack(
        children: [
          // Your app content
          YourAppContent(),
          
          // TGO Widget Launcher - adds floating button
          TgoWidgetLauncher(),
        ],
      ),
    );
  }
}
```

### 3. Or Open Chat Programmatically

```dart
// Show as bottom sheet
TgoWidget.show(context);

// Show as full screen
TgoWidget.showFullScreen(context);

// Hide chat screen
TgoWidget.hide(context);
```

## Configuration

### TgoWidgetConfig Options

| Option | Type | Default | Description |
|--------|------|---------|-------------|
| `title` | String | "Customer Service" | Title displayed in the header |
| `themeColor` | Color | 0xFF2F80ED | Primary theme color |
| `position` | WidgetPosition | bottomRight | Launcher button position |
| `welcomeMessage` | String? | null | Welcome message for visitors |
| `logoUrl` | String? | null | Custom logo URL |
| `darkMode` | bool? | null | Force dark/light mode |
| `locale` | String? | null | Language code ('en', 'zh') |

### Widget Positions

- `WidgetPosition.bottomRight` (default)
- `WidgetPosition.bottomLeft`
- `WidgetPosition.topRight`
- `WidgetPosition.topLeft`

## Visitor Management

TGO Widget supports visitor identity management, allowing you to associate chat sessions with your app's users.

### VisitorInfo Options

| Option | Type | Description |
|--------|------|-------------|
| `platformOpenId` | String? | Unique identifier for the visitor in your platform |
| `name` | String? | Full name of the visitor |
| `nickname` | String? | Nickname of the visitor |
| `avatarUrl` | String? | URL to the visitor's avatar image |
| `phoneNumber` | String? | Phone number |
| `email` | String? | Email address |
| `company` | String? | Company name |
| `jobTitle` | String? | Job title |
| `customAttributes` | Map<String, String?>? | Custom key-value attributes |

### Initialize with Visitor Info

```dart
await TgoWidget.init(
  apiKey: 'your-platform-api-key',
  visitor: VisitorInfo(
    platformOpenId: 'user_12345',
    name: 'John Doe',
    avatarUrl: 'https://example.com/avatar.png',
    email: 'john@example.com',
  ),
);
```

### Set Visitor at Runtime (e.g., after login)

```dart
// When user logs in
await TgoWidget.setVisitor(VisitorInfo(
  platformOpenId: 'user_12345',
  name: 'John Doe',
  email: 'john@example.com',
  company: 'ACME Inc.',
  customAttributes: {
    'plan': 'premium',
    'signup_date': '2024-01-15',
  },
));
```

### Clear Visitor (e.g., on logout)

```dart
// When user logs out - returns to anonymous state
await TgoWidget.clearVisitor();
```

### Important Notes on `platformOpenId`

- If `platformOpenId` is provided, the same visitor identity will be used across different sessions
- If `platformOpenId` changes (e.g., user switches accounts), chat history will be cleared and a new session starts
- If `platformOpenId` is not provided, an anonymous visitor session will be created
- The visitor registration API is idempotent - calling with the same `platformOpenId` will update existing visitor info

## Event Listening

### Unread Count

```dart
TgoWidget.unreadCountStream.listen((count) {
  print('Unread messages: $count');
  // Update your app's badge
});

// Get current unread count
int count = TgoWidget.unreadCount;
```

### Connection Status

```dart
TgoWidget.connectionStatusStream.listen((status) {
  switch (status) {
    case ConnectionStatus.connected:
      print('Connected to server');
      break;
    case ConnectionStatus.connecting:
      print('Connecting...');
      break;
    case ConnectionStatus.disconnected:
      print('Disconnected from server');
      break;
    case ConnectionStatus.error:
      print('Connection error');
      break;
  }
});

// Get current connection status
ConnectionStatus status = TgoWidget.connectionStatus;
```

### Check Initialization Status

```dart
if (TgoWidget.isInitialized) {
  // Widget is ready to use
  TgoWidget.show(context);
}
```

## Advanced Usage

### Send Message Programmatically

```dart
await TgoWidget.sendMessage('Hello from my app!');
```

### Clear Unread Count

```dart
TgoWidget.clearUnreadCount();
```

### Update Configuration at Runtime

```dart
TgoWidget.updateConfig(TgoWidgetConfig(
  title: 'New Title',
  themeColor: Colors.green,
));
```

### Access Current Configuration

```dart
TgoWidgetConfig currentConfig = TgoWidget.config;
String? apiBase = TgoWidget.apiBase;
String? apiKey = TgoWidget.apiKey;
```

### Access ChatProvider (Advanced)

For advanced use cases, you can access the underlying ChatProvider:

```dart
ChatProvider? provider = TgoWidget.chatProvider;
if (provider != null) {
  // Access messages, connection state, etc.
  List<Message> messages = provider.messages;
  bool isConnected = provider.isConnected;
}
```

### Cleanup

```dart
// Call when your app is closing or when you need to reinitialize
await TgoWidget.dispose();
```

## Complete Example

```dart
import 'package:flutter/material.dart';
import 'package:tgo_widget/tgo_widget.dart';

void main() async {
  WidgetsFlutterBinding.ensureInitialized();
  
  await TgoWidget.init(
    apiKey: 'your-platform-api-key',
    config: TgoWidgetConfig(
      title: 'Support',
      themeColor: Color(0xFF2F80ED),
    ),
  );
  
  runApp(MyApp());
}

class MyApp extends StatelessWidget {
  @override
  Widget build(BuildContext context) {
    return MaterialApp(
      home: HomePage(),
    );
  }
}

class HomePage extends StatefulWidget {
  @override
  _HomePageState createState() => _HomePageState();
}

class _HomePageState extends State<HomePage> {
  int _unreadCount = 0;
  bool _isLoggedIn = false;

  @override
  void initState() {
    super.initState();
    TgoWidget.unreadCountStream.listen((count) {
      setState(() => _unreadCount = count);
    });
  }

  Future<void> _login() async {
    // Your login logic...
    await TgoWidget.setVisitor(VisitorInfo(
      platformOpenId: 'user_12345',
      name: 'John Doe',
      email: 'john@example.com',
    ));
    setState(() => _isLoggedIn = true);
  }

  Future<void> _logout() async {
    // Your logout logic...
    await TgoWidget.clearVisitor();
    setState(() => _isLoggedIn = false);
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(
        title: Text('My App'),
        actions: [
          Stack(
            children: [
              IconButton(
                icon: Icon(Icons.chat),
                onPressed: () => TgoWidget.show(context),
              ),
              if (_unreadCount > 0)
                Positioned(
                  right: 8,
                  top: 8,
                  child: Container(
                    padding: EdgeInsets.all(4),
                    decoration: BoxDecoration(
                      color: Colors.red,
                      shape: BoxShape.circle,
                    ),
                    child: Text(
                      '$_unreadCount',
                      style: TextStyle(color: Colors.white, fontSize: 12),
                    ),
                  ),
                ),
            ],
          ),
        ],
      ),
      body: Center(
        child: Column(
          mainAxisAlignment: MainAxisAlignment.center,
          children: [
            Text(_isLoggedIn ? 'Logged in as John' : 'Not logged in'),
            SizedBox(height: 20),
            ElevatedButton(
              onPressed: _isLoggedIn ? _logout : _login,
              child: Text(_isLoggedIn ? 'Logout' : 'Login'),
            ),
            SizedBox(height: 20),
            ElevatedButton(
              onPressed: () => TgoWidget.showFullScreen(context),
              child: Text('Open Support Chat'),
            ),
          ],
        ),
      ),
      // Alternative: Use TgoWidgetLauncher for floating button
      // floatingActionButton: TgoWidgetLauncher(),
    );
  }
}
```

## Theming

The widget automatically adapts to your app's theme. You can also customize specific aspects:

```dart
TgoWidgetConfig(
  themeColor: Color(0xFF2F80ED),
  darkMode: true, // Force dark mode
)
```

## Internationalization

Built-in support for English and Chinese:

```dart
TgoWidgetConfig(
  locale: 'zh', // Chinese
)
```

## Platform Support

| Platform | Status |
|----------|--------|
| Android | ✅ Supported |
| iOS | ✅ Supported |
| Web | ✅ Supported |
| macOS | ✅ Supported |
| Windows | ✅ Supported |
| Linux | ✅ Supported |

## Requirements

- Flutter SDK >= 3.0.0
- Dart SDK >= 3.0.0

## License

MIT License - see the [LICENSE](LICENSE) file for details.

## Support

- 📖 [Documentation](https://docs.tgo.ai)
- 🐛 [Issues](https://github.com/AIDotNet/tgo-widget-flutter/issues)
- 💬 [Discussions](https://github.com/AIDotNet/tgo-widget-flutter/discussions)

