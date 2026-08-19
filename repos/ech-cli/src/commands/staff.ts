import { Command } from 'commander';
import { TgoClient } from '../client.js';
import { resolveOutput, resolveServer } from '../config.js';
import { printError, printResult } from '../output.js';

function makeClient(globals: Record<string, string>) {
  return new TgoClient({ server: resolveServer(globals.server), token: globals.token });
}

export function registerStaffCommands(parent: Command): void {
  const staff = parent.command('staff').description('Staff management');

  staff
    .command('list')
    .description('List staff members')
    .option('--role <r>', 'Filter by role (user, admin, agent)')
    .option('--status <s>', 'Filter by status (online, offline, busy)')
    .option('--limit <n>', 'Limit', '20')
    .option('--offset <n>', 'Offset', '0')
    .action(async (opts, cmd) => {
      const globals = cmd.parent!.parent!.opts();
      const format = resolveOutput(globals.output);
      try {
        const client = makeClient(globals);
        const result = await staffList(client, {
          role: opts.role,
          status: opts.status,
          limit: parseInt(opts.limit),
          offset: parseInt(opts.offset),
        });
        printResult(result, format);
      } catch (err) {
        printError(err, format);
      }
    });

  staff
    .command('get <id>')
    .description('Get staff details')
    .action(async (id, _opts, cmd) => {
      const globals = cmd.parent!.parent!.opts();
      const format = resolveOutput(globals.output);
      try {
        const client = makeClient(globals);
        const result = await staffGet(client, id);
        printResult(result, format);
      } catch (err) {
        printError(err, format);
      }
    });

  staff
    .command('pause [id]')
    .description('Pause service (self if no ID)')
    .action(async (id, _opts, cmd) => {
      const globals = cmd.parent!.parent!.opts();
      const format = resolveOutput(globals.output);
      try {
        const client = makeClient(globals);
        const result = await staffPause(client, id);
        printResult(result, format);
      } catch (err) {
        printError(err, format);
      }
    });

  staff
    .command('resume [id]')
    .description('Resume service (self if no ID)')
    .action(async (id, _opts, cmd) => {
      const globals = cmd.parent!.parent!.opts();
      const format = resolveOutput(globals.output);
      try {
        const client = makeClient(globals);
        const result = await staffResume(client, id);
        printResult(result, format);
      } catch (err) {
        printError(err, format);
      }
    });
}

// MCP action functions
export async function staffList(
  client: TgoClient,
  params?: { role?: string; status?: string; limit?: number; offset?: number },
): Promise<unknown> {
  const qs = new URLSearchParams();
  if (params?.role) qs.set('role', params.role);
  if (params?.status) qs.set('status', params.status);
  if (params?.limit) qs.set('limit', String(params.limit));
  if (params?.offset) qs.set('offset', String(params.offset));
  const query = qs.toString();
  return client.get(`/v1/staff${query ? `?${query}` : ''}`);
}

export async function staffGet(client: TgoClient, id: string): Promise<unknown> {
  return client.get(`/v1/staff/${id}`);
}

export async function staffPause(client: TgoClient, id?: string): Promise<unknown> {
  if (id) {
    return client.put(`/v1/staff/${id}/service-paused?paused=true`);
  }
  return client.put('/v1/staff/me/service-paused?paused=true');
}

export async function staffResume(client: TgoClient, id?: string): Promise<unknown> {
  if (id) {
    return client.put(`/v1/staff/${id}/service-paused?paused=false`);
  }
  return client.put('/v1/staff/me/service-paused?paused=false');
}
