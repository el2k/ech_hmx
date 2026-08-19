import { existsSync, mkdirSync, readFileSync, writeFileSync } from 'node:fs';
import { homedir } from 'node:os';
import { dirname, join } from 'node:path';

export interface TgoConfig {
  server?: string;
  token?: string;
  output?: 'json' | 'table' | 'compact';
}

const CONFIG_DIR = join(homedir(), '.tgo');
const CONFIG_PATH = join(CONFIG_DIR, 'config.json');

export function loadConfig(): TgoConfig {
  if (!existsSync(CONFIG_PATH)) return {};
  try {
    return JSON.parse(readFileSync(CONFIG_PATH, 'utf-8'));
  } catch {
    return {};
  }
}

export function saveConfig(config: TgoConfig): void {
  mkdirSync(dirname(CONFIG_PATH), { recursive: true });
  writeFileSync(CONFIG_PATH, JSON.stringify(config, null, 2) + '\n');
}

export function updateConfig(patch: Partial<TgoConfig>): void {
  const config = loadConfig();
  Object.assign(config, patch);
  // Remove undefined/null values
  for (const key of Object.keys(config) as (keyof TgoConfig)[]) {
    if (config[key] == null) delete config[key];
  }
  saveConfig(config);
}

/** Resolve a setting with priority: CLI flag > env var > config file */
export function resolveServer(flag?: string): string | undefined {
  return flag || process.env.TGO_SERVER || loadConfig().server;
}

export function resolveToken(flag?: string): string | undefined {
  return flag || process.env.TGO_TOKEN || loadConfig().token;
}

export function resolveOutput(flag?: string): 'json' | 'table' | 'compact' {
  const v = flag || process.env.TGO_OUTPUT || loadConfig().output;
  if (v === 'table' || v === 'compact') return v;
  return 'json';
}
