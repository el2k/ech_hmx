"""
API v1 版本总路由入口
作用：统一导入并挂载所有 v1 版本的业务接口路由
统一管理接口前缀、接口文档分组（tags）
"""

from fastapi import APIRouter

# 导入所有 v1 版本下的业务模块子路由
from app.api.v1.endpoints import (
    ai_agents,               # AI 智能体相关接口
    ai_models,               # AI 模型管理接口
    ai_skills,               # AI 技能配置接口
    ai_tools,                # AI 工具管理接口
    ai_workflows,            # AI 工作流编排接口
    conversations,           # 会话/对话记录接口
    device_control,          # 设备控制代理接口
    docs,                    # 统一文档接口
    email,                   # 邮件发送/管理接口
    onboarding,              # 初始化引导/配置接口
    platforms,               # 第三方平台接入接口
    plugins,                 # 插件系统主接口
    plugin_tools,            # 插件工具管理接口
    projects,                # 项目管理接口
    remote_agents,           # 远端智能体（AgentOS）管理接口
    wukongim,                # 悟空 IM 即时通讯接口
    wukongim_webhook,        # 悟空 IM WebHook 回调接口
    rag_collections,         # RAG 知识库集合管理
    rag_files,               # RAG 文件上传与解析
    rag_qa_pairs,            # RAG 问答对管理
    rag_websites,            # RAG 网站内容抓取
    sessions,                # 用户在线会话管理
    staff,                   # 客服/员工管理接口
    tags,                    # 标签管理接口
    visitors,                # 访客管理接口
    visitor_assignment_rules, # 访客分配规则接口
    visitor_waiting_queue,   # 访客等待队列接口
    chat,                    # 聊天接口
    channels,                # 渠道管理接口
    search,                  # 全局搜索接口
    ai_providers,            # AI 服务商（如 OpenAI 等）管理
    ai_runs,                 # AI 执行任务记录
    setup,                   # 系统初始化安装接口
    system,                  # 系统信息、监控、配置接口
    store,                   # 应用商店/插件市场接口
    utils,                   # 通用工具接口（时间、加密、校验等）
)

# 创建 v1 版本总路由实例
api_router = APIRouter()

# ====================== 系统初始化接口（无需登录鉴权） ======================
api_router.include_router(
    setup.router,            # 初始化子路由
    prefix="/setup",         # 接口前缀：/v1/setup/xxx
    tags=["Setup"]           # Swagger 文档分组：Setup
)

# ====================== 核心业务接口 ======================
# 项目管理
api_router.include_router(
    projects.router,
    prefix="/projects",
    tags=["Projects"]
)

# 初始化引导流程（需 JWT 登录，项目 ID 从当前用户上下文获取）
api_router.include_router(
    onboarding.router,
    prefix="/onboarding",
    tags=["Onboarding"]
)

# 员工/坐席管理
api_router.include_router(
    staff.router,
    prefix="/staff",
    tags=["Staff"]
)

# 访客管理
api_router.include_router(
    visitors.router,
    prefix="/visitors",
    tags=["Visitors"]
)

# 访客分配规则
api_router.include_router(
    visitor_assignment_rules.router,
    prefix="/visitor-assignment-rules",
    tags=["Visitor Assignment Rules"]
)

# 访客等待队列
api_router.include_router(
    visitor_waiting_queue.router,
    prefix="/visitor-waiting-queue",
    tags=["Visitor Waiting Queue"]
)

# 标签管理
api_router.include_router(
    tags.router,
    prefix="/tags",
    tags=["Tags"]
)

# 第三方平台对接
api_router.include_router(
    platforms.router,
    prefix="/platforms",
    tags=["Platforms"]
)

# AI 模型服务商管理（如 OpenAI、Anthropic、本地模型等）
api_router.include_router(
    ai_providers.router,
    prefix="/ai/providers",
    tags=["AI Providers"]
)

# ====================== RAG 知识库服务接口 ======================
# RAG 知识库集合
api_router.include_router(
    rag_collections.router,
    prefix="/rag/collections",
    tags=["RAG Collections"]
)

# RAG 文件管理
api_router.include_router(
    rag_files.router,
    prefix="/rag/files",
    tags=["RAG Files"]
)

# RAG 网站抓取
api_router.include_router(
    rag_websites.router,
    prefix="/rag/websites",
    tags=["RAG Websites"]
)

# RAG 问答对管理
api_router.include_router(
    rag_qa_pairs.router,
    prefix="/rag",
    tags=["RAG QA Pairs"]
)

# AI 模型管理
api_router.include_router(
    ai_models.router,
    prefix="/ai-models",
    tags=["AI Models"]
)

# AI 智能体
api_router.include_router(
    ai_agents.router,
    prefix="/ai/agents",
    tags=["AI Agents"]
)

# AI 执行记录（AI 调用日志、任务执行）
api_router.include_router(
    ai_runs.router,
    prefix="/ai/runs",
    tags=["AI Runs"]
)

# AI 工具
api_router.include_router(
    ai_tools.router,
    prefix="/ai/tools",
    tags=["AI Tools"]
)

# AI 技能
api_router.include_router(
    ai_skills.router,
    prefix="/ai/skills",
    tags=["AI Skills"]
)

# AI 工作流
api_router.include_router(
    ai_workflows.router,
    prefix="/ai/workflows",
    tags=["AI Workflows"]
)

# ====================== 即时通讯 IM 接口 ======================
# 悟空 IM 主接口
api_router.include_router(
    wukongim.router,
    prefix="/wukongim",
    tags=["WuKongIM"]
)

# 悟空 IM WebHook 回调（无额外前缀）
api_router.include_router(
    wukongim_webhook.router
)

# ====================== 消息与邮件 ======================
# 邮件服务
api_router.include_router(
    email.router,
    prefix="/email",
    tags=["Email"]
)

# 聊天接口
api_router.include_router(
    chat.router,
    prefix="/chat",
    tags=["Chat"],
)

# 渠道管理（如网页端、小程序、APP 等接入渠道）
api_router.include_router(
    channels.router,
    prefix="/channels",
    tags=["Channels"],
)

# 对话记录管理
api_router.include_router(
    conversations.router,
    prefix="/conversations",
    tags=["Conversations"],
)

# 用户会话管理
api_router.include_router(
    sessions.router,
    prefix="/sessions",
    tags=["Sessions"],
)

# 全局搜索
api_router.include_router(
    search.router,
    prefix="/search",
    tags=["Search"],
)

# ====================== 系统与工具 ======================
# 系统信息、监控、运行状态
api_router.include_router(
    system.router,
    prefix="/system",
    tags=["System"],
)

# 统一接口文档
api_router.include_router(
    docs.router,
    tags=["Documentation"],
)

# 应用商店/市场
api_router.include_router(
    store.router,
    prefix="/store",
    tags=["Store"],
)

# 通用工具类接口
api_router.include_router(
    utils.router,
    prefix="/utils",
    tags=["Utils"],
)

# ====================== 插件系统 ======================
# 插件工具管理
api_router.include_router(
    plugin_tools.router,
    prefix="/plugins/tools",
    tags=["Plugin Tools"],
)

# 插件主管理
api_router.include_router(
    plugins.router,
    prefix="/plugins",
    tags=["Plugins"],
)

# ====================== 设备与远端智能体 ======================
# 设备控制（代理转发到 tgo-device-control 微服务）
api_router.include_router(
    device_control.router,
    prefix="/device-control",
    tags=["Device Control"],
)

# 远端智能体管理（对接 AgentOS）
api_router.include_router(
    remote_agents.router,
    prefix="/remote-agents",
    tags=["Remote Agents"],
)
'''这是一个典型的 FastAPI 模块化路由设计
所有业务模块拆分为独立子路由，统一在 api_router 挂载
每个模块有独立 prefix 和 tags，方便在 Swagger 文档中分类
接口按业务域划分：系统初始化、项目、访客、AI、RAG、IM、插件、设备、远端智能体等
无业务逻辑，只做路由聚合，便于扩展和维护'''