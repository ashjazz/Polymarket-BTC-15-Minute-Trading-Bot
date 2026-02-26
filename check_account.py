"""
检查 Polymarket 账户信息
"""
import os
import asyncio
from dotenv import load_dotenv
from web3 import Web3

load_dotenv()

async def check_account():
    print("=" * 60)
    print("POLYMARKET 账户信息检查")
    print("=" * 60)

    # 1. 检查环境变量
    pk = os.getenv("POLYMARKET_PK")
    api_key = os.getenv("POLYMARKET_API_KEY")
    api_secret = os.getenv("POLYMARKET_API_SECRET")
    passphrase = os.getenv("POLYMARKET_PASSPHRASE")
    funder = os.getenv("POLYMARKET_FUNDER")

    print("\n📋 环境变量检查:")
    print(f"  POLYMARKET_PK: {'✅ 已设置' if pk else '❌ 未设置'} ({len(pk)} chars)" if pk else "  POLYMARKET_PK: ❌ 未设置")
    print(f"  POLYMARKET_API_KEY: {'✅ 已设置' if api_key else '❌ 未设置'}")
    print(f"  POLYMARKET_API_SECRET: {'✅ 已设置' if api_secret else '❌ 未设置'}")
    print(f"  POLYMARKET_PASSPHRASE: {'✅ 已设置' if passphrase else '❌ 未设置'}")
    print(f"  POLYMARKET_FUNDER: {funder if funder else '未设置'}")

    # 2. 从私钥推导钱包地址
    if pk:
        try:
            w3 = Web3()
            account = w3.eth.account.from_key(pk)
            wallet_address = account.address
            print(f"\n🔐 钱包信息:")
            print(f"  钱包地址: {wallet_address}")
            print(f"  Funder地址: {funder}")
        except Exception as e:
            print(f"\n❌ 私钥解析失败: {e}")
            return

    # 3. 尝试连接 Polymarket CLOB
    print("\n🔗 连接 Polymarket CLOB...")
    try:
        from py_clob_client.client import ClobClient
        from py_clob_client.clob_types import ApiCreds

        host = "https://clob.polymarket.com"
        chain_id = 137  # Polygon mainnet

        # 创建 API 凭证对象
        creds = ApiCreds(
            api_key=api_key,
            api_secret=api_secret,
            api_passphrase=passphrase,
        )

        client = ClobClient(
            host=host,
            key=pk,
            chain_id=chain_id,
            creds=creds,
            signature_type=1,
        )

        print(f"  ✅ 客户端初始化成功")

        # 4. 获取服务器时间 (测试连接)
        print("\n⏰ 服务器状态:")
        try:
            server_time = client.get_server_time()
            print(f"  服务器时间: {server_time}")
        except Exception as e:
            print(f"  ⚠️ 获取服务器时间失败: {e}")

        # 5. 获取余额
        print("\n💰 账户余额:")
        try:
            balances = client.get_balances()
            if balances:
                for token, amount in balances.items():
                    print(f"  {token}: {amount}")
            else:
                print("  无余额数据")
        except Exception as e:
            print(f"  ⚠️ 获取余额失败: {e}")

        # 6. 获取订单
        print("\n📝 订单状态:")
        try:
            orders = client.get_orders()
            if orders:
                live_orders = [o for o in orders if o.get('status') == 'live']
                filled_orders = [o for o in orders if o.get('status') == 'filled']
                print(f"  活跃订单: {len(live_orders)}")
                print(f"  已成交订单: {len(filled_orders)}")
                print(f"  总订单数: {len(orders)}")
            else:
                print("  无订单数据")
        except Exception as e:
            print(f"  ⚠️ 获取订单失败: {e}")

        # 7. 获取交易历史
        print("\n📊 交易历史:")
        try:
            trades = client.get_trades()
            if trades:
                print(f"  总交易数: {len(trades)}")
                if trades:
                    print(f"  最近交易:")
                    for trade in trades[:3]:
                        print(f"    - {trade.get('asset_id', 'N/A')[:20]}... | "
                              f"{trade.get('side', 'N/A')} | "
                              f"${float(trade.get('price', 0)):.4f}")
            else:
                print("  无交易记录")
        except Exception as e:
            print(f"  ⚠️ 获取交易历史失败: {e}")

        # 8. 获取 API 密钥列表
        print("\n🔑 API 密钥:")
        try:
            api_keys = client.get_api_keys()
            if api_keys:
                print(f"  已注册的 API 密钥数: {len(api_keys)}")
                for key in api_keys[:3]:
                    print(f"    - {key.get('api_key', 'N/A')[:20]}...")
            else:
                print("  无 API 密钥数据")
        except Exception as e:
            print(f"  ⚠️ 获取 API 密钥失败: {e}")

    except Exception as e:
        print(f"  ❌ 连接失败: {e}")
        import traceback
        traceback.print_exc()

    print("\n" + "=" * 60)
    print("检查完成")
    print("=" * 60)

    # 安全提醒
    print("\n⚠️  安全提醒:")
    print("  这些凭证已从 git 历史中泄露!")
    print("  请立即:")
    print("  1. 转移钱包中的所有资金到新地址")
    print("  2. 在 Polymarket 网站上重新生成 API 密钥")
    print("  3. 清理 git 历史或删除仓库重新创建")


if __name__ == "__main__":
    asyncio.run(check_account())
