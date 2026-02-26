"""
Enhanced Connection Configuration
解决连接超时和稳定性问题
"""
import os
from dataclasses import dataclass
from typing import Optional


@dataclass
class ConnectionConfig:
    """连接配置 - 针对不稳定网络优化"""
    
    # NautilusTrader 超时设置（秒）
    NODE_TIMEOUT: int = 300  # 增加到 5 分钟
    DATA_ENGINE_TIMEOUT: int = 180  # 数据引擎超时
    EXEC_ENGINE_TIMEOUT: int = 180  # 执行引擎超时
    
    # WebSocket 重连配置
    WS_MAX_RECONNECT_ATTEMPTS: int = 10  # 增加重连次数
    WS_INITIAL_BACKOFF: float = 2.0  # 初始退避时间
    WS_MAX_BACKOFF: float = 120.0  # 最大退避时间
    WS_HEALTH_CHECK_INTERVAL: int = 20  # 健康检查间隔
    
    # Polymarket API 配置
    API_CONNECT_TIMEOUT: int = 30  # API 连接超时
    API_READ_TIMEOUT: int = 60  # API 读取超时
    API_MAX_RETRIES: int = 3  # API 重试次数
    API_RETRY_DELAY: float = 5.0  # 重试延迟
    
    # Redis 配置
    REDIS_SOCKET_TIMEOUT: int = 10  # Redis socket 超时
    REDIS_CONNECT_TIMEOUT: int = 5  # Redis 连接超时
    
    # 数据引擎队列配置
    DATA_ENGINE_QSIZE: int = 10000  # 增加队列大小
    EXEC_ENGINE_QSIZE: int = 10000
    
    # 断路器配置
    CIRCUIT_BREAKER_THRESHOLD: int = 5  # 连续失败次数阈值
    CIRCUIT_BREAKER_TIMEOUT: int = 300  # 断路器开启时长（秒）
    
    @classmethod
    def from_env(cls) -> "ConnectionConfig":
        """从环境变量加载配置"""
        return cls(
            NODE_TIMEOUT=int(os.getenv("NODE_TIMEOUT", 300)),
            DATA_ENGINE_TIMEOUT=int(os.getenv("DATA_ENGINE_TIMEOUT", 180)),
            EXEC_ENGINE_TIMEOUT=int(os.getenv("EXEC_ENGINE_TIMEOUT", 180)),
            WS_MAX_RECONNECT_ATTEMPTS=int(os.getenv("WS_MAX_RECONNECT_ATTEMPTS", 10)),
            WS_INITIAL_BACKOFF=float(os.getenv("WS_INITIAL_BACKOFF", 2.0)),
            WS_MAX_BACKOFF=float(os.getenv("WS_MAX_BACKOFF", 120.0)),
            API_CONNECT_TIMEOUT=int(os.getenv("API_CONNECT_TIMEOUT", 30)),
            API_READ_TIMEOUT=int(os.getenv("API_READ_TIMEOUT", 60)),
        )


@dataclass
class RetryPolicy:
    """重试策略"""
    max_attempts: int = 3
    initial_delay: float = 1.0
    max_delay: float = 60.0
    exponential_base: float = 2.0
    
    def get_delay(self, attempt: int) -> float:
        """计算第 N 次重试的延迟时间"""
        delay = self.initial_delay * (self.exponential_base ** attempt)
        return min(delay, self.max_delay)


# 全局配置实例
CONNECTION_CONFIG = ConnectionConfig.from_env()

# 重试策略
DEFAULT_RETRY_POLICY = RetryPolicy()
