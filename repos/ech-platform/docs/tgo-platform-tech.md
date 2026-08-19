## tgo-platform 技术说明（简版）

### 系统概述
`tgo-platform` 是一个第三方平台消息聚合系统，支持企业微信、Email、WhatsApp、Telegram 等多种渠道。系统统一接入消息，调用内部 AI 能力并将结果按目标平台能力以流式或非流式方式输出。

---

### 系统架构
- tgo-platform
  - 渠道监听器：对接外部渠道（如 SMTP 邮箱、Webhook 等）
  - 平台适配器：按各第三方平台能力封装发送逻辑（是否支持流式）
  - 消息编排：统一触发 tgo-api 的对话/处理能力
- tgo-api
  - 统一消息接口：`/v1/wukongim/messages/send-stream`（SSE 流式返回）
  - 对接 WuKongIM 与 AI 服务，承接并转发流式事件
- 外部系统
  - SMTP 邮箱（接入 Email）
  - 第三方平台（企业微信、WhatsApp、Telegram 等）
  - WuKongIM 与 AI 服务（消息路由与流式推理）

时序示意（Email 场景）：
- Email → tgo-platform（监听）→ tgo-api（SSE）→ tgo-platform（适配）→ 第三方平台用户

---

### 核心消息流转（以 Email 为例）
1) 消息监听：tgo-platform 轮询或 webhook 方式监听用户配置的 SMTP 邮箱。
2) 消息触发：新邮件到达后，tgo-platform 组装请求，并调用 tgo-api 的流式发送接口。
3) API 处理：tgo-api 调用 WuKongIM，AI 服务开始处理并以 SSE 事件流返回。
4) 平台适配：
   - 支持流式的平台：tgo-platform 按事件到达实时输出。
   - 不支持流式的平台：tgo-platform 缓存事件，待“完整结果”到齐后再一次性发送。

---

### 平台适配规则
- 支持 stream 的平台：
  - 直接转发 SSE 事件中的内容片段（按事件类型聚合/渲染）。
  - 连接建立/断开、错误事件需做状态提示。
- 不支持 stream 的平台：
  - 缓存 `team_run_content`、`team_member_content` 等增量事件。
  - 以 `workflow_completed/failed` 或 `team_run_completed` 为完成信号，整合文本后一次性发送。
- 通用注意事项：
  - 记录 `request_id`、`correlation_id` 便于端到端追踪。
  - 设定超时（参考 `timeout_seconds`），避免无尽等待。
  - 错误事件回退为非流式兜底方案并提示用户。

---

### 接口说明：`/v1/wukongim/messages/send-stream`
- 方法：POST
- 路径：`/v1/wukongim/messages/send-stream`
- 返回：SSE（`text/event-stream`），对齐 AI 服务事件模型
- 认证：请求体内携带 `api_key`（401 表示无效）

请求体（MessageSendStreamRequest）：
- 必填：
  - `api_key`: string，平台 API Key
  - `message`: string，发送的文本内容
  - `channel_id`: string，WuKongIM 渠道 ID
  - `channel_type`: integer，1=个人，2=群组
  - `from_uid`: string，发送方用户 ID（如 visitor ID）
- 可选：
  - `extra`: object，附加元数据
  - `timeout_seconds`: integer，超时时间（秒），默认 120，范围 1–600

示例请求（节选）：
```json
{
  "api_key": "your_api_key",
  "message": "Hello",
  "channel_id": "ch_123",
  "channel_type": 1,
  "from_uid": "visitor_001"
}
```

SSE 事件：
- 事件名：`connected` | `event` | `error` | `disconnected`
- `event` 事件载荷：StreamingEvent JSON（字段：`event_type`, `timestamp`, `correlation_id`, `request_id`, `severity`, `data`, `metadata`）
- 常见 `event_type`：`team_run_started`, `team_member_content`, `team_run_content`, `team_run_completed`, `workflow_completed/failed`

SSE 响应示例（节选）：
```text
event: connected
data: {"message":"Stream connected","request_id":"req-123"}

event: event
data: {"event_type":"team_member_content","data":{"content_chunk":"...","is_final":false}}

event: disconnected
data: {"message":"Stream disconnected"}
```

错误码：
- 401 Invalid api_key
- 422 Validation Error（参见通用 ErrorResponse）

---

### 端到端流程（详细）
1) Email 到达：解析发件人、主题、正文、附件等，按业务规则确定映射到的 `channel_id`/`from_uid`。
2) 调用 tgo-api：POST `/v1/wukongim/messages/send-stream`，建立 SSE 连接。
3) 处理流事件：
   - `connected`：建立成功，记录 `request_id`/`correlation_id`。
   - `event`：按 `event_type` 增量渲染（可直接转发或缓存）。
   - `error`：记录错误并回退到非流式发送（必要时提示重试）。
   - `disconnected`：结束，非流式平台在此或“完成事件”后统一发送。
4) 平台输出：
   - 流式平台：逐事件更新消息。
   - 非流式平台：聚合后一次性发送。

---

### 配置与运维要点（简）
- SMTP 监听：连接参数（主机、端口、协议、凭据、轮询/推送策略）；去重与幂等（基于 Message-ID/时间戳）。
- 平台适配：平台能力枚举（是否支持 stream）、消息长度限额、速率限制；回退策略（SSE 失败 → 非流式发送）。
- 可靠性：超时与重试（遵循 `timeout_seconds`）；可观测性（贯穿记录 `request_id`/`correlation_id`，指标与日志分层）。

---

### 术语速览
- SSE（Server-Sent Events）：服务端单向推送事件流协议。
- WuKongIM：消息路由与 IM 能力的后端组件。
- `event_type`：业务事件分类，驱动 UI/适配器行为。

