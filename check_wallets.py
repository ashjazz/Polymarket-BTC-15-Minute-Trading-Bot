"""
全面查询 Polymarket 双钱包余额
"""
import os
import sys
from pathlib import Path
from web3 import Web3
from dotenv import load_dotenv
import requests

# 加载 .env
env_path = Path(__file__).parent / ".env"
load_dotenv(env_path)

pk = os.getenv("POLYMARKET_PK")
funder = os.getenv("POLYMARKET_FUNDER")
api_key = os.getenv("POLYMARKET_API_KEY")

# 从私钥派生地址
w3 = Web3()
account = w3.eth.account.from_key(pk)
proxy_address = account.address

print("=" * 70)
print("POLYMARKET 双钱包余额查询")
print("=" * 70)

print("\n📋 配置信息:")
print(f"  POLYMARKET_FUNDER: {funder}")
print(f"  私钥派生地址:      {proxy_address}")
print(f"  API Key:           {api_key}")

if funder and funder.lower() == proxy_address.lower():
    print("\n  ⚠️  注意: Funder 和 Proxy 地址相同！这可能意味着你使用的是单一钱包模式")
else:
    print(f"\n  📌 双钱包模式: Funder 和 Proxy 是不同的地址")

# Polygon RPC endpoints
rpc_urls = [
    "https://polygon-rpc.com",
    "https://polygon-mainnet.infura.io/v3/9aa3d95b3bc440fa88ea12eaa4456161",
    "https://polygon.llamarpc.com",
]

w3_polygon = None
for rpc in rpc_urls:
    try:
        w3_polygon = Web3(Web3.HTTPProvider(rpc, request_kwargs={'timeout': 10}))
        if w3_polygon.is_connected():
            print(f"\n✅ 已连接到 Polygon 网络: {rpc}")
            break
    except:
        continue

if not w3_polygon or not w3_polygon.is_connected():
    print("\n❌ 无法连接到 Polygon 网络")
    sys.exit(1)

# USDC 合约地址 (Polygon)
usdc_address = "0x2791Bca1f2de4661ED88A30C99A7a9449Aa84174"

# ERC20 ABI
erc20_abi = '''[{"constant":true,"inputs":[{"name":"_owner","type":"address"}],"name":"balanceOf","outputs":[{"name":"balance","type":"uint256"}],"type":"function"},{"constant":true,"inputs":[],"name":"decimals","outputs":[{"name":"","type":"uint8"}],"type":"function"}]'''

usdc_contract = w3_polygon.eth.contract(
    address=Web3.to_checksum_address(usdc_address),
    abi=erc20_abi
)

def query_address(address, name):
    """查询地址余额"""
    print(f"\n{'='*70}")
    print(f"📍 {name}: {address}")
    print("=" * 70)
    
    try:
        # USDC 余额
        decimals = usdc_contract.functions.decimals().call()
        balance_raw = usdc_contract.functions.balanceOf(address).call()
        balance_usdc = balance_raw / (10 ** decimals)
        print(f"  💵 USDC: ${balance_usdc:,.2f}")
    except Exception as e:
        print(f"  ❌ USDC 查询失败: {e}")
    
    try:
        # POL (MATIC) 余额
        pol_balance = w3_polygon.eth.get_balance(address)
        pol_formatted = w3_polygon.from_wei(pol_balance, 'ether')
        print(f"  🔷 POL: {pol_formatted:.6f}")
    except Exception as e:
        print(f"  ❌ POL 查询失败: {e}")
    
    return balance_usdc if 'balance_usdc' in dir() else 0

# 查询两个地址
addresses_to_check = []

# 1. Funder 地址
if funder:
    addresses_to_check.append((funder, "Funder Wallet (资金钱包)"))

# 2. Proxy 地址（从私钥派生）
addresses_to_check.append((proxy_address, "Proxy Wallet (交易钱包，由私钥派生)"))

for addr, name in addresses_to_check:
    query_address(Web3.to_checksum_address(addr), name)

# 通过 Gamma API 查询 Polymarket 账户信息
print(f"\n{'='*70}")
print("📊 Polymarket 账户信息 (Gamma API)")
print("=" * 70)

try:
    # Gamma API 不需要认证，可以查询公开数据
    gamma_url = f"https://gamma-api.polymarket.com/user-positions?address={proxy_address}"
    resp = requests.get(gamma_url, timeout=10)
    
    if resp.status_code == 200:
        positions = resp.json()
        if positions:
            print(f"\n  持仓数量: {len(positions)}")
            for pos in positions[:5]:  # 显示前5个
                market = pos.get('market', 'Unknown')
                size = pos.get('size', 0)
                print(f"    - {market[:30]}... : {size}")
        else:
            print("\n  无持仓")
    else:
        print(f"  API 返回: {resp.status_code}")
except Exception as e:
    print(f"  ❌ Gamma API 查询失败: {e}")

# 查询 Polymarket 余额（通过 CLOB API）
print(f"\n{'='*70}")
print("💰 Polymarket CLOB 余额 (需要有效 API Key)")
print("=" * 70)

try:
    from py_clob_client.client import ClobClient
    from py_clob_client.clob_types import ApiCreds
    
    api_secret = os.getenv("POLYMARKET_API_SECRET")
    passphrase = os.getenv("POLYMARKET_PASSPHRASE")
    
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
    
    # 尝试获取余额
    try:
        balances = client.get_balances()
        print(f"\n  ✅ 余额查询成功:")
        for bal in balances:
            asset = bal.get('asset', 'Unknown')
            amount = float(bal.get('amount', 0))
            print(f"    {asset}: {amount:.2f}")
    except Exception as e:
        print(f"  ❌ get_balances 失败: {e}")
    
    # 获取交易记录
    try:
        trades = client.get_trades()
        print(f"\n  📈 总交易数: {len(trades)}")
    except Exception as e:
        print(f"  ❌ get_trades 失败: {e}")
        
except Exception as e:
    print(f"  ❌ CLOB 连接失败: {e}")
    print("\n  💡 提示: API Key 可能无效或已过期")
    print("     请前往 https://polymarket.com/portfolio 重新生成 API Key")

print("\n" + "=" * 70)
print("查询完成")
print("=" * 70)
