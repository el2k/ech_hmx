import { WKIM, WKIMEvent, WKIMChannelType, ReasonCode } from 'easyjssdk';
import type { RecvMessage, EventNotification } from 'easyjssdk';
import type { TgoClient } from './client.js';

const isDebug = !!process.env.TGO_DEBUG;

// Store original console methods for restoration
const _origConsoleLog = console.log;
const _origConsoleWarn = console.warn;
const _origConsoleDebug = console.debug;

/**
 * Suppress easyjssdk console.log noise globally.
 * The SDK fires async callbacks (ping/pong, events) that log extensively.
 * We suppress all console.log/warn/debug while WKIM is active and restore on disconnect.
 */
function suppressSDKLogs(): void {
  if (isDebug) return;
  console.log = () => {};
  console.warn = () => {};
  console.debug = () => {};
}

export function restoreSDKLogs(): void {
  console.log = _origConsoleLog;
  console.warn = _origConsoleWarn;
  console.debug = _origConsoleDebug;
}

export interface WuKongIMSendResult {
  messageId: string;
  messageSeq: number;
  reasonCode: number;
}

export interface WuKongIMRecvMessage {
  messageId: string;
  messageSeq: number;
  timestamp: number;
  channelId: string;
  channelType: number;
  fromUid: string;
  payload: unknown;
  clientMsgNo?: string;
}

export interface WuKongIMEvent {
  id: string;
  type: string;
  timestamp: number;
  data: unknown;
}

type MessageHandler = (msg: WuKongIMRecvMessage) => void;
type EventHandler = (evt: WuKongIMEvent) => void;

const STAFF_UID_SUFFIX = '-staff';

/**
 * WuKongIM WebSocket client for tgo-cli.
 * Wraps easyjssdk WKIM for Node.js usage.
 *
 * Usage patterns:
 * - CLI (short-lived): connect → send → disconnect
 * - MCP (long-lived):  lazy connect on first send, keep alive, listen for messages
 * - Listen mode:       connect → print incoming messages as JSONL → Ctrl+C
 */
export class WuKongIMClient {
  private im?: WKIM;
  private _uid?: string;
  private _isConnected = false;
  private messageHandlers: MessageHandler[] = [];
  private eventHandlers: EventHandler[] = [];

  get isConnected(): boolean {
    return this._isConnected;
  }

  get uid(): string | undefined {
    return this._uid;
  }

  /**
   * Connect to WuKongIM WebSocket.
   * 1. Fetch current user info (GET /v1/staff/me) to get user ID
   * 2. Resolve WebSocket URL via route API (GET /v1/wukongim/route?uid=...)
   * 3. Initialize and connect WKIM SDK
   */
  async connect(client: TgoClient): Promise<void> {
    if (this._isConnected && this.im) {
      return;
    }

    // 1. Get current user info
    const me = await client.get<{ id: string }>('/v1/staff/me');
    this._uid = `${me.id}${STAFF_UID_SUFFIX}`;

    // 2. Get WebSocket route
    const route = await client.get<{ tcp_addr: string; ws_addr: string; wss_addr: string }>(
      `/v1/wukongim/route?uid=${encodeURIComponent(this._uid)}`,
    );

    // Prefer ws_addr for CLI (typically local/dev). Build full URL if needed.
    let wsUrl = route.wss_addr || route.ws_addr;
    if (wsUrl && !wsUrl.includes('://')) {
      wsUrl = `ws://${wsUrl}`;
    }
    if (!wsUrl) {
      throw new Error('No WebSocket address returned from route API');
    }

    // 3. Initialize WKIM
    const token = client.token;
    if (!token) {
      throw new Error('No auth token available for WuKongIM connection');
    }

    // Suppress SDK verbose logging
    suppressSDKLogs();

    this.im = WKIM.init(wsUrl, { uid: this._uid!, token }, {});

    // Setup event listeners before connecting
    this.setupListeners();

    // 4. Connect with timeout
    const timeout = new Promise<never>((_, reject) =>
      setTimeout(() => reject(new Error('WuKongIM connection timeout (10s)')), 10000),
    );
    await Promise.race([this.im!.connect(), timeout]);
    this._isConnected = true;
  }

  /**
   * Send a message through WuKongIM WebSocket.
   * @param channelId Target channel ID
   * @param channelType Channel type (1=person, 2=group, etc.)
   * @param payload Message payload object (will be base64-encoded by SDK)
   * @param clientMsgNo Optional client message ID for deduplication
   */
  async send(
    channelId: string,
    channelType: number,
    payload: object,
    clientMsgNo?: string,
  ): Promise<WuKongIMSendResult> {
    if (!this.im || !this._isConnected) {
      throw new Error('WuKongIM not connected. Call connect() first.');
    }

    const wkimChannelType = this.convertChannelType(channelType);
    const opts: { clientMsgNo?: string } = {};
    if (clientMsgNo) opts.clientMsgNo = clientMsgNo;

    const result = await this.im!.send(channelId, wkimChannelType, payload, opts);

    if (result.reasonCode !== ReasonCode.Success) {
      const msg = REASON_CODE_MESSAGES[result.reasonCode] || `Send failed (code: ${result.reasonCode})`;
      throw new Error(msg);
    }

    return {
      messageId: result.messageId,
      messageSeq: result.messageSeq,
      reasonCode: result.reasonCode,
    };
  }

  /**
   * Register a handler for incoming messages.
   * Returns an unsubscribe function.
   */
  onMessage(handler: MessageHandler): () => void {
    this.messageHandlers.push(handler);
    return () => {
      const idx = this.messageHandlers.indexOf(handler);
      if (idx > -1) this.messageHandlers.splice(idx, 1);
    };
  }

  /**
   * Register a handler for custom events (AI streaming, presence, etc).
   * Returns an unsubscribe function.
   */
  onEvent(handler: EventHandler): () => void {
    this.eventHandlers.push(handler);
    return () => {
      const idx = this.eventHandlers.indexOf(handler);
      if (idx > -1) this.eventHandlers.splice(idx, 1);
    };
  }

  /**
   * Disconnect from WuKongIM.
   */
  disconnect(): void {
    if (this.im) {
      try {
        this.im.disconnect();
      } catch {
        // Ignore close errors
      }
      this.im = undefined;
    }
    this._isConnected = false;
    this._uid = undefined;
    // Restore console logging
    restoreSDKLogs();
  }

  private setupListeners(): void {
    if (!this.im) return;

    this.im.on(WKIMEvent.Connect, () => {
      this._isConnected = true;
    });

    this.im.on(WKIMEvent.Disconnect, () => {
      this._isConnected = false;
    });

    this.im.on(WKIMEvent.Message, (msg: RecvMessage) => {
      const converted: WuKongIMRecvMessage = {
        messageId: msg.messageId,
        messageSeq: msg.messageSeq,
        timestamp: msg.timestamp,
        channelId: msg.channelId,
        channelType: msg.channelType,
        fromUid: msg.fromUid,
        payload: msg.payload,
        clientMsgNo: msg.clientMsgNo,
      };
      for (const handler of this.messageHandlers) {
        try {
          handler(converted);
        } catch {
          // Don't let one handler crash others
        }
      }
    });

    this.im.on(WKIMEvent.CustomEvent, (evt: EventNotification) => {
      const converted: WuKongIMEvent = {
        id: evt.id,
        type: evt.type,
        timestamp: evt.timestamp,
        data: typeof evt.data === 'string' ? tryParseJSON(evt.data) : evt.data,
      };
      for (const handler of this.eventHandlers) {
        try {
          handler(converted);
        } catch {
          // Don't let one handler crash others
        }
      }
    });

    this.im.on(WKIMEvent.Error, (error: unknown) => {
      this._isConnected = false;
      // In CLI mode, errors are typically fatal
      if (process.env.TGO_DEBUG) {
        console.error('[wukongim] error:', error);
      }
    });
  }

  /**
   * Convert TGO channel type to WuKongIM SDK channel type.
   * PERSON (1) and GROUP (2) have direct mappings; others pass through.
   */
  private convertChannelType(channelType: number): WKIMChannelType | number {
    switch (channelType) {
      case 1: return WKIMChannelType.Person;
      case 2: return WKIMChannelType.Group;
      default: return channelType;
    }
  }
}

/**
 * Singleton WuKongIM client instance.
 * Shared across CLI commands and MCP tools.
 * In MCP mode (long-lived process), the connection persists.
 * In CLI mode, connect → use → disconnect within the command.
 */
let _sharedClient: WuKongIMClient | undefined;

export function getSharedWuKongIMClient(): WuKongIMClient {
  if (!_sharedClient) {
    _sharedClient = new WuKongIMClient();
  }
  return _sharedClient;
}

/**
 * Ensure the shared WuKongIM client is connected.
 * Lazy-connects on first call; reuses existing connection.
 */
export async function ensureWuKongIMConnected(client: TgoClient): Promise<WuKongIMClient> {
  const wkim = getSharedWuKongIMClient();
  if (!wkim.isConnected) {
    await wkim.connect(client);

    // Auto-disconnect on process exit (CLI mode)
    const cleanup = () => {
      wkim.disconnect();
    };
    process.once('exit', cleanup);
    process.once('SIGINT', () => { cleanup(); process.exit(0); });
    process.once('SIGTERM', () => { cleanup(); process.exit(0); });
  }
  return wkim;
}

// -- Helpers --

function tryParseJSON(str: string): unknown {
  try {
    return JSON.parse(str);
  } catch {
    return str;
  }
}

const REASON_CODE_MESSAGES: Record<number, string> = {
  [ReasonCode.Unknown]: 'Unknown error',
  [ReasonCode.AuthFail]: 'Authentication failed',
  [ReasonCode.SubscriberNotExist]: 'Subscriber not exist',
  [ReasonCode.InBlacklist]: 'In blacklist',
  [ReasonCode.ChannelNotExist]: 'Channel not exist',
  [ReasonCode.UserNotOnNode]: 'User not on node',
  [ReasonCode.SenderOffline]: 'Sender offline',
  [ReasonCode.PayloadDecodeError]: 'Payload decode error',
  [ReasonCode.NotAllowSend]: 'Not allowed to send',
  [ReasonCode.ConnectKick]: 'Connection kicked',
  [ReasonCode.NotInWhitelist]: 'Not in whitelist',
  [ReasonCode.SystemError]: 'System error',
  [ReasonCode.ChannelIDError]: 'Channel ID error',
  [ReasonCode.Ban]: 'Channel banned',
  [ReasonCode.RateLimit]: 'Rate limited',
  [ReasonCode.NotSupportChannelType]: 'Unsupported channel type',
  [ReasonCode.Disband]: 'Channel disbanded',
  [ReasonCode.SendBan]: 'Send banned',
};
