import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from tests.unit_tests.conftest import COLDKEY_SS58


MODULE = "bittensor_cli.src.commands.sudo"


def _receipt() -> MagicMock:
    receipt = MagicMock()
    receipt.get_extrinsic_identifier = AsyncMock(return_value="0xabc-1")
    return receipt


@pytest.mark.asyncio
async def test_max_burn_no_prompt_owner_uses_owner_path(mock_wallet, mock_subtensor):
    from bittensor_cli.src.commands.sudo import set_hyperparameter_extrinsic

    direct_call = MagicMock(name="direct_call")
    mock_subtensor.query = AsyncMock(return_value=COLDKEY_SS58)
    mock_subtensor.substrate.metadata = MagicMock()
    mock_subtensor.substrate.get_metadata_call_function = AsyncMock(
        return_value={"fields": [{"name": "netuid"}, {"name": "max_burn"}]}
    )
    mock_subtensor.substrate.compose_call = AsyncMock(return_value=direct_call)
    mock_subtensor.sign_and_send_extrinsic = AsyncMock(
        return_value=(True, "", _receipt())
    )

    with (
        patch(f"{MODULE}.unlock_key", return_value=MagicMock(success=True)),
        patch(f"{MODULE}.requires_bool", return_value=False),
        patch(f"{MODULE}.print_extrinsic_id", new_callable=AsyncMock),
    ):
        success, err_msg, ext_id = await set_hyperparameter_extrinsic(
            subtensor=mock_subtensor,
            wallet=mock_wallet,
            netuid=1,
            proxy=None,
            parameter="max_burn",
            value="10000000000",
            wait_for_inclusion=False,
            wait_for_finalization=False,
            prompt=False,
        )

    assert success is True
    assert err_msg == ""
    assert ext_id == "0xabc-1"
    mock_subtensor.substrate.compose_call.assert_awaited_once_with(
        call_module="AdminUtils",
        call_function="sudo_set_max_burn",
        call_params={"netuid": 1, "max_burn": "10000000000"},
    )
    mock_subtensor.sign_and_send_extrinsic.assert_awaited_once_with(
        direct_call,
        mock_wallet,
        False,
        False,
        proxy=None,
    )


@pytest.mark.asyncio
async def test_max_burn_no_prompt_non_owner_uses_sudo_path(mock_wallet, mock_subtensor):
    from bittensor_cli.src.commands.sudo import set_hyperparameter_extrinsic

    direct_call = MagicMock(name="direct_call")
    sudo_call = MagicMock(name="sudo_call")
    mock_subtensor.query = AsyncMock(
        return_value="5FLSigC9H8M5Xo6z8xN7f6cXnHboRcgk4v6R7zDNz6w5jN3q"
    )
    mock_subtensor.substrate.metadata = MagicMock()
    mock_subtensor.substrate.get_metadata_call_function = AsyncMock(
        return_value={"fields": [{"name": "netuid"}, {"name": "max_burn"}]}
    )
    mock_subtensor.substrate.compose_call = AsyncMock(
        side_effect=[direct_call, sudo_call]
    )
    mock_subtensor.sign_and_send_extrinsic = AsyncMock(
        return_value=(True, "", _receipt())
    )

    with (
        patch(f"{MODULE}.unlock_key", return_value=MagicMock(success=True)),
        patch(f"{MODULE}.requires_bool", return_value=False),
        patch(f"{MODULE}.print_extrinsic_id", new_callable=AsyncMock),
    ):
        success, err_msg, ext_id = await set_hyperparameter_extrinsic(
            subtensor=mock_subtensor,
            wallet=mock_wallet,
            netuid=1,
            proxy=None,
            parameter="max_burn",
            value="10000000000",
            wait_for_inclusion=False,
            wait_for_finalization=False,
            prompt=False,
        )

    assert success is True
    assert err_msg == ""
    assert ext_id == "0xabc-1"
    assert mock_subtensor.substrate.compose_call.await_count == 2
    assert mock_subtensor.substrate.compose_call.await_args_list[0].kwargs == {
        "call_module": "AdminUtils",
        "call_function": "sudo_set_max_burn",
        "call_params": {"netuid": 1, "max_burn": "10000000000"},
    }
    assert mock_subtensor.substrate.compose_call.await_args_list[1].kwargs == {
        "call_module": "Sudo",
        "call_function": "sudo",
        "call_params": {"call": direct_call},
    }
    mock_subtensor.sign_and_send_extrinsic.assert_awaited_once_with(
        sudo_call,
        mock_wallet,
        False,
        False,
        proxy=None,
    )
