"""Logging configuration."""
# 模块功能：统一的应用日志配置，提供控制台文本输出 + 文件JSON结构化输出
# 核心特性：自定义JSON字段规范、启动日志纯净输出、自动携带extra上下文、第三方日志降噪


# 导入Python标准日志库、操作系统接口、JSON序列化工具
import logging
import os
import json

# 导入第三方JSON日志格式化器，用于将日志输出为标准JSON格式
from pythonjsonlogger import jsonlogger


class CustomJsonFormatter(jsonlogger.JsonFormatter):
    """Custom JSON formatter that includes extra fields automatically."""
    # 自定义JSON日志格式化器，继承自python-json-logger的基础实现
    # 作用：统一JSON日志的字段命名，规范输出结构，适配日志采集系统（ELK/Loki等）

    def add_fields(self, log_record, record, message_dict):
        """重写字段添加钩子，自定义最终输出的JSON字段结构。"""
        # 先调用父类方法，填充默认的基础字段
        super().add_fields(log_record, record, message_dict)

        # 统一添加标准字段，规范字段名，便于日志系统统一解析
        log_record['timestamp'] = self.formatTime(record, self.datefmt)  # 日志时间戳
        log_record['level'] = record.levelname                           # 日志级别（统一用level字段）
        log_record['logger'] = record.name                               # 日志器名称（统一用logger字段）

        # 移除父类默认生成的冗余字段，避免重复
        # 父类默认会输出 levelname 和 name，我们已经统一重命名为 level 和 logger
        log_record.pop('levelname', None)
        log_record.pop('name', None)


class StartupFormatter(logging.Formatter):
    """Custom formatter for clean startup messages."""
    # 控制台专用日志格式化器
    # 设计目标：启动日志纯净无冗余，普通日志清晰可读，同时自动展示extra附加信息

    def format(self, record):
        """重写日志格式化方法，根据日志类型采用不同输出样式。"""
        # 情况1：标记为startup的启动日志 → 纯文本输出，去掉时间、logger名等前缀，界面更干净
        if hasattr(record, 'startup') and record.startup:
            return record.getMessage()

        # 情况2：普通业务日志 → 先使用基础格式模板生成主体内容
        base = super().format(record)

        # ========== 提取用户通过 extra=... 注入的自定义字段 ==========
        # LogRecord 内置标准属性集合，用于区分「系统字段」和「用户自定义字段」
        standard_attrs = {
            "name", "msg", "args", "levelname", "levelno", "pathname", "filename", "module",
            "exc_info", "exc_text", "stack_info", "lineno", "funcName", "created", "msecs",
            "relativeCreated", "thread", "threadName", "processName", "process",
        }
        # 遍历日志记录的所有属性，筛选出非标准的自定义字段（即用户通过extra传入的上下文）
        extras = {
            k: v
            for k, v in record.__dict__.items()
            if k not in standard_attrs and k != "startup"
        }

        # 如果没有自定义附加字段，直接返回基础格式化结果
        if not extras:
            return base

        # 有附加字段时，序列化为JSON拼在日志末尾
        # ensure_ascii=False 保证中文正常显示；default=str 处理无法直接序列化的对象
        try:
            extra_json = json.dumps(extras, ensure_ascii=False, default=str)
        except Exception:
            # 序列化失败兜底：直接转字符串，避免日志系统自身报错
            extra_json = str(extras)

        return f"{base} | extra={extra_json}"


def setup_logging() -> None:
    """Set up logging configuration."""
    # 日志初始化入口函数，项目启动时调用一次即可完成全局日志配置

    # 1. 确保日志目录存在，不存在则创建；exist_ok=True 表示已存在时不报错
    os.makedirs("logs", exist_ok=True)

    # ========== 2. 配置控制台输出处理器 ==========
    # 输出到终端/控制台，INFO级别，面向开发人员阅读，使用友好的文本格式
    console_handler = logging.StreamHandler()
    console_handler.setLevel(logging.INFO)
    console_handler.setFormatter(StartupFormatter(
        fmt="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S"
    ))

    # ========== 3. 配置文件输出处理器 ==========
    # 输出到 logs/app.log 文件，DEBUG级别，使用结构化JSON格式，便于日志采集与检索
    file_handler = logging.FileHandler("logs/app.log")
    file_handler.setLevel(logging.DEBUG)
    file_handler.setFormatter(CustomJsonFormatter(
        fmt="%(timestamp)s %(level)s %(logger)s %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S"
    ))

    # ========== 4. 配置根日志器 ==========
    root_logger = logging.getLogger()
    root_logger.setLevel(logging.INFO)   # 全局默认日志级别
    root_logger.addHandler(console_handler)  # 挂载控制台处理器
    root_logger.addHandler(file_handler)     # 挂载文件处理器

    # ========== 5. 第三方库日志降噪 ==========
    # 抬高第三方库的日志级别，避免大量冗余框架日志淹没业务日志
    logging.getLogger("uvicorn.access").setLevel(logging.WARNING)    # Uvicorn访问日志只保留警告以上
    logging.getLogger("sqlalchemy.engine").setLevel(logging.WARNING) # SQLAlchemy不输出默认SQL语句
    logging.getLogger("passlib").setLevel(logging.ERROR)             # 密码库只保留错误


def get_logger(name: str) -> logging.Logger:
    """Get a logger instance."""
    # 统一的日志器获取入口，封装标准logging.getLogger
    # 业务代码中通过 get_logger(__name__) 获取对应模块的日志器
    return logging.getLogger(name)


def startup_log(message: str, level: int = logging.INFO) -> None:
    """Log a startup message with clean formatting."""
    # 专用启动日志输出函数
    # 特点：控制台纯净输出（无时间戳、无logger名、无代码位置），启动界面更整洁美观

    logger = logging.getLogger("startup")
    # 手动构造日志记录，而非直接调用logger.info
    # 目的：清空文件名、行号等定位信息，启动日志不需要代码溯源，只做信息展示
    record = logger.makeRecord(
        logger.name, level, "", 0, message, (), None
    )
    record.startup = True  # 打上启动标记，格式化器据此使用纯净输出样式
    logger.handle(record)