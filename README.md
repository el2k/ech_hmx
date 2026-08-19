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


