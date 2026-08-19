import { describe, it, expect, vi } from 'vitest';
import {
  conversationList,
  conversationAccept,
  conversationTransfer,
  conversationClose,
  conversationWaitingCount,
} from './conversation.js';
import type { TgoClient } from '../client.js';

/** Create a mock TgoClient */
function mockClient() {
  return {
    get: vi.fn().mockResolvedValue({}),
    post: vi.fn().mockResolvedValue({}),
    put: vi.fn().mockResolvedValue({}),
    patch: vi.fn().mockResolvedValue({}),
    delete: vi.fn().mockResolvedValue({}),
  } as unknown as TgoClient & {
    get: ReturnType<typeof vi.fn>;
    post: ReturnType<typeof vi.fn>;
  };
}

describe('conversation commands', () => {
  describe('conversationList', () => {
    it('should POST /v1/conversations/my for scope=mine', async () => {
      const client = mockClient();
      await conversationList(client, { scope: 'mine', msgCount: 20 });
      expect(client.post).toHaveBeenCalledWith('/v1/conversations/my', { msg_count: 20 });
    });

    it('should POST /v1/conversations/waiting for scope=waiting', async () => {
      const client = mockClient();
      await conversationList(client, { scope: 'waiting', msgCount: 10, limit: 5, offset: 0 });
      expect(client.post).toHaveBeenCalledWith(
        '/v1/conversations/waiting?msg_count=10&limit=5&offset=0',
        {},
      );
    });

    it('should POST /v1/conversations/all for scope=all', async () => {
      const client = mockClient();
      await conversationList(client, { scope: 'all', limit: 50, offset: 10 });
      expect(client.post).toHaveBeenCalledWith('/v1/conversations/all', {
        msg_count: 20,
        limit: 50,
        offset: 10,
      });
    });

    it('should default scope to mine', async () => {
      const client = mockClient();
      await conversationList(client, {});
      expect(client.post).toHaveBeenCalledWith('/v1/conversations/my', { msg_count: 20 });
    });
  });

  describe('conversationAccept', () => {
    it('should POST /v1/visitors/:id/accept', async () => {
      const client = mockClient();
      await conversationAccept(client, 'visitor-123');
      expect(client.post).toHaveBeenCalledWith('/v1/visitors/visitor-123/accept', {});
    });
  });

  describe('conversationTransfer', () => {
    it('should POST transfer with target staff and reason', async () => {
      const client = mockClient();
      await conversationTransfer(client, 'v-1', 'staff-2', 'customer request');
      expect(client.post).toHaveBeenCalledWith('/v1/sessions/visitor/v-1/transfer', {
        target_staff_id: 'staff-2',
        reason: 'customer request',
      });
    });

    it('should omit reason when not provided', async () => {
      const client = mockClient();
      await conversationTransfer(client, 'v-1', 'staff-2');
      expect(client.post).toHaveBeenCalledWith('/v1/sessions/visitor/v-1/transfer', {
        target_staff_id: 'staff-2',
      });
    });
  });

  describe('conversationClose', () => {
    it('should POST /v1/sessions/visitor/:id/close', async () => {
      const client = mockClient();
      await conversationClose(client, 'v-1');
      expect(client.post).toHaveBeenCalledWith('/v1/sessions/visitor/v-1/close', {});
    });
  });

  describe('conversationWaitingCount', () => {
    it('should GET /v1/visitor-waiting-queue/count', async () => {
      const client = mockClient();
      (client.get as ReturnType<typeof vi.fn>).mockResolvedValue({ count: 5 });
      const result = await conversationWaitingCount(client);
      expect(client.get).toHaveBeenCalledWith('/v1/visitor-waiting-queue/count');
      expect(result).toEqual({ count: 5 });
    });
  });
});
