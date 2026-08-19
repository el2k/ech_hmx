import { describe, it, expect, vi } from 'vitest';
import { agentList, agentGet, agentCreate, agentUpdate, agentDelete } from './agent.js';
import type { TgoClient } from '../client.js';

function mockClient() {
  return {
    get: vi.fn().mockResolvedValue({}),
    post: vi.fn().mockResolvedValue({}),
    patch: vi.fn().mockResolvedValue({}),
    delete: vi.fn().mockResolvedValue(undefined),
  } as unknown as TgoClient & {
    get: ReturnType<typeof vi.fn>;
    post: ReturnType<typeof vi.fn>;
    patch: ReturnType<typeof vi.fn>;
    delete: ReturnType<typeof vi.fn>;
  };
}

describe('agent commands', () => {
  describe('agentList', () => {
    it('should GET /v1/ai/agents with pagination', async () => {
      const client = mockClient();
      await agentList(client, { limit: 10, offset: 5 });
      expect(client.get).toHaveBeenCalledWith('/v1/ai/agents?limit=10&offset=5');
    });

    it('should GET /v1/ai/agents without query when no params', async () => {
      const client = mockClient();
      await agentList(client);
      expect(client.get).toHaveBeenCalledWith('/v1/ai/agents');
    });
  });

  describe('agentGet', () => {
    it('should GET /v1/ai/agents/:id', async () => {
      const client = mockClient();
      await agentGet(client, 'agent-1');
      expect(client.get).toHaveBeenCalledWith('/v1/ai/agents/agent-1');
    });
  });

  describe('agentCreate', () => {
    it('should POST /v1/ai/agents with full data', async () => {
      const client = mockClient();
      await agentCreate(client, {
        name: 'Test Agent',
        model: 'openai:gpt-4',
        instruction: 'Be helpful',
        ai_provider_id: 'prov-1',
      });
      expect(client.post).toHaveBeenCalledWith('/v1/ai/agents', {
        name: 'Test Agent',
        model: 'openai:gpt-4',
        instruction: 'Be helpful',
        ai_provider_id: 'prov-1',
      });
    });

    it('should POST /v1/ai/agents with minimal data', async () => {
      const client = mockClient();
      await agentCreate(client, { name: 'Bot', model: 'qwen:qwen-max' });
      expect(client.post).toHaveBeenCalledWith('/v1/ai/agents', {
        name: 'Bot',
        model: 'qwen:qwen-max',
      });
    });
  });

  describe('agentUpdate', () => {
    it('should PATCH /v1/ai/agents/:id', async () => {
      const client = mockClient();
      await agentUpdate(client, 'agent-1', { name: 'Updated' });
      expect(client.patch).toHaveBeenCalledWith('/v1/ai/agents/agent-1', { name: 'Updated' });
    });
  });

  describe('agentDelete', () => {
    it('should DELETE /v1/ai/agents/:id', async () => {
      const client = mockClient();
      await agentDelete(client, 'agent-1');
      expect(client.delete).toHaveBeenCalledWith('/v1/ai/agents/agent-1');
    });
  });
});
