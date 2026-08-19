import { Command } from 'commander';
import { TgoClient } from '../client.js';
import { resolveOutput, resolveServer } from '../config.js';
import { printError, printResult } from '../output.js';
import { ensureWuKongIMConnected, getSharedWuKongIMClient } from '../wukongim.js';

function makeClient(globals: Record<string, string>) {
  return new TgoClient({ server: resolveServer(globals.server), token: globals.token });
}

export function registerChatCommands(parent: Command): void {
  const chat = parent.command('chat').description('Chat messaging');

  chat
    .command('send')
    .description('Send a message via WuKongIM WebSocket (works for all platform types)')
    .requiredOption('--channel <id>', 'Channel ID')
    .requiredOption('--type <n>', 'Channel type (e.g. 1=person, 2=group)')
    .requiredOption('--message <text>', 'Message text')
    .action(async (opts, cmd) => {
      const globals = cmd.parent!.parent!.opts();
      const format = resolveOutput(globals.output);
      let result: unknown;
      let error: unknown;
      try {
        const client = makeClient(globals);
        result = await chatSend(client, {
          channel_id: opts.channel,
          channel_type: parseInt(opts.type),
          message: opts.message,
        });
      } catch (err) {
        error = err;
      }
      // Disconnect first (while logs are still suppressed), then restore and print
      getSharedWuKongIMClient().disconnect();
      if (error) {
        printError(error, format);
      } else {
        printResult(result, format);
      }
    });

  chat
    .command('agent')
    .description('Chat with AI agent')
    .requiredOption('--message <text>', 'Message')
    .requiredOption('--agent <id>', 'Agent ID')
    .action(async (opts, cmd) => {
      const globals = cmd.parent!.parent!.opts();
      const format = resolveOutput(globals.output);
      try {
        const client = makeClient(globals);
        const result = await chatAgent(client, {
          message: opts.message,
          agent_id: opts.agent,
        });
        printResult(result, format);
      } catch (err) {
        printError(err, format);
      }
    });

  chat
    .command('clear-memory')
    .description('Clear AI memory for a channel')
    .requiredOption('--channel <id>', 'Channel ID')
    .requiredOption('--type <n>', 'Channel type')
    .action(async (opts, cmd) => {
      const globals = cmd.parent!.parent!.opts();
      const format = resolveOutput(globals.output);
      try {
        const client = makeClient(globals);
        const result = await chatClearMemory(client, {
          channel_id: opts.channel,
          channel_type: parseInt(opts.type),
        });
        printResult(result, format);
      } catch (err) {
        printError(err, format);
      }
    });

  chat
    .command('listen')
    .description('Listen for incoming messages via WuKongIM WebSocket (JSONL output)')
    .option('--channel <id>', 'Filter by channel ID')
    .option('--events', 'Also print custom events (AI streaming, presence, etc)')
    .action(async (opts, cmd) => {
      const globals = cmd.parent!.parent!.opts();
      try {
        const client = makeClient(globals);
        await chatListen(client, {
          channel_id: opts.channel,
          include_events: opts.events,
        });
      } catch (err) {
        printError(err, resolveOutput(globals.output));
      }
    });
}

// -- MCP action functions --

/**
 * Send a message via WuKongIM WebSocket.
 * This is the universal send path - works for all platform types including website.
 * Mirrors tgo-web's ChatWindow.tsx sendWsMessage flow.
 */
export async function chatSend(
  client: TgoClient,
  params: { channel_id: string; channel_type: number; message: string },
): Promise<unknown> {
  const wkim = await ensureWuKongIMConnected(client);

  // Build payload matching tgo-web's format
  const payload = { content: params.message, type: 1 };
  const clientMsgNo = generateClientMsgNo();

  const result = await wkim.send(
    params.channel_id,
    params.channel_type,
    payload,
    clientMsgNo,
  );

  return {
    messageId: result.messageId,
    messageSeq: result.messageSeq,
    clientMsgNo,
    status: 'sent',
  };
}

/**
 * Send a message to a non-website platform channel via HTTP API.
 * For platforms like WeChat/LINE, the HTTP API forwards to the external platform.
 * This is an additional path alongside WebSocket for non-website platforms.
 */
export async function chatSendPlatform(
  client: TgoClient,
  params: { channel_id: string; channel_type: number; message: string; client_msg_no?: string },
): Promise<unknown> {
  return client.post('/v1/chat/messages/send', {
    channel_id: params.channel_id,
    channel_type: params.channel_type,
    payload: { content: params.message, type: 1 },
    client_msg_no: params.client_msg_no,
  });
}

export async function chatAgent(
  client: TgoClient,
  params: { message: string; agent_id: string },
): Promise<unknown> {
  return client.post('/v1/chat/agent', {
    message: params.message,
    agent_id: params.agent_id,
  });
}

export async function chatClearMemory(
  client: TgoClient,
  params: { channel_id: string; channel_type: number },
): Promise<unknown> {
  return client.delete(`/v1/chat/memory?channel_id=${params.channel_id}&channel_type=${params.channel_type}`);
}

/**
 * Listen for incoming messages and events via WuKongIM WebSocket.
 * Prints each message/event as a JSON line to stdout.
 * Runs until the process is terminated (Ctrl+C).
 */
export async function chatListen(
  client: TgoClient,
  params?: { channel_id?: string; include_events?: boolean },
): Promise<void> {
  const wkim = await ensureWuKongIMConnected(client);

  console.error(`Connected as ${wkim.uid}. Listening for messages... (Ctrl+C to stop)`);

  // Message handler
  wkim.onMessage((msg) => {
    if (params?.channel_id && msg.channelId !== params.channel_id) {
      return; // Filter by channel
    }
    const line = JSON.stringify({
      type: 'message',
      messageId: msg.messageId,
      messageSeq: msg.messageSeq,
      timestamp: msg.timestamp,
      channelId: msg.channelId,
      channelType: msg.channelType,
      fromUid: msg.fromUid,
      payload: msg.payload,
      clientMsgNo: msg.clientMsgNo,
    });
    console.log(line);
  });

  // Event handler (optional)
  if (params?.include_events) {
    wkim.onEvent((evt) => {
      const line = JSON.stringify({
        type: 'event',
        id: evt.id,
        eventType: evt.type,
        timestamp: evt.timestamp,
        data: evt.data,
      });
      console.log(line);
    });
  }

  // Keep the process alive
  await new Promise<void>(() => {
    // Never resolves - waits for SIGINT/SIGTERM
  });
}

// -- Helpers --

function generateClientMsgNo(): string {
  // Simple UUID v4-like generator (no crypto dependency)
  return 'xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx'.replace(/[xy]/g, (c) => {
    const r = (Math.random() * 16) | 0;
    const v = c === 'x' ? r : (r & 0x3) | 0x8;
    return v.toString(16);
  });
}
