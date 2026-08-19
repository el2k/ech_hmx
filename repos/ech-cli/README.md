# tgo-cli

TGO 客服系统的命令行工具，提供 **CLI** 和 **MCP Server** 双模式，让 AI Agent 能通过命令行或 MCP 协议执行与人类客服相同的操作。

## 快速开始

### 安装

```bash
cd repos/tgo-cli
npm install
npm run build
```

或通过根目录 Makefile：

```bash
make install-cli
make build-cli
```

### 登录

```bash
# 登录并保存 token 到 ~/.tgo/config.json
tgo auth login -s http://localhost:8000/api -u admin@example.com -p yourpassword

# 验证登录
tgo auth whoami
```

登录成功后，server 和 token 会自动保存，后续命令无需重复指定。

### 基本用法

```bash
# 查看等待队列
tgo conversation list --scope waiting

# 接待访客
tgo conversation accept <visitor-id>

# 发送消息
tgo chat send --channel <channel-id> --type 251 --message "您好，有什么可以帮您？"

# 查看访客列表
tgo visitor list --online --limit 10

# 关闭会话
tgo conversation close <visitor-id>
```

## 全局选项

```
-s, --server <url>     API 服务器地址（优先级：CLI 参数 > TGO_SERVER 环境变量 > 配置文件）
-t, --token <token>    认证 token（优先级：CLI 参数 > TGO_TOKEN 环境变量 > 配置文件）
-o, --output <format>  输出格式：json（默认）| table | compact
-v, --verbose          详细输出
```

## 命令参考

### auth - 认证

```bash
tgo auth login -s <url> -u <user> -p <pass>   # 登录
tgo auth logout                                 # 登出
tgo auth whoami                                 # 当前用户信息
```

### conversation - 会话管理

```bash
tgo conversation list [--scope mine|waiting|all] [--limit N] [--offset N]
tgo conversation accept <visitor-id>
tgo conversation transfer <visitor-id> --to <staff-id> [--reason <text>]
tgo conversation close <visitor-id>
tgo conversation waiting-count
```

别名：`tgo conv`

### chat - 消息

```bash
tgo chat send --channel <id> --type <N> --message <text>
tgo chat agent --message <text> --agent <id>
tgo chat clear-memory --channel <id> --type <N>
```

### visitor - 访客管理

```bash
tgo visitor list [--online] [--search <q>] [--tag <id>] [--platform <id>] [--limit N]
tgo visitor get <id>
tgo visitor update <id> [--name <n>] [--email <e>] [--phone <p>] [--company <c>] [--note <text>]
tgo visitor enable-ai <id>
tgo visitor disable-ai <id>
```

### agent - AI Agent

```bash
tgo agent list [--limit N] [--offset N]
tgo agent get <id>
tgo agent create --name <n> --model <m> [--instructions <text>] [--provider-id <id>]
tgo agent update <id> [--name <n>] [--model <m>] [--instructions <text>]
tgo agent delete <id>
```

### provider - AI 模型供应商

```bash
tgo provider list
tgo provider create --name <n> --provider <type> --api-key <key> [--api-base <url>]
tgo provider test <id>
tgo provider enable <id>
tgo provider disable <id>
```

### knowledge - 知识库

```bash
tgo knowledge list [--limit N] [--offset N]
tgo knowledge get <id>
tgo knowledge create --name <n> [--description <d>]
tgo knowledge search <collection-id> --query <text> [--limit N]
tgo knowledge upload <collection-id> <file-path>
tgo knowledge delete <id>
```

别名：`tgo kb`

### workflow - 工作流

```bash
tgo workflow list [--limit N]
tgo workflow get <id>
tgo workflow execute <id> [--input <json>]
tgo workflow validate <id>
```

别名：`tgo wf`

### staff - 客服人员

```bash
tgo staff list [--role <r>] [--status <s>] [--limit N]
tgo staff get <id>
tgo staff pause [<id>]       # 无 id 时暂停自己
tgo staff resume [<id>]      # 无 id 时恢复自己
```

### platform / tag / system

```bash
tgo platform list
tgo platform get <id>

tgo tag list [--category <cat>]
tgo tag create --name <n> [--category <cat>] [--color <hex>]
tgo tag delete <id>

tgo system info
```

## 输出格式

```bash
# JSON（默认，AI Agent 友好）
tgo visitor list -o json

# 表格（人类调试用）
tgo staff list -o table

# 紧凑单行（快速浏览）
tgo conversation list --scope waiting -o compact
```

## 环境变量

| 变量 | 说明 |
|------|------|
| `TGO_SERVER` | API 服务器地址 |
| `TGO_TOKEN` | 认证 token |
| `TGO_OUTPUT` | 默认输出格式 |

配置优先级：CLI 参数 > 环境变量 > `~/.tgo/config.json`

## MCP Server 模式

tgo-cli 内置 MCP Server，可让 Claude Code、Cursor 等 AI 工具直接调用客服系统 API。

### 启动

```bash
tgo mcp serve
```

### Claude Code 配置

在项目的 `.mcp.json` 中添加：

```json
{
  "mcpServers": {
    "tgo": {
      "command": "node",
      "args": ["/path/to/repos/tgo-cli/bin/tgo.js", "mcp", "serve"]
    }
  }
}
```

### 可用 Tools（40+）

| Tool | 说明 |
|------|------|
| `tgo_auth_login` | 登录 |
| `tgo_auth_whoami` | 当前用户 |
| `tgo_conversation_list` | 会话列表 |
| `tgo_conversation_accept` | 接待访客 |
| `tgo_conversation_transfer` | 转接 |
| `tgo_conversation_close` | 关闭会话 |
| `tgo_conversation_waiting_count` | 等待数量 |
| `tgo_chat_send` | 发送消息 |
| `tgo_chat_agent` | 与 AI Agent 对话 |
| `tgo_chat_clear_memory` | 清除 AI 记忆 |
| `tgo_visitor_list` | 访客列表 |
| `tgo_visitor_get` | 访客详情 |
| `tgo_visitor_update` | 更新访客 |
| `tgo_visitor_enable_ai` | 开启 AI |
| `tgo_visitor_disable_ai` | 关闭 AI |
| `tgo_agent_list` | Agent 列表 |
| `tgo_agent_get` | Agent 详情 |
| `tgo_agent_create` | 创建 Agent |
| `tgo_agent_update` | 更新 Agent |
| `tgo_agent_delete` | 删除 Agent |
| `tgo_provider_list` | 供应商列表 |
| `tgo_provider_create` | 创建供应商 |
| `tgo_provider_test` | 测试连接 |
| `tgo_provider_enable` | 启用供应商 |
| `tgo_provider_disable` | 禁用供应商 |
| `tgo_knowledge_list` | 知识库列表 |
| `tgo_knowledge_get` | 知识库详情 |
| `tgo_knowledge_create` | 创建知识库 |
| `tgo_knowledge_search` | 知识库搜索 |
| `tgo_knowledge_delete` | 删除知识库 |
| `tgo_workflow_list` | 工作流列表 |
| `tgo_workflow_get` | 工作流详情 |
| `tgo_workflow_execute` | 执行工作流 |
| `tgo_workflow_validate` | 验证工作流 |
| `tgo_staff_list` | 人员列表 |
| `tgo_staff_get` | 人员详情 |
| `tgo_staff_pause` | 暂停接待 |
| `tgo_staff_resume` | 恢复接待 |
| `tgo_platform_list` | 平台列表 |
| `tgo_platform_get` | 平台详情 |
| `tgo_tag_list` | 标签列表 |
| `tgo_tag_create` | 创建标签 |
| `tgo_tag_delete` | 删除标签 |
| `tgo_system_info` | 系统信息 |

## 典型工作流示例

### AI Agent 自动接待

```bash
# 1. 检查等待队列
tgo conv waiting-count

# 2. 查看等待中的访客
tgo conv list --scope waiting

# 3. 接待第一个访客
tgo conv accept <visitor-id>

# 4. 查看访客信息
tgo visitor get <visitor-id>

# 5. 发送欢迎消息
tgo chat send --channel <channel-id> --type 251 --message "您好！请问有什么可以帮您？"

# 6. 需要时转接人工
tgo conv transfer <visitor-id> --to <staff-id> --reason "客户要求人工服务"
```

### 管理 AI Agent 配置

```bash
# 查看所有 Agent
tgo agent list

# 创建新 Agent
tgo agent create --name "售后客服" --model "openai:gpt-4" \
  --instructions "你是一个专业的售后客服，负责处理退换货和投诉问题"

# 更新 Agent 指令
tgo agent update <id> --instructions "新的指令内容"
```

### 知识库管理

```bash
# 创建知识库
tgo kb create --name "产品文档" --description "所有产品的使用手册"

# 上传文档
tgo kb upload <collection-id> ./docs/user-guide.pdf

# 搜索知识库
tgo kb search <collection-id> --query "如何退货"
```

## 开发

```bash
# 安装依赖
npm install

# 开发模式（监听文件变化自动重新构建）
npm run dev

# 构建
npm run build

# 直接运行（开发时）
node bin/tgo.js --help
```

## 项目结构

```
src/
├── index.ts            # CLI 入口（Commander）
├── client.ts           # HTTP API 客户端（fetch + auth + SSE）
├── config.ts           # 配置管理（~/.tgo/config.json）
├── output.ts           # 输出格式化（json/table/compact）
├── commands/
│   ├── auth.ts         # 认证
│   ├── conversation.ts # 会话
│   ├── chat.ts         # 消息
│   ├── visitor.ts      # 访客
│   ├── agent.ts        # AI Agent
│   ├── provider.ts     # AI 供应商
│   ├── knowledge.ts    # 知识库
│   ├── workflow.ts     # 工作流
│   ├── staff.ts        # 客服人员
│   ├── platform.ts     # 平台
│   ├── tag.ts          # 标签
│   └── system.ts       # 系统
└── mcp/
    └── server.ts       # MCP Server（stdio）
```
