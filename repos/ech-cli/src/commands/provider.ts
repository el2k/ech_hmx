import { Command } from 'commander';
import { TgoClient } from '../client.js';
import { resolveOutput, resolveServer } from '../config.js';
import { printError, printResult } from '../output.js';

function makeClient(globals: Record<string, string>) {
  return new TgoClient({ server: resolveServer(globals.server), token: globals.token });
}

export function registerProviderCommands(parent: Command): void {
  const provider = parent.command('provider').description('AI Provider management');

  provider
    .command('list')
    .description('List AI providers')
    .action(async (_opts, cmd) => {
      const globals = cmd.parent!.parent!.opts();
      const format = resolveOutput(globals.output);
      try {
        const client = makeClient(globals);
        const result = await providerList(client);
        printResult(result, format);
      } catch (err) {
        printError(err, format);
      }
    });

  provider
    .command('create')
    .description('Create a new AI provider')
    .requiredOption('--name <n>', 'Provider name')
    .requiredOption('--provider <type>', 'Provider type (openai, azure, qwen, etc.)')
    .requiredOption('--api-key <key>', 'API key')
    .option('--api-base <url>', 'Custom API base URL')
    .action(async (opts, cmd) => {
      const globals = cmd.parent!.parent!.opts();
      const format = resolveOutput(globals.output);
      try {
        const client = makeClient(globals);
        const result = await providerCreate(client, {
          name: opts.name,
          provider_type: opts.provider,
          api_key: opts.apiKey,
          api_base: opts.apiBase,
        });
        printResult(result, format);
      } catch (err) {
        printError(err, format);
      }
    });

  provider
    .command('test <id>')
    .description('Test an AI provider connection')
    .action(async (id, _opts, cmd) => {
      const globals = cmd.parent!.parent!.opts();
      const format = resolveOutput(globals.output);
      try {
        const client = makeClient(globals);
        const result = await providerTest(client, id);
        printResult(result, format);
      } catch (err) {
        printError(err, format);
      }
    });

  provider
    .command('enable <id>')
    .description('Enable an AI provider')
    .action(async (id, _opts, cmd) => {
      const globals = cmd.parent!.parent!.opts();
      const format = resolveOutput(globals.output);
      try {
        const client = makeClient(globals);
        const result = await providerEnable(client, id);
        printResult(result, format);
      } catch (err) {
        printError(err, format);
      }
    });

  provider
    .command('disable <id>')
    .description('Disable an AI provider')
    .action(async (id, _opts, cmd) => {
      const globals = cmd.parent!.parent!.opts();
      const format = resolveOutput(globals.output);
      try {
        const client = makeClient(globals);
        const result = await providerDisable(client, id);
        printResult(result, format);
      } catch (err) {
        printError(err, format);
      }
    });
}

// MCP action functions
export async function providerList(client: TgoClient): Promise<unknown> {
  return client.get('/v1/ai/providers');
}

export async function providerCreate(
  client: TgoClient,
  data: { name: string; provider_type: string; api_key: string; api_base?: string },
): Promise<unknown> {
  return client.post('/v1/ai/providers', data);
}

export async function providerTest(client: TgoClient, id: string): Promise<unknown> {
  return client.post(`/v1/ai/providers/${id}/test`, {});
}

export async function providerEnable(client: TgoClient, id: string): Promise<unknown> {
  return client.post(`/v1/ai/providers/${id}/enable`, {});
}

export async function providerDisable(client: TgoClient, id: string): Promise<unknown> {
  return client.post(`/v1/ai/providers/${id}/disable`, {});
}
