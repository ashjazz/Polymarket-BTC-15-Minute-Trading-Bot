"""
入场逻辑单元测试
"""
import pytest
from decimal import Decimal
from datetime import datetime, timezone, timedelta
from unittest.mock import MagicMock

from strategy.config import StrategyConfig
from strategy.entry_logic import check_entry, EntrySignal, should_skip_entry
from strategy.market_state import MarketState, TokenPrice
from strategy.position import Position, PositionDirection


class TestCheckEntry:
    """check_entry 测试类"""

    @pytest.fixture
    def config(self):
        """默认配置"""
        return StrategyConfig()

    @pytest.fixture
    def market_state(self):
        """创建市场状态（开盘后2分钟）"""
        now = datetime.now(timezone.utc)
        return MarketState(
            market_slug="btc-updown-15m-test",
            market_start_time=now - timedelta(minutes=2),
            market_end_time=now + timedelta(minutes=13),
        )

    def test_entry_yes_in_range(self, config, market_state):
        """测试 YES 价格在入场区间内触发"""
        yes_price = TokenPrice.from_quote_tick(Decimal("0.29"), Decimal("0.31"))  # mid=0.30
        no_price = TokenPrice.from_quote_tick(Decimal("0.69"), Decimal("0.71"))   # mid=0.70

        signal = check_entry(yes_price, no_price, config, market_state)

        assert signal is not None
        assert signal.direction == PositionDirection.UP
        assert signal.token_type == "YES"
        assert config.entry_price_low <= signal.price <= config.entry_price_high

    def test_entry_no_in_range(self, config, market_state):
        """测试 NO 价格在入场区间内触发"""
        yes_price = TokenPrice.from_quote_tick(Decimal("0.69"), Decimal("0.71"))   # mid=0.70
        no_price = TokenPrice.from_quote_tick(Decimal("0.29"), Decimal("0.31"))   # mid=0.30

        signal = check_entry(yes_price, no_price, config, market_state)

        assert signal is not None
        assert signal.direction == PositionDirection.DOWN
        assert signal.token_type == "NO"

    def test_no_entry_outside_range(self, config, market_state):
        """测试价格不在入场区间内不触发"""
        yes_price = TokenPrice.from_quote_tick(Decimal("0.69"), Decimal("0.71"))   # mid=0.70
        no_price = TokenPrice.from_quote_tick(Decimal("0.69"), Decimal("0.71"))   # mid=0.70

        signal = check_entry(yes_price, no_price, config, market_state)

        assert signal is None

    def test_no_entry_with_existing_position(self, config, market_state):
        """测试已有持仓时不触发"""
        # 添加持仓
        market_state.current_position = Position(
            market_slug="btc-updown-15m-test",
            direction=PositionDirection.UP,
            entry_price=Decimal("0.30"),
            entry_time=datetime.now(timezone.utc),
            size_usd=Decimal("2.0"),
        )

        yes_price = TokenPrice.from_quote_tick(Decimal("0.29"), Decimal("0.31"))

        signal = check_entry(yes_price, None, config, market_state)

        assert signal is None

    def test_no_entry_outside_window(self, config):
        """测试超出买入窗口不触发"""
        # 市场开盘10分钟（超出默认8分钟窗口）
        now = datetime.now(timezone.utc)
        market_state = MarketState(
            market_slug="test",
            market_start_time=now - timedelta(minutes=10),
            market_end_time=now + timedelta(minutes=5),
        )

        yes_price = TokenPrice.from_quote_tick(Decimal("0.29"), Decimal("0.31"))

        signal = check_entry(yes_price, None, config, market_state)

        assert signal is None

    def test_entry_with_custom_config(self, market_state):
        """测试自定义配置"""
        config = StrategyConfig(
            entry_price_low=Decimal("0.25"),
            entry_price_high=Decimal("0.35"),
            buy_window_minutes=10,
        )

        # 价格 0.26 在自定义区间 [0.25, 0.35] 内
        yes_price = TokenPrice.from_quote_tick(Decimal("0.25"), Decimal("0.27"))

        signal = check_entry(yes_price, None, config, market_state)

        assert signal is not None


class TestShouldSkipEntry:
    """should_skip_entry 测试类"""

    @pytest.fixture
    def config(self):
        return StrategyConfig()

    @pytest.fixture
    def market_state(self):
        now = datetime.now(timezone.utc)
        return MarketState(
            market_slug="test",
            market_start_time=now,
            market_end_time=now + timedelta(minutes=15),
        )

    def test_skip_with_position(self, config, market_state):
        """测试有持仓时跳过"""
        market_state.current_position = Position(
            market_slug="test",
            direction=PositionDirection.UP,
            entry_price=Decimal("0.30"),
            entry_time=datetime.now(timezone.utc),
            size_usd=Decimal("2.0"),
        )

        should_skip, reason = should_skip_entry(market_state, config)

        assert should_skip is True
        assert "position" in reason.lower()

    def test_skip_outside_window(self, config):
        """测试超出窗口时跳过"""
        now = datetime.now(timezone.utc)
        market_state = MarketState(
            market_slug="test",
            market_start_time=now - timedelta(minutes=10),
            market_end_time=now + timedelta(minutes=5),
        )

        should_skip, reason = should_skip_entry(market_state, config)

        assert should_skip is True
        assert "window" in reason.lower()

    def test_no_skip_ok_to_check(self, config, market_state):
        """测试可以检查入场"""
        should_skip, reason = should_skip_entry(market_state, config)

        assert should_skip is False
        assert reason == "OK to check entry"
