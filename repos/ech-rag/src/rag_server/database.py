import logging
from contextlib import asynccontextmanager
from typing import AsyncGenerator

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool
from sqlalchemy import text

from .config import get_settings
from .models import Base

logger = logging.getLogger(__name__)

# Global variables for database engine and session factory
engine = None
async_session_factory = None
# 解决celery worker中出现的"Future attached to a different loop"错误
def reset_db_state():
    global engine, async_session_factory
    engine = None
    async_session_factory = None
    logger.debug("Database state reset for new event loop")

# 这段代码是一个非常规范且健壮的生产级异步数据库引擎（Async Engine）工厂函数。
# 它通过区分运行环境，动态调整了数据库连接池（Connection Pool）的策略，以兼顾开发调试的便利性与生产环境的性能。
def create_database_engine():
    global engine
    settings = get_settings()
    engine_kwargs = {
        "echo":settings.debug, # 在调试模式下，SQLAlchemy会打印所有执行的SQL语句，方便开发者进行调试和排查问题。
        "pool_pre_ping": True, # 这个参数启用了连接池的“预检测”功能，在每次从连接池获取连接时，都会先执行一个轻量级的SQL查询（通常是SELECT 1），以确保连接仍然有效。这对于长时间运行的应用程序尤为重要，因为数据库连接可能会因为网络问题或数据库重启而失效。
    }
    if settings.environment in ("development", "test"):
        engine_kwargs["poolclass"] = NullPool  
        # 在开发和测试环境中，使用NullPool意味着每次请求数据库时都会创建一个新的连接，而不是从连接池中复用已有的连接。
        # 这种方式虽然在性能上不如连接池高效，但它简化了调试过程，因为每次请求都是独立的，避免了连接状态的干扰。
    else:
        engine_kwargs.update({
            "pool_size": settings.database_pool_size,  # 连接池的大小，决定了同时可以保持多少个数据库连接。
            "max_overflow": settings.database_max_overflow, # 允许的最大溢出连接数，即在连接池满时，额外可以创建的临时连接数。
            "pool_timeout": settings.database_pool_timeout, # 获取连接的超时时间，超过这个时间未获取到连接时，会抛出异常，防止请求无限期等待。
        })
    engine = create_async_engine(settings.database_url, **engine_kwargs)
    logger.info(f"Database engine created for {settings.environment} environment")
    return engine

# 它利用已创建的全局 engine，实例化了一个异步会话工厂（async_sessionmaker）。

def create_session_factory():
    global async_session_factory,engine
    if engine is None:
        engine = create_database_engine()
    async_session_factory = async_sessionmaker(
        engine,
        class_=AsyncSession, # 指定了会话类为 AsyncSession，这是 SQLAlchemy 提供的异步会话类，支持异步数据库操作。
        expire_on_commit=False, # 设置为 False，意味着在事务提交后，ORM 对象不会过期，仍然可以继续访问其属性。
        autoflush=True, # 设置为 True，表示在执行查询之前，会自动将会话中的更改刷新到数据库。这有助于确保查询结果的准确性。
        autocommit=False, # 设置为 False，表示会话不会自动提交事务，需要显式调用 commit() 方法来提交事务。
    )
    logger.info("Async session factory created")
    return async_session_factory

# 这段代码使用 Python 的 contextlib 库定义了一个异步上下文管理器，用于安全、优雅地管理异步数据库会话（AsyncSession）。

'''@asynccontextmanager：这是 contextlib 提供的装饰器。它允许你将一个包含 yield 的异步生成器函数，
直接转换为一个异步上下文管理器。这意味着你可以使用 async with get_db_session() as session: 的语法来管理资源。'''
@asynccontextmanager
async def get_db_session() -> AsyncGenerator[AsyncSession, None]:
    global async_session_factory
    if async_session_factory is None:
        async_session_factory = create_session_factory()
# async with async_session_factory() as session:：从工厂获取一个 session，并在退出时自动处理底层连接的归还
    async with async_session_factory() as session:
        try:
            yield session
# yield session：将 session 交给调用方（即 async with 块内的代码）。调用方在此期间执行各种数据库查询或修改
            await session.commit()
# await session.commit()：如果 yield 之后的代码没有抛出异常（即业务逻辑顺利执行完毕），则自动提交事务。这实现了自动提交机制
        except Exception as e:
            await session.rollback()
            logger.error(f"Session rollback due to exception: {e}")
            raise
        finally:
            await session.close()

# FastAPI 的依赖注入约定：FastAPI 官方推荐通过 yield 来管理依赖项的生命周期。
# 当一个依赖项（Dependency）是一个带有 yield 的异步生成器时，FastAPI 会在路由函数执行前获取 yield 前面的值（注入给路由），
# 在路由函数执行完毕后，自动接管 yield 后面的清理工作。
async def get_db_session_dependency() -> AsyncGenerator[AsyncSession,None]:
    async with get_db_session() as session:
        yield session

# 初始化数据库引擎
async def init_database():
    global engine
    if engine is None:
        engine = create_database_engine()
    logger.info("Database initialized (schema management by Alembic)")

# 关闭数据库引擎
async def close_database():
    global engine
    if engine:
        await engine.dispose()
        logger.info("Database engine disposed")
# 为什么必须调用？ 如果应用重启或关闭时不调用 dispose()，底层的 TCP 连接可能不会被正确释放，
# 导致数据库端出现大量 Sleep 状态的僵尸连接，最终耗尽数据库的最大连接数（max_connections），引发严重的线上故障。

async def check_database_connection() -> bool:
# 这个函数用于检查数据库连接是否正常。它通过执行一个简单的 SQL 查询（SELECT 1）来验证数据库的可用性。
    try:
        async with get_db_session() as session:
            result = await session.execute(text("SELECT 1")) # select 1 是一个非常轻量级的查询，它不会对数据库造成负担，但足以验证连接是否可用。
            result.scalar()  # 获取查询结果的标量值
        return True
    except Exception as e:
        logger.error(f"Database connection check failed: {e}")
        return False

async def create_tables():
    # 这个函数用于在数据库中创建所有定义的表结构
    await init_database()  # 确保数据库引擎已初始化

async def drop_tables():
    # 这个函数用于在数据库中删除所有定义的表结构
    global engine
    if engine is None:
        engine = create_database_engine()  # 确保数据库引擎已初始化
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)  # 删除所有表结构
    logger.warning("All database tables dropped")

async def reset_database():
    # 这个函数用于重置数据库，即删除所有表结构并重新创建它们
    await drop_tables()  # 删除所有表结构
    await create_tables()  # 重新创建所有表结构
    logger.info("Database reset completed")

# 这段代码实现了一个数据库健康检查（Health Check）机制，通常用于微服务架构中的探针（Probes），
# 如 Kubernetes 的 Liveness/Readiness Probe，或者运维监控系统的告警触发器。

async def database_health_check() -> dict:
    health_status = {
        "status": "unhealthy",
        "connection": False,
        "tables_exist": False,
        "error": None
    }
    try:
        connection_ok = await check_database_connection()
        health_status["connection"] = connection_ok
        if connection_ok:
            async with get_db_session() as session:
                result = await session.execute(text("SELECT 1 FROM rag_projects LIMIT 1"))
                result.scalar()  # 尝试查询一个主要表，以验证表是否存在
                health_status["tables_exist"] = True
                health_status["status"] = "healthy"
    except Exception as e:
        health_status["error"] = str(e)
        logger.error(f"Database health check failed: {e}")
    return health_status