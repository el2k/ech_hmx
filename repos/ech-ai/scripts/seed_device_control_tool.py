"""
种子脚本：将 tgo‑device-control 注册为 MCP 工具，写入 ai_tools 数据表

使用方式：
    python -m scripts.seed_device_control_tool --project-id <UUID>

功能说明：
    在数据库 ai_tools 表插入一条【本地MCP工具】记录，指向 tgo‑device-control 的 MCP Streamable‑HTTP 接口地址。
    URL 中包含模板变量 ``{device_id}``，运行时会被替换为真实设备的UUID。

注意：
    脚本仅仅完成工具注册；**还需要通过管理后台界面 / API，在 ai_agent_tool_associations 表把该工具绑定给某个Agent，Agent才可以调用**。


执行seed_device_control_tool.py
        ↓
ai_tools表新增一条MCP工具记录（endpoint带{device_id}模板）
        ↓
手动/接口写入 ai_agent_tool_associations，绑定Agent ←【必须做】
        ↓
Agent执行推理，决定调用设备控制工具
        ↓
后端读取ai_tools记录，把endpoint模板 {device_id} 替换为真实设备UUID
        ↓
HTTP请求访问 tgo‑device‑control 的MCP‑HTTP接口
        ↓
设备控制MCP服务执行截图、点击等动作，MCP协议返回结果给Agent大模型
"""

import argparse
import uuid
import sys

import sqlalchemy as sa

# ------------------------------------------------------------------ #
# 配置区 — 根据实际环境修改参数
# ------------------------------------------------------------------ #

TABLE_NAME = "ai_tools"                     # 存储AI工具的数据库表
TOOL_NAME = "device-control"                # 工具内部标识名
TOOL_TITLE_ZH = "设备控制"                  # 工具中文显示名称
TOOL_TITLE_EN = "Device Control"            # 工具英文显示名称
TOOL_DESCRIPTION = (
    "MCP透明代理，用于远程设备控制。"
    "动态暴露目标设备的可用工具（截图、点击、输入文字、滚动页面等），基于MCP协议调用。"
    "接口地址中的 {device_id} 会在运行时替换为目标设备的UUID。"
)

# Docker内部网络地址，容器之间互通；根据部署情况修改host/port
DEVICE_CONTROL_ENDPOINT = "http://tgo-device-control:8085/mcp/{device_id}"


def main() -> None:
    # 解析命令行参数
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--project-id",
        required=True,
        type=str,
        help="要注册该工具所属项目的UUID",
    )
    parser.add_argument(
        "--database-url",
        default=None,
        help="PostgreSQL数据库连接地址，不填则自动读取ai服务的.env配置",
    )
    parser.add_argument(
        "--endpoint",
        default=DEVICE_CONTROL_ENDPOINT,
        help=f"MCP接口模板地址，默认：{DEVICE_CONTROL_ENDPOINT}",
    )
    args = parser.parse_args()

    # 1、获取数据库连接URL
    db_url = args.database_url
    if not db_url:
        try:
            # 导入项目配置，读取.env中的DATABASE_URL
            from app.config import settings  # type: ignore[import-untyped]
            db_url = str(settings.DATABASE_URL)
        except Exception:
            print(
                "ERROR: 无法获取数据库地址。"
                "请手动传入 --database-url 参数，或者在 tgo‑ai‑service 目录下运行脚本。",
                file=sys.stderr,
            )
            sys.exit(1)

    # 2、适配同步数据库驱动
    # 项目业务代码用asyncpg异步驱动；本脚本是种子脚本，需要同步psycopg2驱动，做替换
    if "asyncpg" in db_url:
        db_url = db_url.replace("postgresql+asyncpg://", "postgresql+psycopg2://")

    # 创建同步数据库引擎
    engine = sa.create_engine(db_url)

    tool_id = uuid.uuid4()          # 生成新工具的唯一ID
    project_id = uuid.UUID(args.project_id)

    # 3、构造插入SQL，写入ai_tools表
    # tool_type='MCP'：标记为MCP类型工具
    # transport_type='http'：使用MCP Streamable HTTP传输模式（不是stdio子进程模式）
    # tool_source_type='LOCAL'：属于本平台内部的MCP服务
    # ON CONFLICT DO NOTHING：记录已存在则跳过，不会重复插入
    insert_sql = sa.text(f"""
        INSERT INTO {TABLE_NAME} (
            id, project_id, name, title_zh, title_en, description,
            tool_type, transport_type, endpoint,
            tool_source_type, config,
            created_at, updated_at
        ) VALUES (
            :id, :project_id, :name, :title_zh, :title_en, :description,
            'MCP', 'http', :endpoint,
            'LOCAL', '{{}}'::jsonb,
            NOW(), NOW()
        )
        ON CONFLICT DO NOTHING
    """)

    # 开启事务执行插入
    with engine.begin() as conn:
        conn.execute(
            insert_sql,
            {
                "id": tool_id,
                "project_id": project_id,
                "name": TOOL_NAME,
                "title_zh": TOOL_TITLE_ZH,
                "title_en": TOOL_TITLE_EN,
                "description": TOOL_DESCRIPTION,
                "endpoint": args.endpoint,
            },
        )

    # 输出注册成功信息
    print(f"✅ MCP工具注册完成：")
    print(f"  ID:         {tool_id}")
    print(f"  Project:    {project_id}")
    print(f"  Name:       {TOOL_NAME}")
    print(f"  Endpoint:   {args.endpoint}")
    print(f"  Source:     LOCAL")
    print(f"  Transport:  http (MCP Streamable HTTP)")
    print()
    print(
        "👉 下一步操作：需要在管理后台界面，或者操作 ai_agent_tool_associations 表，"
        "把本工具绑定给目标Agent，Agent才能够调用设备控制能力。"
    )


if __name__ == "__main__":
    main()