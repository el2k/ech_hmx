import { describe, it, expect, vi } from 'vitest';
import { visitorList, visitorGet, visitorUpdate, visitorEnableAi, visitorDisableAi } from './visitor.js';
import type { TgoClient } from '../client.js';

function mockClient() {
  return {
    get: vi.fn().mockResolvedValue({}),
    post: vi.fn().mockResolvedValue({}),
    put: vi.fn().mockResolvedValue({}),
  } as unknown as TgoClient & {
    get: ReturnType<typeof vi.fn>;
    post: ReturnType<typeof vi.fn>;
    put: ReturnType<typeof vi.fn>;
  };
}

describe('visitor commands', () => {
  describe('visitorList', () => {
    it('should build query string from all params', async () => {
      const client = mockClient();
      await visitorList(client, {
        is_online: true,
        search: 'alice',
        tag_ids: ['t1', 't2'],
        platform_id: 'p1',
        limit: 10,
        offset: 5,
      });
      const url = client.get.mock.calls[0][0] as string;
      expect(url).toContain('/v1/visitors?');
      expect(url).toContain('is_online=true');
      expect(url).toContain('search=alice');
      expect(url).toContain('platform_id=p1');
      expect(url).toContain('limit=10');
      expect(url).toContain('offset=5');
      expect(url).toContain('tag_ids=t1');
      expect(url).toContain('tag_ids=t2');
    });

    it('should call /v1/visitors without query when no params', async () => {
      const client = mockClient();
      await visitorList(client, {});
      expect(client.get).toHaveBeenCalledWith('/v1/visitors');
    });
  });

  describe('visitorGet', () => {
    it('should GET /v1/visitors/:id', async () => {
      const client = mockClient();
      const mockVisitor = { id: 'v-1', name: 'Alice', is_online: true };
      client.get.mockResolvedValue(mockVisitor);

      const result = await visitorGet(client, 'v-1');
      expect(client.get).toHaveBeenCalledWith('/v1/visitors/v-1');
      expect(result).toEqual(mockVisitor);
    });
  });

  describe('visitorUpdate', () => {
    it('should PUT /v1/visitors/:id/attributes', async () => {
      const client = mockClient();
      await visitorUpdate(client, 'v-1', { name: 'Bob', email: 'bob@test.com' });
      expect(client.put).toHaveBeenCalledWith('/v1/visitors/v-1/attributes', {
        name: 'Bob',
        email: 'bob@test.com',
      });
    });
  });

  describe('visitorEnableAi', () => {
    it('should POST /v1/visitors/:id/enable-ai', async () => {
      const client = mockClient();
      await visitorEnableAi(client, 'v-1');
      expect(client.post).toHaveBeenCalledWith('/v1/visitors/v-1/enable-ai', {});
    });
  });

  describe('visitorDisableAi', () => {
    it('should POST /v1/visitors/:id/disable-ai', async () => {
      const client = mockClient();
      await visitorDisableAi(client, 'v-1');
      expect(client.post).toHaveBeenCalledWith('/v1/visitors/v-1/disable-ai', {});
    });
  });
});
