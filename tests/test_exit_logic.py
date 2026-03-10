"""
出场逻辑单元测试
"""
import pytest
from decimal import Decimal
from datetime import datetime, timezone, timedelta

from strategy.config import StrategyConfig
from strategy.exit_logic import (
    check_exit,
    check_take_profit,
    check_stop_loss,
    ExitSignal,
    get_next_checkpoint,
)
from strategy.market_state import MarketState
from strategy.position import Position, PositionStatus, PositionDirection


class TestCheckStopLoss:
    """check_stop_loss 测试类"""

    @pytest.fixture
    def config(self):
        return StrategyConfig()

    @pytest.fixture
    def position(self):
        return Position(
            market_slug="test",
            direction=PositionDirection.UP,
            entry_price=Decimal("0.30"),
            entry_time=datetime.now(timezone.utc),
            size_usd=Decimal("2.0"),
        )

    def test_stop_loss_triggered(self, config, position):
        """测试止损触发"""
        signal = check_stop_loss(position, Decimal("0.19"), config)

        assert signal is not None
        assert signal.exit_status == PositionStatus.CLOSED_SL
        assert signal.checkpoint == 0

    def test_stop_loss_at_threshold(self, config, position):
        """测试价格等于止损线时触发"""
        signal = check_stop_loss(position, Decimal("0.20"), config)

        assert signal is not None
        assert signal.exit_status == PositionStatus.CLOSED_SL

    def test_no_stop_loss_above_threshold(self, config, position):
        """测试价格高于止损线不触发"""
        signal = check_stop_loss(position, Decimal("0.25"), config)

        assert signal is None


class TestCheckTakeProfit:
    """check_take_profit 测试类"""

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

    def test_tp1_triggered(self, config, market_state):
        """测试 TP1 触发"""
        # 创建 2 分钟前的持仓
        entry_time = datetime.now(timezone.utc) - timedelta(minutes=2.5)
        position = Position(
            market_slug="test",
            direction=PositionDirection.UP,
            entry_price=Decimal("0.30"),
            entry_time=entry_time,
            size_usd=Decimal("2.0"),
        )

        signal = check_take_profit(position, config, market_state, Decimal("0.42"))

        assert signal is not None
        assert signal.exit_status == PositionStatus.CLOSED_TP1
        assert signal.checkpoint == 1

    def test_tp1_not_reached(self, config, market_state):
        """测试 TP1 价格未达标"""
        entry_time = datetime.now(timezone.utc) - timedelta(minutes=2.5)
        position = Position(
            market_slug="test",
            direction=PositionDirection.UP,
            entry_price=Decimal("0.30"),
            entry_time=entry_time,
            size_usd=Decimal("2.0"),
        )

        signal = check_take_profit(position, config, market_state, Decimal("0.38"))

        assert signal is None
        assert market_state.tp1_checked is True  # 检查点已标记

    def test_tp2_triggered_at_4min(self, config, market_state):
        """测试 TP2 在 4 分钟时触发"""
        # 创建 4 分钟前的持仓
        entry_time = datetime.now(timezone.utc) - timedelta(minutes=4)
        position = Position(
            market_slug="test",
            direction=PositionDirection.UP,
            entry_price=Decimal("0.30"),
            entry_time=entry_time,
            size_usd=Decimal("2.0"),
        )

        # 标记 TP1 为已检查
        market_state.mark_checkpoint_checked(1)

        # 直接检查 TP2（价格 0.50 >= 目标 0.48，应该触发）
        signal = check_take_profit(position, config, market_state, Decimal("0.50"))
        assert signal is not None
        assert signal.exit_status == PositionStatus.CLOSED_TP2

    def test_all_checkpoints_checked(self, config, market_state):
        """测试所有检查点都被标记"""
        entry_time = datetime.now(timezone.utc) - timedelta(minutes=7)
        position = Position(
            market_slug="test",
            direction=PositionDirection.UP,
            entry_price=Decimal("0.30"),
            entry_time=entry_time,
            size_usd=Decimal("2.0"),
        )

        # 价格未达标
        signal = check_take_profit(position, config, market_state, Decimal("0.35"))

        assert signal is None
        assert market_state.tp1_checked is True
        assert market_state.tp2_checked is True
        assert market_state.tp3_checked is True


class TestCheckExit:
    """check_exit 测试类"""

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

    def test_stop_loss_priority(self, config, market_state):
        """测试止损优先级高于止盈"""
        entry_time = datetime.now(timezone.utc) - timedelta(minutes=2)
        position = Position(
            market_slug="test",
            direction=PositionDirection.UP,
            entry_price=Decimal("0.30"),
            entry_time=entry_time,
            size_usd=Decimal("2.0"),
        )

        # 价格同时满足止损和 TP1 条件时，止损优先
        signal = check_exit(position, Decimal("0.19"), config, market_state)

        assert signal is not None
        assert signal.exit_status == PositionStatus.CLOSED_SL

    def test_closed_position_no_signal(self, config, market_state):
        """测试已平仓的持仓不产生信号"""
        position = Position(
            market_slug="test",
            direction=PositionDirection.UP,
            entry_price=Decimal("0.30"),
            entry_time=datetime.now(timezone.utc),
            size_usd=Decimal("2.0"),
            status=PositionStatus.CLOSED_TP1,
        )

        signal = check_exit(position, Decimal("0.19"), config, market_state)

        assert signal is None


class TestGetNextCheckpoint:
    """get_next_checkpoint 测试类"""

    @pytest.fixture
    def market_state(self):
        now = datetime.now(timezone.utc)
        return MarketState(
            market_slug="test",
            market_start_time=now,
            market_end_time=now + timedelta(minutes=15),
        )

    def test_first_checkpoint(self, market_state):
        """测试第一个检查点"""
        assert get_next_checkpoint(market_state) == 1

    def test_second_checkpoint(self, market_state):
        """测试第二个检查点"""
        market_state.tp1_checked = True
        assert get_next_checkpoint(market_state) == 2

    def test_third_checkpoint(self, market_state):
        """测试第三个检查点"""
        market_state.tp1_checked = True
        market_state.tp2_checked = True
        assert get_next_checkpoint(market_state) == 3

    def test_all_checked(self, market_state):
        """测试所有检查点已检查"""
        market_state.tp1_checked = True
        market_state.tp2_checked = True
        market_state.tp3_checked = True
        assert get_next_checkpoint(market_state) == 0
