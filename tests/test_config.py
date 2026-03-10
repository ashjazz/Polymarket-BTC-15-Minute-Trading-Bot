"""
StrategyConfig 单元测试
"""
import os
import pytest
from decimal import Decimal
from strategy.config import StrategyConfig


class TestStrategyConfig:
    """StrategyConfig 测试类"""

    def test_default_values(self):
        """测试默认配置值"""
        config = StrategyConfig()

        assert config.entry_price_low == Decimal("0.28")
        assert config.entry_price_high == Decimal("0.32")
        assert config.position_size_usd == Decimal("2.0")
        assert config.buy_window_minutes == 8

        assert config.take_profit_1_minutes == 2
        assert config.take_profit_1_price == Decimal("0.40")
        assert config.take_profit_2_minutes == 4
        assert config.take_profit_2_price == Decimal("0.48")
        assert config.take_profit_3_minutes == 6
        assert config.take_profit_3_price == Decimal("0.55")

        assert config.stop_loss_price == Decimal("0.20")

    def test_from_env(self, monkeypatch):
        """测试从环境变量加载配置"""
        # 设置环境变量
        monkeypatch.setenv("ENTRY_PRICE_LOW", "0.25")
        monkeypatch.setenv("ENTRY_PRICE_HIGH", "0.35")
        monkeypatch.setenv("POSITION_SIZE_USD", "5.0")
        monkeypatch.setenv("BUY_WINDOW_MINUTES", "10")
        monkeypatch.setenv("STOP_LOSS_PRICE", "0.15")

        config = StrategyConfig.from_env()

        assert config.entry_price_low == Decimal("0.25")
        assert config.entry_price_high == Decimal("0.35")
        assert config.position_size_usd == Decimal("5.0")
        assert config.buy_window_minutes == 10
        assert config.stop_loss_price == Decimal("0.15")

    def test_validate_valid_config(self):
        """测试有效配置验证"""
        config = StrategyConfig()
        errors = config.validate()
        assert len(errors) == 0

    def test_validate_invalid_entry_range(self):
        """测试无效入场区间"""
        config = StrategyConfig(
            entry_price_low=Decimal("0.35"),
            entry_price_high=Decimal("0.30"),
        )
        errors = config.validate()
        assert any("entry_price_low" in e for e in errors)

    def test_validate_invalid_stop_loss(self):
        """测试止损价格高于入场区间"""
        config = StrategyConfig(
            stop_loss_price=Decimal("0.30"),
        )
        errors = config.validate()
        assert any("stop_loss_price" in e for e in errors)

    def test_validate_invalid_tp_order(self):
        """测试止盈时间顺序错误"""
        config = StrategyConfig(
            take_profit_1_minutes=5,
            take_profit_2_minutes=3,
        )
        errors = config.validate()
        assert any("止盈检查点时间必须递增" in e for e in errors)

    def test_is_entry_price(self):
        """测试入场价格判断"""
        config = StrategyConfig()

        assert config.is_entry_price(Decimal("0.28")) is True
        assert config.is_entry_price(Decimal("0.30")) is True
        assert config.is_entry_price(Decimal("0.32")) is True
        assert config.is_entry_price(Decimal("0.27")) is False
        assert config.is_entry_price(Decimal("0.33")) is False

    def test_is_in_buy_window(self):
        """测试买入窗口判断"""
        config = StrategyConfig()

        assert config.is_in_buy_window(0) is True
        assert config.is_in_buy_window(4) is True
        assert config.is_in_buy_window(7.9) is True
        assert config.is_in_buy_window(8) is False
        assert config.is_in_buy_window(10) is False
        assert config.is_in_buy_window(-1) is False

    def test_get_take_profit_target(self):
        """测试获取止盈目标"""
        config = StrategyConfig()

        minutes, price = config.get_take_profit_target(1)
        assert minutes == 2
        assert price == Decimal("0.40")

        minutes, price = config.get_take_profit_target(2)
        assert minutes == 4
        assert price == Decimal("0.48")

        minutes, price = config.get_take_profit_target(3)
        assert minutes == 6
        assert price == Decimal("0.55")

        # 无效检查点
        minutes, price = config.get_take_profit_target(4)
        assert minutes == 0
        assert price == Decimal("0")
