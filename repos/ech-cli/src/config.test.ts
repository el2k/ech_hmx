import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { join } from 'node:path';

// Mock fs before importing config
vi.mock('node:fs', async (importOriginal) => {
  const actual = await importOriginal<typeof import('node:fs')>();
  return {
    ...actual,
    existsSync: vi.fn(),
    readFileSync: vi.fn(),
    writeFileSync: vi.fn(),
    mkdirSync: vi.fn(),
  };
});

// Mock os.homedir to use a temp path
vi.mock('node:os', async (importOriginal) => {
  const actual = await importOriginal<typeof import('node:os')>();
  return {
    ...actual,
    homedir: vi.fn(() => '/tmp/tgo-test-home'),
  };
});

import { existsSync, readFileSync, writeFileSync, mkdirSync } from 'node:fs';
import {
  loadConfig,
  saveConfig,
  updateConfig,
  resolveServer,
  resolveToken,
  resolveOutput,
} from './config.js';

describe('config', () => {
  const CONFIG_PATH = join('/tmp/tgo-test-home', '.tgo', 'config.json');

  beforeEach(() => {
    vi.mocked(existsSync).mockReturnValue(false);
    vi.mocked(readFileSync).mockReturnValue('{}');
    vi.mocked(writeFileSync).mockImplementation(() => {});
    vi.mocked(mkdirSync).mockImplementation(() => '' as any);
  });

  afterEach(() => {
    vi.unstubAllEnvs();
  });

  describe('loadConfig', () => {
    it('should return empty object when config file does not exist', () => {
      vi.mocked(existsSync).mockReturnValue(false);
      expect(loadConfig()).toEqual({});
    });

    it('should parse config file when it exists', () => {
      vi.mocked(existsSync).mockReturnValue(true);
      vi.mocked(readFileSync).mockReturnValue(
        JSON.stringify({ server: 'http://localhost:8000/api', token: 'abc' }),
      );
      expect(loadConfig()).toEqual({ server: 'http://localhost:8000/api', token: 'abc' });
      expect(readFileSync).toHaveBeenCalledWith(CONFIG_PATH, 'utf-8');
    });

    it('should return empty object when config file is invalid JSON', () => {
      vi.mocked(existsSync).mockReturnValue(true);
      vi.mocked(readFileSync).mockReturnValue('not json');
      expect(loadConfig()).toEqual({});
    });
  });

  describe('saveConfig', () => {
    it('should create directory and write config', () => {
      saveConfig({ server: 'http://test', token: 'tok' });
      expect(mkdirSync).toHaveBeenCalledWith(join('/tmp/tgo-test-home', '.tgo'), { recursive: true });
      expect(writeFileSync).toHaveBeenCalledWith(
        CONFIG_PATH,
        JSON.stringify({ server: 'http://test', token: 'tok' }, null, 2) + '\n',
      );
    });
  });

  describe('updateConfig', () => {
    it('should merge patch into existing config', () => {
      vi.mocked(existsSync).mockReturnValue(true);
      vi.mocked(readFileSync).mockReturnValue(JSON.stringify({ server: 'http://old' }));

      updateConfig({ token: 'new-token' });

      const written = vi.mocked(writeFileSync).mock.calls[0][1] as string;
      const saved = JSON.parse(written);
      expect(saved).toEqual({ server: 'http://old', token: 'new-token' });
    });

    it('should remove keys set to undefined', () => {
      vi.mocked(existsSync).mockReturnValue(true);
      vi.mocked(readFileSync).mockReturnValue(
        JSON.stringify({ server: 'http://s', token: 'tok' }),
      );

      updateConfig({ token: undefined });

      const written = vi.mocked(writeFileSync).mock.calls[0][1] as string;
      const saved = JSON.parse(written);
      expect(saved).toEqual({ server: 'http://s' });
      expect(saved).not.toHaveProperty('token');
    });
  });

  describe('resolveServer', () => {
    it('should prefer CLI flag over everything', () => {
      vi.stubEnv('TGO_SERVER', 'http://env');
      vi.mocked(existsSync).mockReturnValue(true);
      vi.mocked(readFileSync).mockReturnValue(JSON.stringify({ server: 'http://config' }));

      expect(resolveServer('http://flag')).toBe('http://flag');
    });

    it('should use env var when no flag', () => {
      vi.stubEnv('TGO_SERVER', 'http://env');
      expect(resolveServer()).toBe('http://env');
    });

    it('should fall back to config file', () => {
      vi.mocked(existsSync).mockReturnValue(true);
      vi.mocked(readFileSync).mockReturnValue(JSON.stringify({ server: 'http://config' }));
      expect(resolveServer()).toBe('http://config');
    });

    it('should return undefined when nothing configured', () => {
      expect(resolveServer()).toBeUndefined();
    });
  });

  describe('resolveToken', () => {
    it('should prefer CLI flag', () => {
      vi.stubEnv('TGO_TOKEN', 'env-tok');
      expect(resolveToken('flag-tok')).toBe('flag-tok');
    });

    it('should use env var when no flag', () => {
      vi.stubEnv('TGO_TOKEN', 'env-tok');
      expect(resolveToken()).toBe('env-tok');
    });
  });

  describe('resolveOutput', () => {
    it('should return json by default', () => {
      expect(resolveOutput()).toBe('json');
    });

    it('should accept table', () => {
      expect(resolveOutput('table')).toBe('table');
    });

    it('should accept compact', () => {
      expect(resolveOutput('compact')).toBe('compact');
    });

    it('should fall back to json for unknown values', () => {
      expect(resolveOutput('xml')).toBe('json');
    });

    it('should read from env var', () => {
      vi.stubEnv('TGO_OUTPUT', 'table');
      expect(resolveOutput()).toBe('table');
    });
  });
});
