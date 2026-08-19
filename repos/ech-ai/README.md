
**ECH‑Tech AI Service** — AI/ML 微服务

本服务为 ECH‑Tech 客服平台提供 AI 智能体管理、知识库操作以及用量统计分析能力。

## 功能特性
- **团队管理**：创建并管理团队，用于对AI智能体做分组组织
- **智能体管理**：AI智能体完整增删改查能力，基于团队做资源划分
- **工具集成**：管理AI智能体绑定的工具
- **知识库**：为RAG检索增强功能提供集合（知识库）管理
- **用量统计**：完整的数据追踪与监控
- **双重身份认证**：同时支持JWT令牌与API密钥两种鉴权方式
- **多租户**：基于项目的数据隔离与访问权限控制

## 技术架构
- **Web框架**：FastAPI，自动生成OpenAPI接口文档
- **数据库**：PostgreSQL，搭配SQLAlchemy ORM，完整支持异步
- **身份认证**：JWT + API密钥
- **依赖注入**：使用FastAPI原生依赖注入管理业务服务
- **配置管理**：Pydantic Settings，支持环境变量读取
- **日志**：基于structlog的结构化日志
- **测试**：基于pytest的完整测试套件，支持依赖Mock模拟

## 快速开始
### 前置依赖
- Python 3.11 及以上版本
- PostgreSQL 12 及以上版本
- Poetry（依赖包管理工具）

### 安装部署
1. 克隆代码仓库
```bash
git clone <repository-url>
cd tgo-ai-service
```

2. 安装项目依赖
```bash
poetry install
```

激活虚拟环境：
```bash
eval $(poetry env activate)
```

3. 配置环境变量
```bash
cp .env.example .env
# 修改 .env 文件，填入对应配置
```

4. 执行数据库迁移
```bash
poetry run alembic upgrade head
```

5. 启动开发服务
```bash
poetry run uvicorn app.main:app --reload --host 0.0.0.0 --port 8081
```

服务启动后访问地址：`http://localhost:8081`
交互式接口文档地址：`http://localhost:8081/docs`

## 配置说明
本服务全部通过环境变量进行配置，全部可配置项参考 `.env.example`。

### 核心配置项
- `DATABASE_URL`：PostgreSQL数据库连接字符串
- `SECRET_KEY`：JWT签名密钥
- `API_KEY_PREFIX`：API密钥前缀（默认：`ak_`）
- `LOG_LEVEL`：日志级别（DEBUG / INFO / WARNING / ERROR）
- `CORS_ORIGINS`：允许跨域访问的来源域名
- `AGENT_SERVICE_URL`：外部智能体运行时服务的基础地址

## API接口文档
项目提供完整OpenAPI文档，访问地址：
- 交互式Swagger文档：`http://localhost:8081/docs`
- ReDoc文档：`http://localhost:8081/redoc`
- OpenAPI原始JSON：`http://localhost:8081/openapi.json`

### 接口鉴权方式
接口支持两种认证方案：

1. **JWT鉴权（服务间调用）**
```bash
Authorization: Bearer <jwt-token>
```

2. **API密钥鉴权（绑定项目维度）**
```bash
X-API-Key: ak_live_1234567890abcdef
```

## 开发指南
### 执行测试用例
```bash
# 执行全部测试
poetry run pytest

# 执行测试并输出覆盖率
poetry run pytest --cov=app

# 运行指定测试文件
poetry run pytest tests/test_teams.py

# 仅执行集成测试
poetry run pytest -m integration
```

### 代码质量工具
```bash
# 代码格式化
poetry run black app tests
poetry run isort app tests

# 代码静态检查
poetry run flake8 app tests
poetry run mypy app

# 执行pre‑commit校验钩子
poetry run pre-commit run --all-files
```

### 数据库迁移（Alembic）
项目使用Alembic做数据库版本迁移，支持异步PostgreSQL。
```bash
# 自动生成迁移脚本
poetry run alembic revision --autogenerate -m "描述信息"

# 执行全部迁移，升级到最新版本
poetry run alembic upgrade head

# 回滚一次迁移
poetry run alembic downgrade -1

# 仅输出SQL脚本，不实际执行（离线模式）
poetry run alembic upgrade head --sql

# 查看当前迁移版本
poetry run alembic current

# 查看迁移历史
poetry run alembic history
```

> 注意：迁移环境配置：在线迁移使用异步`asyncpg`驱动；离线生成SQL脚本使用同步驱动。

### 依赖注入
项目基于FastAPI原生依赖注入管理业务服务：
```python
# 业务服务通过Depends注入
@router.get("/teams")
async def list_teams(
    team_service: TeamService = Depends(get_team_service),
    project_id: uuid.UUID = Depends(get_current_project_id),
) -> dict:
    teams, total = await team_service.list_teams(project_id)
    return {"data": teams, "total": total}
```

**优势：**
- **易于测试**：单元测试中可以很方便mock模拟业务服务
- **关注点分离**：各层职责边界清晰
- **灵活可替换**：业务实现可以轻松替换
- **原生适配FastAPI**

### 开发环境专属能力
项目内置开发环境便捷特性

#### 开发专用API密钥
- 当环境变量 `ENVIRONMENT=development`，会自动生成特殊密钥 `dev`
- 使用该密钥可以直接访问接口，无需配置正式API密钥
- 应用启动时会自动初始化开发测试项目数据
- **生产环境下 `dev` 密钥会直接返回401拒绝访问**

```bash
# 开发模式启动服务
ENVIRONMENT=development poetry run uvicorn app.main:app --reload

# 使用开发密钥测试接口
curl -H "X-API-Key: dev" http://localhost:8000/api/v1/teams
```

#### OpenAPI文档鉴权
- Swagger UI同时支持JWT Bearer令牌、API密钥两种鉴权
- 在 `/docs` 页面点击「Authorize」按钮填入鉴权信息
- 开发环境：API密钥填写 `dev`
- 生产环境：使用项目真实API密钥，格式：`ak_...`

**鉴权模式：**
- **Bearer Auth**：请求头 `Authorization: Bearer <token>` 携带JWT
- **API Key Auth**：请求头 `X‑API‑Key: <key>` 携带API密钥

## 项目目录结构
```
app/
├── __init__.py
├── main.py                 # FastAPI应用入口
├── config.py              # 配置读取
├── database.py            # 数据库连接、会话管理
├── dependencies.py        # FastAPI依赖
├── exceptions.py          # 自定义异常类
├── middleware.py          # 自定义中间件
├── models/                # SQLAlchemy数据库ORM模型
├── schemas/               # Pydantic接口数据模型
├── api/                   # API路由
├── services/              # 业务逻辑服务层
├── auth/                  # 认证鉴权模块
└── utils/                 # 通用工具函数

tests/                     # 测试用例目录
migrations/               # Alembic数据库迁移脚本
```

## 部署
### Docker部署
```bash
# 构建镜像
docker build -t tgo-ai-service .

# 启动容器
docker run -p 8081:8081 --env-file .env tgo-ai-service
```

## 贡献代码
1. Fork本仓库
2. 创建功能分支
3. 编写代码
4. 为新增功能补充单元测试
5. 保证全部测试用例通过
6. 提交Pull Request
