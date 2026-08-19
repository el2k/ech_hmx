import { describe, it, expect, vi } from 'vitest';
import { staffList, staffGet, staffPause, staffResume } from './staff.js';
import type { TgoClient } from '../client.js';

function mockClient() {
  return {
    get: vi.fn().mockResolvedValue({}),
    put: vi.fn().mockResolvedValue({}),
  } as unknown as TgoClient & {
    get: ReturnType<typeof vi.fn>;
    put: ReturnType<typeof vi.fn>;
  };
}

describe('staff commands', () => {
  describe('staffList', () => {
    it('should GET /v1/staff with filters', async () => {
      const client = mockClient();
      await staffList(client, { role: 'admin', status: 'online', limit: 5 });
      const url = client.get.mock.calls[0][0] as string;
      expect(url).toContain('/v1/staff?');
      expect(url).toContain('role=admin');
      expect(url).toContain('status=online');
      expect(url).toContain('limit=5');
    });
  });

  describe('staffGet', () => {
    it('should GET /v1/staff/:id', async () => {
      const client = mockClient();
      await staffGet(client, 'staff-1');
      expect(client.get).toHaveBeenCalledWith('/v1/staff/staff-1');
    });
  });

  describe('staffPause', () => {
    it('should PUT /v1/staff/me/service-paused when no id', async () => {
      const client = mockClient();
      await staffPause(client);
      expect(client.put).toHaveBeenCalledWith('/v1/staff/me/service-paused?paused=true');
    });

    it('should PUT /v1/staff/:id/service-paused when id provided', async () => {
      const client = mockClient();
      await staffPause(client, 'staff-1');
      expect(client.put).toHaveBeenCalledWith('/v1/staff/staff-1/service-paused?paused=true');
    });
  });

  describe('staffResume', () => {
    it('should PUT service-paused=false for self', async () => {
      const client = mockClient();
      await staffResume(client);
      expect(client.put).toHaveBeenCalledWith('/v1/staff/me/service-paused?paused=false');
    });

    it('should PUT service-paused=false for specific staff', async () => {
      const client = mockClient();
      await staffResume(client, 'staff-1');
      expect(client.put).toHaveBeenCalledWith('/v1/staff/staff-1/service-paused?paused=false');
    });
  });
});
