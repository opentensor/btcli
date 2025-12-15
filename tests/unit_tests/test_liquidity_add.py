import pytest
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

from bittensor_cli.src.bittensor.balances import Balance
from bittensor_cli.src.commands.liquidity import liquidity as liquidity_cmd
from bittensor_cli.src.commands.liquidity.utils import max_liquidity_in_range


def _wallet_stub():
    wallet = MagicMock()
    wallet.name = "test_wallet"
    wallet.coldkeypub.ss58_address = "5F3sa2TJcPq7Qm8kXy...coldkey"
    return wallet


@pytest.mark.asyncio
async def test_add_liquidity_json_output_on_unlock_failure(monkeypatch):
    subtensor = MagicMock()

    # Force unlock failure
    monkeypatch.setattr(
        liquidity_cmd,
        "unlock_key",
        lambda _wallet: SimpleNamespace(success=False, message="unlock failed"),
    )

    printed = {}

    def fake_print_json(*, data):
        printed["data"] = data

    monkeypatch.setattr(liquidity_cmd.json_console, "print_json", fake_print_json)

    success, message = await liquidity_cmd.add_liquidity(
        subtensor=subtensor,
        wallet=_wallet_stub(),
        hotkey_ss58="5F3sa2TJcPq7Qm8kXy...hotkey",
        netuid=1,
        proxy=None,
        liquidity=Balance.from_tao(1.0),
        price_low=Balance.from_tao(1.0),
        price_high=Balance.from_tao(2.0),
        prompt=False,
        json_output=True,
    )

    assert success is False
    assert message == "unlock failed"
    assert printed["data"] == {
        "success": False,
        "message": "unlock failed",
        "extrinsic_identifier": None,
    }


@pytest.mark.asyncio
async def test_add_liquidity_json_output_on_subnet_missing(monkeypatch):
    subtensor = MagicMock()
    subtensor.subnet_exists = AsyncMock(return_value=False)

    monkeypatch.setattr(
        liquidity_cmd,
        "unlock_key",
        lambda _wallet: SimpleNamespace(success=True, message=""),
    )

    printed = {}

    def fake_print_json(*, data):
        printed["data"] = data

    monkeypatch.setattr(liquidity_cmd.json_console, "print_json", fake_print_json)

    success, message = await liquidity_cmd.add_liquidity(
        subtensor=subtensor,
        wallet=_wallet_stub(),
        hotkey_ss58="5F3sa2TJcPq7Qm8kXy...hotkey",
        netuid=120,
        proxy=None,
        liquidity=Balance.from_tao(100.0),
        price_low=Balance.from_tao(1.0),
        price_high=Balance.from_tao(2.0),
        prompt=False,
        json_output=True,
    )

    assert success is False
    assert "Subnet with netuid: 120" in message
    assert printed["data"]["success"] is False
    assert printed["data"]["message"] == message
    assert printed["data"]["extrinsic_identifier"] is None


@pytest.mark.asyncio
async def test_add_liquidity_json_output_on_extrinsic_failure(monkeypatch):
    subtensor = MagicMock()
    subtensor.subnet_exists = AsyncMock(return_value=True)

    monkeypatch.setattr(
        liquidity_cmd,
        "unlock_key",
        lambda _wallet: SimpleNamespace(success=True, message=""),
    )

    add_ext = AsyncMock(return_value=(False, "Invalid Transaction", None))
    monkeypatch.setattr(liquidity_cmd, "add_liquidity_extrinsic", add_ext)

    printed = {}

    def fake_print_json(*, data):
        printed["data"] = data

    monkeypatch.setattr(liquidity_cmd.json_console, "print_json", fake_print_json)

    success, message = await liquidity_cmd.add_liquidity(
        subtensor=subtensor,
        wallet=_wallet_stub(),
        hotkey_ss58="5F3sa2TJcPq7Qm8kXy...hotkey",
        netuid=120,
        proxy=None,
        liquidity=Balance.from_tao(100.0),
        price_low=Balance.from_tao(1.0),
        price_high=Balance.from_tao(2.0),
        prompt=False,
        json_output=True,
    )

    assert success is False
    assert message == "Invalid Transaction"
    assert printed["data"] == {
        "success": False,
        "message": "Invalid Transaction",
        "extrinsic_identifier": None,
    }

    add_ext.assert_awaited_once()


def test_max_liquidity_in_range_uses_limiting_side():
    # price_low=1, price_high=4, current_price=2.25
    # sqrt_low=1, sqrt_high=2, sqrt_cur=1.5
    # L_from_tao = tao / (1.5-1) = 2*tao
    # L_from_alpha = alpha / (1/1.5-1/2) = alpha / (2/3-1/2)= alpha / (1/6)= 6*alpha
    # => tao-limited for equal tao/alpha
    l_max = max_liquidity_in_range(
        tao_available=Balance.from_tao(10.0),
        alpha_available=Balance.from_tao(10.0),
        current_price=Balance.from_tao(2.25),
        price_low=Balance.from_tao(1.0),
        price_high=Balance.from_tao(4.0),
    )
    assert l_max.tao == pytest.approx(20.0)
