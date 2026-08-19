"""
Event emitter for streaming coordination workflow events.
流式协同工作流事件发射器，底层核心事件调度模块
职责：实现基础事件订阅/发布；支持异步流式队列；全局注册表管理每个请求的发射器实例
"""

import asyncio
import json
from datetime import datetime
from typing import Any, Callable, Dict, List, Optional
from uuid import uuid4

from app.core.logging import get_logger
# 流式模型：事件实体、事件类型枚举、事件级别、事件数据基类
from app.models.streaming import StreamingEvent, EventType, EventSeverity, BaseEventData

# 获取模块级logger
logger = get_logger(__name__)


class EventEmitter:
    """Base event emitter for coordination workflow events.
    基础事件发射器，实现经典的发布‑订阅模式（Observer）
    能力：注册/注销监听器、emit触发事件、事件内存缓冲区保存全部历史事件
    不包含异步流式能力，作为父类被StreamingEventEmitter继承
    """
    
    def __init__(self, request_id: str, correlation_id: str):
        """
        :param request_id: 外部请求全局ID，一次HTTP/WebSocket请求唯一标识
        :param correlation_id: 链路追踪ID，可跨多个request追踪一条业务链路
        """
        self.request_id = request_id
        self.correlation_id = correlation_id
        # 事件监听器字典 key:事件类型，value:回调函数列表
        self.listeners: Dict[EventType, List[Callable]] = {}
        # 事件缓冲区：保存该发射器发出的全部事件，用于回溯/调试
        self._event_buffer: List[StreamingEvent] = []
        # 绑定日志上下文，每条日志自动带上request_id/correlation_id，方便链路排查
        self.logger = logger.bind(
            request_id=request_id,
            correlation_id=correlation_id
        )
    
    def on(self, event_type: EventType, callback: Callable[[StreamingEvent], None]) -> None:
        """Register an event listener.
        注册事件监听器：当指定类型事件emit时，会调用callback
        :param event_type: 需要监听的事件类型
        :param callback: 回调函数，入参为StreamingEvent实例，无返回值
        """
        if event_type not in self.listeners:
            self.listeners[event_type] = []
        self.listeners[event_type].append(callback)
    
    def off(self, event_type: EventType, callback: Callable[[StreamingEvent], None]) -> None:
        """Remove an event listener.
        移除指定事件的监听器；回调不存在则静默忽略，不抛异常
        """
        if event_type in self.listeners:
            try:
                self.listeners[event_type].remove(callback)
            except ValueError:
                pass
    
    def emit(self, event_type: EventType, data: BaseEventData, 
             severity: EventSeverity = EventSeverity.INFO, 
             metadata: Optional[Dict[str, Any]] = None) -> StreamingEvent:
        """Emit an event to all listeners.
        发布事件：构建StreamingEvent对象，存入缓冲区，分发到所有注册的监听器
        :param event_type: 事件类型枚举
        :param data: 业务载荷，继承BaseEventData的Pydantic模型
        :param severity: 事件严重等级 INFO / SUCCESS / ERROR
        :param metadata: 链路追踪元数据字典
        :return: 构造完成的事件对象
        """
        event = StreamingEvent(
            event_type=event_type,
            timestamp=datetime.utcnow(),    # UTC时间戳
            correlation_id=self.correlation_id,
            request_id=self.request_id,
            severity=severity,
            data=data,
            metadata=metadata or {}
        )
        
        # 1.加入内存事件缓冲区，留存全部事件
        self._event_buffer.append(event)
        
        # 2.通知所有该事件类型的监听器
        if event_type in self.listeners:
            for callback in self.listeners[event_type]:
                try:
                    callback(event)
                except Exception as e:
                    # 单个监听器异常不能搞崩整个事件分发流程，仅打错误日志
                    self.logger.error(
                        "Error in event listener",
                        event_type=event_type,
                        error=str(e)
                    )
        
        return event
    
    def get_events(self) -> List[StreamingEvent]:
        """Get all events from the buffer. 获取缓冲区全部事件，返回副本防止外部篡改内部列表"""
        return self._event_buffer.copy()
    
    def clear_events(self) -> None:
        """Clear the event buffer. 清空事件缓冲区"""
        self._event_buffer.clear()


class StreamingEventEmitter(EventEmitter):
    """Event emitter with streaming capabilities.
    带异步流式能力的事件发射器，继承基础EventEmitter
    在发布订阅之上增加：asyncio队列、多流输出、SSE/WebSocket流对接；
    上层 WorkflowEventEmitter 持有该类实例做业务事件封装。
    """
    
    def __init__(self, request_id: str, correlation_id: str):
        super().__init__(request_id, correlation_id)
        self._streaming_enabled = False          # 流式开关
        self._stream_queue: Optional[asyncio.Queue] = None # 异步事件队列，供消费端await取事件
        self._active_streams: List[Any] = []     # 活跃流对象列表（ws连接、sse生成器等）
    
    def enable_streaming(self) -> None:
        """Enable streaming mode. 开启流式模式，初始化asyncio队列"""
        self._streaming_enabled = True
        self._stream_queue = asyncio.Queue()
    
    def disable_streaming(self) -> None:
        """Disable streaming mode. 关闭流式，置空队列"""
        self._streaming_enabled = False
        self._stream_queue = None
    
    def is_streaming_enabled(self) -> bool:
        """Check if streaming is enabled. 查询流式是否开启"""
        return self._streaming_enabled
    
    def add_stream(self, stream: Any) -> None:
        """Add a stream to receive events.
        注册一个流接收事件；流对象可以是websocket、自定义异步队列等，
        需要实现 send_event(event) 或者 put_nowait(event)
        """
        if stream not in self._active_streams:
            self._active_streams.append(stream)
    
    def remove_stream(self, stream: Any) -> None:
        """Remove a stream from receiving events. 移除流，不再接收事件推送"""
        if stream in self._active_streams:
            self._active_streams.remove(stream)
    
    def emit(self, event_type: EventType, data: BaseEventData, 
             severity: EventSeverity = EventSeverity.INFO, 
             metadata: Optional[Dict[str, Any]] = None) -> StreamingEvent:
        """Emit an event and send to streams if enabled.
        重写父类emit：先执行父类发布订阅逻辑；如果流式开启，把事件推送到各个stream
        """
        event = super().emit(event_type, data, severity, metadata)
        
        # 如果流式模式打开，分发事件到流
        if self._streaming_enabled:
            self._send_to_streams(event)
        
        return event
    
    def _send_to_streams(self, event: StreamingEvent) -> None:
        """Send event to all active streams.
        私有方法：把事件推送到内部队列 + 所有注册的active stream
        遍历的时候做列表拷贝，防止迭代过程中列表被修改抛出异常
        """
        if self._stream_queue:
            try:
                self._stream_queue.put_nowait(event)
            except asyncio.QueueFull:
                self.logger.warning("Stream queue is full, dropping event")
        
        # 遍历副本，避免迭代时元素被删除导致异常
        for stream in self._active_streams[:]:
            try:
                # 兼容两种流对象协议
                if hasattr(stream, 'send_event'):
                    stream.send_event(event)
                elif hasattr(stream, 'put_nowait'):
                    stream.put_nowait(event)
            except Exception as e:
                self.logger.error(
                    "Failed to send event to stream",
                    error=str(e)
                )
                # 发送失败直接移除该坏掉的流
                self._active_streams.remove(stream)
    
    async def get_next_event(self, timeout: Optional[float] = None) -> Optional[StreamingEvent]:
        """Get the next event from the stream queue.
        消费端异步从队列取下一条事件；支持超时；超时/队列未初始化返回None
        :param timeout: 等待超时秒数，None代表无限等待
        """
        if not self._stream_queue:
            return None
        
        try:
            if timeout:
                return await asyncio.wait_for(self._stream_queue.get(), timeout=timeout)
            else:
                return await self._stream_queue.get()
        except asyncio.TimeoutError:
            return None
    
    def get_stream_stats(self) -> Dict[str, Any]:
        """Get streaming statistics. 获取流式运行状态指标，用于监控/调试"""
        return {
            "streaming_enabled": self._streaming_enabled,
            "active_streams": len(self._active_streams),
            "queue_size": self._stream_queue.qsize() if self._stream_queue else 0,
            "total_events": len(self._event_buffer)
        }


# ---------------- 全局发射器注册表 ----------------
# key: f"{request_id}:{correlation_id}"，value: StreamingEventEmitter实例
_event_emitters: Dict[str, StreamingEventEmitter] = {}


def get_event_emitter(request_id: str, correlation_id: str) -> StreamingEventEmitter:
    """Get or create an event emitter for a request.
    工厂函数：获取或新建对应请求链路的发射器；全局单例复用，避免重复创建
    """
    key = f"{request_id}:{correlation_id}"
    
    if key not in _event_emitters:
        _event_emitters[key] = StreamingEventEmitter(request_id, correlation_id)
    
    return _event_emitters[key]


def cleanup_event_emitter(request_id: str, correlation_id: str) -> None:
    """Clean up an event emitter.
    请求链路结束后必须调用清理：关闭流式、清空缓冲区、从全局注册表删除，防止内存泄漏
    """
    key = f"{request_id}:{correlation_id}"
    
    if key in _event_emitters:
        emitter = _event_emitters[key]
        emitter.disable_streaming()
        emitter.clear_events()
        del _event_emitters[key]


def get_active_emitters() -> Dict[str, StreamingEventEmitter]:
    """Get all active event emitters. 获取全部活跃发射器副本，用于监控排查"""
    return _event_emitters.copy()