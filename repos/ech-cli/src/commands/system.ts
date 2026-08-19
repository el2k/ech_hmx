import { Command } from 'commander';
import { TgoClient } from '../client.js';
import { resolveOutput, resolveServer } from '../config.js';
import { printError, printResult } from '../output.js';

export function registerSystemCommands(parent: Command): void {
  const system = parent.command('system').description('System commands');

  system
    .command('info')
    .description('Get system information')
    .action(async (_opts, cmd) => {
      const globals = cmd.parent!.parent!.opts();
      const format = resolveOutput(globals.output);
      try {
        const server = resolveServer(globals.server);
        if (!server) throw new Error('Server URL required.');
        // system info is unauthenticated
        const res = await fetch(`${server.replace(/\/+$/, '')}/v1/system/info`);
        const data = await res.json();
        printResult(data, format);
      } catch (err) {
        printError(err, format);
      }
    });
}

// MCP action function
export async function systemInfo(server: string): Promise<unknown> {
  const res = await fetch(`${server.replace(/\/+$/, '')}/v1/system/info`);
  return res.json();
}
