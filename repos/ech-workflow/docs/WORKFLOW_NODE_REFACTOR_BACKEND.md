# 工作流节点重构后端适配指南 (Workflow Node Refactor)

## 1. 变更背景
为了提高工作流的灵活性和扩展性，前端已将原有的 `start` (开始) 和 `end` (结束) 节点重构为更具体的 **触发节点 (Trigger Nodes)** 和 **回复节点 (Answer Node)**。

- **移除**: `start`, `end`
- **新增触发节点**: `input`, `timer`, `webhook`, `event`
- **新增输出节点**: `answer`

---

## 2. 数据结构定义 (JSON Schema / DTO)

### 2.1 触发节点 (Trigger Nodes)

所有触发节点必须作为工作流的入口点。

#### A. 用户输入 (`input`)
用于对话场景，接收用户消息。
```json
{
  "type": "input",
  "label": "用户输入",
  "input_variables": [
    { "name": "query", "type": "string", "description": "用户输入的消息内容" }
  ]
}
```

#### B. 定时触发 (`timer`)
按计划自动执行。
```json
{
  "type": "timer",
  "label": "定时触发",
  "cron_expression": "0 * * * *", // 标准 Cron 格式
}
```

#### C. Webhook 触发 (`webhook`)
通过外部 HTTP 请求触发。
```json
{
  "type": "webhook",
  "label": "Webhook",
  "path": "custom-endpoint", // 可选路径后缀
  "method": "POST" // GET 或 POST
}
```

#### D. 事件触发 (`event`)
系统内部总线事件触发。
```json
{
  "type": "event",
  "label": "事件触发",
  "event_type": "user_registered" // 具体的事件标识
}
```

### 2.2 回复节点 (`answer`)

用于在流程中任何位置返回结果给调用方或用户。
```json
{
  "type": "answer",
  "label": "回复",
  "output_type": "template", // "variable" | "template" | "structured"
  "output_template": "您好，查询到的结果是：{{api_1.body}}",
  "output_variable": "final_result",
  "output_structure": [
    { "key": "status", "value": "success" }
  ]
}
```

---

## 3. 执行引擎适配建议

### 3.1 流程启动 (Entry Point)
- 引擎应支持多入口或根据触发类型（Trigger Type）动态选择起始节点。
- 只有类型为 `input`, `timer`, `webhook`, `event` 的节点可以作为无前置节点的起始点。

### 3.2 变量注入 (Variables)
- `input` 节点启动时，应将用户传递的 `query` 或其他 `input_variables` 注入上下文。
- `timer` 启动时，可注入执行时间戳等元数据。
- `webhook` 启动时，应注入 `body`, `params`, `headers` 等请求信息。

### 3.3 输出处理 (Answer)
- 当执行流到达 `answer` 节点时，引擎应立即构造响应并返回给调用方。
- 如果一个流程有多个 `answer` 节点（如分支逻辑），则以执行路径上第一个到达的 `answer` 为准。

---

## 4. 数据库迁移建议 (Migration)

建议对现有的 `workflows` 表中的 `definition` (JSON) 字段进行如下迁移：

1. **Start 节点转换**:
   - 如果 `start` 节点的 `trigger_type` 是 `manual` -> 转换为 `input` 类型。
   - 如果 `start` 节点的 `trigger_type` 是 `cron` -> 转换为 `timer` 类型。
2. **End 节点转换**:
   - 所有 `end` 节点 -> 转换为 `answer` 类型。

---

## 5. Webhook 端点设计 (可选)

建议后端提供统一的 Webhook 入口：
`POST /v1/workflows/execute/webhook/{workflow_id}/{path?}`

- 校验 `workflow_id` 是否存在且已启用。
- 校验 `path` 是否匹配 `webhook` 节点的配置。
- 启动工作流执行。

