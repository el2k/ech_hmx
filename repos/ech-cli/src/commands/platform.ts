import { Command } from 'commander';
import { TgoClient } from '../client.js';
import { resolveOutput, resolveServer } from '../config.js';
import { printError, printResult } from '../output.js';

function makeClient(globals: Record<string, string>) {
  return new TgoClient({ server: resolveServer(globals.server), token: globals.token });
}

export function registerPlatformCommands(parent: Command): void {
  const platform = parent.command('platform').description('Platform management');

  platform
    .command('list')
    .description('List platforms')
    .action(async (_opts, cmd) => {
      const globals = cmd.parent!.parent!.opts();
      const format = resolveOutput(globals.output);
      try {
        const client = makeClient(globals);
        const result = await platformList(client);
        printResult(result, format);
      } catch (err) {
        printError(err, format);
      }
    });

  platform
    .command('get <id>')
    .description('Get platform details')
    .action(async (id, _opts, cmd) => {
      const globals = cmd.parent!.parent!.opts();
      const format = resolveOutput(globals.output);
      try {
        const client = makeClient(globals);
        const result = await platformGet(client, id);
        printResult(result, format);
      } catch (err) {
        printError(err, format);
      }
    });
}

// MCP action functions
export async function platformList(client: TgoClient): Promise<unknown> {
  return client.get('/v1/platforms');
}

export async function platformGet(client: TgoClient, id: string): Promise<unknown> {
  return client.get(`/v1/platforms/${id}`);
}
