"""
查询 Polymarket 钱包余额
"""
import os
import sys
from pathlib import Path
from web3 import Web3
from dotenv import load_dotenv

# 加载 .env
env_path = Path(__file__).parent / ".env"
load_dotenv(env_path)

pk = os.getenv("POLYMARKET_PK")
api_key = os.getenv("POLYMARKET_API_KEY")
api_secret = os.getenv("POLYMARKET_API_SECRET")
passphrase = os.getenv("POLYMARKET_PASSPHRASE")

# 钱包地址
w3 = Web3()
account = w3.eth.account.from_key(pk)
wallet_address = account.address

print("=" * 60)
print("POLYMARKET 钱包余额查询")
print("=" * 60)
print(f"\n🔐 钱包地址: {wallet_address}")

# 1. 通过 Polygon RPC 查询 USDC 余额
print("\n💰 Polygon 链上资产:")

# Polygon RPC
polygon_rpc = "https://polygon-rpc.com"
w3_polygon = Web3(Web3.HTTPProvider(polygon_rpc))

if not w3_polygon.is_connected():
    print("  ❌ 无法连接到 Polygon 网络")
else:
    print("  ✅ 已连接到 Polygon 网络")

    # USDC 合约地址 (Polygon)
    usdc_address = "0x2791Bca1f2de4661ED88A30C99A7a9449Aa84174"

    # ERC20 ABI (简化版)
    erc20_abi = '''
    [
        {"constant":true,"inputs":[{"name":"_owner","type":"address"}],"name":"balanceOf","outputs":[{"name":"balance","type":"uint256"}],"type":"function"},
        {"constant":true,"inputs":[],"name":"decimals","outputs":[{"name":"","type":"uint8"}],"type":"function"},
        {"constant":true,"inputs":[],"name":"symbol","outputs":[{"name":"","type":"string"}],"type":"function"}
    ]
    '''

    usdc_contract = w3_polygon.eth.contract(
        address=Web3.to_checksum_address(usdc_address),
        abi=erc20_abi
    )

    try:
        decimals = usdc_contract.functions.decimals().call()
        balance_raw = usdc_contract.functions.balanceOf(wallet_address).call()
        balance_usdc = balance_raw / (10 ** decimals)
        print(f"  USDC: ${balance_usdc:,.2f}")
    except Exception as e:
        print(f"  USDC 查询失败: {e}")

    # 2. 查询 Polygon POL (原 MATIC) 余额
    try:
        pol_balance = w3_polygon.eth.get_balance(wallet_address)
        pol_balance_formatted = w3_polygon.from_wei(pol_balance, 'ether')
        print(f"  POL: {pol_balance_formatted:.6f}")
    except Exception as e:
        print(f"  POL 查询失败: {e}")

# 3. 通过 Polymarket API 查询
print("\n📊 Polymarket 交易账户:")
try:
    from py_clob_client.client import ClobClient
    from py_clob_client.clob_types import ApiCreds

    creds = ApiCreds(
        api_key=api_key,
        api_secret=api_secret,
        api_passphrase=passphrase,
    )

    client = ClobClient(
        host="https://clob.polymarket.com",
        key=pk,
        chain_id=137,
        creds=creds,
        signature_type=1,
    )

    # 获取交易记录
    trades = client.get_trades()
    print(f"  总交易数: {len(trades)}")

    # 计算交易统计
    if trades:
        buy_trades = [t for t in trades if t.get('side') == 'BUY']
        sell_trades = [t for t in trades if t.get('side') == 'SELL']
        print(f"  买入: {len(buy_trades)} 笔")
        print(f"  卖出: {len(sell_trades)} 笔")

        # 最近交易
        print(f"\n  最近 5 笔交易:")
        for trade in trades[:5]:
            asset_id = trade.get('asset_id', 'N/A')
            side = trade.get('side', 'N/A')
            price = float(trade.get('price', 0))
            size = float(trade.get('size', 0))
            print(f"    {side}: {size:.2f} @ ${price:.4f}")

    # 获取订单
    orders = client.get_orders()
    active_orders = [o for o in orders if o.get('status') == 'live'] if orders else []
    print(f"\n  活跃订单: {len(active_orders)}")

    # 获取 API 密钥信息
    api_keys = client.get_api_keys()
    print(f"  API 密钥: {len(api_keys) if api_keys else 0} 个")

except Exception as e:
    print(f"  API 连接失败: {e}")
    import traceback
    traceback.print_exc()

print("\n" + "=" * 60)
