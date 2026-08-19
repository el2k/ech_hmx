# Ech 智能服务平台

这是一个面向企业客服场景的多服务智能应用平台。项目采用 Docker Compose 编排 PostgreSQL、Redis、即时通讯、知识库、模型服务、业务 API、工作流和前端等组件，便于本地联调和后续按需部署。

## 项目组成

| 目录 | 作用 | 技术栈 |
| --- | --- | --- |
| `repos/ech-ai` | 模型接入、智能体和工具调用服务 | Python / FastAPI |
| `repos/ech-api` | 用户、会话、权限和业务接口 | Python / FastAPI |
| `repos/ech-cli` | 命令行工具及 MCP 服务 | TypeScript / Node.js |
| `repos/ech-device-agent` | 运行在受管设备上的远程执行代理 | Go |
| `repos/ech-device-control` | 设备连接和远程操作控制服务 | Python / FastAPI |
| `repos/ech-platform` | 多渠道消息接入与回调处理 | Python / FastAPI |
| `repos/ech-plugin-runtime` | 插件安装、运行和生命周期管理 | Python |
| `repos/ech-rag` | 文档处理、向量检索和异步知识库任务 | Python / FastAPI / Celery |

根目录的 `docker-compose.yml` 负责统一编排这些服务及其依赖。Compose 中部分服务名仍使用 `tgo-*`，这是服务间地址和现有配置的一部分，修改时需要同步调整环境变量与各子服务配置。

## 运行环境

- Linux、macOS 或 WSL2
- Docker Engine 及 Docker Compose V2
- 至少 4 核 CPU、8 GiB 内存
- 如需单独开发 Python 服务，建议使用 Python 3.11 或更高版本
- 如需开发前端或 CLI，需要 Node.js 18 或更高版本

## 配置环境

先复制开发环境模板：

```bash
cp .env.dev.example .env.dev
```

首次启动前，请检查 `.env.dev` 中的数据库密码、密钥、模型服务凭据、前端 API 地址和对外访问地址。生产环境不要使用模板中的默认密钥和默认密码。

## 启动服务

当前仓库可直接使用根目录 Compose 文件启动基础设施和已配置的服务：

```bash
docker compose --env-file .env.dev up -d --build
```

查看服务状态和日志：

```bash
docker compose --env-file .env.dev ps
docker compose --env-file .env.dev logs -f
```

停止服务：

```bash
docker compose --env-file .env.dev down
```

如果只需要启动基础设施：

```bash
docker compose --env-file .env.dev up -d postgres redis wukongim
```

## 常用访问地址

默认开发端口如下，实际端口以 `.env.dev` 和 Compose 配置为准：

| 组件 | 地址 |
| --- | --- |
| 业务 API | `http://localhost:8000` |
| API 文档 | `http://localhost:8000/v1/docs` |
| AI 服务 | `http://localhost:8081` |
| 平台接入服务 | `http://localhost:8003` |
| 工作流服务 | `http://localhost:8004` |
| 插件运行时 | `http://localhost:8090` |
| 设备控制服务 | `http://localhost:8085` |
| RAG 服务 | `http://localhost:18082` |
| Web 前端 | `http://localhost:5173` |
| Widget 调试页面 | `http://localhost:5174` |
| WuKongIM WebSocket | `ws://localhost:5200` |
| Celery Flower | `http://localhost:15555` |

## 单服务开发

进入对应服务目录后，按照该目录的 README 或项目配置安装依赖。例如 API 服务：

```bash
cd repos/ech-api
poetry install
poetry run uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```

AI 服务、平台服务和 CLI 的具体命令请分别参考：

- `repos/ech-ai/README.md`
- `repos/ech-api/README.md`
- `repos/ech-cli/README.md`
- `repos/ech-device-agent/README.md`

## 数据持久化

运行过程中产生的数据默认保存在根目录的 `data/` 下，包括 PostgreSQL、Redis、即时通讯服务和知识库上传文件。执行 `docker compose down -v` 前请确认是否需要保留这些数据。

## 开发建议

- 服务间调用使用 Compose 服务名，不要在容器内使用 `localhost` 访问其他服务。
- 浏览器侧地址使用 `localhost` 映射端口；容器侧地址使用内部服务名和容器端口。
- 修改服务名或端口时，同时检查 `.env.dev`、Compose 文件和各子服务配置。
- 提交前分别运行受影响服务的测试、类型检查或 lint 命令。

## 许可证与第三方声明

本仓库包含多个独立服务和第三方组件。各子目录中的许可证、版权声明和 NOTICE 文件继续适用于对应代码及依赖。进行二次开发、发布镜像或重新分发时，请保留这些声明并遵守各组件的许可证条款。
<p align="center">
  <img src="resources/readme-banner-en.svg" width="100%" alt="Build AI Agent Teams for Customer Service">
</p>

<p align="center">
  <a href="./README.md">English</a> | <a href="./README_CN.md">简体中文</a> | <a href="./README_TC.md">繁體中文</a> | <a href="./README_JP.md">日本語</a> | <a href="./README_RU.md">Русский</a>
</p>

<p align="center">
  <a href="https://tgo.ai">Website</a> | <a href="https://tgo.ai">Documentation</a>
</p>

## TGO Introduction

TGO is an open-source AI agent customer service platform dedicated to helping enterprises "Build AI Agent Teams for Customer Service". It integrates multi-channel access, agent orchestration, knowledge base management (RAG), and human agent collaboration.

<img src="resources/home_en.png" width="100%">

## 🚀 Quick Start

### One-Click Deployment

Run the following command on your server to check requirements, clone the repository, and start the services:

```bash
REF=latest curl -fsSL https://raw.githubusercontent.com/tgoai/tgo/main/bootstrap.sh | bash
```

> **For users in China** (using Gitee and Aliyun mirrors):
> ```bash
> REF=latest curl -fsSL https://gitee.com/tgoai/tgo/raw/main/bootstrap_cn.sh | bash
> ```

### Local Development

Start the full development environment with Docker Compose:

```bash
cp .env.dev.example .env.dev
make dev
```

Useful variants:

```bash
make dev PROFILES=monitoring
make dev DISABLE=tgo-rag-beat,tgo-workflow-worker
```

---

For more details, please visit the [Documentation](https://tgo.ai).

## ✨ Features

### 🤖 AI Agent Orchestration
- **Multi-Agent Support** - Configure multiple AI agents for different business scenarios
- **Multi-Model Integration** - Connect with various LLM providers (OpenAI, Anthropic, etc.)
- **Streaming Response** - Real-time AI responses via SSE for smooth conversation experience
- **Context Memory** - Maintain conversation history for coherent dialogue

### 📚 Knowledge Base (RAG)
- **Document Knowledge Base** - Upload documents to enhance AI response accuracy
- **Q&A Knowledge Base** - Create question-answer pairs for quick knowledge expansion
- **Website Knowledge Base** - Crawl website content to keep information up-to-date
- **Smart Retrieval** - Vector-based semantic search for precise answers

### 🔧 MCP Tools Integration
- **Tool Store** - Rich library of MCP tools, enable on demand
- **Custom Tools** - Project-level tool configuration and management
- **OpenAPI Schema** - Auto-parse schemas to generate interactive forms

### 🌐 Multi-Channel Access
- **Web Widget** - Embeddable chat widget for websites
- **WeChat Integration** - Official Account and Mini Program support
- **Unified Management** - Manage all channels from a single dashboard

### 💬 Real-time Communication
- **WuKongIM Integration** - Stable and reliable instant messaging
- **WebSocket Connection** - Efficient bidirectional communication
- **Message Sync** - Read/unread status, delivery confirmation
- **Rich Media** - Support for text, images, files and more

### 👥 Human-AI Collaboration
- **Smart Handoff** - Seamlessly transfer to human agents when needed
- **Visitor Management** - Collect visitor info, assign sessions, track history
- **Agent Workspace** - Unified interface for human agents

### 🎨 UI Widget System
- **Structured Display** - Render orders, products, logistics as beautiful cards
- **Rich Components** - Order cards, logistics tracking, product display, price comparison
- **Action Protocol** - Standardized URI protocol for interactions

## 📦 Repository Structure

| Repository | Description | Tech Stack |
|:---|:---|:---|
| [tgo-ai](repos/tgo-ai) | AI/ML operations service for managing agents, tool bindings, knowledge bases, and usage analytics | Python / FastAPI |
| [tgo-api](repos/tgo-api) | Core business logic service handling user management, visitor tracking, assignment, and communication | Python / FastAPI |
| [tgo-cli](repos/tgo-cli) | CLI tool & MCP Server enabling AI agents to execute customer service operations with 40+ built-in tools | TypeScript / Node.js |
| [tgo-device-agent](repos/tgo-device-agent) | Embedded agent running on managed devices providing file and shell capabilities via TCP JSON-RPC | Go |
| [tgo-device-control](repos/tgo-device-control) | Device control service managing TCP/JSON-RPC connections for remote device management with MCP Agent | Python / FastAPI |
| [tgo-platform](repos/tgo-platform) | Multi-channel message intake service supporting WeChat, Feishu, DingTalk, Telegram, Slack, email, etc. | Python / FastAPI |
| [tgo-plugin-runtime](repos/tgo-plugin-runtime) | Plugin lifecycle management and execution service with dynamic tool synchronization | Python / FastAPI |
| [tgo-rag](repos/tgo-rag) | RAG service providing document processing, hybrid semantic/full-text search, and async processing | Python / FastAPI |
| [tgo-web](repos/tgo-web) | Admin frontend with real-time chat, AI agent management, knowledge base, and MCP tool integration | TypeScript / React 19 |
| [tgo-workflow](repos/tgo-workflow) | AI Agent workflow execution engine supporting DAG topology with LLM, API, condition, and tool nodes | Python / FastAPI |

### Widget SDKs

| Repository | Description | Tech Stack |
|:---|:---|:---|
| [tgo-widget-js](repos/tgo-widget-js) | Embeddable customer service chat widget (Intercom-style) for websites | TypeScript / React 18 |
| [tgo-widget-ios](repos/tgo-widget-ios) | Native iOS customer service chat SDK with SwiftUI views and UIKit bridging | Swift / SwiftUI |
| [tgo-widget-flutter](repos/tgo-widget-flutter) | Cross-platform customer service chat widget for iOS and Android | Dart / Flutter |
| [tgo-widget-cli](repos/tgo-widget-cli) | Visitor-facing CLI tool & MCP Server providing customer service interface | TypeScript / Node.js |
| [tgo-widget-miniprogram](repos/tgo-widget-miniprogram) | WeChat Mini Program chat widget component with AI streaming responses and Markdown rendering | TypeScript |

## 🏗️ System Architecture

<p align="center">
  <img src="resources/architecture_en.svg" width="100%" alt="TGO System Architecture">
</p>

## Product Preview

| | |
|:---:|:---:|
| **Dashboard** <br> <img src="resources/screenshot/en/home_dark.png" width="100%"> | **Agent Orchestration** <br> <img src="resources/screenshot/en/agent_dark.png" width="100%"> |
| **Knowledge Base** <br> <img src="resources/screenshot/en/knowledge_dark.png" width="100%"> | **Q&A Debugging** <br> <img src="resources/screenshot/en/knowledge_qa_dark.png" width="100%"> |
| **MCP Tools** <br> <img src="resources/screenshot/en/mcp_dark.png" width="100%"> | **Platform Admin** <br> <img src="resources/screenshot/en/platform_dark.png" width="100%"> |

## System Requirements
- **CPU**: >= 4 Core
- **RAM**: >= 8 GiB
- **OS**: macOS / Linux / WSL2
