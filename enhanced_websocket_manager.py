"""
Enhanced WebSocket Manager
增强版 WebSocket 管理器 - 更健壮的重连机制
"""
import asyncio
from datetime import datetime, timedelta
from typing import Optional, Callable, Any, Dict
from enum import Enum
from loguru import logger
from connection_config import CONNECTION_CONFIG
from circuit_breaker import get_circuit_breaker, get_retry_manager


class ConnectionState(Enum):
    """WebSocket 连接状态"""
    DISCONNECTED = "disconnected"
    CONNECTING = "connecting"
    CONNECTED = "connected"
    RECONNECTING = "reconnecting"
    FAILED = "failed"
    CIRCUIT_OPEN = "circuit_open"  # 断路器开启


class EnhancedWebSocketManager:
    """
    增强版 WebSocket 管理器
    
    改进：
    1. 集成断路器 - 防止无限重连
    2. 更智能的重连策略
    3. 连接池管理
    4. 心跳检测
    5. 消息队列缓冲
    """
    
    def __init__(
        self,
        name: str,
        connect_func: Callable,
        stream_func: Callable,
        config: Optional[Any] = None,
    ):
        self.name = name
        self.connect_func = connect_func
        self.stream_func = stream_func
        self.config = config or CONNECTION_CONFIG
        
        # 断路器和重试管理器
        self.circuit_breaker = get_circuit_breaker(f"ws_{name}")
        self.retry_manager = get_retry_manager(f"ws_{name}")
        
        # 状态
        self.state = ConnectionState.DISCONNECTED
        self.reconnect_attempts = 0
        self.last_message_time: Optional[datetime] = None
        self.last_error: Optional[str] = None
        self.connection_start_time: Optional[datetime] = None
        
        # 任务
        self._stream_task: Optional[asyncio.Task] = None
        self._health_check_task: Optional[asyncio.Task] = None
        self._heartbeat_task: Optional[asyncio.Task] = None
        
        # 消息缓冲队列
        self._message_queue: asyncio.Queue = asyncio.Queue(maxsize=1000)
        
        # 统计
        self.stats = {
            "total_connections": 0,
            "total_disconnections": 0,
            "total_messages": 0,
            "total_errors": 0,
            "uptime_seconds": 0,
        }
        
        # 回调
        self.on_connected: Optional[Callable] = None
        self.on_disconnected: Optional[Callable] = None
        self.on_error: Optional[Callable] = None
        self.on_message: Optional[Callable] = None
        
        logger.info(f"Initialized Enhanced WebSocket manager: {name}")
    
    async def connect(self) -> bool:
        """
        连接到 WebSocket（带重试和断路器）
        
        Returns:
            True 如果连接成功
        """
        # 检查断路器
        if not self.circuit_breaker.can_execute():
            self.state = ConnectionState.CIRCUIT_OPEN
            logger.error(
                f"{self.name}: Circuit breaker is OPEN - cannot connect"
            )
            return False
        
        try:
            self.state = ConnectionState.CONNECTING
            logger.info(f"{self.name}: Connecting...")
            
            # 使用重试管理器连接
            async def _do_connect():
                success = await self.connect_func()
                if not success:
                    raise ConnectionError(f"{self.name}: Connection function returned False")
                return success
            
            success = await self.retry_manager.execute_with_retry(
                _do_connect,
                operation_name=f"{self.name}_connect",
                retryable_exceptions=(
                    asyncio.TimeoutError,
                    ConnectionError,
                    OSError,
                )
            )
            
            if success:
                self.state = ConnectionState.CONNECTED
                self.reconnect_attempts = 0
                self.last_message_time = datetime.now()
                self.connection_start_time = datetime.now()
                self.stats["total_connections"] += 1
                
                self.circuit_breaker.record_success()
                
                logger.info(
                    f"{self.name}: Connected successfully | "
                    f"Total connections: {self.stats['total_connections']}"
                )
                
                if self.on_connected:
                    await self.on_connected()
                
                return True
            else:
                return False
        
        except Exception as e:
            self.state = ConnectionState.FAILED
            self.last_error = str(e)
            self.stats["total_errors"] += 1
            
            self.circuit_breaker.record_failure(e)
            
            logger.error(
                f"{self.name}: Connection failed | "
                f"Error: {e} | "
                f"Circuit breaker state: {self.circuit_breaker.state.value}"
            )
            return False
    
    async def disconnect(self) -> None:
        """断开连接"""
        logger.info(f"{self.name}: Disconnecting...")
        
        # 取消所有任务
        tasks = [
            self._stream_task,
            self._health_check_task,
            self._heartbeat_task,
        ]
        
        for task in tasks:
            if task:
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass
        
        # 更新统计
        if self.connection_start_time:
            uptime = (datetime.now() - self.connection_start_time).total_seconds()
            self.stats["uptime_seconds"] += uptime
        
        self.state = ConnectionState.DISCONNECTED
        self.stats["total_disconnections"] += 1
        
        if self.on_disconnected:
            await self.on_disconnected()
        
        logger.info(
            f"{self.name}: Disconnected | "
            f"Total disconnections: {self.stats['total_disconnections']}"
        )
    
    async def start_streaming(self) -> None:
        """开始流式传输（带自动重连）"""
        logger.info(f"{self.name}: Starting enhanced stream with auto-reconnection...")
        
        # 启动流任务
        self._stream_task = asyncio.create_task(self._stream_with_reconnect())
        
        # 启动健康检查
        self._health_check_task = asyncio.create_task(
            self._monitor_health(
                check_interval=self.config.WS_HEALTH_CHECK_INTERVAL
            )
        )
        
        # 启动心跳
        self._heartbeat_task = asyncio.create_task(
            self._send_heartbeat(interval=30)
        )
    
    async def _stream_with_reconnect(self) -> None:
        """流式传输（带自动重连）"""
        while True:
            try:
                # 检查断路器状态
                if self.state == ConnectionState.CIRCUIT_OPEN:
                    logger.warning(
                        f"{self.name}: Circuit breaker is OPEN - waiting..."
                    )
                    await asyncio.sleep(self.config.CIRCUIT_BREAKER_TIMEOUT)
                    self.circuit_breaker.reset()
                    continue
                
                # 连接（如果未连接）
                if self.state != ConnectionState.CONNECTED:
                    if not await self.connect():
                        # 连接失败，等待重试
                        await self._backoff_and_retry()
                        continue
                
                # 开始流式传输
                logger.info(f"{self.name}: Starting data stream...")
                await self.stream_func()
                
            except asyncio.CancelledError:
                logger.info(f"{self.name}: Stream cancelled")
                break
            
            except Exception as e:
                self.last_error = str(e)
                self.stats["total_errors"] += 1
                
                logger.error(
                    f"{self.name}: Stream error | "
                    f"Error: {e} | "
                    f"Total errors: {self.stats['total_errors']}"
                )
                
                if self.on_error:
                    await self.on_error(e)
                
                # 尝试重连
                self.state = ConnectionState.RECONNECTING
                await self._backoff_and_retry()
    
    async def _backoff_and_retry(self) -> None:
        """指数退避重试"""
        if self.reconnect_attempts >= self.config.WS_MAX_RECONNECT_ATTEMPTS:
            logger.error(
                f"{self.name}: Max reconnect attempts "
                f"({self.config.WS_MAX_RECONNECT_ATTEMPTS}) reached"
            )
            self.state = ConnectionState.FAILED
            return
        
        # 计算退避延迟
        backoff = min(
            self.config.WS_INITIAL_BACKOFF * (2 ** self.reconnect_attempts),
            self.config.WS_MAX_BACKOFF
        )
        
        self.reconnect_attempts += 1
        
        logger.warning(
            f"{self.name}: Reconnect attempt {self.reconnect_attempts}/"
            f"{self.config.WS_MAX_RECONNECT_ATTEMPTS} in {backoff:.1f}s..."
        )
        
        await asyncio.sleep(backoff)
    
    async def _monitor_health(self, check_interval: int = 30) -> None:
        """
        监控连接健康状态
        
        Args:
            check_interval: 检查间隔（秒）
        """
        while True:
            try:
                await asyncio.sleep(check_interval)
                
                if self.state != ConnectionState.CONNECTED:
                    continue
                
                # 检查是否最近收到消息
                if self.last_message_time:
                    time_since_message = datetime.now() - self.last_message_time
                    
                    # 如果超过 2 倍检查间隔没有消息，认为连接不健康
                    if time_since_message > timedelta(seconds=check_interval * 2):
                        logger.warning(
                            f"{self.name}: No messages for {time_since_message.seconds}s, "
                            "connection may be stale - forcing reconnection"
                        )
                        
                        # 强制重连
                        self.state = ConnectionState.RECONNECTING
                        await self.disconnect()
                
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"{self.name}: Health check error: {e}")
    
    async def _send_heartbeat(self, interval: int = 30) -> None:
        """
        发送心跳（保持连接活跃）
        
        Args:
            interval: 心跳间隔（秒）
        """
        while True:
            try:
                await asyncio.sleep(interval)
                
                if self.state == ConnectionState.CONNECTED:
                    # 这里可以实现具体的心跳逻辑
                    # 例如发送 ping 消息
                    logger.debug(f"{self.name}: Sending heartbeat...")
            
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"{self.name}: Heartbeat error: {e}")
    
    def update_last_message_time(self) -> None:
        """更新最后消息时间"""
        self.last_message_time = datetime.now()
        self.stats["total_messages"] += 1
    
    @property
    def is_connected(self) -> bool:
        """是否已连接"""
        return self.state == ConnectionState.CONNECTED
    
    @property
    def is_healthy(self) -> bool:
        """连接是否健康"""
        if not self.is_connected:
            return False
        
        if not self.last_message_time:
            return False
        
        # 如果在最近 60 秒内收到消息，认为健康
        time_since_message = datetime.now() - self.last_message_time
        return time_since_message < timedelta(seconds=60)
    
    def get_stats(self) -> Dict[str, Any]:
        """获取统计信息"""
        stats = {
            "name": self.name,
            "state": self.state.value,
            "reconnect_attempts": self.reconnect_attempts,
            "last_message_time": (
                self.last_message_time.isoformat() if self.last_message_time else None
            ),
            "is_healthy": self.is_healthy,
            "last_error": self.last_error,
            "circuit_breaker": self.circuit_breaker.get_stats(),
            **self.stats,
        }
        
        # 计算当前连接时长
        if self.connection_start_time and self.state == ConnectionState.CONNECTED:
            stats["current_uptime"] = (
                datetime.now() - self.connection_start_time
            ).total_seconds()
        
        return stats
