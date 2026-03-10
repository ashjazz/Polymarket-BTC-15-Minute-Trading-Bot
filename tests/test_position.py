"""
Position 单元测试
"""
import pytest
from decimal import Decimal
from datetime import datetime, timezone, timedelta
from strategy.position import Position, PositionStatus, PositionDirection


class TestPosition:
    """Position 测试类"""

    @pytest.fixture
    def sample_position(self):
        """创建示例持仓"""
        return Position(
            market_slug="btc-updown-15m-1709251200",
            direction=PositionDirection.UP,
            entry_price=Decimal("0.30"),
            entry_time=datetime.now(timezone.utc) - timedelta(minutes=2),
            size_usd=Decimal("2.0"),
        )

    def test_position_creation(self, sample_position):
        """测试持仓创建"""
        assert sample_position.market_slug == "btc-updown-15m-1709251200"
        assert sample_position.direction == PositionDirection.UP
        assert sample_position.entry_price == Decimal("0.30")
        assert sample_position.size_usd == Decimal("2.0")
        assert sample_position.status == PositionStatus.OPEN
        assert sample_position.is_open is True

    def test_holding_minutes(self, sample_position):
        """测试持有时间计算"""
        # 持仓创建于 2 分钟前
        assert 1.9 < sample_position.holding_minutes < 2.1

    def test_close_position(self, sample_position):
        """测试平仓"""
        exit_time = datetime.now(timezone.utc)
        sample_position.close(
            exit_price=Decimal("0.40"),
            exit_time=exit_time,
            reason="TP1 triggered",
            status=PositionStatus.CLOSED_TP1,
        )

        assert sample_position.status == PositionStatus.CLOSED_TP1
        assert sample_position.is_open is False
        assert sample_position.exit_price == Decimal("0.40")
        assert sample_position.exit_reason == "TP1 triggered"

    def test_pnl_calculation(self, sample_position):
        """测试盈亏计算"""
        # 先平仓
        sample_position.close(
            exit_price=Decimal("0.40"),
            exit_time=datetime.now(timezone.utc),
            reason="TP1",
            status=PositionStatus.CLOSED_TP1,
        )

        # 盈亏 = (0.40 - 0.30) / 0.30 * 2.0 = 0.666...
        expected_pnl = (Decimal("0.40") - Decimal("0.30")) / Decimal("0.30") * Decimal("2.0")
        assert abs(sample_position.pnl - expected_pnl) < Decimal("0.01")

        # 盈亏百分比 = (0.40 - 0.30) / 0.30 * 100 = 33.33%
        expected_pnl_pct = (Decimal("0.40") - Decimal("0.30")) / Decimal("0.30") * 100
        assert abs(sample_position.pnl_percent - expected_pnl_pct) < Decimal("0.1")

    def test_loss_pnl_calculation(self, sample_position):
        """测试亏损计算"""
        sample_position.close(
            exit_price=Decimal("0.20"),
            exit_time=datetime.now(timezone.utc),
            reason="Stop loss",
            status=PositionStatus.CLOSED_SL,
        )

        # 亏损 = (0.20 - 0.30) / 0.30 * 2.0 = -0.666...
        assert sample_position.pnl < 0
        assert sample_position.pnl_percent < 0

    def test_unrealized_pnl(self, sample_position):
        """测试未实现盈亏"""
        # 当前价格 0.45
        unrealized = sample_position.unrealized_pnl(Decimal("0.45"))
        expected = (Decimal("0.45") - Decimal("0.30")) / Decimal("0.30") * Decimal("2.0")
        assert abs(unrealized - expected) < Decimal("0.01")

    def test_to_dict(self, sample_position):
        """测试序列化"""
        data = sample_position.to_dict()

        assert data["market_slug"] == "btc-updown-15m-1709251200"
        assert data["direction"] == "UP"
        assert data["entry_price"] == "0.30"
        assert data["status"] == "OPEN"
        assert data["exit_price"] is None

    def test_from_dict(self):
        """测试反序列化"""
        data = {
            "market_slug": "btc-updown-15m-1709251200",
            "direction": "UP",
            "entry_price": "0.30",
            "entry_time": "2026-03-10T00:00:00+00:00",
            "size_usd": "2.0",
            "status": "CLOSED_TP1",
            "exit_price": "0.40",
            "exit_time": "2026-03-10T00:02:00+00:00",
            "exit_reason": "TP1 triggered",
        }

        position = Position.from_dict(data)

        assert position.market_slug == "btc-updown-15m-1709251200"
        assert position.direction == PositionDirection.UP
        assert position.entry_price == Decimal("0.30")
        assert position.status == PositionStatus.CLOSED_TP1
        assert position.exit_price == Decimal("0.40")

    def test_position_directions(self):
        """测试持仓方向"""
        up_position = Position(
            market_slug="test",
            direction=PositionDirection.UP,
            entry_price=Decimal("0.30"),
            entry_time=datetime.now(timezone.utc),
            size_usd=Decimal("2.0"),
        )
        assert up_position.direction == PositionDirection.UP

        down_position = Position(
            market_slug="test",
            direction=PositionDirection.DOWN,
            entry_price=Decimal("0.30"),
            entry_time=datetime.now(timezone.utc),
            size_usd=Decimal("2.0"),
        )
        assert down_position.direction == PositionDirection.DOWN
