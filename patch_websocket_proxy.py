"""
WebSocket Proxy Patch for NautilusTrader
为 NautilusTrader 的 WebSocket 客户端添加代理支持和可靠的重连机制

特性：
1. 代理支持（可选）
2. 主动心跳检测（WebSocket ping/pong）
3. 连接健康监控
4. 自动重连（指数退避）
5. 断路器保护
"""

import asyncio
import os
import time
from typing import Any, Callable, Optional
from enum import Enum
from datetime import datetime

import aiohttp
from loguru import logger

# 代理配置 - 从环境变量读取，如果没有配置则为 None（直连模式）
PROXY_URL = os.getenv("PROXY_URL", "").strip() or None

# 心跳和重连配置
HEARTBEAT_INTERVAL = int(os.getenv("WS_HEARTBEAT_INTERVAL", "15"))  # 心跳间隔（秒）
HEARTBEAT_TIMEOUT = int(os.getenv("WS_HEARTBEAT_TIMEOUT", "30"))  # 心跳超时（秒）
MAX_RECONNECT_ATTEMPTS = int(os.getenv("WS_MAX_RECONNECT_ATTEMPTS", "10"))  # 最大重连次数
INITIAL_RECONNECT_DELAY = float(os.getenv("WS_INITIAL_RECONNECT_DELAY", "1.0"))  # 初始重连延迟
MAX_RECONNECT_DELAY = float(os.getenv("WS_MAX_RECONNECT_DELAY", "60.0"))  # 最大重连延迟
IDLE_TIMEOUT = int(os.getenv("WS_IDLE_TIMEOUT", "60"))  # 无数据超时（秒）


class ConnectionState(Enum):
    """WebSocket 连接状态"""
    DISCONNECTED = "disconnected"
    CONNECTING = "connecting"
    CONNECTED = "connected"
    RECONNECTING = "reconnecting"
    FAILED = "failed"


class ProxyWebSocketClient:
    """
    支持代理和可靠重连的 WebSocket 客户端包装器

    改进：
    1. 主动心跳 - 定期发送 ping，检测 pong 响应
    2. 健康监控 - 检测长时间无数据
    3. 自动重连 - 指数退避重试
    """

    def __init__(
        self,
        ws_url: str,
        handler: Callable[[bytes], None],
        on_reconnect: Callable[[], None] | None = None,
        proxy_url: str | None = None,
        heartbeat_interval: int = HEARTBEAT_INTERVAL,
        heartbeat_timeout: int = HEARTBEAT_TIMEOUT,
        idle_timeout: int = IDLE_TIMEOUT,
    ):
        self._ws_url = ws_url
        self._handler = handler
        self._on_reconnect = on_reconnect
        self._proxy_url = proxy_url or PROXY_URL
        self._heartbeat_interval = heartbeat_interval
        self._heartbeat_timeout = heartbeat_timeout
        self._idle_timeout = idle_timeout

        # 连接状态
        self._session: aiohttp.ClientSession | None = None
        self._ws: aiohttp.ClientWebSocketResponse | None = None
        self._state = ConnectionState.DISCONNECTED
        self._is_active = False

        # 心跳追踪
        self._last_ping_time: float = 0
        self._last_pong_time: float = 0
        self._last_message_time: float = 0
        self._waiting_for_pong = False

        # 重连追踪
        self._reconnect_attempts = 0
        self._max_reconnect_attempts = MAX_RECONNECT_ATTEMPTS

        # 后台任务
        self._receive_task: asyncio.Task | None = None
        self._heartbeat_task: asyncio.Task | None = None
        self._health_check_task: asyncio.Task | None = None

        # 统计
        self._stats = {
            "total_connections": 0,
            "total_disconnections": 0,
            "total_messages_received": 0,
            "total_pings_sent": 0,
            "total_pongs_received": 0,
            "total_reconnects": 0,
            "last_error": None,
        }

    def is_active(self) -> bool:
        """检查连接是否活跃"""
        return (
            self._is_active
            and self._ws is not None
            and not self._ws.closed
            and self._state == ConnectionState.CONNECTED
        )

    @property
    def state(self) -> ConnectionState:
        return self._state

    async def connect(self) -> None:
        """建立 WebSocket 连接"""
        self._state = ConnectionState.CONNECTING

        if self._proxy_url:
            logger.info(f"[WS] 连接到 {self._ws_url} (代理: {self._proxy_url})")
        else:
            logger.info(f"[WS] 连接到 {self._ws_url} (直连模式)")

        # 创建 session
        self._session = aiohttp.ClientSession()

        try:
            # 连接 WebSocket
            kwargs = {
                "timeout": aiohttp.ClientTimeout(total=30),
                "heartbeat": self._heartbeat_interval,  # aiohttp 内置心跳
            }
            if self._proxy_url:
                kwargs["proxy"] = self._proxy_url

            self._ws = await self._session.ws_connect(self._ws_url, **kwargs)
            self._is_active = True
            self._state = ConnectionState.CONNECTED
            self._reconnect_attempts = 0  # 重置重连计数

            # 初始化心跳追踪
            current_time = time.time()
            self._last_ping_time = current_time
            self._last_pong_time = current_time
            self._last_message_time = current_time
            self._waiting_for_pong = False

            # 更新统计
            self._stats["total_connections"] += 1

            logger.info(
                f"[WS] ✓ 已连接 | 连接次数: {self._stats['total_connections']} | "
                f"心跳间隔: {self._heartbeat_interval}s"
            )

            # 启动后台任务
            self._receive_task = asyncio.create_task(self._receive_loop())
            self._heartbeat_task = asyncio.create_task(self._heartbeat_loop())
            self._health_check_task = asyncio.create_task(self._health_check_loop())

        except Exception as e:
            self._state = ConnectionState.FAILED
            self._stats["last_error"] = str(e)
            logger.error(f"[WS] ✗ 连接失败: {e}")

            if self._session:
                await self._session.close()
                self._session = None
            raise

    async def _receive_loop(self) -> None:
        """接收消息循环"""
        try:
            async for msg in self._ws:
                # 更新最后消息时间
                self._last_message_time = time.time()

                if msg.type == aiohttp.WSMsgType.BINARY:
                    self._handler(msg.data)
                    self._stats["total_messages_received"] += 1

                elif msg.type == aiohttp.WSMsgType.TEXT:
                    self._handler(msg.data.encode())
                    self._stats["total_messages_received"] += 1

                elif msg.type == aiohttp.WSMsgType.PONG:
                    # 收到 pong 响应
                    self._last_pong_time = time.time()
                    self._waiting_for_pong = False
                    self._stats["total_pongs_received"] += 1
                    logger.debug(f"[WS] 收到 PONG 响应")

                elif msg.type == aiohttp.WSMsgType.PING:
                    # 收到 ping，aiohttp 会自动回复 pong
                    logger.debug(f"[WS] 收到 PING")

                elif msg.type == aiohttp.WSMsgType.ERROR:
                    error = self._ws.exception()
                    logger.error(f"[WS] WebSocket 错误: {error}")
                    self._stats["last_error"] = str(error)
                    break

                elif msg.type == aiohttp.WSMsgType.CLOSED:
                    logger.warning("[WS] WebSocket 已关闭 (CLOSED)")
                    break

                elif msg.type == aiohttp.WSMsgType.CLOSING:
                    logger.debug("[WS] WebSocket 正在关闭")
                    break

        except asyncio.CancelledError:
            logger.debug("[WS] 接收任务被取消")
        except Exception as e:
            logger.error(f"[WS] 接收循环错误: {e}")
            self._stats["last_error"] = str(e)
        finally:
            await self._handle_disconnect()

    async def _heartbeat_loop(self) -> None:
        """心跳循环 - 主动发送 ping 检测连接健康"""
        while self._state == ConnectionState.CONNECTED:
            try:
                await asyncio.sleep(self._heartbeat_interval)

                if not self.is_active():
                    continue

                current_time = time.time()

                # 检查是否等待 pong 超时
                if self._waiting_for_pong:
                    time_since_ping = current_time - self._last_ping_time
                    if time_since_ping > self._heartbeat_timeout:
                        logger.warning(
                            f"[WS] ⚠ 心跳超时! {time_since_ping:.1f}s 未收到 PONG 响应"
                        )
                        # 标记连接不健康，触发重连
                        await self._trigger_reconnect("心跳超时")
                        return

                # 发送 ping
                try:
                    await self._ws.ping()
                    self._last_ping_time = current_time
                    self._waiting_for_pong = True
                    self._stats["total_pings_sent"] += 1
                    logger.debug(f"[WS] 发送 PING")
                except Exception as e:
                    logger.warning(f"[WS] 发送 PING 失败: {e}")
                    await self._trigger_reconnect(f"PING 失败: {e}")
                    return

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"[WS] 心跳循环错误: {e}")
                break

    async def _health_check_loop(self) -> None:
        """健康检查循环 - 检测长时间无数据"""
        while self._state == ConnectionState.CONNECTED:
            try:
                await asyncio.sleep(self._idle_timeout / 2)  # 检查频率是超时的一半

                if not self.is_active():
                    continue

                current_time = time.time()
                time_since_message = current_time - self._last_message_time

                # 如果超过 idle_timeout 没收到任何数据，可能是僵尸连接
                if time_since_message > self._idle_timeout:
                    logger.warning(
                        f"[WS] ⚠ 连接空闲超时! {time_since_message:.1f}s 未收到数据"
                    )
                    # 发送 ping 测试连接
                    try:
                        await self._ws.ping()
                        # 等待 pong
                        await asyncio.sleep(5)
                        if current_time - self._last_pong_time > 5:
                            await self._trigger_reconnect("空闲超时且 PING 无响应")
                    except Exception:
                        await self._trigger_reconnect("空闲超时检测失败")

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"[WS] 健康检查错误: {e}")

    async def _handle_disconnect(self) -> None:
        """处理断开连接"""
        self._is_active = False
        self._state = ConnectionState.DISCONNECTED
        self._stats["total_disconnections"] += 1

        logger.warning(
            f"[WS] 连接断开 | 断开次数: {self._stats['total_disconnections']}"
        )

    async def _trigger_reconnect(self, reason: str) -> None:
        """触发重连"""
        logger.warning(f"[WS] 触发重连 | 原因: {reason}")

        # 清理当前连接
        await self._cleanup()

        # 调用重连回调
        if self._on_reconnect:
            try:
                self._on_reconnect()
            except Exception as e:
                logger.error(f"[WS] 重连回调失败: {e}")

    async def _cleanup(self) -> None:
        """清理连接资源"""
        # 取消后台任务
        for task in [self._heartbeat_task, self._health_check_task]:
            if task and not task.done():
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass

        self._heartbeat_task = None
        self._health_check_task = None

        # 关闭 WebSocket
        if self._ws and not self._ws.closed:
            try:
                await self._ws.close()
            except Exception:
                pass
        self._ws = None

        # 关闭 Session
        if self._session and not self._session.closed:
            try:
                await self._session.close()
            except Exception:
                pass
        self._session = None

        self._is_active = False

    async def send_text(self, data: bytes) -> None:
        """发送文本消息"""
        if self._ws and not self._ws.closed:
            await self._ws.send_str(data.decode())
        else:
            raise RuntimeError("WebSocket 未连接")

    async def send_bytes(self, data: bytes) -> None:
        """发送二进制消息"""
        if self._ws and not self._ws.closed:
            await self._ws.send_bytes(data)
        else:
            raise RuntimeError("WebSocket 未连接")

    async def disconnect(self) -> None:
        """主动断开连接"""
        logger.info("[WS] 主动断开连接")
        self._state = ConnectionState.DISCONNECTED
        await self._cleanup()

    def get_stats(self) -> dict:
        """获取连接统计信息"""
        return {
            "state": self._state.value,
            "is_active": self.is_active(),
            "proxy_url": self._proxy_url,
            "reconnect_attempts": self._reconnect_attempts,
            "last_ping_time": self._last_ping_time,
            "last_pong_time": self._last_pong_time,
            "last_message_time": self._last_message_time,
            "waiting_for_pong": self._waiting_for_pong,
            **self._stats,
        }


class WebSocketReconnectManager:
    """
    WebSocket 重连管理器

    管理连接的生命周期，包括：
    - 自动重连（指数退避）
    - 断路器保护
    - 连接状态追踪
    """

    def __init__(
        self,
        ws_url: str,
        handler: Callable[[bytes], None],
        on_reconnect: Callable[[], None] | None = None,
        proxy_url: str | None = None,
    ):
        self._ws_url = ws_url
        self._handler = handler
        self._on_reconnect = on_reconnect
        self._proxy_url = proxy_url or PROXY_URL

        self._client: ProxyWebSocketClient | None = None
        self._reconnect_attempts = 0
        self._is_reconnecting = False
        self._should_reconnect = True

        # 重连配置
        self._max_attempts = MAX_RECONNECT_ATTEMPTS
        self._initial_delay = INITIAL_RECONNECT_DELAY
        self._max_delay = MAX_RECONNECT_DELAY

    async def connect(self) -> None:
        """建立连接（带自动重连）"""
        self._should_reconnect = True

        while self._should_reconnect:
            try:
                self._client = ProxyWebSocketClient(
                    ws_url=self._ws_url,
                    handler=self._handler,
                    on_reconnect=self._handle_reconnect,
                    proxy_url=self._proxy_url,
                )
                await self._client.connect()
                return  # 连接成功

            except Exception as e:
                self._reconnect_attempts += 1

                if self._reconnect_attempts >= self._max_attempts:
                    logger.error(
                        f"[WS] ✗ 达到最大重连次数 ({self._max_attempts})，放弃重连"
                    )
                    raise

                # 计算退避延迟
                delay = min(
                    self._initial_delay * (2 ** (self._reconnect_attempts - 1)),
                    self._max_delay,
                )

                logger.warning(
                    f"[WS] 连接失败，{delay:.1f}s 后重试 "
                    f"({self._reconnect_attempts}/{self._max_attempts}) | 错误: {e}"
                )

                await asyncio.sleep(delay)

    def _handle_reconnect(self) -> None:
        """处理重连请求（从回调中调用）"""
        if self._is_reconnecting:
            return

        self._is_reconnecting = True
        self._reconnect_attempts += 1

        # 在新任务中执行重连
        asyncio.create_task(self._do_reconnect())

    async def _do_reconnect(self) -> None:
        """执行重连"""
        if not self._should_reconnect:
            return

        if self._reconnect_attempts >= self._max_attempts:
            logger.error(f"[WS] ✗ 达到最大重连次数，停止重连")
            return

        # 计算延迟
        delay = min(
            self._initial_delay * (2 ** (self._reconnect_attempts - 1)),
            self._max_delay,
        )

        logger.info(
            f"[WS] 准备重连 | 延迟: {delay:.1f}s | "
            f"尝试: {self._reconnect_attempts}/{self._max_attempts}"
        )

        await asyncio.sleep(delay)

        try:
            # 清理旧连接
            if self._client:
                try:
                    await self._client._cleanup()
                except Exception:
                    pass

            # 建立新连接
            self._client = ProxyWebSocketClient(
                ws_url=self._ws_url,
                handler=self._handler,
                on_reconnect=self._handle_reconnect,
                proxy_url=self._proxy_url,
            )
            await self._client.connect()

            # 重连成功，重置计数
            self._reconnect_attempts = 0
            logger.info("[WS] ✓ 重连成功")

            # 调用外部回调
            if self._on_reconnect:
                try:
                    self._on_reconnect()
                except Exception as e:
                    logger.error(f"[WS] 重连回调失败: {e}")

        except Exception as e:
            logger.error(f"[WS] 重连失败: {e}")
            # 继续尝试
            self._handle_reconnect()

        finally:
            self._is_reconnecting = False

    async def disconnect(self) -> None:
        """断开连接"""
        self._should_reconnect = False
        if self._client:
            await self._client.disconnect()

    def is_active(self) -> bool:
        """检查连接是否活跃"""
        return self._client is not None and self._client.is_active()

    def get_stats(self) -> dict:
        """获取统计信息"""
        stats = {
            "reconnect_attempts": self._reconnect_attempts,
            "is_reconnecting": self._is_reconnecting,
        }
        if self._client:
            stats.update(self._client.get_stats())
        return stats


def apply_websocket_proxy_patch():
    """
    应用 WebSocket 代理补丁到 NautilusTrader

    如果未配置代理 (PROXY_URL 为空)，则跳过代理设置，但仍然应用
    改进的重连和心跳机制。
    """
    try:
        from nautilus_trader.adapters.polymarket.websocket import client as ws_client

        # 保存原始 connect 方法
        original_connect = ws_client.PolymarketWebSocketClient.connect

        async def patched_connect(self) -> None:
            """使用增强客户端的连接方法"""
            self._log.debug(f"Connecting to {self._ws_url}")
            self._is_connecting = True

            try:
                # 创建增强版 WebSocket 客户端
                enhanced_client = ProxyWebSocketClient(
                    ws_url=self._ws_url,
                    handler=self._handler,
                    on_reconnect=self.reconnect,
                    proxy_url=PROXY_URL,
                )

                await enhanced_client.connect()

                # 替换内部的 _client
                self._client = enhanced_client
                self._is_connecting = False

                proxy_info = f" (代理: {PROXY_URL})" if PROXY_URL else " (直连)"
                self._log.info(f"Connected to {self._ws_url}{proxy_info}")

                await self._subscribe_all()

            except Exception as e:
                self._is_connecting = False
                self._log.error(f"Failed to connect: {e}")
                raise

        # 应用补丁
        ws_client.PolymarketWebSocketClient.connect = patched_connect

        if PROXY_URL:
            logger.info(f"✓ WebSocket 补丁已应用 (代理: {PROXY_URL})")
        else:
            logger.info("✓ WebSocket 补丁已应用 (直连模式)")

        logger.info(
            f"  心跳间隔: {HEARTBEAT_INTERVAL}s | "
            f"心跳超时: {HEARTBEAT_TIMEOUT}s | "
            f"最大重连: {MAX_RECONNECT_ATTEMPTS}次"
        )
        return True

    except Exception as e:
        logger.error(f"应用 WebSocket 补丁失败: {e}")
        return False


def verify_websocket_connection():
    """验证 WebSocket 连接是否正常工作"""
    import asyncio

    async def test():
        ws_url = "wss://ws-subscriptions-clob.polymarket.com/ws/market"
        logger.info(f"测试 WebSocket 连接: {ws_url}")

        client = ProxyWebSocketClient(
            ws_url=ws_url,
            handler=lambda x: logger.debug(f"收到消息: {len(x)} bytes"),
            proxy_url=PROXY_URL,
        )

        try:
            await client.connect()
            logger.info("✓ WebSocket 连接成功!")

            # 等待看看心跳是否正常
            await asyncio.sleep(HEARTBEAT_INTERVAL + 5)

            stats = client.get_stats()
            logger.info(f"连接统计: {stats}")

            await client.disconnect()
            return True
        except Exception as e:
            logger.error(f"✗ WebSocket 连接失败: {e}")
            return False

    return asyncio.run(test())


if __name__ == "__main__":
    print("=" * 60)
    print("WebSocket 连接测试")
    print("=" * 60)
    if PROXY_URL:
        print(f"代理 URL: {PROXY_URL}")
    else:
        print("模式: 直连 (无代理)")
    print(f"心跳间隔: {HEARTBEAT_INTERVAL}s")
    print(f"心跳超时: {HEARTBEAT_TIMEOUT}s")
    print(f"最大重连: {MAX_RECONNECT_ATTEMPTS}次")
    print("=" * 60)
    print()

    if verify_websocket_connection():
        print("\n✓ WebSocket 测试通过!")
    else:
        print("\n✗ WebSocket 测试失败!")
        if PROXY_URL:
            print("\n请检查:")
            print("1. 代理软件是否正常运行")
            print(f"2. 代理端口是否正确 (当前: {PROXY_URL})")
            print("3. 代理是否支持 WebSocket 协议")
        else:
            print("\n请检查网络连接是否正常")