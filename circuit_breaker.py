"""
Circuit Breaker and Retry Manager
断路器和重试管理器 - 防止级联失败
"""
import asyncio
import time
from datetime import datetime, timedelta
from typing import Optional, Callable, Any, Dict
from enum import Enum
from dataclasses import dataclass, field
from loguru import logger
from connection_config import CONNECTION_CONFIG, RetryPolicy


class CircuitState(Enum):
    """断路器状态"""
    CLOSED = "closed"  # 正常状态
    OPEN = "open"  # 断开状态（拒绝请求）
    HALF_OPEN = "half_open"  # 半开状态（尝试恢复）


@dataclass
class CircuitBreaker:
    """
    断路器 - 防止级联失败
    
    工作原理：
    1. CLOSED 状态：正常工作，记录失败次数
    2. 失败次数超过阈值 → OPEN 状态：拒绝所有请求
    3. 超时后 → HALF_OPEN 状态：允许一次试探请求
    4. 试探成功 → CLOSED，失败 → OPEN
    """
    name: str
    failure_threshold: int = CONNECTION_CONFIG.CIRCUIT_BREAKER_THRESHOLD
    timeout: int = CONNECTION_CONFIG.CIRCUIT_BREAKER_TIMEOUT
    
    # 状态
    state: CircuitState = CircuitState.CLOSED
    failure_count: int = 0
    last_failure_time: Optional[datetime] = None
    last_success_time: Optional[datetime] = None
    
    # 统计
    total_requests: int = 0
    total_failures: int = 0
    total_successes: int = 0
    
    def can_execute(self) -> bool:
        """检查是否可以执行请求"""
        self.total_requests += 1
        
        if self.state == CircuitState.CLOSED:
            return True
        
        elif self.state == CircuitState.OPEN:
            # 检查是否超时，可以进入半开状态
            if self._should_attempt_reset():
                self.state = CircuitState.HALF_OPEN
                logger.info(f"{self.name}: Circuit breaker entering HALF_OPEN state")
                return True
            return False
        
        elif self.state == CircuitState.HALF_OPEN:
            # 半开状态只允许一个请求
            return True
        
        return False
    
    def record_success(self) -> None:
        """记录成功"""
        self.failure_count = 0
        self.last_success_time = datetime.now()
        self.total_successes += 1
        
        if self.state == CircuitState.HALF_OPEN:
            self.state = CircuitState.CLOSED
            logger.info(f"{self.name}: Circuit breaker recovered -> CLOSED")
    
    def record_failure(self, error: Optional[Exception] = None) -> None:
        """记录失败"""
        self.failure_count += 1
        self.last_failure_time = datetime.now()
        self.total_failures += 1
        
        error_msg = str(error) if error else "Unknown error"
        
        if self.state == CircuitState.HALF_OPEN:
            # 半开状态下失败，立即回到 OPEN
            self.state = CircuitState.OPEN
            logger.warning(
                f"{self.name}: Circuit breaker failed in HALF_OPEN -> OPEN | "
                f"Error: {error_msg}"
            )
        
        elif self.failure_count >= self.failure_threshold:
            # 失败次数超过阈值，进入 OPEN 状态
            self.state = CircuitState.OPEN
            logger.error(
                f"{self.name}: Circuit breaker OPENED | "
                f"Failures: {self.failure_count}/{self.failure_threshold} | "
                f"Error: {error_msg}"
            )
    
    def _should_attempt_reset(self) -> bool:
        """检查是否应该尝试重置"""
        if not self.last_failure_time:
            return True
        
        elapsed = datetime.now() - self.last_failure_time
        return elapsed > timedelta(seconds=self.timeout)
    
    def reset(self) -> None:
        """手动重置断路器"""
        self.state = CircuitState.CLOSED
        self.failure_count = 0
        logger.info(f"{self.name}: Circuit breaker manually reset")
    
    def get_stats(self) -> Dict[str, Any]:
        """获取统计信息"""
        return {
            "name": self.name,
            "state": self.state.value,
            "failure_count": self.failure_count,
            "failure_threshold": self.failure_threshold,
            "total_requests": self.total_requests,
            "total_successes": self.total_successes,
            "total_failures": self.total_failures,
            "success_rate": (
                self.total_successes / self.total_requests * 100
                if self.total_requests > 0 else 0
            ),
            "last_failure": self.last_failure_time.isoformat() if self.last_failure_time else None,
            "last_success": self.last_success_time.isoformat() if self.last_success_time else None,
        }


class RetryManager:
    """
    重试管理器 - 智能重试机制
    
    特性：
    - 指数退避
    - 最大重试次数
    - 可配置的重试条件
    """
    
    def __init__(
        self,
        policy: Optional[RetryPolicy] = None,
        circuit_breaker: Optional[CircuitBreaker] = None,
    ):
        self.policy = policy or RetryPolicy()
        self.circuit_breaker = circuit_breaker
    
    async def execute_with_retry(
        self,
        func: Callable[[], Any],
        operation_name: str = "operation",
        retryable_exceptions: Optional[tuple] = None,
    ) -> Any:
        """
        执行函数并在失败时重试
        
        Args:
            func: 要执行的异步函数
            operation_name: 操作名称（用于日志）
            retryable_exceptions: 可重试的异常类型元组
        
        Returns:
            函数执行结果
        
        Raises:
            最后一次失败的异常
        """
        if retryable_exceptions is None:
            retryable_exceptions = (
                asyncio.TimeoutError,
                ConnectionError,
                OSError,
            )
        
        # 检查断路器
        if self.circuit_breaker and not self.circuit_breaker.can_execute():
            raise Exception(
                f"{operation_name}: Circuit breaker is OPEN - refusing request"
            )
        
        last_exception = None
        
        for attempt in range(self.policy.max_attempts):
            try:
                result = await func()
                
                # 记录成功
                if self.circuit_breaker:
                    self.circuit_breaker.record_success()
                
                if attempt > 0:
                    logger.info(
                        f"{operation_name}: SUCCESS on attempt {attempt + 1}"
                    )
                
                return result
            
            except retryable_exceptions as e:
                last_exception = e
                
                # 记录失败
                if self.circuit_breaker:
                    self.circuit_breaker.record_failure(e)
                
                if attempt < self.policy.max_attempts - 1:
                    delay = self.policy.get_delay(attempt)
                    logger.warning(
                        f"{operation_name}: Attempt {attempt + 1}/{self.policy.max_attempts} failed | "
                        f"Error: {e} | Retrying in {delay:.1f}s..."
                    )
                    await asyncio.sleep(delay)
                else:
                    logger.error(
                        f"{operation_name}: All {self.policy.max_attempts} attempts failed | "
                        f"Last error: {e}"
                    )
        
        # 所有重试都失败
        raise last_exception or Exception(f"{operation_name}: All retry attempts failed")


# 全局断路器实例
CIRCUIT_BREAKERS = {
    "polymarket_api": CircuitBreaker("polymarket_api"),
    "websocket": CircuitBreaker("websocket"),
    "redis": CircuitBreaker("redis"),
    "data_engine": CircuitBreaker("data_engine"),
}


def get_circuit_breaker(name: str) -> CircuitBreaker:
    """获取断路器实例"""
    if name not in CIRCUIT_BREAKERS:
        CIRCUIT_BREAKERS[name] = CircuitBreaker(name)
    return CIRCUIT_BREAKERS[name]


def get_retry_manager(name: str, policy: Optional[RetryPolicy] = None) -> RetryManager:
    """获取重试管理器"""
    circuit_breaker = get_circuit_breaker(name)
    return RetryManager(policy=policy, circuit_breaker=circuit_breaker)
