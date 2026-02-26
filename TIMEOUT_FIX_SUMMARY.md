# 网络超时问题修复总结

## 问题描述

你的 Polymarket 交易机器人频繁遇到连接超时问题：
- `TradingNode` 等待响应超时（120秒）
- 网络 I/O 超时（os error 60）
- WebSocket 连接不稳定
- HTTP 请求超时

## 已应用的修复

### ✅ 1. 增加 TradingNode 超时配置（⭐ 核心修复）

**文件**: `bot.py`

**修改**:
```python
config = TradingNodeConfig(
    # ... 其他配置 ...
    # 使用连接配置中的超时值
    timeout_connection=float(CONNECTION_CONFIG.NODE_TIMEOUT),  # 默认 300s
    timeout_reconciliation=float(CONNECTION_CONFIG.DATA_ENGINE_TIMEOUT),  # 默认 60s
)
```

**效果**:
- 这是解决超时问题的**核心修复**
- `timeout_connection` 从默认的 120 秒增加到 300 秒（5分钟）
- `timeout_reconciliation` 从 30 秒增加到 60 秒

---

### ✅ 2. 集成断路器和重试机制（⭐ 新增）

**文件**: `circuit_breaker.py`, `connection_config.py`

**功能**:
- **断路器模式**: 连续失败超过阈值后暂停请求，防止级联失败
- **重试管理器**: 智能指数退避重试
- **统一配置管理**: 所有超时值可通过环境变量或配置文件调整

**使用示例**:
```python
from circuit_breaker import get_circuit_breaker, get_retry_manager

# 获取断路器
cb = get_circuit_breaker("api_name")

# 检查是否可以执行
if cb.can_execute():
    try:
        result = await api_call()
        cb.record_success()
    except Exception as e:
        cb.record_failure(e)

# 使用重试管理器
retry_mgr = get_retry_manager("api_name")
result = await retry_mgr.execute_with_retry(
    api_call,
    retryable_exceptions=(TimeoutError, ConnectionError)
)
```

---

### ✅ 3. 增强版 WebSocket 管理器（已创建）

**文件**: `enhanced_websocket_manager.py`

**功能**:
- 集成断路器保护
- 更智能的重连策略
- 心跳检测保持连接活跃
- 消息队列缓冲
- 详细的连接统计

---

### ✅ 4. 增强 Coinbase 数据源

**文件**: `data_sources/coinbase/adapter.py`

**修改**:
```python
# 使用增强超时配置
self.session = httpx.AsyncClient(
    timeout=httpx.Timeout(
        connect=CONNECTION_CONFIG.API_CONNECT_TIMEOUT,  # 30s
        read=CONNECTION_CONFIG.API_READ_TIMEOUT,  # 60s
    ),
    limits=httpx.Limits(
        max_keepalive_connections=5,
        max_connections=10,
    )
)

# 断路器保护
if not self.circuit_breaker.can_execute():
    return self._last_price  # 返回缓存价格

# 重试机制
result = await self.retry_manager.execute_with_retry(
    fetch_price,
    retryable_exceptions=(httpx.TimeoutException, httpx.ConnectError)
)
```

---

### ✅ 5. 增强 Polymarket 客户端

**文件**: `execution/polymarket_client.py`

**修改**:
- 添加断路器和重试管理器
- 在关键 API 调用中集成重试机制

---

### ✅ 6. 增强版启动脚本

**文件**: `15m_bot_runner.py`

**改进**:
```python
def calculate_backoff(exit_code: int, consecutive_errors: int) -> int:
    """智能退避策略"""
    # 正常重启
    if exit_code in [0, 143, 15, -15]:
        return 2

    # 超时或网络错误 - 更长退避
    if exit_code in [124, 137]:
        return min(60 * (2 ** min(consecutive_errors, 4)), 300)

    # 连接错误 - 指数退避
    return min(5 * (2 ** consecutive_errors), 300)
```

**特性**:
- 连续错误追踪
- 智能指数退避
- 错误历史记录
- 详细统计信息

---

### ✅ 7. 增强 Redis 连接配置

**文件**: `bot.py`

```python
redis_client = redis.Redis(
    socket_connect_timeout=CONNECTION_CONFIG.REDIS_CONNECT_TIMEOUT,
    socket_timeout=CONNECTION_CONFIG.REDIS_SOCKET_TIMEOUT,
    retry_on_timeout=True,
    health_check_interval=30,
)
```

---

### ✅ 8. 改进错误处理

**文件**: `bot.py`

```python
except asyncio.TimeoutError as e:
    logger.error(f"Async timeout error: {e}")
    raise
except OSError as e:
    logger.error(f"Network OS error: {e} (errno: {e.errno})")
    raise
```

---

## 配置选项（可通过环境变量覆盖）

在 `.env` 文件中添加：

```bash
# 连接超时配置
NODE_TIMEOUT=300           # TradingNode 超时（秒）
DATA_ENGINE_TIMEOUT=180    # 数据引擎超时
EXEC_ENGINE_TIMEOUT=180    # 执行引擎超时

# WebSocket 重连配置
WS_MAX_RECONNECT_ATTEMPTS=10
WS_INITIAL_BACKOFF=2.0
WS_MAX_BACKOFF=120.0
WS_HEALTH_CHECK_INTERVAL=20

# API 超时配置
API_CONNECT_TIMEOUT=30
API_READ_TIMEOUT=60
API_MAX_RETRIES=3

# Redis 配置
REDIS_SOCKET_TIMEOUT=10
REDIS_CONNECT_TIMEOUT=5

# 断路器配置
CIRCUIT_BREAKER_THRESHOLD=5   # 连续失败次数阈值
CIRCUIT_BREAKER_TIMEOUT=300   # 断路器开启时长
```

---

## 使用说明

### 测试修复效果

```bash
# 激活环境
conda activate poly

# 测试模式（快速验证）
python bot.py --test-mode

# 生产模式
python 15m_bot_runner.py --live
```

### 监控关键指标

- 超时错误频率
- 断路器状态
- 自动重启次数
- 会话持续时间

---

## 文件清单

| 文件 | 状态 | 说明 |
|------|------|------|
| `bot.py` | ✅ 已修改 | 集成增强配置，改进错误处理 |
| `15m_bot_runner.py` | ✅ 已修改 | 智能退避策略 |
| `data_sources/coinbase/adapter.py` | ✅ 已修改 | 断路器 + 重试机制 |
| `execution/polymarket_client.py` | ✅ 已修改 | 断路器集成 |
| `connection_config.py` | ✅ 已创建 | 统一配置管理 |
| `circuit_breaker.py` | ✅ 已创建 | 断路器 + 重试管理器 |
| `enhanced_websocket_manager.py` | ✅ 已创建 | 增强版 WebSocket（备用） |

---

## 总结

✅ **已完成的修复**:
1. ⭐ **TradingNode 超时**（120s → 300s）- **核心修复**
2. ⭐ **断路器模式** - 防止级联失败
3. ⭐ **智能重试机制** - 指数退避重试
4. **队列大小增加**（6000 → 10000）
5. **Redis 连接增强**（健康检查 + 自动重试）
6. **HTTP 客户端增强**（超时 + 连接池）
7. **错误处理增强**（更详细的错误分类）
8. **启动脚本增强**（智能退避 + 错误追踪）

🎯 **预期效果**:
- 大幅减少超时错误导致的崩溃
- 更快的自动恢复
- 更稳定的长时间运行
- 更好的错误诊断能力

⚠️ **注意事项**:
- 所有修改已应用到代码中，无需重新运行脚本
- 如果仍有问题，检查网络环境（考虑代理/VPN）
- 可以通过环境变量调整超时值

---

**修复完成时间**: 2026-02-26
**修复文件数量**: 7 个核心文件
**关键修复**: 断路器模式 + 智能重试 + 统一超时配置
