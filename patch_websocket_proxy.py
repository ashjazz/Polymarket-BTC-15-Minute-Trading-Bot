"""
WebSocket Proxy Patch for NautilusTrader
为 NautilusTrader 的 WebSocket 客户端添加代理支持

这个补丁通过替换 PolymarketWebSocketClient.connect 方法来使用支持代理的 aiohttp。
"""

import asyncio
import os
from typing import Any, Callable

import aiohttp
from loguru import logger

# 代理配置
PROXY_URL = os.getenv("PROXY_URL", "http://localhost:8001")


class ProxyWebSocketClient:
    """
    支持代理的 WebSocket 客户端包装器
    """

    def __init__(
        self,
        ws_url: str,
        handler: Callable[[bytes], None],
        on_reconnect: Callable[[], None] | None = None,
        proxy_url: str | None = None,
        heartbeat: int = 10,
    ):
        self._ws_url = ws_url
        self._handler = handler
        self._on_reconnect = on_reconnect
        self._proxy_url = proxy_url or PROXY_URL
        self._heartbeat = heartbeat

        self._session: aiohttp.ClientSession | None = None
        self._ws: aiohttp.ClientWebSocketResponse | None = None
        self._is_active = False
        self._receive_task: asyncio.Task | None = None
        self._heartbeat_task: asyncio.Task | None = None

    def is_active(self) -> bool:
        return self._is_active and self._ws is not None and not self._ws.closed

    async def connect(self) -> None:
        """建立 WebSocket 连接"""
        logger.info(f"[ProxyWS] 连接到 {self._ws_url} (代理: {self._proxy_url})")

        # 创建 session
        if self._proxy_url:
            connector = aiohttp.TCPConnector()
            self._session = aiohttp.ClientSession(connector=connector)
        else:
            self._session = aiohttp.ClientSession()

        try:
            # 连接 WebSocket
            kwargs = {"timeout": aiohttp.ClientTimeout(total=30)}
            if self._proxy_url:
                kwargs["proxy"] = self._proxy_url

            self._ws = await self._session.ws_connect(self._ws_url, **kwargs)
            self._is_active = True

            logger.info(f"[ProxyWS] 已连接到 {self._ws_url}")

            # 启动接收任务
            self._receive_task = asyncio.create_task(self._receive_loop())

        except Exception as e:
            logger.error(f"[ProxyWS] 连接失败: {e}")
            self._is_active = False
            if self._session:
                await self._session.close()
                self._session = None
            raise

    async def _receive_loop(self) -> None:
        """接收消息循环"""
        try:
            async for msg in self._ws:
                if msg.type == aiohttp.WSMsgType.BINARY:
                    self._handler(msg.data)
                elif msg.type == aiohttp.WSMsgType.TEXT:
                    self._handler(msg.data.encode())
                elif msg.type == aiohttp.WSMsgType.ERROR:
                    logger.error(f"[ProxyWS] WebSocket 错误: {self._ws.exception()}")
                    break
                elif msg.type == aiohttp.WSMsgType.CLOSED:
                    logger.warning("[ProxyWS] WebSocket 已关闭")
                    break
        except asyncio.CancelledError:
            logger.debug("[ProxyWS] 接收任务被取消")
        except Exception as e:
            logger.error(f"[ProxyWS] 接收循环错误: {e}")
        finally:
            self._is_active = False
            # 触发重连
            if self._on_reconnect:
                try:
                    self._on_reconnect()
                except Exception as e:
                    logger.error(f"[ProxyWS] 重连回调失败: {e}")

    async def send_text(self, data: bytes) -> None:
        """发送文本消息"""
        if self._ws and not self._ws.closed:
            await self._ws.send_str(data.decode())
        else:
            raise RuntimeError("WebSocket 未连接")

    async def disconnect(self) -> None:
        """断开连接"""
        self._is_active = False

        if self._receive_task:
            self._receive_task.cancel()
            try:
                await self._receive_task
            except asyncio.CancelledError:
                pass
            self._receive_task = None

        if self._ws and not self._ws.closed:
            await self._ws.close()
            self._ws = None

        if self._session:
            await self._session.close()
            self._session = None

        logger.info("[ProxyWS] 已断开连接")


def apply_websocket_proxy_patch():
    """
    应用 WebSocket 代理补丁到 NautilusTrader
    """
    try:
        from nautilus_trader.adapters.polymarket.websocket import client as ws_client

        # 保存原始 connect 方法
        original_connect = ws_client.PolymarketWebSocketClient.connect

        async def patched_connect(self) -> None:
            """使用代理的连接方法"""
            self._log.debug(f"Connecting to {self._ws_url} (via proxy: {PROXY_URL})")
            self._is_connecting = True

            try:
                # 创建支持代理的 WebSocket 客户端
                proxy_client = ProxyWebSocketClient(
                    ws_url=self._ws_url,
                    handler=self._handler,
                    on_reconnect=self.reconnect,
                    proxy_url=PROXY_URL,
                )

                await proxy_client.connect()

                # 替换内部的 _client
                self._client = proxy_client
                self._is_connecting = False
                self._log.info(f"Connected to {self._ws_url} (via proxy)")

                await self._subscribe_all()

            except Exception as e:
                self._is_connecting = False
                self._log.error(f"Failed to connect via proxy: {e}")
                raise

        # 应用补丁
        ws_client.PolymarketWebSocketClient.connect = patched_connect
        logger.info(f"✓ WebSocket 代理补丁已应用 (代理: {PROXY_URL})")
        return True

    except Exception as e:
        logger.error(f"应用 WebSocket 代理补丁失败: {e}")
        return False


def verify_websocket_connection():
    """验证 WebSocket 连接是否可以通过代理工作"""
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

            # 等待一下看看是否有错误
            await asyncio.sleep(3)

            await client.disconnect()
            return True
        except Exception as e:
            logger.error(f"✗ WebSocket 连接失败: {e}")
            return False

    return asyncio.run(test())


if __name__ == "__main__":
    print(f"测试 WebSocket 代理连接...")
    print(f"代理 URL: {PROXY_URL}")
    print()

    if verify_websocket_connection():
        print("\n✓ WebSocket 代理连接测试通过!")
    else:
        print("\n✗ WebSocket 代理连接测试失败!")
        print("\n请检查:")
        print("1. 代理软件是否正常运行")
        print("2. 代理端口是否正确 (当前: 8001)")
        print("3. 代理是否支持 WebSocket 协议")
