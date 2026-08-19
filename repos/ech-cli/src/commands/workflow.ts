import { Command } from 'commander';
import { TgoClient } from '../client.js';
import { resolveOutput, resolveServer } from '../config.js';
import { printError, printResult } from '../output.js';

function makeClient(globals: Record<string, string>) {
  return new TgoClient({ server: resolveServer(globals.server), token: globals.token });
}

export function registerWorkflowCommands(parent: Command): void {
  const workflow = parent.command('workflow').alias('wf').description('Workflow management');

  workflow
    .command('list')
    .description('List workflows')
    .option('--limit <n>', 'Limit', '20')
    .option('--offset <n>', 'Offset', '0')
    .action(async (opts, cmd) => {
      const globals = cmd.parent!.parent!.opts();
      const format = resolveOutput(globals.output);
      try {
        const client = makeClient(globals);
        const result = await workflowList(client, {
          limit: parseInt(opts.limit),
          offset: parseInt(opts.offset),
        });
        printResult(result, format);
      } catch (err) {
        printError(err, format);
      }
    });

  workflow
    .command('get <id>')
    .description('Get workflow details')
    .action(async (id, _opts, cmd) => {
      const globals = cmd.parent!.parent!.opts();
      const format = resolveOutput(globals.output);
      try {
        const client = makeClient(globals);
        const result = await workflowGet(client, id);
        printResult(result, format);
      } catch (err) {
        printError(err, format);
      }
    });

  workflow
    .command('execute <id>')
    .description('Execute a workflow')
    .option('--input <json>', 'Input JSON')
    .action(async (id, opts, cmd) => {
      const globals = cmd.parent!.parent!.opts();
      const format = resolveOutput(globals.output);
      try {
        const client = makeClient(globals);
        const input = opts.input ? JSON.parse(opts.input) : undefined;
        const result = await workflowExecute(client, id, input);
        printResult(result, format);
      } catch (err) {
        printError(err, format);
      }
    });

  workflow
    .command('validate <id>')
    .description('Validate a workflow')
    .action(async (id, _opts, cmd) => {
      const globals = cmd.parent!.parent!.opts();
      const format = resolveOutput(globals.output);
      try {
        const client = makeClient(globals);
        const result = await workflowValidate(client, id);
        printResult(result, format);
      } catch (err) {
        printError(err, format);
      }
    });
}

// MCP action functions
export async function workflowList(
  client: TgoClient,
  params?: { limit?: number; offset?: number },
): Promise<unknown> {
  const qs = new URLSearchParams();
  if (params?.limit) qs.set('limit', String(params.limit));
  if (params?.offset) qs.set('offset', String(params.offset));
  const query = qs.toString();
  return client.get(`/v1/ai/workflows${query ? `?${query}` : ''}`);
}

export async function workflowGet(client: TgoClient, id: string): Promise<unknown> {
  return client.get(`/v1/ai/workflows/${id}`);
}

export async function workflowExecute(
  client: TgoClient,
  id: string,
  input?: Record<string, unknown>,
): Promise<unknown> {
  return client.post(`/v1/ai/workflows/${id}/execute`, { inputs: input || {} });
}

export async function workflowValidate(client: TgoClient, id: string): Promise<unknown> {
  return client.post(`/v1/ai/workflows/${id}/validate`, {});
}
