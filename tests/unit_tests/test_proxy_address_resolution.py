"""Tests for proxy address resolution in stake move/transfer/swap and sudo trim.

When a proxy is active, chain queries (get_stake, SubnetOwner) must use the
proxied account address, not the signer's address.
"""

import pytest
from contextlib import contextmanager
from unittest.mock import AsyncMock, MagicMock, patch

from bittensor_cli.src.bittensor.balances import Balance

SIGNER_SS58 = "5FHneW46xGXgs5mUiveU4sbTyGBzmstUspZC92UhjJM694ty"
PROXY_SS58 = "5GrwvaEF5zXb26Fz9rcQpDWS57CtERHpNehXCPcNoHGKutQY"
HOTKEY_SS58 = "5CiQ1cV1MmMwsep7YP37QZKEgBgaVXeSPnETB5JBgwYRoXbP"
DEST_HOTKEY_SS58 = "5DAAnrj7VHTznn2AWBemMuyBwZWs6FNFjdyVXUeYum3PTXFy"


def _mock_wallet():
    wallet = MagicMock()
    wallet.coldkeypub.ss58_address = SIGNER_SS58
    wallet.hotkey.ss58_address = HOTKEY_SS58
    wallet.hotkey_str = "default"
    return wallet


def _mock_subtensor(stake_balance=Balance.from_tao(100)):
    receipt = AsyncMock()
    receipt.get_extrinsic_identifier = AsyncMock(return_value="0x123-1")
    receipt.is_success = True
    subtensor = MagicMock()
    subtensor.network = "finney"
    subtensor.substrate = MagicMock()
    subtensor.substrate.get_chain_head = AsyncMock(return_value="0xabc")
    subtensor.substrate.compose_call = AsyncMock(return_value=MagicMock())
    subtensor.get_stake = AsyncMock(return_value=stake_balance)
    subtensor.get_balance = AsyncMock(return_value=Balance.from_tao(500))
    subtensor.subnet_exists = AsyncMock(return_value=True)
    subtensor.get_extrinsic_fee = AsyncMock(return_value=Balance.from_tao(0.001))
    subtensor.substrate.get_account_next_index = AsyncMock(return_value=0)
    subtensor.sim_swap = AsyncMock(
        return_value=MagicMock(alpha_amount=100, tao_fee=1, alpha_fee=1)
    )
    subtensor.sign_and_send_extrinsic = AsyncMock(return_value=(True, "", receipt))
    subtensor.query = AsyncMock()
    return subtensor


@contextmanager
def _move_patches(**extra):
    base = "bittensor_cli.src.commands.stake.move"
    with (
        patch(
            f"{base}.get_movement_pricing",
            new_callable=AsyncMock,
            return_value=MagicMock(rate_with_tolerance=None),
        ),
        patch(f"{base}.unlock_key", return_value=MagicMock(success=True)),
        patch(f"{base}.print_extrinsic_id", new_callable=AsyncMock),
    ):
        if "hotkey" in extra:
            with patch(f"{base}.get_hotkey_pub_ss58", return_value=extra["hotkey"]):
                yield
        else:
            yield


@pytest.mark.asyncio
async def test_move_stake_uses_proxy_for_stake_lookup():
    """move_stake must query stake using the proxied account address."""
    from bittensor_cli.src.commands.stake.move import move_stake

    subtensor = _mock_subtensor()
    with _move_patches():
        await move_stake(
            subtensor=subtensor,
            wallet=_mock_wallet(),
            origin_netuid=1,
            origin_hotkey=HOTKEY_SS58,
            destination_netuid=2,
            destination_hotkey=DEST_HOTKEY_SS58,
            amount=10.0,
            stake_all=False,
            era=3,
            prompt=False,
            proxy=PROXY_SS58,
            mev_protection=False,
        )
    for call in subtensor.get_stake.call_args_list:
        assert call.kwargs["coldkey_ss58"] == PROXY_SS58


@pytest.mark.asyncio
async def test_trim_allows_proxy_owner():
    """trim must accept the proxied account as subnet owner."""
    from bittensor_cli.src.commands.sudo import trim

    subtensor = _mock_subtensor()
    subtensor.query = AsyncMock(return_value=PROXY_SS58)
    base = "bittensor_cli.src.commands.sudo"
    with (
        patch(f"{base}.unlock_key", return_value=MagicMock(success=True)),
        patch(f"{base}.print_extrinsic_id", new_callable=AsyncMock),
    ):
        result = await trim(
            wallet=_mock_wallet(),
            subtensor=subtensor,
            netuid=1,
            proxy=PROXY_SS58,
            max_n=100,
            period=100,
            prompt=False,
            decline=False,
            quiet=True,
            json_output=False,
        )
    assert result is True


@pytest.mark.asyncio
async def test_trim_rejects_non_owner_with_proxy():
    """trim must reject when the proxy doesn't own the subnet."""
    from bittensor_cli.src.commands.sudo import trim

    subtensor = _mock_subtensor()
    subtensor.query = AsyncMock(return_value="5UNRELATED_ADDRESS")
    result = await trim(
        wallet=_mock_wallet(),
        subtensor=subtensor,
        netuid=1,
        proxy=PROXY_SS58,
        max_n=100,
        period=100,
        prompt=False,
        decline=False,
        quiet=True,
        json_output=False,
    )
    assert result is False
