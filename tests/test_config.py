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

        # 多目标价（从高到低）
        assert config.take_profit_prices == [
            Decimal("0.55"), Decimal("0.50"), Decimal("0.45")
        ]

        assert config.stop_loss_price == Decimal("0.20")

    def test_from_env(self, monkeypatch):
        """测试从环境变量加载配置"""
        # 设置环境变量
        monkeypatch.setenv("ENTRY_PRICE_LOW", "0.25")
        monkeypatch.setenv("ENTRY_PRICE_HIGH", "0.35")
        monkeypatch.setenv("POSITION_SIZE_USD", "5.0")
        monkeypatch.setenv("BUY_WINDOW_MINUTES", "10")
        monkeypatch.setenv("TAKE_PROFIT_PRICES", "0.60,0.55,0.50")
        monkeypatch.setenv("STOP_LOSS_PRICE", "0.15")

        config = StrategyConfig.from_env()

        assert config.entry_price_low == Decimal("0.25")
        assert config.entry_price_high == Decimal("0.35")
        assert config.position_size_usd == Decimal("5.0")
        assert config.buy_window_minutes == 10
        assert config.take_profit_prices == [
            Decimal("0.60"), Decimal("0.55"), Decimal("0.50")
        ]
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

    def test_validate_tp_prices_order(self):
        """测试止盈目标价必须从高到低排序"""
        config = StrategyConfig(
            take_profit_prices=[Decimal("0.45"), Decimal("0.55"), Decimal("0.50")],  # 乱序
        )
        errors = config.validate()
        assert any("从高到低排序" in e for e in errors)

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

    def test_check_take_profit_hit(self):
        """测试止盈目标价命中检测"""
        config = StrategyConfig()

        # 价格 0.50 >= 0.50（第二目标价）
        hit, level, target = config.check_take_profit_hit(Decimal("0.50"))
        assert hit is True
        assert level == 2
        assert target == Decimal("0.50")

        # 价格 0.55 >= 0.55（最高目标价）- 优先匹配最高
        hit, level, target = config.check_take_profit_hit(Decimal("0.55"))
        assert hit is True
        assert level == 1  # 最高目标价
        assert target == Decimal("0.55")

        # 价格 0.57 >= 0.55（超过最高目标价）
        hit, level, target = config.check_take_profit_hit(Decimal("0.57"))
        assert hit is True
        assert level == 1  # 仍然匹配最高目标价
        assert target == Decimal("0.55")

        # 价格 0.44 < 0.45（未达到最低目标价）
        hit, level, target = config.check_take_profit_hit(Decimal("0.44"))
        assert hit is False

    def test_get_lowest_highest_take_profit(self):
        """测试获取最低/最高止盈目标价"""
        config = StrategyConfig()

        assert config.get_lowest_take_profit() == Decimal("0.45")
        assert config.get_highest_take_profit() == Decimal("0.55")
