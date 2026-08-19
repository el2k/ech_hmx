import json
import logging
import sys
import traceback
from contextvars import ContextVar
from datetime import datetime, timezone
from typing import Any, Dict, Optional
'''
    这三个变量是 上下文变量(ContextVar),作用是给当前请求/协程自动带上日志上下文。
    request_id_ctx:记录当前请求的唯一 ID,方便串联一整次请求的日志 
    project_id_ctx:记录当前项目 ID,方便按项目排查问题
    user_id_ctx:记录当前用户 ID,方便定位是谁触发的操作'''
request_id_ctx: ContextVar[Optional[str]] = ContextVar("request_id", default=None)
project_id_ctx: ContextVar[Optional[str]] = ContextVar("project_id", default=None)
user_id_ctx: ContextVar[Optional[str]] = ContextVar("user_id", default=None)
# Global flag to track if logging has been configured
_logging_configured = False
'''
这段代码定义了一个自定义的日志过滤器 ContextFilter，
它的核心作用是自动将当前请求的上下文信息（如请求ID、项目ID、用户ID）注入到每一条日志记录中。
这在 Web 服务或微服务架构中非常常见，主要用于日志追踪（Log Tracing），
让你能在海量日志中通过 request_id 快速串联起同一个请求的所有处理过程。
'''
class ContextFilter(logging.Filter):
    """
    Logging filter that automatically adds context variables to log records.

    Injects request_id, project_id, and user_id from context variables if available.
    """
    # 继承自 Python 标准库 logging.Filter，用于在日志输出前对日志记录（LogRecord）进行过滤或修改.

    def filter(self, record: logging.LogRecord) -> bool:
        """Add context variables to the log record."""
        # filter 方法是 logging.Filter 的核心方法。
        # 每当产生一条日志时，如果该 Filter 被添加到了 Logger 或 Handler 上，
        # 就会自动调用这个方法。传入的 record 就是当前这条日志的对象。

        # --- 注入 request_id (请求ID) ---
        # 从上下文变量（Context Variable）中获取当前的 request_id
        # 这里的 request_id_ctx 应该是在代码其他地方定义的 contextvars.ContextVar 对象
        request_id = request_id_ctx.get()
        # 如果获取到了有效的 request_id（不为 None 或空字符串）
        if request_id:
            # 动态地将 request_id 作为属性添加到日志记录对象上
            # 这样在后续的日志格式化（Formatter）中，就可以使用 %(request_id)s 来输出它
            record.request_id = request_id

        # --- 注入 project_id (项目ID) ---
        # 同样的逻辑，获取并注入项目ID，方便按项目维度过滤日志
        project_id = project_id_ctx.get()
        if project_id:
            record.project_id = project_id

        # --- 注入 user_id (用户ID) ---
        # 获取并注入当前操作用户的ID，方便追踪具体用户的操作轨迹
        user_id = user_id_ctx.get()
        if user_id:
            record.user_id = user_id

        # 始终返回 True
        # 因为这里的目的是“附加信息”而不是“拦截/丢弃日志”，
        # 所以无论是否成功注入了上下文变量，都允许这条日志继续被记录和输出
        return True
    
'''它的核心作用是将原本纯文本格式的日志转换为标准的 JSON 字符串。
这在现代云原生架构、微服务和 ELK（Elasticsearch, Logstash, Kibana）等日志收集系统中非常关键，
因为 JSON 格式可以被机器轻松解析、检索和聚合。'''
class JSONFormatter(logging.Formatter):
    """
    Custom JSON formatter for structured logging output.

    Formats log records as JSON with timestamp, level, logger name, message,
    and any additional context or extra fields.
    """
    # 继承 logging.Formatter，重写其核心的 format 方法，以实现自定义的 JSON 结构化输出。

    def format(self, record: logging.LogRecord) -> str:
        """Format the log record as JSON."""
        
        # 1. 构建基础的日志字典 (Base Log Entry)
        # 将日志记录对象（LogRecord）中的核心信息提取出来，放入一个字典中
        log_data: Dict[str, Any] = {
            # 将时间戳转换为 ISO 8601 格式的 UTC 时间字符串，这是日志系统的标准时间格式
            "timestamp": datetime.fromtimestamp(record.created, tz=timezone.utc).isoformat(),
            # 获取日志级别（如 INFO, ERROR），并统一转换为小写
            "level": record.levelname.lower(),
            # 获取产生日志的 Logger 名称
            "logger": record.name,
            # 获取格式化后的日志消息内容
            "event": record.getMessage(),
        }

        # 2. 注入上下文变量 (Context Variables)
        # 这里正好用到了你上一个问题中提到的 ContextFilter！
        # 检查日志记录对象上是否被 Filter 动态添加了这些属性
        if hasattr(record, "request_id"):
            log_data["request_id"] = record.request_id
        if hasattr(record, "project_id"):
            log_data["project_id"] = record.project_id
        if hasattr(record, "user_id"):
            log_data["user_id"] = record.user_id

        # 3. 捕获额外的自定义字段 (Extra Fields)
        # 开发者在打日志时可能会传入 extra={"user_agent": "xxx"}，这些会被附加到 record 上
        if hasattr(record, "__dict__"):
            # 定义一个黑名单，排除掉 Python logging 模块自带的标准属性，避免重复输出
            exclude_attrs = {
                "name", "msg", "args", "created", "filename", "funcName", "levelname",
                "levelno", "lineno", "module", "msecs", "message", "pathname", "process",
                "processName", "relativeCreated", "thread", "threadName", "exc_info",
                "exc_text", "stack_info", "request_id", "project_id", "user_id"
            }

            # 遍历日志记录对象的所有属性
            for key, value in record.__dict__.items():
                # 只保留不在黑名单中，且不以 "_" 开头的自定义属性
                if key not in exclude_attrs and not key.startswith("_"):
                    log_data[key] = value

        # 4. 处理异常信息 (Exception Info)
        # 如果当前日志是因为异常触发的（例如 logger.exception() 或 exc_info=True）
        if record.exc_info:
            # 将异常信息结构化，而不是像默认格式化器那样输出纯文本的 traceback
            log_data["exception"] = {
                # 异常类型名称，如 "ValueError"
                "type": record.exc_info[0].__name__ if record.exc_info[0] else None,
                # 异常的详细消息
                "message": str(record.exc_info[1]) if record.exc_info[1] else None,
                # 完整的堆栈追踪信息，格式化为字符串列表
                "traceback": traceback.format_exception(*record.exc_info)
            }

        # 5. 返回最终的 JSON 字符串
        # 将组装好的字典序列化为 JSON 格式，作为最终输出到文件或控制台的日志内容
        return json.dumps(log_data)
    
'''它的核心作用是为开发者提供高可读性、带颜色高亮的控制台日志输出。在本地开发或调试阶段，这种格式能让程序员一眼看清日志级别和关键上下文。'''
class ConsoleFormatter(logging.Formatter):
    """
    Custom console formatter for human-readable development output.

    Formats log records with colors and structured key-value pairs.
    """
    # 继承 logging.Formatter，专为本地控制台（终端）开发调试设计。

    # 1. 定义 ANSI 颜色转义码
    # 这些代码用于在支持 ANSI 的终端中给文本上色
    COLORS = {
        "DEBUG": "\033[36m",      # 青色 (Cyan)，通常用于调试信息
        "INFO": "\033[32m",       # 绿色 (Green)，表示正常流程
        "WARNING": "\033[33m",    # 黄色 (Yellow)，表示警告
        "ERROR": "\033[31m",      # 红色 (Red)，表示错误
        "CRITICAL": "\033[35m",   # 洋红色 (Magenta)，表示严重致命错误
    }
    RESET = "\033[0m"  # 重置颜色，防止后续终端输出被污染
    BOLD = "\033[1m"   # 加粗样式，用于突出核心日志消息

    def format(self, record: logging.LogRecord) -> str:
        """Format the log record for console output."""
        
        # 2. 根据日志级别获取对应的颜色
        # 如果级别不在字典中，默认返回空字符串（不上色）
        color = self.COLORS.get(record.levelname, "")

        # 3. 格式化时间戳
        # 转换为易读的 "年-月-日 时:分:秒" 格式
        timestamp = datetime.fromtimestamp(record.created, tz=timezone.utc).strftime("%Y-%m-%d %H:%M:%S")

        # 4. 构建基础日志消息部分
        # 使用列表收集各个片段，最后用空格拼接，保证格式整齐
        parts = [
            f"{timestamp}",
            # 将级别名称左对齐，固定占 8 个字符宽度，并用颜色包裹
            f"{color}[{record.levelname.lower():8}]{self.RESET}",
            # 核心日志消息，使用加粗样式
            f"{self.BOLD}{record.getMessage()}{self.RESET}",
        ]

        # 5. 收集上下文变量和额外字段 (Extra Fields)
        extra_fields = {}

        # 提取由 ContextFilter 注入的上下文变量
        if hasattr(record, "request_id"):
            extra_fields["request_id"] = record.request_id
        if hasattr(record, "project_id"):
            extra_fields["project_id"] = record.project_id
        if hasattr(record, "user_id"):
            extra_fields["user_id"] = record.user_id

        # 提取通过 extra={} 传入的自定义字段
        # 同样使用黑名单排除 logging 模块自带的标准属性
        exclude_attrs = {
            "name", "msg", "args", "created", "filename", "funcName", "levelname",
            "levelno", "lineno", "module", "msecs", "message", "pathname", "process",
            "processName", "relativeCreated", "thread", "threadName", "exc_info",
            "exc_text", "stack_info", "request_id", "project_id", "user_id"
        }

        for key, value in record.__dict__.items():
            if key not in exclude_attrs and not key.startswith("_"):
                extra_fields[key] = value

        # 6. 将额外字段格式化为 "key=value" 的紧凑形式
        # 例如: request_id=abc123 user_id=999
        if extra_fields:
            extra_str = " ".join(f"{k}={v}" for k, v in extra_fields.items())
            parts.append(extra_str)

        # 7. 拼接所有基础片段
        message = " ".join(parts)

        # 8. 处理异常信息 (Exception Info)
        # 如果有异常，将完整的堆栈追踪（traceback）追加到消息末尾，并换行显示
        if record.exc_info:
            message += "\n" + "".join(traceback.format_exception(*record.exc_info))

        # 9. 返回最终格式化后的纯文本字符串
        return message

'''它的核心作用是根据传入的参数（如日志级别、输出格式），自动完成日志系统的初始化工作：创建处理器、添加过滤器、设置格式化器，
并将它们全部挂载到根日志记录器上。这相当于一个“一键安装”脚本，让开发者无需在每个文件中重复配置。'''
def configure_logging(
    log_level: str = "INFO",
    json_output: bool = True,
    force_reconfigure: bool = False
) -> None:
    """
    Configure structured logging for the application.

    Args:
        log_level: Logging level (DEBUG, INFO, WARNING, ERROR, CRITICAL)
        json_output: If True, use JSON output (production). If False, use console output (development)
        force_reconfigure: If True, reconfigure even if already configured
    """
    # 声明使用全局变量 _logging_configured
    # 这个变量用于记录日志系统是否已经被配置过，防止重复配置
    global _logging_configured

    # 1. 幂等性检查 (Idempotency Check)
    # 如果已经配置过，且没有强制重新配置的指令，则直接返回，避免重复添加 Handler 导致日志重复打印
    if _logging_configured and not force_reconfigure:
        return

    # 2. 解析日志级别
    # 将传入的字符串（如 "INFO"）转换为 logging 模块对应的常量（如 logging.INFO）
    log_level = log_level.upper()
    level = getattr(logging, log_level, logging.INFO) # 如果找不到对应级别，默认为 INFO

    # 3. 获取根日志记录器 (Root Logger)
    # 获取全局的根 logger，所有 logger 最终都会向上传递给根 logger
    root_logger = logging.getLogger()

    # 4. 清理旧的处理器 (Handlers)
    # 如果是强制重新配置，先清空根 logger 上已有的所有处理器，确保配置干净
    if force_reconfigure:
        root_logger.handlers.clear()

    # 5. 设置根日志记录器的级别
    # 只有级别高于等于此设置的日志才会被处理
    root_logger.setLevel(level)

    # 6. 创建控制台处理器 (StreamHandler)
    # 创建一个将日志输出到标准输出（sys.stdout）的处理器
    handler = logging.StreamHandler(sys.stdout)
    handler.setLevel(level) # 设置处理器的级别

    # 7. 添加上下文过滤器 (ContextFilter)
    # 实例化之前定义的 ContextFilter
    # 并将其添加到处理器上，这样每条经过此处理器的日志都会被自动注入 request_id 等上下文信息
    context_filter = ContextFilter()
    handler.addFilter(context_filter)

    # 8. 设置格式化器 (Formatter)
    # 根据 json_output 参数决定使用哪种格式化器
    # - True: 使用 JSONFormatter，适合生产环境，方便机器解析
    # - False: 使用 ConsoleFormatter，适合开发环境，方便人类阅读
    if json_output:
        formatter = JSONFormatter()
    else:
        formatter = ConsoleFormatter()

    # 将选定的格式化器绑定到处理器上
    handler.setFormatter(formatter)

    # 9. 将处理器添加到根日志记录器
    root_logger.addHandler(handler)

    # 10. 禁止日志传播 (Prevent Propagation)
    # 设置为 False 可以防止日志向父级 logger 传播，避免在某些复杂配置下出现日志重复打印的问题
    root_logger.propagate = False

    # 11. 标记为已配置
    _logging_configured = True

'''它的核心作用是提供向后兼容的日志调用语法，让开发者能以更简洁、现代的方式（类似 structlog）传递上下文数据。
在 Python 标准库中，传递额外字段必须使用冗长的 extra={} 字典。这个适配器允许开发者直接使用 key=value 的形式，
并在底层自动将其转换为标准库能识别的格式。
拦截前：msg="User login", kwargs={"user_id": 123, "ip": "1.1.1.1"}
拦截后：msg="User login", kwargs={"extra": {"user_id": 123, "ip": "1.1.1.1"}}'''
class LoggerAdapter(logging.LoggerAdapter):
    """
    Custom logger adapter that provides backward compatibility with structlog-style logging.

    Allows both standard logging style:
        logger.info("message", extra={"key": "value"})

    And structlog-style (for backward compatibility):
        logger.info("message", key="value")
    """
    # 继承自 logging.LoggerAdapter。
    # LoggerAdapter 的作用是作为标准 Logger 的“代理”，在日志真正被记录之前，
    # 拦截并修改传入的消息或参数。

    def process(self, msg, kwargs):
        """Process the logging call to handle both styles."""
        # process 方法是 LoggerAdapter 的核心钩子。
        # 每次调用 logger.info() 等方法时，都会先经过这里。
        # msg: 日志消息
        # kwargs: 传递给日志方法的所有关键字参数

        # 1. 定义标准库保留的关键字集合
        # 这些是 logging 模块内部使用的参数，绝对不能被当作自定义字段处理
        standard_kwargs = {
            'extra', 'exc_info', 'stack_info', 'stacklevel',
            # Internal logging parameters that should not be overridden
            'level', 'pathname', 'lineno', 'msg', 'args', 'func'
        }

        # 2. 提取非标准的自定义字段
        extra_fields = {}      # 用于存放提取出的自定义字段
        keys_to_remove = []    # 记录需要从 kwargs 中删除的键

        for key, value in kwargs.items():
            # 如果参数不在标准库保留集合中，说明它是开发者传入的自定义业务字段
            if key not in standard_kwargs:
                extra_fields[key] = value
                keys_to_remove.append(key)

        # 3. 从原始 kwargs 中移除自定义字段
        # 防止这些字段被传给底层的 logging 模块导致 TypeError
        for key in keys_to_remove:
            del kwargs[key]

        # 4. 合并到标准的 extra 字典中
        # 如果调用方已经传了 extra={"a": 1}，且又传了 b=2，需要将它们合并
        if 'extra' in kwargs:
            if isinstance(kwargs['extra'], dict):
                kwargs['extra'].update(extra_fields)
            else:
                kwargs['extra'] = extra_fields
        elif extra_fields:
            # 如果原本没有 extra 参数，但提取出了自定义字段，则新建一个 extra 字典
            kwargs['extra'] = extra_fields

        # 5. 返回处理后的消息和参数
        # 此时 kwargs 中的自定义字段已经被安全地转移到了 extra 字典中
        return msg, kwargs

def get_logger(name: str) -> LoggerAdapter:
    """
    Get a configured logger instance.

    This is the main API for getting loggers throughout the application.
    The logger will automatically include context variables (request_id, project_id, etc.)

    Args:
        name: Logger name, typically __name__ of the calling module

    Returns:
        Configured LoggerAdapter instance that supports both standard logging
        and structlog-style keyword arguments

    Example:
        logger = get_logger(__name__)
        # Both styles work:
        logger.info("Processing file", file_id=file_id, status="started")
        logger.info("Processing file", extra={"file_id": file_id, "status": "started"})
    """
    # 1. 懒加载与防呆设计 (Lazy Initialization & Fail-Safe)
    # 检查日志系统是否已经配置。如果没有配置，自动使用默认参数进行配置。
    # 这极大地提高了系统的容错率：即使开发者忘记在 main.py 中调用 configure_logging()，
    # 只要调用了 get_logger，日志系统依然能正常工作。
    if not _logging_configured:
        # Auto-configure with defaults if not yet configured
        configure_logging()

    # 2. 获取标准库 Logger 并包装
    # 使用传入的模块名（通常是 __name__）获取 Python 原生的 Logger
    base_logger = logging.getLogger(name)
    # 使用之前定义的 LoggerAdapter 进行包装，返回给业务代码
    # 第二个参数 {} 是默认上下文，这里传空字典即可，因为上下文主要靠 ContextVar 动态注入
    return LoggerAdapter(base_logger, {})


def set_request_context(
    request_id: Optional[str] = None,
    project_id: Optional[str] = None,
    user_id: Optional[str] = None
) -> None:  
    """
    Set context variables for the current async context.

    These values will be automatically included in all log entries within this context.

    Args:
        request_id: Unique request identifier
        project_id: Project identifier
        user_id: User identifier

    Example:
        set_request_context(request_id="req-123", project_id="proj-456")
        logger.info("Processing")  # Will include request_id and project_id
    """
    # 3. 安全地设置上下文变量 (Context Variables)
    # 只有当参数不为 None 时才进行设置，避免意外覆盖上下文中已有的值
    if request_id is not None:
        request_id_ctx.set(request_id)
    if project_id is not None:
        project_id_ctx.set(project_id)
    if user_id is not None:
        user_id_ctx.set(user_id)


def clear_request_context() -> None:
    """
    Clear all context variables for the current async context.

    Useful for cleanup after request processing.
    """
    # 4. 上下文清理 (Context Cleanup)
    # 将上下文变量重置为 None。
    # 这通常用在请求处理完毕后的中间件中，防止上一个请求的上下文数据
    # 泄漏到下一个请求中（尤其是在使用线程池或协程复用的场景下）。
    request_id_ctx.set(None)
    project_id_ctx.set(None)
    user_id_ctx.set(None)


def init_logging_from_settings() -> None:
    """
    Initialize logging using application settings.

    This should be called once at application startup.
    Reads configuration from settings and configures logging accordingly.
    """
    # 5. 从应用配置中初始化日志 (Settings-Driven Initialization)
    # 这是一个非常工程化的最佳实践：将日志配置与业务配置解耦。
    # 导入应用的配置对象（通常基于 Pydantic 或类似库）
    from .config import get_settings

    settings = get_settings()

    # 根据运行环境自动决定输出格式：
    # 开发环境 (development) -> 使用彩色控制台输出 (json_output=False)
    # 生产/测试环境 -> 使用 JSON 结构化输出 (json_output=True)
    json_output = settings.environment.lower() != "development"

    # 调用核心配置函数，并强制重新配置（force_reconfigure=True），
    # 确保应用启动时的配置是最新的。
    configure_logging(
        log_level=settings.log_level,
        json_output=json_output,
        force_reconfigure=True
    )
'''
def __main__():
    """Simple smoke test for logging module."""
    # 强制使用控制台输出，便于本地直接观察
    configure_logging(log_level="INFO", json_output=False, force_reconfigure=True)

    logger = get_logger(__name__)

    # 测试上下文注入
    set_request_context(
        request_id="test-request-001",
        project_id="test-project-001",
        user_id="test-user-001",
    )

    logger.info("logging module smoke test started", step="init")

    # 测试普通日志
    # ...existing code...
    logger.info("hello from logging module", component="logging_config")
    # ...existing code...

    # 测试异常日志
    try:
        1 / 0
    except Exception:
        logger.exception("exception logging test", step="exception")

    # 测试清理上下文
    clear_request_context()
    logger.info("logging module smoke test finished", step="done")


if __name__ == "__main__":
    __main__()
'''