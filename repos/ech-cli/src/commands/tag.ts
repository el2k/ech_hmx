import { Command } from 'commander';
import { TgoClient } from '../client.js';
import { resolveOutput, resolveServer } from '../config.js';
import { printError, printResult } from '../output.js';

function makeClient(globals: Record<string, string>) {
  return new TgoClient({ server: resolveServer(globals.server), token: globals.token });
}

export function registerTagCommands(parent: Command): void {
  const tag = parent.command('tag').description('Tag management');

  tag
    .command('list')
    .description('List tags')
    .option('--category <cat>', 'Filter by category (visitor, knowledge)')
    .action(async (opts, cmd) => {
      const globals = cmd.parent!.parent!.opts();
      const format = resolveOutput(globals.output);
      try {
        const client = makeClient(globals);
        const result = await tagList(client, { category: opts.category });
        printResult(result, format);
      } catch (err) {
        printError(err, format);
      }
    });

  tag
    .command('create')
    .description('Create a tag')
    .requiredOption('--name <n>', 'Tag name')
    .option('--category <cat>', 'Category (visitor, knowledge)', 'visitor')
    .option('--color <hex>', 'Color hex')
    .action(async (opts, cmd) => {
      const globals = cmd.parent!.parent!.opts();
      const format = resolveOutput(globals.output);
      try {
        const client = makeClient(globals);
        const result = await tagCreate(client, {
          name: opts.name,
          category: opts.category,
          color: opts.color,
        });
        printResult(result, format);
      } catch (err) {
        printError(err, format);
      }
    });

  tag
    .command('delete <id>')
    .description('Delete a tag')
    .action(async (id, _opts, cmd) => {
      const globals = cmd.parent!.parent!.opts();
      const format = resolveOutput(globals.output);
      try {
        const client = makeClient(globals);
        await tagDelete(client, id);
        printResult({ success: true, message: `Tag ${id} deleted` }, format);
      } catch (err) {
        printError(err, format);
      }
    });
}

// MCP action functions
export async function tagList(
  client: TgoClient,
  params?: { category?: string },
): Promise<unknown> {
  const qs = new URLSearchParams();
  if (params?.category) qs.set('category', params.category);
  const query = qs.toString();
  return client.get(`/v1/tags${query ? `?${query}` : ''}`);
}

export async function tagCreate(
  client: TgoClient,
  data: { name: string; category?: string; color?: string },
): Promise<unknown> {
  return client.post('/v1/tags', data);
}

export async function tagDelete(client: TgoClient, id: string): Promise<unknown> {
  return client.delete(`/v1/tags/${id}`);
}
