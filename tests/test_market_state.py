"""
MarketState 单元测试
"""
import pytest
from decimal import Decimal
from datetime import datetime, timezone, timedelta
from strategy.market_state import MarketState, TokenPrice
from strategy.position import Position, PositionDirection


class TestTokenPrice:
    """TokenPrice 测试类"""

    def test_from_quote_tick(self):
        """测试从报价创建"""
        price = TokenPrice.from_quote_tick(
            bid=Decimal("0.29"),
            ask=Decimal("0.31"),
        )

        assert price.bid == Decimal("0.29")
        assert price.ask == Decimal("0.31")
        assert price.mid == Decimal("0.30")
        assert price.timestamp is not None

    def test_spread_calculation(self):
        """测试价差计算"""
        price = TokenPrice.from_quote_tick(
            bid=Decimal("0.28"),
            ask=Decimal("0.32"),
        )

        assert price.spread == Decimal("0.04")
        # 价差百分比 = 0.04 / 0.30 * 100 = 13.33%
        expected_spread_pct = Decimal("0.04") / Decimal("0.30") * 100
        assert abs(price.spread_percent - expected_spread_pct) < Decimal("0.1")


class TestMarketState:
    """MarketState 测试类"""

    @pytest.fixture
    def sample_market(self):
        """创建示例市场状态"""
        now = datetime.now(timezone.utc)
        return MarketState(
            market_slug="btc-updown-15m-1709251200",
            market_start_time=now,
            market_end_time=now + timedelta(minutes=15),
        )

    def test_market_creation(self, sample_market):
        """测试市场状态创建"""
        assert sample_market.market_slug == "btc-updown-15m-1709251200"
        assert sample_market.yes_price is None
        assert sample_market.no_price is None
        assert sample_market.current_position is None
        assert sample_market.has_position is False

    def test_minutes_since_open(self, sample_market):
        """测试市场开盘时间计算"""
        # 市场刚开盘
        assert 0 <= sample_market.minutes_since_open < 0.1

    def test_update_prices(self, sample_market):
        """测试更新价格"""
        sample_market.update_yes_price(Decimal("0.70"), Decimal("0.72"))
        sample_market.update_no_price(Decimal("0.28"), Decimal("0.30"))

        assert sample_market.yes_price is not None
        assert sample_market.yes_price.mid == Decimal("0.71")
        assert sample_market.no_price is not None
        assert sample_market.no_price.mid == Decimal("0.29")

    def test_is_active(self, sample_market):
        """测试市场活跃状态"""
        assert sample_market.is_active is True

        # 创建已结束的市场
        ended_market = MarketState(
            market_slug="ended",
            market_start_time=datetime.now(timezone.utc) - timedelta(minutes=20),
            market_end_time=datetime.now(timezone.utc) - timedelta(minutes=5),
        )
        assert ended_market.is_active is False

    def test_has_position(self, sample_market):
        """测试持仓状态"""
        assert sample_market.has_position is False

        # 添加持仓
        sample_market.current_position = Position(
            market_slug="btc-updown-15m-1709251200",
            direction=PositionDirection.UP,
            entry_price=Decimal("0.30"),
            entry_time=datetime.now(timezone.utc),
            size_usd=Decimal("2.0"),
        )
        assert sample_market.has_position is True

    def test_checkpoint_management(self, sample_market):
        """测试检查点管理"""
        assert sample_market.tp1_checked is False
        assert sample_market.tp2_checked is False
        assert sample_market.tp3_checked is False

        # 标记检查点
        sample_market.mark_checkpoint_checked(1)
        assert sample_market.tp1_checked is True
        assert sample_market.is_checkpoint_checked(1) is True

        sample_market.mark_checkpoint_checked(2)
        assert sample_market.tp2_checked is True

        # 重置
        sample_market.reset_checkpoints()
        assert sample_market.tp1_checked is False
        assert sample_market.tp2_checked is False

    def test_to_dict(self, sample_market):
        """测试序列化"""
        sample_market.update_yes_price(Decimal("0.70"), Decimal("0.72"))

        data = sample_market.to_dict()

        assert data["market_slug"] == "btc-updown-15m-1709251200"
        assert data["yes_price"]["mid"] == "0.71"
        assert data["current_position"] is None
        assert "checkpoints" in data
