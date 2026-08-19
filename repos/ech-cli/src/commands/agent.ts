import { Command } from 'commander';
import { TgoClient } from '../client.js';
import { resolveOutput, resolveServer } from '../config.js';
import { printError, printResult } from '../output.js';

function makeClient(globals: Record<string, string>) {
  return new TgoClient({ server: resolveServer(globals.server), token: globals.token });
}

export function registerAgentCommands(parent: Command): void {
  const agent = parent.command('agent').description('AI Agent management');

  agent
    .command('list')
    .description('List AI agents')
    .option('--limit <n>', 'Limit', '20')
    .option('--offset <n>', 'Offset', '0')
    .action(async (opts, cmd) => {
      const globals = cmd.parent!.parent!.opts();
      const format = resolveOutput(globals.output);
      try {
        const client = makeClient(globals);
        const result = await agentList(client, {
          limit: parseInt(opts.limit),
          offset: parseInt(opts.offset),
        });
        printResult(result, format);
      } catch (err) {
        printError(err, format);
      }
    });

  agent
    .command('get <id>')
    .description('Get agent details')
    .action(async (id, _opts, cmd) => {
      const globals = cmd.parent!.parent!.opts();
      const format = resolveOutput(globals.output);
      try {
        const client = makeClient(globals);
        const result = await agentGet(client, id);
        printResult(result, format);
      } catch (err) {
        printError(err, format);
      }
    });

  agent
    .command('create')
    .description('Create a new AI agent')
    .requiredOption('--name <n>', 'Agent name')
    .requiredOption('--model <m>', 'Model (e.g. openai:gpt-4)')
    .option('--instructions <text>', 'Agent instructions')
    .option('--provider-id <id>', 'AI provider ID')
    .action(async (opts, cmd) => {
      const globals = cmd.parent!.parent!.opts();
      const format = resolveOutput(globals.output);
      try {
        const client = makeClient(globals);
        const result = await agentCreate(client, {
          name: opts.name,
          model: opts.model,
          instruction: opts.instructions,
          ai_provider_id: opts.providerId,
        });
        printResult(result, format);
      } catch (err) {
        printError(err, format);
      }
    });

  agent
    .command('update <id>')
    .description('Update an AI agent')
    .option('--name <n>', 'Agent name')
    .option('--model <m>', 'Model')
    .option('--instructions <text>', 'Agent instructions')
    .action(async (id, opts, cmd) => {
      const globals = cmd.parent!.parent!.opts();
      const format = resolveOutput(globals.output);
      try {
        const client = makeClient(globals);
        const data: Record<string, unknown> = {};
        if (opts.name) data.name = opts.name;
        if (opts.model) data.model = opts.model;
        if (opts.instructions) data.instruction = opts.instructions;
        const result = await agentUpdate(client, id, data);
        printResult(result, format);
      } catch (err) {
        printError(err, format);
      }
    });

  agent
    .command('delete <id>')
    .description('Delete an AI agent')
    .action(async (id, _opts, cmd) => {
      const globals = cmd.parent!.parent!.opts();
      const format = resolveOutput(globals.output);
      try {
        const client = makeClient(globals);
        await agentDelete(client, id);
        printResult({ success: true, message: `Agent ${id} deleted` }, format);
      } catch (err) {
        printError(err, format);
      }
    });
}

// MCP action functions
export async function agentList(
  client: TgoClient,
  params?: { limit?: number; offset?: number },
): Promise<unknown> {
  const qs = new URLSearchParams();
  if (params?.limit) qs.set('limit', String(params.limit));
  if (params?.offset) qs.set('offset', String(params.offset));
  const query = qs.toString();
  return client.get(`/v1/ai/agents${query ? `?${query}` : ''}`);
}

export async function agentGet(client: TgoClient, id: string): Promise<unknown> {
  return client.get(`/v1/ai/agents/${id}`);
}

export async function agentCreate(
  client: TgoClient,
  data: { name: string; model: string; instruction?: string; ai_provider_id?: string },
): Promise<unknown> {
  return client.post('/v1/ai/agents', data);
}

export async function agentUpdate(
  client: TgoClient,
  id: string,
  data: Record<string, unknown>,
): Promise<unknown> {
  return client.patch(`/v1/ai/agents/${id}`, data);
}

export async function agentDelete(client: TgoClient, id: string): Promise<unknown> {
  return client.delete(`/v1/ai/agents/${id}`);
}
