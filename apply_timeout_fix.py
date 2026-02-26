#!/usr/bin/env python3
"""
Auto-apply timeout fixes to bot.py
自动应用超时修复补丁
"""
import shutil
from pathlib import Path
from datetime import datetime
import re


def backup_file(filepath: Path) -> Path:
    """创建备份文件"""
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_path = filepath.parent / f"{filepath.stem}.backup_{timestamp}{filepath.suffix}"
    shutil.copy2(filepath, backup_path)
    print(f"✅ 备份已创建: {backup_path}")
    return backup_path


def apply_import_fixes(content: str) -> str:
    """添加新的导入"""
    # 在现有导入后添加新导入
    import_insertion = """
# Enhanced connection management
from connection_config import CONNECTION_CONFIG
from circuit_breaker import get_circuit_breaker, get_retry_manager
"""
    
    # 在 'from loguru import logger' 后插入
    pattern = r'(from loguru import logger)'
    replacement = r'\1\n' + import_insertion
    
    content = re.sub(pattern, replacement, content)
    return content


def apply_config_fixes(content: str) -> str:
    """修复 TradingNodeConfig 配置"""
    # 查找并替换 data_engine 配置
    old_data_engine = r'data_engine=LiveDataEngineConfig\(qsize=6000\)'
    new_data_engine = f'''data_engine=LiveDataEngineConfig(
            qsize=CONNECTION_CONFIG.DATA_ENGINE_QSIZE,
            timeout=CONNECTION_CONFIG.DATA_ENGINE_TIMEOUT,
        )'''
    
    content = re.sub(old_data_engine, new_data_engine, content)
    
    # 查找并替换 exec_engine 配置
    old_exec_engine = r'exec_engine=LiveExecEngineConfig\(qsize=6000\)'
    new_exec_engine = f'''exec_engine=LiveExecEngineConfig(
            qsize=CONNECTION_CONFIG.EXEC_ENGINE_QSIZE,
            timeout=CONNECTION_CONFIG.EXEC_ENGINE_TIMEOUT,
        )'''
    
    content = re.sub(old_exec_engine, new_exec_engine, content)
    
    return content


def apply_redis_fixes(content: str) -> str:
    """修复 Redis 连接配置"""
    # 查找 init_redis 函数
    pattern = r'def init_redis\(\):.*?return None'
    
    replacement = '''def init_redis():
    """Initialize Redis connection for simulation mode control."""
    try:
        redis_client = redis.Redis(
            host=os.getenv('REDIS_HOST', 'localhost'),
            port=int(os.getenv('REDIS_PORT', 6379)),
            db=int(os.getenv('REDIS_DB', 2)),
            decode_responses=True,
            socket_connect_timeout=CONNECTION_CONFIG.REDIS_SOCKET_TIMEOUT,
            socket_timeout=CONNECTION_CONFIG.REDIS_SOCKET_TIMEOUT,
            socket_keepalive=True,
            retry_on_timeout=True,
            health_check_interval=30,
        )
        redis_client.ping()
        logger.info("Redis connection established with enhanced config")
        return redis_client
    except Exception as e:
        logger.warning(f"Redis connection failed: {e}")
        logger.warning("Simulation mode will be static (from .env)")
        return None'''
    
    content = re.sub(pattern, replacement, content, flags=re.DOTALL)
    return content


def apply_health_check(content: str) -> str:
    """添加健康检查方法"""
    # 在 IntegratedBTCStrategy 类的 __init__ 方法后添加
    health_check_method = '''
    def check_connection_health(self) -> bool:
        """检查所有关键连接的健康状态"""
        # 检查 Redis
        if self.redis_client:
            try:
                self.redis_client.ping()
            except Exception as e:
                logger.error(f"Redis health check failed: {e}")
                return False
        
        # 检查数据引擎
        if hasattr(self, 'data_engine') and not self.data_engine.is_running:
            logger.error("Data engine is not running")
            return False
        
        # 检查执行引擎
        if hasattr(self, 'exec_engine') and not self.exec_engine.is_running:
            logger.error("Exec engine is not running")
            return False
        
        return True
'''
    
    # 在 __init__ 方法后插入
    pattern = r'(class IntegratedBTCStrategy.*?def __init__.*?\n(?:.*?\n)*?super\(\).__init__\(\))'
    replacement = r'\1\n' + health_check_method
    
    content = re.sub(pattern, replacement, content, flags=re.DOTALL)
    return content


def main():
    """主函数"""
    bot_file = Path("bot.py")
    
    if not bot_file.exists():
        print("❌ 错误: bot.py 不存在")
        return
    
    print("=" * 80)
    print("应用超时修复补丁")
    print("=" * 80)
    print()
    
    # 1. 备份原文件
    print("1️⃣  备份原文件...")
    backup_path = backup_file(bot_file)
    print()
    
    # 2. 读取原文件
    print("2️⃣  读取 bot.py...")
    with open(bot_file, 'r', encoding='utf-8') as f:
        content = f.read()
    print(f"✅ 文件大小: {len(content)} 字符")
    print()
    
    # 3. 应用修复
    print("3️⃣  应用修复补丁...")
    
    fixes = [
        ("导入修复", apply_import_fixes),
        ("配置修复", apply_config_fixes),
        ("Redis 修复", apply_redis_fixes),
        ("健康检查", apply_health_check),
    ]
    
    for name, fix_func in fixes:
        try:
            content = fix_func(content)
            print(f"  ✅ {name}")
        except Exception as e:
            print(f"  ❌ {name}: {e}")
    
    print()
    
    # 4. 写入修改后的文件
    print("4️⃣  写入修改后的文件...")
    with open(bot_file, 'w', encoding='utf-8') as f:
        f.write(content)
    print("✅ bot.py 已更新")
    print()
    
    # 5. 更新 .env 文件
    print("5️⃣  检查 .env 文件...")
    env_file = Path(".env")
    if env_file.exists():
        with open(env_file, 'r') as f:
            env_content = f.read()
        
        # 检查是否已有超时配置
        if "NODE_TIMEOUT" not in env_content:
            print("  添加超时配置到 .env...")
            timeout_config = """
# 连接超时配置（由 apply_timeout_fix.py 添加）
NODE_TIMEOUT=300
DATA_ENGINE_TIMEOUT=180
EXEC_ENGINE_TIMEOUT=180
WS_MAX_RECONNECT_ATTEMPTS=10
WS_INITIAL_BACKOFF=2.0
WS_MAX_BACKOFF=120.0
API_CONNECT_TIMEOUT=30
API_READ_TIMEOUT=60
REDIS_SOCKET_TIMEOUT=10
"""
            with open(env_file, 'a') as f:
                f.write(timeout_config)
            print("  ✅ .env 已更新")
        else:
            print("  ℹ️  .env 已包含超时配置")
    print()
    
    # 6. 完成
    print("=" * 80)
    print("✅ 补丁应用完成!")
    print("=" * 80)
    print()
    print("📝 主要改进:")
    print("  • 增加超时时间（120s → 300s）")
    print("  • 增强队列配置（6000 → 10000）")
    print("  • 改进 Redis 连接（健康检查 + 重试）")
    print("  • 添加连接健康检查方法")
    print()
    print("🚀 下一步:")
    print("  1. 测试运行: python bot.py --test-mode")
    print("  2. 如果出现问题，恢复备份: cp {backup_path} bot.py")
    print("  3. 查看日志: tail -f logs/nautilus/*.log")
    print()
    print("💡 如需更多增强功能（断路器、增强重连），请手动集成:")
    print("  - circuit_breaker.py")
    print("  - enhanced_websocket_manager.py")
    print()


if __name__ == "__main__":
    main()
