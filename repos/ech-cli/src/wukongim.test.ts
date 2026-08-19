import { describe, it, expect, vi, beforeEach } from 'vitest';
import type { TgoClient } from './client.js';

// Mock easyjssdk
const mockSend = vi.fn();
const mockConnect = vi.fn();
const mockDisconnect = vi.fn();
const mockOn = vi.fn();

vi.mock('easyjssdk', () => ({
  WKIM: {
    init: vi.fn(() => ({
      connect: mockConnect,
      disconnect: mockDisconnect,
      send: mockSend,
      on: mockOn,
      off: vi.fn(),
      isConnected: true,
    })),
  },
  WKIMEvent: {
    Connect: 'connect',
    Disconnect: 'disconnect',
    Message: 'message',
    Error: 'error',
    CustomEvent: 'customevent',
  },
  WKIMChannelType: {
    Person: 1,
    Group: 2,
  },
  ReasonCode: {
    Unknown: 0,
    Success: 1,
    AuthFail: 2,
    ChannelNotExist: 5,
    NotAllowSend: 11,
  },
}));

function mockClient(): TgoClient {
  return {
    get: vi.fn()
      .mockResolvedValueOnce({ id: 'user-123' }) // GET /v1/staff/me
      .mockResolvedValueOnce({ tcp_addr: '', ws_addr: 'ws://localhost:5100', wss_addr: '' }), // GET /v1/wukongim/route
    token: 'jwt-token',
    serverUrl: 'http://localhost:8000',
    requireAuth: vi.fn(),
  } as unknown as TgoClient;
}

describe('WuKongIMClient', () => {
  beforeEach(() => {
    mockSend.mockReset().mockResolvedValue({
      messageId: 'msg-1',
      messageSeq: 42,
      reasonCode: 1,
    });
    mockConnect.mockReset().mockResolvedValue(undefined);
    mockDisconnect.mockReset();
    mockOn.mockReset();
  });

  it('connect should fetch user info, route, and connect WKIM', async () => {
    // Dynamic import to get fresh module (needed because of singleton)
    vi.resetModules();
    const { WuKongIMClient } = await import('./wukongim.js');
    const wkim = new WuKongIMClient();
    const client = mockClient();

    await wkim.connect(client);

    expect(client.get).toHaveBeenCalledWith('/v1/staff/me');
    expect(client.get).toHaveBeenCalledWith('/v1/wukongim/route?uid=user-123-staff');
    expect(mockConnect).toHaveBeenCalled();
    expect(wkim.isConnected).toBe(true);
    expect(wkim.uid).toBe('user-123-staff');
  });

  it('send should call WKIM send with correct parameters', async () => {
    vi.resetModules();
    const { WuKongIMClient } = await import('./wukongim.js');
    const wkim = new WuKongIMClient();
    const client = mockClient();
    await wkim.connect(client);

    const result = await wkim.send('ch-1', 1, { content: 'Hello', type: 1 }, 'msg-no-1');

    expect(mockSend).toHaveBeenCalledWith('ch-1', 1, { content: 'Hello', type: 1 }, { clientMsgNo: 'msg-no-1' });
    expect(result.messageId).toBe('msg-1');
    expect(result.messageSeq).toBe(42);
  });

  it('send should throw if not connected', async () => {
    vi.resetModules();
    const { WuKongIMClient } = await import('./wukongim.js');
    const wkim = new WuKongIMClient();

    await expect(wkim.send('ch-1', 1, { content: 'Hello', type: 1 }))
      .rejects.toThrow('WuKongIM not connected');
  });

  it('send should throw on non-success reason code', async () => {
    mockSend.mockResolvedValueOnce({
      messageId: 'msg-2',
      messageSeq: 43,
      reasonCode: 11, // NotAllowSend
    });

    vi.resetModules();
    const { WuKongIMClient } = await import('./wukongim.js');
    const wkim = new WuKongIMClient();
    const client = mockClient();
    await wkim.connect(client);

    await expect(wkim.send('ch-1', 1, { content: 'test', type: 1 }))
      .rejects.toThrow('Not allowed to send');
  });

  it('disconnect should clean up', async () => {
    vi.resetModules();
    const { WuKongIMClient } = await import('./wukongim.js');
    const wkim = new WuKongIMClient();
    const client = mockClient();
    await wkim.connect(client);

    wkim.disconnect();

    expect(mockDisconnect).toHaveBeenCalled();
    expect(wkim.isConnected).toBe(false);
    expect(wkim.uid).toBeUndefined();
  });

  it('onMessage should register handler and return unsub', async () => {
    vi.resetModules();
    const { WuKongIMClient } = await import('./wukongim.js');
    const wkim = new WuKongIMClient();
    const handler = vi.fn();

    const unsub = wkim.onMessage(handler);
    expect(typeof unsub).toBe('function');
    unsub();
  });

  it('connect should skip if already connected', async () => {
    vi.resetModules();
    const { WuKongIMClient } = await import('./wukongim.js');
    const wkim = new WuKongIMClient();
    const client = mockClient();
    await wkim.connect(client);

    // Reset client mock to verify no second call
    (client.get as any).mockClear();

    // Second connect should be a no-op
    await wkim.connect(client);
    expect(client.get).not.toHaveBeenCalled();
  });
});
