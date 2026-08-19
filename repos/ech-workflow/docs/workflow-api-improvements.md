# AI Workflows API 完善建议

> 本文档基于前端工作流编辑器的实现需求，列出后端 API 需要补充和优化的内容。

---

## 一、需要新增的接口

### 1.1 工作流克隆 (P0 - 必须)

**路径**: `POST /v1/workflows/{workflow_id}/duplicate`

**用途**: 基于现有工作流创建副本，用于模板复用场景。

**请求参数**:
```json
{
  "name": "新工作流名称（可选，默认为 '原名称 (副本)'）"
}
```

**响应示例**:
```json
{
  "id": "wf_new_123",
  "name": "客服问答流程 (副本)",
  "description": "...",
  "status": "draft",
  "version": 1,
  "nodes": [...],
  "edges": [...],
  "tags": [...],
  "created_at": "2024-01-15T10:00:00Z",
  "updated_at": "2024-01-15T10:00:00Z"
}
```

**后端逻辑要点**:
- 复制原工作流的 `nodes`、`edges`、`description`、`tags`
- 重置 `status` 为 `draft`
- 重置 `version` 为 `1`
- 生成新的 `id`
- 更新 `created_at` 和 `updated_at`

---

### 1.2 工作流验证 (P0 - 必须)

**路径**: `POST /v1/workflows/validate`

**用途**: 在保存/发布前验证工作流结构的合法性。

**请求体**:
```json
{
  "nodes": [...],
  "edges": [...]
}
```

**响应示例**:
```json
{
  "valid": false,
  "errors": [
    {
      "code": "MISSING_START_NODE",
      "message": "工作流必须有一个开始节点",
      "node_id": null
    },
    {
      "code": "DISCONNECTED_NODE",
      "message": "节点 'LLM调用' 未连接到任何其他节点",
      "node_id": "node-123"
    },
    {
      "code": "MISSING_REQUIRED_FIELD",
      "message": "Agent节点 '客服助手' 未选择AI员工",
      "node_id": "node-456"
    }
  ]
}
```

**验证规则**:
| 规则 | 错误码 | 说明 |
|------|--------|------|
| 有且只有一个 `start` 节点 | `MISSING_START_NODE` / `MULTIPLE_START_NODES` | |
| 至少有一个 `end` 节点 | `MISSING_END_NODE` | |
| 所有节点可从 `start` 到达 | `UNREACHABLE_NODE` | 使用 BFS/DFS |
| 所有节点可到达某个 `end` | `DEAD_END_NODE` | |
| 无循环依赖 | `CIRCULAR_DEPENDENCY` | 使用 Kahn 算法 |
| `agent` 节点必须有 `agentId` | `MISSING_REQUIRED_FIELD` | |
| `tool` 节点必须有 `toolId` | `MISSING_REQUIRED_FIELD` | |
| `llm` 节点必须有 `userPrompt` | `MISSING_REQUIRED_FIELD` | |
| `api` 节点必须有 `url` | `MISSING_REQUIRED_FIELD` | |
| `classifier` 节点必须有 `categories` | `MISSING_REQUIRED_FIELD` | |

---

### 1.3 取消执行 (P1 - 重要)

**路径**: `POST /v1/workflows/executions/{execution_id}/cancel`

**用途**: 中止正在运行的工作流执行。

**响应示例**:
```json
{
  "id": "exec_123",
  "status": "cancelled",
  "cancelled_at": "2024-01-15T10:05:00Z"
}
```

**后端逻辑要点**:
- 向 Celery Worker 发送取消信号
- 更新执行状态为 `cancelled`
- 记录当前已完成的节点执行结果

---

### 1.4 可用变量查询 (P2 - 建议)

**路径**: `GET /v1/workflows/{workflow_id}/variables`

**用途**: 获取工作流中所有节点的输出变量，供前端变量选择器使用。

**响应示例**:
```json
{
  "variables": [
    {
      "node_id": "node-1",
      "reference_key": "start_1",
      "node_type": "start",
      "node_label": "开始",
      "outputs": [
        { "name": "user_input", "type": "string", "description": "用户输入" },
        { "name": "user_name", "type": "string", "description": "用户姓名" }
      ]
    },
    {
      "node_id": "node-2",
      "reference_key": "llm_1",
      "node_type": "llm",
      "node_label": "LLM调用",
      "outputs": [
        { "name": "text", "type": "string", "description": "LLM 输出文本" }
      ]
    },
    {
      "node_id": "node-3",
      "reference_key": "api_1",
      "node_type": "api",
      "node_label": "API调用",
      "outputs": [
        { "name": "body", "type": "object", "description": "响应体" },
        { "name": "status_code", "type": "number", "description": "HTTP 状态码" },
        { "name": "headers", "type": "object", "description": "响应头" }
      ]
    }
  ]
}
```

---

### 1.5 发布工作流 (P2 - 建议)

**路径**: `POST /v1/workflows/{workflow_id}/publish`

**用途**: 将工作流从 `draft` 状态发布为 `active`。

**响应示例**:
```json
{
  "id": "wf_123",
  "status": "active",
  "version": 2,
  "published_at": "2024-01-15T10:00:00Z"
}
```

**后端逻辑要点**:
- 执行验证（同 1.2）
- 验证通过后更新 `status` 为 `active`
- 可选：创建版本快照

---

## 二、现有接口优化建议

### 2.1 GET /v1/workflows - 列表接口

**当前参数**:
- `skip` (int)
- `limit` (int)
- `status` (string, optional)

**建议增加**:
| 参数 | 类型 | 说明 |
|------|------|------|
| `search` | string | 按名称/描述模糊搜索 |
| `tags` | string[] | 按标签筛选（多选，OR 逻辑） |
| `sort_by` | string | 排序字段 (name, created_at, updated_at) |
| `sort_order` | string | asc / desc |

**响应优化**:
当前响应为 `array`，建议改为分页包装结构：
```json
{
  "data": [
    {
      "id": "wf_123",
      "name": "客服问答",
      "description": "...",
      "status": "active",
      "version": 2,
      "node_count": 5,
      "tags": ["客服", "FAQ"],
      "created_at": "...",
      "updated_at": "..."
    }
  ],
  "pagination": {
    "total": 42,
    "limit": 20,
    "offset": 0,
    "has_next": true,
    "has_prev": false
  }
}
```

**新增字段**:
- `node_count`: 节点数量（便于列表展示）

---

### 2.2 GET /v1/workflows/{workflow_id} - 详情接口

**响应结构优化**:
确保返回完整的节点和边数据，结构如下：
```json
{
  "id": "wf_123",
  "name": "客服问答",
  "description": "自动回复客户问题",
  "status": "active",
  "version": 2,
  "tags": ["客服"],
  "nodes": [
    {
      "id": "node-1",
      "type": "start",
      "position": { "x": 100, "y": 200 },
      "data": {
        "label": "开始",
        "reference_key": "start_1",
        "trigger_type": "manual",
        "input_variables": [
          { "name": "user_input", "type": "string", "description": "用户问题" }
        ]
      }
    }
  ],
  "edges": [
    {
      "id": "edge-1",
      "source": "node-1",
      "target": "node-2",
      "source_handle": null,
      "target_handle": null,
      "type": "smoothstep"
    }
  ],
  "created_at": "...",
  "updated_at": "...",
  "created_by": "user_456"
}
```

---

### 2.3 GET /v1/workflows/executions/{execution_id} - 执行详情

**关键要求**: 响应**必须**包含 `node_executions` 数组。

**完整响应结构**:
```json
{
  "id": "exec_123",
  "workflow_id": "wf_456",
  "status": "completed",
  "input": {
    "user_input": "你好"
  },
  "output": {
    "result": "您好，有什么可以帮助您的？"
  },
  "error": null,
  "started_at": "2024-01-15T10:00:00Z",
  "completed_at": "2024-01-15T10:00:05Z",
  "duration": 5000,
  "node_executions": [
    {
      "id": "ne_1",
      "node_id": "node-1",
      "node_type": "start",
      "status": "completed",
      "input": null,
      "output": { "user_input": "你好" },
      "error": null,
      "started_at": "2024-01-15T10:00:00Z",
      "completed_at": "2024-01-15T10:00:00Z",
      "duration": 10
    },
    {
      "id": "ne_2",
      "node_id": "node-2",
      "node_type": "llm",
      "status": "completed",
      "input": { "user_prompt": "你好" },
      "output": { "text": "您好，有什么可以帮助您的？" },
      "error": null,
      "started_at": "2024-01-15T10:00:00Z",
      "completed_at": "2024-01-15T10:00:04Z",
      "duration": 4000
    }
  ]
}
```

---

### 2.4 POST /v1/workflows/{workflow_id}/execute - 执行接口

**优化建议**:
1. 支持同步/异步模式切换：
   - `sync=true`: 等待执行完成后返回结果（适用于简单工作流）
   - `sync=false`（默认）: 立即返回 `execution_id`，后续轮询状态

2. 请求体增加参数校验：
   - 根据 `start` 节点的 `input_variables` 定义验证传入的 `inputs`

---

## 三、数据结构规范

### 3.1 节点类型枚举

```python
class WorkflowNodeType(str, Enum):
    START = "start"
    END = "end"
    LLM = "llm"
    AGENT = "agent"
    TOOL = "tool"
    API = "api"
    CONDITION = "condition"
    CLASSIFIER = "classifier"
    PARALLEL = "parallel"
```

### 3.2 工作流状态枚举

```python
class WorkflowStatus(str, Enum):
    DRAFT = "draft"
    ACTIVE = "active"
    ARCHIVED = "archived"
```

### 3.3 执行状态枚举

```python
class ExecutionStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"
```

### 3.4 各节点 data 结构

#### Start 节点
```json
{
  "type": "start",
  "label": "开始",
  "reference_key": "start_1",
  "trigger_type": "manual | cron",
  "cron_expression": "0 9 * * *",
  "input_variables": [
    { "name": "user_input", "type": "string", "description": "用户问题" }
  ]
}
```

#### End 节点
```json
{
  "type": "end",
  "label": "结束",
  "reference_key": "end_1",
  "output_type": "variable | template | structured",
  "output_variable": "{{llm_1.text}}",
  "output_template": "回答: {{llm_1.text}}",
  "output_structure": [
    { "key": "answer", "value": "{{llm_1.text}}" },
    { "key": "source", "value": "{{api_1.body.source}}" }
  ]
}
```

#### LLM 节点
```json
{
  "type": "llm",
  "label": "LLM调用",
  "reference_key": "llm_1",
  "provider_id": "openai",
  "model_id": "gpt-4o",
  "model_name": "GPT-4o",
  "system_prompt": "你是一个客服助手",
  "user_prompt": "用户问题: {{start_1.user_input}}",
  "temperature": 0.7,
  "max_tokens": 2000,
  "tools": ["tool_id_1", "tool_id_2"],
  "knowledge_bases": ["kb_id_1"]
}
```
**固定输出**: `{{reference_key.text}}`

#### Agent 节点
```json
{
  "type": "agent",
  "label": "AI Agent",
  "reference_key": "agent_1",
  "agent_id": "agent_123",
  "agent_name": "客服助手",
  "input_mapping": {
    "message": "{{start_1.user_input}}"
  }
}
```
**固定输出**: `{{reference_key.text}}`

#### Tool 节点
```json
{
  "type": "tool",
  "label": "MCP工具",
  "reference_key": "tool_1",
  "tool_id": "tool_456",
  "tool_name": "搜索工具",
  "input_mapping": {
    "query": "{{start_1.user_input}}"
  }
}
```
**固定输出**: `{{reference_key.result}}`

#### API 节点
```json
{
  "type": "api",
  "label": "API调用",
  "reference_key": "api_1",
  "method": "POST",
  "url": "https://api.example.com/search?q={{start_1.user_input}}",
  "headers": [
    { "key": "Authorization", "value": "Bearer {{secrets.api_key}}" }
  ],
  "params": [
    { "key": "limit", "value": "10" }
  ],
  "body_type": "json | form-data | x-www-form-urlencoded | raw | none",
  "body": "{\"query\": \"{{start_1.user_input}}\"}",
  "form_data": [
    { "key": "file", "value": "...", "type": "file" }
  ],
  "form_url_encoded": [
    { "key": "username", "value": "test" }
  ],
  "raw_type": "text | html | xml | javascript"
}
```
**固定输出**: 
- `{{reference_key.body}}` - 响应体
- `{{reference_key.status_code}}` - HTTP 状态码
- `{{reference_key.headers}}` - 响应头

#### Condition 节点
```json
{
  "type": "condition",
  "label": "条件判断",
  "reference_key": "condition_1",
  "condition_type": "expression | variable | llm",
  "expression": "{{start_1.score}} > 80",
  "variable": "{{start_1.status}}",
  "operator": "equals | notEquals | contains | greaterThan | lessThan | isEmpty | isNotEmpty",
  "compare_value": "active",
  "llm_prompt": "判断用户问题是否属于退款类问题",
  "provider_id": "openai",
  "model_id": "gpt-4o-mini"
}
```
**输出句柄**: `true` / `false`

#### Classifier 节点
```json
{
  "type": "classifier",
  "label": "问题分类器",
  "reference_key": "classifier_1",
  "input_variable": "{{start_1.user_input}}",
  "provider_id": "openai",
  "model_id": "gpt-4o",
  "categories": [
    { "id": "refund", "name": "退款问题", "description": "用户询问退款政策、退款进度" },
    { "id": "shipping", "name": "物流问题", "description": "用户询问发货、配送状态" },
    { "id": "other", "name": "其他问题", "description": "无法归类的问题" }
  ]
}
```
**固定输出**:
- `{{reference_key.category_id}}` - 匹配的分类 ID
- `{{reference_key.category_name}}` - 匹配的分类名称

**输出句柄**: 每个 `category.id` 对应一个句柄

#### Parallel 节点
```json
{
  "type": "parallel",
  "label": "并行执行",
  "reference_key": "parallel_1",
  "branches": 3,
  "wait_for_all": true,
  "timeout": 30
}
```

---

## 五、优先级汇总

| 优先级 | 接口/优化项 | 类型 | 说明 |
|--------|-------------|------|------|
| P0 | `POST .../duplicate` | 新增 | 工作流克隆 |
| P0 | `POST .../validate` | 新增 | 工作流验证 |
| P0 | 执行详情返回 `node_executions` | 优化 | 前端展示执行轨迹必需 |
| P1 | `POST .../cancel` | 新增 | 取消执行 |
| P1 | 列表接口增加 `search`/`tags` | 优化 | 提升搜索体验 |
| P2 | `GET .../variables` | 新增 | 变量选择器支持 |
| P2 | `POST .../publish` | 新增 | 发布管理 |

---

## 六、前端文件参考

- **类型定义**: `src/types/workflow.ts`
- **API 服务**: `src/services/workflowApi.ts`
- **状态管理**: `src/stores/workflowStore.ts`
- **节点组件**: `src/components/workflow/nodes/*.tsx`
- **配置面板**: `src/components/workflow/panels/NodeConfigPanel.tsx`

---

*文档生成时间: 2025-01-01*

