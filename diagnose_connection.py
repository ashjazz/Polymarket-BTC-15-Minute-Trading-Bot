#!/usr/bin/env python3
"""
Connection Diagnostics
连接诊断工具 - 检测网络和 API 连接问题
"""
import asyncio
import time
import sys
from pathlib import Path
from datetime import datetime
import os

# 添加项目路径
project_root = Path(__file__).parent
sys.path.insert(0, str(project_root))

from dotenv import load_dotenv
import redis

load_dotenv()


def check_redis_connection() -> dict:
    """检查 Redis 连接"""
    print("\n🔍 检查 Redis 连接...")
    
    result = {
        "service": "Redis",
        "status": "UNKNOWN",
        "latency_ms": None,
        "error": None,
    }
    
    try:
        start_time = time.time()
        
        client = redis.Redis(
            host=os.getenv('REDIS_HOST', 'localhost'),
            port=int(os.getenv('REDIS_PORT', 6379)),
            db=int(os.getenv('REDIS_DB', 2)),
            socket_connect_timeout=5,
            socket_timeout=5,
        )
        
        client.ping()
        
        latency = (time.time() - start_time) * 1000
        
        result["status"] = "OK"
        result["latency_ms"] = round(latency, 2)
        
        print(f"  ✅ Redis 连接正常")
        print(f"  📊 延迟: {result['latency_ms']}ms")
        print(f"  📍 地址: {os.getenv('REDIS_HOST')}:{os.getenv('REDIS_PORT')}")
        
    except Exception as e:
        result["status"] = "FAILED"
        result["error"] = str(e)
        
        print(f"  ❌ Redis 连接失败: {e}")
    
    return result


async def check_polymarket_api() -> dict:
    """检查 Polymarket API 连接"""
    print("\n🔍 检查 Polymarket API...")
    
    result = {
        "service": "Polymarket API",
        "status": "UNKNOWN",
        "latency_ms": None,
        "error": None,
    }
    
    try:
        import aiohttp
        
        start_time = time.time()
        
        async with aiohttp.ClientSession() as session:
            # 测试 Gamma API
            async with session.get(
                "https://gamma-api.polymarket.com/markets?limit=1",
                timeout=aiohttp.ClientTimeout(total=10)
            ) as response:
                if response.status == 200:
                    latency = (time.time() - start_time) * 1000
                    
                    result["status"] = "OK"
                    result["latency_ms"] = round(latency, 2)
                    
                    print(f"  ✅ Polymarket API 连接正常")
                    print(f"  📊 延迟: {result['latency_ms']}ms")
                else:
                    raise Exception(f"HTTP {response.status}")
    
    except Exception as e:
        result["status"] = "FAILED"
        result["error"] = str(e)
        
        print(f"  ❌ Polymarket API 连接失败: {e}")
    
    return result


async def check_clob_api() -> dict:
    """检查 Polymarket CLOB API"""
    print("\n🔍 检查 Polymarket CLOB API...")
    
    result = {
        "service": "Polymarket CLOB",
        "status": "UNKNOWN",
        "latency_ms": None,
        "error": None,
    }
    
    try:
        import aiohttp
        
        start_time = time.time()
        
        async with aiohttp.ClientSession() as session:
            # 测试 CLOB API
            async with session.get(
                "https://clob.polymarket.com/markets",
                timeout=aiohttp.ClientTimeout(total=10)
            ) as response:
                if response.status == 200:
                    latency = (time.time() - start_time) * 1000
                    
                    result["status"] = "OK"
                    result["latency_ms"] = round(latency, 2)
                    
                    print(f"  ✅ CLOB API 连接正常")
                    print(f"  📊 延迟: {result['latency_ms']}ms")
                else:
                    raise Exception(f"HTTP {response.status}")
    
    except Exception as e:
        result["status"] = "FAILED"
        result["error"] = str(e)
        
        print(f"  ❌ CLOB API 连接失败: {e}")
    
    return result


async def check_coinbase_api() -> dict:
    """检查 Coinbase API"""
    print("\n🔍 检查 Coinbase API...")
    
    result = {
        "service": "Coinbase API",
        "status": "UNKNOWN",
        "latency_ms": None,
        "error": None,
    }
    
    try:
        import aiohttp
        
        start_time = time.time()
        
        async with aiohttp.ClientSession() as session:
            async with session.get(
                "https://api.coinbase.com/v2/prices/BTC-USD/spot",
                timeout=aiohttp.ClientTimeout(total=10)
            ) as response:
                if response.status == 200:
                    latency = (time.time() - start_time) * 1000
                    
                    result["status"] = "OK"
                    result["latency_ms"] = round(latency, 2)
                    
                    print(f"  ✅ Coinbase API 连接正常")
                    print(f"  📊 延迟: {result['latency_ms']}ms")
                else:
                    raise Exception(f"HTTP {response.status}")
    
    except Exception as e:
        result["status"] = "FAILED"
        result["error"] = str(e)
        
        print(f"  ❌ Coinbase API 连接失败: {e}")
    
    return result


def check_network_stability() -> dict:
    """检查网络稳定性"""
    print("\n🔍 检查网络稳定性...")
    
    result = {
        "test": "Network Stability",
        "pings": [],
        "packet_loss": None,
        "avg_latency_ms": None,
    }
    
    import subprocess
    import platform
    
    # Ping 测试（Google DNS）
    target = "8.8.8.8"
    
    # Windows 使用 -n，Unix 使用 -c
    param = '-n' if platform.system().lower() == 'windows' else '-c'
    
    try:
        # 执行 5 次 ping
        output = subprocess.check_output(
            ['ping', param, '5', target],
            stderr=subprocess.STDOUT,
            universal_newlines=True
        )
        
        print(f"  ✅ Ping {target} 成功")
        
        # 解析输出（简化版）
        if platform.system().lower() == 'windows':
            # Windows ping 输出
            for line in output.split('\n'):
                if 'time=' in line or 'time<' in line:
                    print(f"  📊 {line.strip()}")
        else:
            # Unix ping 输出
            print(f"  📊 Ping 统计:")
            for line in output.split('\n'):
                if 'packets transmitted' in line or 'rtt min' in line:
                    print(f"     {line.strip()}")
        
        result["status"] = "OK"
        
    except Exception as e:
        result["status"] = "FAILED"
        result["error"] = str(e)
        
        print(f"  ❌ Ping 测试失败: {e}")
    
    return result


def check_environment_config() -> dict:
    """检查环境配置"""
    print("\n🔍 检查环境配置...")
    
    required_vars = [
        "POLYMARKET_PK",
        "POLYMARKET_API_KEY",
        "POLYMARKET_API_SECRET",
        "POLYMARKET_PASSPHRASE",
        "REDIS_HOST",
        "REDIS_PORT",
    ]
    
    result = {
        "test": "Environment Config",
        "missing": [],
        "status": "OK",
    }
    
    for var in required_vars:
        value = os.getenv(var)
        if not value:
            result["missing"].append(var)
            print(f"  ❌ {var}: 未设置")
        else:
            # 隐藏敏感信息
            if "KEY" in var or "SECRET" in var or "PASSPHRASE" in var:
                display_value = value[:8] + "..." if len(value) > 8 else "***"
            else:
                display_value = value
            
            print(f"  ✅ {var}: {display_value}")
    
    if result["missing"]:
        result["status"] = "FAILED"
        print(f"\n  ⚠️  缺少环境变量: {', '.join(result['missing'])}")
    
    return result


async def run_diagnostics():
    """运行所有诊断测试"""
    print("=" * 80)
    print("🔧 连接诊断工具")
    print(f"时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 80)
    
    results = []
    
    # 1. 环境配置检查
    results.append(check_environment_config())
    
    # 2. Redis 检查
    results.append(check_redis_connection())
    
    # 3. Polymarket API 检查
    results.append(await check_polymarket_api())
    results.append(await check_clob_api())
    
    # 4. Coinbase API 检查
    results.append(await check_coinbase_api())
    
    # 5. 网络稳定性检查
    results.append(check_network_stability())
    
    # 总结
    print("\n" + "=" * 80)
    print("📋 诊断总结")
    print("=" * 80)
    
    ok_count = sum(1 for r in results if r.get("status") == "OK")
    failed_count = sum(1 for r in results if r.get("status") == "FAILED")
    
    print(f"\n✅ 通过: {ok_count}")
    print(f"❌ 失败: {failed_count}")
    
    if failed_count > 0:
        print("\n⚠️  建议操作:")
        
        for result in results:
            if result.get("status") == "FAILED":
                service = result.get("service") or result.get("test")
                error = result.get("error", "未知错误")
                
                print(f"\n  {service}:")
                print(f"    错误: {error}")
                
                # 给出具体建议
                if "Redis" in service:
                    print("    建议:")
                    print("      - 检查 Redis 服务是否运行: redis-cli ping")
                    print("      - 检查 .env 中的 REDIS_HOST 和 REDIS_PORT")
                    print("      - 检查防火墙设置")
                
                elif "Polymarket" in service:
                    print("    建议:")
                    print("      - 检查网络连接")
                    print("      - 检查是否被限流（降低请求频率）")
                    print("      - 使用 VPN 或代理")
                
                elif "Environment" in service:
                    print("    建议:")
                    print("      - 检查 .env 文件是否存在")
                    print("      - 确保所有必需的环境变量都已设置")
    
    print("\n" + "=" * 80)
    
    return results


if __name__ == "__main__":
    asyncio.run(run_diagnostics())
