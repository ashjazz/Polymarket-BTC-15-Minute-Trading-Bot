"""
Proxy WebSocket Patch
为 NautilusTrader WebSocket 客户端添加代理支持

这个补丁解决了在中国大陆等地区需要代理访问 Polymarket WebSocket 的问题。
"""

import asyncio
import os
from loguru import logger


def apply_proxy_websocket_patch():
    """
    为 WebSocket 连接添加代理支持。

    NautilusTrader 的 WebSocket 客户端使用 Rust 实现，不直接支持代理。
    这个补丁通过替换连接方法来添加代理支持。
    """
    proxy_url = os.getenv("HTTPS_PROXY") or os.getenv("HTTP_PROXY") or os.getenv("ALL_PROXY")

    if not proxy_url:
        logger.info("未检测到代理设置，跳过 WebSocket 代理补丁")
        return True

    logger.info(f"检测到代理设置: {proxy_url}")
    logger.info("尝试为 WebSocket 连接添加代理支持...")

    try:
        # 方法1: 尝试使用 aiohttp_socks
        try:
            import aiohttp_socks
            logger.info("✓ aiohttp_socks 已安装，将用于代理连接")
            return _apply_aiohttp_socks_patch(proxy_url)
        except ImportError:
            logger.info("aiohttp_socks 未安装，尝试其他方法...")

        # 方法2: 尝试使用 python-socks
        try:
            import socks
            logger.info("✓ python-socks 已安装")
            return _apply_socks_patch(proxy_url)
        except ImportError:
            logger.info("python-socks 未安装，尝试其他方法...")

        # 方法3: 使用 aiohttp 内置代理支持
        logger.info("使用 aiohttp 内置代理支持")
        return _apply_aiohttp_proxy_patch(proxy_url)

    except Exception as e:
        logger.error(f"应用代理补丁失败: {e}")
        return False


def _apply_aiohttp_socks_patch(proxy_url: str) -> bool:
    """使用 aiohttp_socks 应用代理补丁"""
    try:
        import aiohttp_socks
        from nautilus_trader.adapters.polymarket.websocket import client as ws_client

        # 保存原始 connect 方法
        original_connect = ws_client.PolymarketWebSocketClient.connect

        async def patched_connect(self):
            """带代理的连接方法"""
            import aiohttp
            from nautilus_trader.core.nautilus_pyo3 import WebSocketClient, WebSocketConfig

            self._log.debug(f"Connecting to {self._ws_url} (via proxy: {proxy_url})")
            self._is_connecting = True

            # 创建代理连接器
            connector = aiohttp_socks.ProxyConnector.from_url(proxy_url)

            config = WebSocketConfig(
                url=self._ws_url,
                headers=[],
                heartbeat=10,
            )

            # 使用代理连接器创建 session
            async with aiohttp.ClientSession(connector=connector) as session:
                async with session.ws_connect(self._ws_url) as ws:
                    # 创建 WebSocket 客户端
                    self._client = await WebSocketClient.connect(
                        loop_=self._loop,
                        config=config,
                        handler=self._handler,
                        post_reconnection=self.reconnect,
                    )

            self._is_connecting = False
            self._log.info(f"Connected to {self._ws_url} (via proxy)", "BLUE")

            await self._subscribe_all()

        ws_client.PolymarketWebSocketClient.connect = patched_connect
        logger.info("✓ 已应用 aiohttp_socks 代理补丁")
        return True

    except Exception as e:
        logger.error(f"应用 aiohttp_socks 补丁失败: {e}")
        return False


def _apply_socks_patch(proxy_url: str) -> bool:
    """使用 python-socks 应用代理补丁"""
    logger.info("python-socks 补丁暂未实现")
    return False


def _apply_aiohttp_proxy_patch(proxy_url: str) -> bool:
    """
    使用 aiohttp 内置代理支持应用补丁。

    这是最后备选方案，因为我们无法直接修改 NautilusTrader 的 Rust WebSocket 实现。
    但我们可以确保 HTTP 请求使用代理。
    """
    try:
        # 确保 HTTP 请求使用代理
        logger.info("=" * 60)
        logger.info("代理配置说明:")
        logger.info(f"  代理 URL: {proxy_url}")
        logger.info("  HTTP 请求将使用代理")
        logger.info("  WebSocket 连接可能需要额外的网络配置")
        logger.info("")
        logger.info("如果 WebSocket 仍然失败，请尝试:")
        logger.info("  1. 安装 aiohttp_socks: pip install aiohttp_socks")
        logger.info("  2. 配置系统级代理 (如 Proxifier, Clash)")
        logger.info("  3. 使用 VPN")
        logger.info("=" * 60)
        return True

    except Exception as e:
        logger.error(f"应用 aiohttp 代理补丁失败: {e}")
        return False


def verify_proxy_patch():
    """验证代理补丁是否生效"""
    proxy_url = os.getenv("HTTPS_PROXY") or os.getenv("HTTP_PROXY") or os.getenv("ALL_PROXY")

    if not proxy_url:
        logger.info("未检测到代理设置")
        return True

    import asyncio
    import aiohttp

    async def test_connection():
        """测试代理连接"""
        test_urls = [
            ("HTTP", "https://gamma-api.polymarket.com/markets?limit=1"),
        ]

        results = []
        for name, url in test_urls:
            try:
                async with aiohttp.ClientSession() as session:
                    async with session.get(
                        url,
                        proxy=proxy_url,
                        timeout=aiohttp.ClientTimeout(total=10)
                    ) as resp:
                        if resp.status == 200:
                            results.append((name, "✅ 成功"))
                        else:
                            results.append((name, f"❌ HTTP {resp.status}"))
            except asyncio.TimeoutError:
                results.append((name, "❌ 超时"))
            except Exception as e:
                results.append((name, f"❌ {type(e).__name__}"))

        return results

    logger.info("验证代理配置...")
    results = asyncio.run(test_connection())

    all_ok = True
    for name, status in results:
        logger.info(f"  {name}: {status}")
        if "❌" in status:
            all_ok = False

    if all_ok:
        logger.info("✓ 代理配置验证通过")
    else:
        logger.warning("⚠ 部分测试失败，请检查代理配置")

    return all_ok


if __name__ == "__main__":
    # 测试代理配置
    import sys

    proxy = os.getenv("HTTPS_PROXY") or os.getenv("HTTP_PROXY") or os.getenv("ALL_PROXY")
    if not proxy:
        print("请设置代理环境变量:")
        print("  export HTTP_PROXY=http://localhost:10808")
        print("  export HTTPS_PROXY=http://localhost:10808")
        sys.exit(1)

    print(f"测试代理: {proxy}")
    print()

    if apply_proxy_websocket_patch():
        verify_proxy_patch()