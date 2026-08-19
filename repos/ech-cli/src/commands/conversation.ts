import { Command } from 'commander';
import { TgoClient } from '../client.js';
import { resolveOutput, resolveServer } from '../config.js';
import { printError, printResult } from '../output.js';

function makeClient(globals: Record<string, string>) {
  return new TgoClient({ server: resolveServer(globals.server), token: globals.token });
}

export function registerConversationCommands(parent: Command): void {
  const conv = parent.command('conversation').alias('conv').description('Conversation management');

  conv
    .command('list')
    .description('List conversations')
    .option('--scope <scope>', 'Scope: mine, waiting, all', 'mine')
    .option('--limit <n>', 'Limit results', '20')
    .option('--offset <n>', 'Offset', '0')
    .option('--msg-count <n>', 'Messages per conversation', '20')
    .action(async (opts, cmd) => {
      const globals = cmd.parent!.parent!.opts();
      const format = resolveOutput(globals.output);
      try {
        const client = makeClient(globals);
        const result = await conversationList(client, {
          scope: opts.scope,
          limit: parseInt(opts.limit),
          offset: parseInt(opts.offset),
          msgCount: parseInt(opts.msgCount),
        });
        printResult(result, format);
      } catch (err) {
        printError(err, format);
      }
    });

  conv
    .command('accept <visitor-id>')
    .description('Accept a visitor from the waiting queue')
    .action(async (visitorId, _opts, cmd) => {
      const globals = cmd.parent!.parent!.opts();
      const format = resolveOutput(globals.output);
      try {
        const client = makeClient(globals);
        const result = await conversationAccept(client, visitorId);
        printResult(result, format);
      } catch (err) {
        printError(err, format);
      }
    });

  conv
    .command('transfer <visitor-id>')
    .description('Transfer a visitor to another staff')
    .requiredOption('--to <staff-id>', 'Target staff ID')
    .option('--reason <text>', 'Transfer reason')
    .action(async (visitorId, opts, cmd) => {
      const globals = cmd.parent!.parent!.opts();
      const format = resolveOutput(globals.output);
      try {
        const client = makeClient(globals);
        const result = await conversationTransfer(client, visitorId, opts.to, opts.reason);
        printResult(result, format);
      } catch (err) {
        printError(err, format);
      }
    });

  conv
    .command('close <visitor-id>')
    .description('Close a visitor session')
    .action(async (visitorId, _opts, cmd) => {
      const globals = cmd.parent!.parent!.opts();
      const format = resolveOutput(globals.output);
      try {
        const client = makeClient(globals);
        const result = await conversationClose(client, visitorId);
        printResult(result, format);
      } catch (err) {
        printError(err, format);
      }
    });

  conv
    .command('waiting-count')
    .description('Get waiting queue count')
    .action(async (_opts, cmd) => {
      const globals = cmd.parent!.parent!.opts();
      const format = resolveOutput(globals.output);
      try {
        const client = makeClient(globals);
        const result = await conversationWaitingCount(client);
        printResult(result, format);
      } catch (err) {
        printError(err, format);
      }
    });
}

// Standalone action functions for MCP
export async function conversationList(
  client: TgoClient,
  params: { scope?: string; limit?: number; offset?: number; msgCount?: number },
): Promise<unknown> {
  const msgCount = params.msgCount ?? 20;
  const limit = params.limit ?? 20;
  const offset = params.offset ?? 0;
  const scope = params.scope ?? 'mine';

  switch (scope) {
    case 'waiting':
      return client.post(`/v1/conversations/waiting?msg_count=${msgCount}&limit=${limit}&offset=${offset}`, {});
    case 'all':
      return client.post(`/v1/conversations/all`, { msg_count: msgCount, limit, offset });
    default: // mine
      return client.post(`/v1/conversations/my`, { msg_count: msgCount });
  }
}

export async function conversationAccept(client: TgoClient, visitorId: string): Promise<unknown> {
  return client.post(`/v1/visitors/${visitorId}/accept`, {});
}

export async function conversationTransfer(
  client: TgoClient,
  visitorId: string,
  targetStaffId: string,
  reason?: string,
): Promise<unknown> {
  return client.post(`/v1/sessions/visitor/${visitorId}/transfer`, {
    target_staff_id: targetStaffId,
    ...(reason ? { reason } : {}),
  });
}

export async function conversationClose(client: TgoClient, visitorId: string): Promise<unknown> {
  return client.post(`/v1/sessions/visitor/${visitorId}/close`, {});
}

export async function conversationWaitingCount(client: TgoClient): Promise<unknown> {
  return client.get('/v1/visitor-waiting-queue/count');
}
