"""
出场逻辑单元测试 - 多目标价止盈策略
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
    get_distance_to_nearest_target,
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
        assert signal.level == 0

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
    """check_take_profit 测试类 - 多目标价策略"""

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

    def test_tp1_highest_triggered(self, config, position):
        """测试最高目标价 TP1 触发"""
        # 价格 0.55 >= 0.55（最高目标价）
        signal = check_take_profit(position, config, Decimal("0.55"))

        assert signal is not None
        assert signal.exit_status == PositionStatus.CLOSED_TP1
        assert signal.level == 1

    def test_tp2_middle_triggered(self, config, position):
        """测试中等目标价 TP2 触发"""
        # 价格 0.50 >= 0.50（中等目标价），但 < 0.55（最高目标价）
        signal = check_take_profit(position, config, Decimal("0.50"))

        assert signal is not None
        assert signal.exit_status == PositionStatus.CLOSED_TP2
        assert signal.level == 2

    def test_tp3_lowest_triggered(self, config, position):
        """测试最低目标价 TP3 触发"""
        # 价格 0.45 >= 0.45（最低目标价），但 < 0.50（中等目标价）
        signal = check_take_profit(position, config, Decimal("0.45"))

        assert signal is not None
        assert signal.exit_status == PositionStatus.CLOSED_TP3
        assert signal.level == 3

    def test_price_between_targets(self, config, position):
        """测试价格在目标价之间触发最低目标价"""
        # 价格 0.47 在 0.45 和 0.50 之间，0.47 >= 0.45 所以触发 TP3
        signal = check_take_profit(position, config, Decimal("0.47"))

        assert signal is not None
        assert signal.level == 3  # 最低目标价
        assert signal.exit_status == PositionStatus.CLOSED_TP3

    def test_price_below_all_targets(self, config, position):
        """测试价格低于所有目标价不触发"""
        # 价格 0.40 < 0.45（最低目标价）
        signal = check_take_profit(position, config, Decimal("0.40"))

        assert signal is None

    def test_price_above_highest_priority(self, config, position):
        """测试价格超过最高目标价时优先以最高价卖出"""
        # 价格 0.60 > 0.55（最高目标价），应该匹配 TP1
        signal = check_take_profit(position, config, Decimal("0.60"))

        assert signal is not None
        assert signal.exit_status == PositionStatus.CLOSED_TP1
        assert signal.level == 1
        # 目标价应该是 0.55（最高）
        assert "0.55" in signal.reason

    def test_high_price_first_check(self, config, position):
        """
        测试高价格优先检查 - 这是多目标价策略的核心测试
        当价格同时满足多个目标价时，应该优先匹配最高目标价
        """
        # 价格 0.58 >= 0.55（最高目标价）
        # 应该直接触发 TP1，而不是 TP2 或 TP3
        signal = check_take_profit(position, config, Decimal("0.58"))

        assert signal is not None
        assert signal.level == 1  # 最高级别
        assert signal.exit_status == PositionStatus.CLOSED_TP1


class TestCheckExit:
    """check_exit 测试类"""

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

    def test_stop_loss_priority(self, config, position):
        """测试止损优先级高于止盈"""
        # 价格 0.19 触发止损
        signal = check_exit(position, Decimal("0.19"), config)

        assert signal is not None
        assert signal.exit_status == PositionStatus.CLOSED_SL

    def test_take_profit_when_price_rises(self, config, position):
        """测试价格上涨时触发止盈"""
        # 价格 0.52 >= 0.50（中等目标价）
        signal = check_exit(position, Decimal("0.52"), config)

        assert signal is not None
        assert signal.exit_status == PositionStatus.CLOSED_TP2

    def test_closed_position_no_signal(self, config):
        """测试已平仓的持仓不产生信号"""
        position = Position(
            market_slug="test",
            direction=PositionDirection.UP,
            entry_price=Decimal("0.30"),
            entry_time=datetime.now(timezone.utc),
            size_usd=Decimal("2.0"),
            status=PositionStatus.CLOSED_TP1,
        )

        signal = check_exit(position, Decimal("0.19"), config)

        assert signal is None


class TestGetDistanceToNearestTarget:
    """get_distance_to_nearest_target 测试类"""

    @pytest.fixture
    def config(self):
        return StrategyConfig()

    def test_distance_to_lowest_target(self, config):
        """测试距离最低目标价的距离"""
        # 价格 0.40，最近目标价是 0.45
        distance, level = get_distance_to_nearest_target(Decimal("0.40"), config)

        assert distance == Decimal("0.05")
        assert level == 3  # 最低目标价

    def test_distance_to_middle_target(self, config):
        """测试距离中等目标价的距离"""
        # 价格 0.47，最近目标价是 0.50
        distance, level = get_distance_to_nearest_target(Decimal("0.47"), config)

        assert distance == Decimal("0.03")
        assert level == 2  # 中等目标价

    def test_all_targets_reached(self, config):
        """测试所有目标价已达到"""
        # 价格 0.60 >= 所有目标价
        distance, level = get_distance_to_nearest_target(Decimal("0.60"), config)

        # 没有更近的目标价
        assert distance == Decimal("999")
        assert level == 0
