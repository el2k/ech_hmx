"""Lightweight logging helpers for supervisor runtime."""

from __future__ import annotations

import json
import logging
from typing import Any, Dict, Optional
# StructuredFormatter 是一个自定义的日志格式化器类，用于在日志记录中显示结构化的字段。
# 它继承自 Python 的内置 logging.Formatter 类，并重写了 format 方法，以便在日志消息中包含额外的上下文信息。
class StructuredFormatter(logging.Formatter):
    """Custom formatter that displays structured logging fields."""

    def format(self, record: logging.LogRecord) -> str:
        """Format log record with structured fields."""
        # Start with the basic formatted message
        base_message = super().format(record)

        # Check if there are extra fields to display
        # 检查日志记录对象是否具有额外的字段（extra_fields）属性，并且该属性不为空。如果存在额外字段，则将其格式化为键值对的形式，并附加到基本消息中，以便在日志输出中显示更多的上下文信息。
        if hasattr(record, "extra_fields") and record.extra_fields:
            # Format extra fields as key=value pairs
            extra_parts = []
            for key, value in record.extra_fields.items():
                # Handle different value types
                if isinstance(value, (dict, list)):
                    value_str = json.dumps(value)
                elif value is None:
                    value_str = "None"
                else:
                    value_str = str(value)
                extra_parts.append(f"{key}={value_str}")

            # Append extra fields to the message
            # 添加额外字段到日志消息中，如果存在额外字段，则将其格式化为键值对的形式，并附加到基本消息中，以便在日志输出中显示更多的上下文信息。
            if extra_parts:
                return f"{base_message} {' '.join(extra_parts)}"

        return base_message

class BoundLogger:
    """Minimal structured logger with ``bind`` support."""
    # 最小化的结构化日志记录器，支持绑定上下文信息。它封装了一个标准的 Python 日志记录器，并允许在日志消息中附加额外的上下文字段，以便在日志输出中提供更多的上下文信息。
    def __init__(self, logger: logging.Logger, context: Optional[Dict[str, Any]] = None) -> None:
        self._logger = logger
        self._context: Dict[str, Any] = context or {}

    # ------------------------------------------------------------------
    # Public API
    def bind(self, **kwargs: Any) -> "BoundLogger":
        """Return a new logger with extended context."""
        # 绑定额外的上下文信息，返回一个新的 BoundLogger 实例。如果提供了额外的关键字参数，则将其与现有的上下文合并，并创建一个新的 BoundLogger 实例，以便在日志消息中包含更多的上下文信息。
        if not kwargs:
            return self
        merged = {**self._context, **kwargs}
        return BoundLogger(self._logger, merged)

    def debug(self, msg: str, **kwargs: Any) -> None:
        self._log(logging.DEBUG, msg, kwargs)

    def info(self, msg: str, **kwargs: Any) -> None:
        self._log(logging.INFO, msg, kwargs)

    def warning(self, msg: str, **kwargs: Any) -> None:
        self._log(logging.WARNING, msg, kwargs)

    def error(self, msg: str, **kwargs: Any) -> None:
        self._log(logging.ERROR, msg, kwargs)

    def exception(self, msg: str, **kwargs: Any) -> None:
        self._log(logging.ERROR, msg, kwargs, exc_info=True)

    # ------------------------------------------------------------------
    # Helpers
    # _log 方法是 BoundLogger 类的一个私有方法，用于处理实际的日志记录操作。它接受日志级别、消息、关键字参数和可选的异常信息，并将这些信息传递给底层的标准日志记录器，以便生成结构化的日志输出。
    def _log(
        self,
        level: int,
        msg: str,
        kwargs: Dict[str, Any],
        *,
        exc_info: bool = False,
    ) -> None:
        extra_fields: Dict[str, Any] = {**self._context}
        if kwargs:
            extra_fields.update(kwargs)

        if extra_fields:
            self._logger.log(level, msg, extra={"extra_fields": extra_fields}, exc_info=exc_info)
        else:
            self._logger.log(level, msg, exc_info=exc_info)

def setup_logging() -> None:
    """Ensure a basic logging configuration is present."""
    # 确保存在基本的日志配置，如果根日志记录器没有处理程序，则创建一个新的处理程序，并使用自定义的 StructuredFormatter 进行格式化，以便在日志输出中显示结构化的字段。
    if not logging.getLogger().handlers:
        # Create handler with structured formatter
        # 创建一个日志处理器，并使用自定义的 StructuredFormatter 进行格式化，以便在日志输出中显示结构化的字段。
        handler = logging.StreamHandler()
        formatter = StructuredFormatter(
            fmt="%(asctime)s [%(levelname)s] %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S"
        )
        handler.setFormatter(formatter)

        # Configure root logger
        # 配置根日志记录器，将处理器添加到根日志记录器，并设置日志级别为 INFO，以便在日志输出中显示信息级别及以上的日志消息。
        root_logger = logging.getLogger()
        root_logger.addHandler(handler)
        root_logger.setLevel(logging.INFO)


def get_logger(name: Optional[str] = None) -> BoundLogger:
    """Return a :class:`BoundLogger` instance."""
    setup_logging()
    return BoundLogger(logging.getLogger(name))
