# TGO Workflow Engine

AI Agent Workflow 后端引擎，基于 FastAPI 和 Celery 构建。

## 功能特性

- **可视化编排**: 支持 DAG (有向无环图) 拓扑执行。
- **多种节点类型**: 
  - `start`, `end`: 流程起止。
  - `llm`: 大语言模型调用。
  - `api`: 外部 HTTP 接口调用。
  - `condition`: 条件分支判断。
  - `classifier`: 语义分类路由。
  - `agent`, `tool`: 集成主系统的 AI 员工和 MCP 工具。
- **变量系统**: 支持 `{{reference_key.var}}` 格式的变量引用和模板渲染。
- **异步执行**: 使用 Celery + Redis 处理耗时任务。
- **执行追踪**: 详细记录每个节点的状态、输入、输出和执行时长。

## 技术栈

- **框架**: FastAPI
- **任务队列**: Celery + Redis
- **数据库**: PostgreSQL (SQLAlchemy 2.0 + Alembic)
- **并发**: asyncio, httpx

## 快速开始

### 1. 启动基础设施 (PostgreSQL & Redis)

```bash
cd tgo-workflow
docker-compose up -d
```

### 2. 安装依赖

```bash
# 安装 Poetry (如果尚未安装)
curl -sSL https://install.python-poetry.org | python3 -

# 安装项目依赖
poetry install
```

### 3. 运行数据库迁移

```bash
poetry run alembic upgrade head
```

### 4. 启动 API 服务

```bash
poetry run uvicorn app.main:app --reload
```

### 5. 启动 Celery Worker

```bash
poetry run celery -A celery_app.celery worker --loglevel=info
```

## API 文档

启动服务后访问:
- Swagger UI: `http://localhost:8000/docs`
- ReDoc: `http://localhost:8000/redoc`

## 项目结构

- `app/api`: 路由定义。
- `app/engine`: 核心执行逻辑、拓扑排序、上下文管理。
- `app/engine/nodes`: 各类型节点的执行实现。
- `app/models`: 数据库 ORM 模型。
- `app/schemas`: Pydantic 数据验证模型。
- `app/services`: 业务逻辑层。
- `celery_app`: 异步任务配置与定义。

