import { readFileSync } from 'node:fs';
import { basename } from 'node:path';
import { Command } from 'commander';
import { TgoClient } from '../client.js';
import { resolveOutput, resolveServer } from '../config.js';
import { printError, printResult } from '../output.js';

function makeClient(globals: Record<string, string>) {
  return new TgoClient({ server: resolveServer(globals.server), token: globals.token });
}

export function registerKnowledgeCommands(parent: Command): void {
  const knowledge = parent.command('knowledge').alias('kb').description('Knowledge base management');

  knowledge
    .command('list')
    .description('List knowledge collections')
    .option('--limit <n>', 'Limit', '20')
    .option('--offset <n>', 'Offset', '0')
    .action(async (opts, cmd) => {
      const globals = cmd.parent!.parent!.opts();
      const format = resolveOutput(globals.output);
      try {
        const client = makeClient(globals);
        const result = await knowledgeList(client, {
          limit: parseInt(opts.limit),
          offset: parseInt(opts.offset),
        });
        printResult(result, format);
      } catch (err) {
        printError(err, format);
      }
    });

  knowledge
    .command('get <id>')
    .description('Get collection details')
    .action(async (id, _opts, cmd) => {
      const globals = cmd.parent!.parent!.opts();
      const format = resolveOutput(globals.output);
      try {
        const client = makeClient(globals);
        const result = await knowledgeGet(client, id);
        printResult(result, format);
      } catch (err) {
        printError(err, format);
      }
    });

  knowledge
    .command('create')
    .description('Create a knowledge collection')
    .requiredOption('--name <n>', 'Collection name')
    .option('--description <d>', 'Description')
    .action(async (opts, cmd) => {
      const globals = cmd.parent!.parent!.opts();
      const format = resolveOutput(globals.output);
      try {
        const client = makeClient(globals);
        const result = await knowledgeCreate(client, {
          display_name: opts.name,
          description: opts.description,
        });
        printResult(result, format);
      } catch (err) {
        printError(err, format);
      }
    });

  knowledge
    .command('search <collection-id>')
    .description('Search documents in a collection')
    .requiredOption('--query <text>', 'Search query')
    .option('--limit <n>', 'Limit results', '10')
    .action(async (collectionId, opts, cmd) => {
      const globals = cmd.parent!.parent!.opts();
      const format = resolveOutput(globals.output);
      try {
        const client = makeClient(globals);
        const result = await knowledgeSearch(client, collectionId, {
          query: opts.query,
          limit: parseInt(opts.limit),
        });
        printResult(result, format);
      } catch (err) {
        printError(err, format);
      }
    });

  knowledge
    .command('upload <collection-id> <file-path>')
    .description('Upload a file to a collection')
    .action(async (collectionId, filePath, _opts, cmd) => {
      const globals = cmd.parent!.parent!.opts();
      const format = resolveOutput(globals.output);
      try {
        const client = makeClient(globals);
        const result = await knowledgeUpload(client, collectionId, filePath);
        printResult(result, format);
      } catch (err) {
        printError(err, format);
      }
    });

  knowledge
    .command('delete <id>')
    .description('Delete a knowledge collection')
    .action(async (id, _opts, cmd) => {
      const globals = cmd.parent!.parent!.opts();
      const format = resolveOutput(globals.output);
      try {
        const client = makeClient(globals);
        await knowledgeDelete(client, id);
        printResult({ success: true, message: `Collection ${id} deleted` }, format);
      } catch (err) {
        printError(err, format);
      }
    });
}

// MCP action functions
export async function knowledgeList(
  client: TgoClient,
  params?: { limit?: number; offset?: number },
): Promise<unknown> {
  const qs = new URLSearchParams();
  if (params?.limit) qs.set('limit', String(params.limit));
  if (params?.offset) qs.set('offset', String(params.offset));
  const query = qs.toString();
  return client.get(`/v1/rag/collections${query ? `?${query}` : ''}`);
}

export async function knowledgeGet(client: TgoClient, id: string): Promise<unknown> {
  return client.get(`/v1/rag/collections/${id}`);
}

export async function knowledgeCreate(
  client: TgoClient,
  data: { display_name: string; description?: string },
): Promise<unknown> {
  return client.post('/v1/rag/collections', data);
}

export async function knowledgeSearch(
  client: TgoClient,
  collectionId: string,
  params: { query: string; limit?: number },
): Promise<unknown> {
  return client.post(`/v1/rag/collections/${collectionId}/documents/search`, {
    query: params.query,
    limit: params.limit ?? 10,
  });
}

export async function knowledgeUpload(
  client: TgoClient,
  collectionId: string,
  filePath: string,
): Promise<unknown> {
  const fileBuffer = readFileSync(filePath);
  const fileName = basename(filePath);
  const blob = new Blob([fileBuffer]);
  const formData = new FormData();
  formData.append('file', blob, fileName);
  formData.append('collection_id', collectionId);
  return client.postFormData('/v1/rag/files', formData);
}

export async function knowledgeDelete(client: TgoClient, id: string): Promise<unknown> {
  return client.delete(`/v1/rag/collections/${id}`);
}
