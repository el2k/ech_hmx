import { Command } from 'commander';
import { TgoClient } from '../client.js';
import { resolveOutput, resolveServer } from '../config.js';
import { printError, printResult } from '../output.js';

function makeClient(globals: Record<string, string>) {
  return new TgoClient({ server: resolveServer(globals.server), token: globals.token });
}

export function registerVisitorCommands(parent: Command): void {
  const visitor = parent.command('visitor').description('Visitor management');

  visitor
    .command('list')
    .description('List visitors')
    .option('--online', 'Only online visitors')
    .option('--search <q>', 'Search query')
    .option('--tag <id>', 'Filter by tag ID (can repeat)', (val, prev: string[]) => [...prev, val], [] as string[])
    .option('--platform <id>', 'Filter by platform ID')
    .option('--limit <n>', 'Limit', '20')
    .option('--offset <n>', 'Offset', '0')
    .action(async (opts, cmd) => {
      const globals = cmd.parent!.parent!.opts();
      const format = resolveOutput(globals.output);
      try {
        const client = makeClient(globals);
        const result = await visitorList(client, {
          is_online: opts.online,
          search: opts.search,
          tag_ids: opts.tag,
          platform_id: opts.platform,
          limit: parseInt(opts.limit),
          offset: parseInt(opts.offset),
        });
        printResult(result, format);
      } catch (err) {
        printError(err, format);
      }
    });

  visitor
    .command('get <id>')
    .description('Get visitor details')
    .action(async (id, _opts, cmd) => {
      const globals = cmd.parent!.parent!.opts();
      const format = resolveOutput(globals.output);
      try {
        const client = makeClient(globals);
        const result = await visitorGet(client, id);
        printResult(result, format);
      } catch (err) {
        printError(err, format);
      }
    });

  visitor
    .command('update <id>')
    .description('Update visitor attributes')
    .option('--name <n>', 'Name')
    .option('--email <e>', 'Email')
    .option('--phone <p>', 'Phone number')
    .option('--company <c>', 'Company')
    .option('--note <text>', 'Note')
    .action(async (id, opts, cmd) => {
      const globals = cmd.parent!.parent!.opts();
      const format = resolveOutput(globals.output);
      try {
        const client = makeClient(globals);
        const attrs: Record<string, string> = {};
        if (opts.name) attrs.name = opts.name;
        if (opts.email) attrs.email = opts.email;
        if (opts.phone) attrs.phone_number = opts.phone;
        if (opts.company) attrs.company = opts.company;
        if (opts.note) attrs.note = opts.note;
        const result = await visitorUpdate(client, id, attrs);
        printResult(result, format);
      } catch (err) {
        printError(err, format);
      }
    });

  visitor
    .command('enable-ai <id>')
    .description('Enable AI for visitor')
    .action(async (id, _opts, cmd) => {
      const globals = cmd.parent!.parent!.opts();
      const format = resolveOutput(globals.output);
      try {
        const client = makeClient(globals);
        const result = await visitorEnableAi(client, id);
        printResult(result, format);
      } catch (err) {
        printError(err, format);
      }
    });

  visitor
    .command('disable-ai <id>')
    .description('Disable AI for visitor')
    .action(async (id, _opts, cmd) => {
      const globals = cmd.parent!.parent!.opts();
      const format = resolveOutput(globals.output);
      try {
        const client = makeClient(globals);
        const result = await visitorDisableAi(client, id);
        printResult(result, format);
      } catch (err) {
        printError(err, format);
      }
    });
}

// MCP action functions
export async function visitorList(
  client: TgoClient,
  params: {
    is_online?: boolean;
    search?: string;
    tag_ids?: string[];
    platform_id?: string;
    limit?: number;
    offset?: number;
  },
): Promise<unknown> {
  const qs = new URLSearchParams();
  if (params.is_online) qs.set('is_online', 'true');
  if (params.search) qs.set('search', params.search);
  if (params.platform_id) qs.set('platform_id', params.platform_id);
  if (params.limit) qs.set('limit', String(params.limit));
  if (params.offset) qs.set('offset', String(params.offset));
  if (params.tag_ids) {
    for (const id of params.tag_ids) qs.append('tag_ids', id);
  }
  const query = qs.toString();
  return client.get(`/v1/visitors${query ? `?${query}` : ''}`);
}

export async function visitorGet(client: TgoClient, id: string): Promise<unknown> {
  return client.get(`/v1/visitors/${id}`);
}

export async function visitorUpdate(
  client: TgoClient,
  id: string,
  attributes: Record<string, unknown>,
): Promise<unknown> {
  return client.put(`/v1/visitors/${id}/attributes`, attributes);
}

export async function visitorEnableAi(client: TgoClient, id: string): Promise<unknown> {
  return client.post(`/v1/visitors/${id}/enable-ai`, {});
}

export async function visitorDisableAi(client: TgoClient, id: string): Promise<unknown> {
  return client.post(`/v1/visitors/${id}/disable-ai`, {});
}
