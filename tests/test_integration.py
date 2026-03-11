"""
集成测试 - 测试完整的策略流程
"""
import pytest
from decimal import Decimal
from datetime import datetime, timezone, timedelta

from strategy.config import StrategyConfig
from strategy.position import Position, PositionDirection, PositionStatus
from strategy.market_state import MarketState, TokenPrice
from strategy.entry_logic import check_entry
from strategy.exit_logic import check_exit


class TestFullStrategyFlow:
    """完整策略流程测试"""

    @pytest.fixture
    def config(self):
        return StrategyConfig()

    def test_full_win_scenario(self, config):
        """测试完整盈利场景"""
        # 1. 创建市场
        now = datetime.now(timezone.utc)
        market = MarketState(
            market_slug="test-market",
            market_start_time=now,
            market_end_time=now + timedelta(minutes=15),
        )

        # 2. 价格进入入场区间
        yes_price = TokenPrice.from_quote_tick(Decimal("0.70"), Decimal("0.72"))
        no_price = TokenPrice.from_quote_tick(Decimal("0.29"), Decimal("0.31"))

        # 3. 检查入场
        entry_signal = check_entry(yes_price, no_price, config, market)
        assert entry_signal is not None
        assert entry_signal.direction == PositionDirection.DOWN

        # 4. 创建持仓
        position = Position(
            market_slug="test-market",
            direction=entry_signal.direction,
            entry_price=entry_signal.price,
            entry_time=now,
            size_usd=config.position_size_usd,
        )
        market.current_position = position

        # 5. 模拟价格上涨到 TP3（最低目标价 0.45）
        current_price = Decimal("0.45")

        # 6. 检查出场
        exit_signal = check_exit(position, current_price, config, market)
        assert exit_signal is not None
        assert exit_signal.exit_status == PositionStatus.CLOSED_TP3

        # 7. 平仓
        position.close(
            exit_price=exit_signal.exit_price,
            exit_time=now,
            reason=exit_signal.reason,
            status=exit_signal.exit_status,
        )

        # 8. 验证盈利
        assert position.pnl > 0
        assert position.pnl_percent > 0

    def test_full_win_high_price_scenario(self, config):
        """测试高价格优先止盈场景"""
        # 1. 创建市场和持仓
        now = datetime.now(timezone.utc)
        market = MarketState(
            market_slug="test-market",
            market_start_time=now,
            market_end_time=now + timedelta(minutes=15),
        )

        position = Position(
            market_slug="test-market",
            direction=PositionDirection.DOWN,
            entry_price=Decimal("0.30"),
            entry_time=now,
            size_usd=config.position_size_usd,
        )
        market.current_position = position

        # 2. 价格上涨到 0.58（超过最高目标价 0.55）
        current_price = Decimal("0.58")

        # 3. 检查出场 - 应该触发 TP1（最高目标价）
        exit_signal = check_exit(position, current_price, config, market)
        assert exit_signal is not None
        assert exit_signal.exit_status == PositionStatus.CLOSED_TP1
        assert exit_signal.level == 1

        # 4. 验证盈利更高
        position.close(
            exit_price=exit_signal.exit_price,
            exit_time=now,
            reason=exit_signal.reason,
            status=exit_signal.exit_status,
        )
        assert position.pnl > 0

    def test_full_loss_scenario(self, config):
        """测试完整亏损场景（止损）"""
        # 1. 创建市场和持仓
        now = datetime.now(timezone.utc)
        market = MarketState(
            market_slug="test-market",
            market_start_time=now,
            market_end_time=now + timedelta(minutes=15),
        )

        position = Position(
            market_slug="test-market",
            direction=PositionDirection.UP,
            entry_price=Decimal("0.30"),
            entry_time=now,
            size_usd=config.position_size_usd,
        )
        market.current_position = position

        # 2. 价格下跌触发止损
        current_price = Decimal("0.19")

        # 3. 检查出场
        exit_signal = check_exit(position, current_price, config, market)
        assert exit_signal is not None
        assert exit_signal.exit_status == PositionStatus.CLOSED_SL

        # 4. 平仓
        position.close(
            exit_price=exit_signal.exit_price,
            exit_time=now,
            reason=exit_signal.reason,
            status=exit_signal.exit_status,
        )

        # 5. 验证亏损
        assert position.pnl < 0
        assert position.pnl_percent < 0

    def test_no_entry_outside_window(self, config):
        """测试超出窗口不入场"""
        # 市场已开盘 10 分钟（超出默认 8 分钟窗口）
        now = datetime.now(timezone.utc)
        market = MarketState(
            market_slug="test-market",
            market_start_time=now - timedelta(minutes=10),
            market_end_time=now + timedelta(minutes=5),
        )

        # 价格在入场区间
        yes_price = TokenPrice.from_quote_tick(Decimal("0.29"), Decimal("0.31"))

        # 不应触发入场
        entry_signal = check_entry(yes_price, None, config, market)
        assert entry_signal is None

    def test_real_time_price_monitoring(self, config):
        """测试实时价格监控 - 不依赖时间检查点"""
        # 1. 创建市场和持仓
        now = datetime.now(timezone.utc)
        market = MarketState(
            market_slug="test-market",
            market_start_time=now,
            market_end_time=now + timedelta(minutes=15),
        )

        position = Position(
            market_slug="test-market",
            direction=PositionDirection.DOWN,
            entry_price=Decimal("0.30"),
            entry_time=now,
            size_usd=config.position_size_usd,
        )
        market.current_position = position

        # 2. 价格立即上涨到 0.55（不需要等待时间检查点）
        current_price = Decimal("0.55")

        # 3. 检查出场 - 应该立即触发，不需要等待
        exit_signal = check_exit(position, current_price, config, market)
        assert exit_signal is not None
        assert exit_signal.exit_status == PositionStatus.CLOSED_TP1
