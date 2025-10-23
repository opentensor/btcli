import pytest
import typer

from bittensor_cli.cli import parse_mnemonic, CLIManager
from unittest.mock import AsyncMock, patch, MagicMock, Mock


def test_parse_mnemonic():
    # standard
    assert parse_mnemonic("hello how are you") == "hello how are you"
    # numbered
    assert parse_mnemonic("1-hello 2-how 3-are 4-you") == "hello how are you"
    with pytest.raises(typer.Exit):
        # not starting with 1
        parse_mnemonic("2-hello 3-how 4-are 5-you")
        # duplicate numbers
        parse_mnemonic("1-hello 1-how 2-are 3-you")
        # missing numbers
        parse_mnemonic("1-hello 3-are 4-you")


@pytest.mark.asyncio
async def test_subnet_sets_price_correctly():
    from bittensor_cli.src.bittensor.subtensor_interface import (
        SubtensorInterface,
        DynamicInfo,
    )

    mock_result = {"some": "data"}
    mock_price = 42.0
    mock_dynamic_info = MagicMock()
    mock_dynamic_info.price = None

    with (
        patch.object(
            SubtensorInterface, "query_runtime_api", new_callable=AsyncMock
        ) as mock_query,
        patch.object(
            SubtensorInterface, "get_subnet_price", new_callable=AsyncMock
        ) as mock_price_method,
        patch.object(DynamicInfo, "from_any", return_value=mock_dynamic_info),
    ):
        mock_query.return_value = mock_result
        mock_price_method.return_value = mock_price

        subtensor = SubtensorInterface("finney")
        subnet_info = await subtensor.subnet(netuid=1)

        mock_query.assert_awaited_once_with(
            "SubnetInfoRuntimeApi", "get_dynamic_info", params=[1], block_hash=None
        )
        mock_price_method.assert_awaited_once_with(netuid=1, block_hash=None)
        assert subnet_info.price == mock_price


@patch("bittensor_cli.cli.Confirm")
@patch("bittensor_cli.cli.console")
def test_swap_hotkey_netuid_0_warning_with_prompt(mock_console, mock_confirm):
    """
    Test that swap_hotkey shows warning when netuid=0 and prompt=True,
    and exits when user declines confirmation
    """
    # Setup
    cli_manager = CLIManager()
    mock_confirm.ask.return_value = False  # User declines

    # Mock dependencies to prevent actual execution
    with (
        patch.object(cli_manager, "verbosity_handler"),
        patch.object(cli_manager, "wallet_ask") as mock_wallet_ask,
        patch.object(cli_manager, "initialize_chain"),
    ):
        mock_wallet_ask.return_value = Mock()

        # Call the method with netuid=0 and prompt=True
        result = cli_manager.wallet_swap_hotkey(
            wallet_name="test_wallet",
            wallet_path="/tmp/test",
            wallet_hotkey="old_hotkey",
            netuid=0,
            all_netuids=False,
            network=None,
            destination_hotkey_name="new_hotkey",
            quiet=False,
            verbose=False,
            prompt=True,
            json_output=False,
        )

        # Assert: Warning was displayed (4 console.print calls for the warning)
        assert mock_console.print.call_count >= 4
        warning_calls = [str(call) for call in mock_console.print.call_args_list]
        assert any(
            "WARNING" in str(call) and "netuid 0" in str(call) for call in warning_calls
        )
        assert any("root network" in str(call) for call in warning_calls)
        assert any(
            "NOT move child hotkey delegation" in str(call) for call in warning_calls
        )

        # Assert: User was asked to confirm
        mock_confirm.ask.assert_called_once()
        confirm_message = mock_confirm.ask.call_args[0][0]
        assert "SURE" in confirm_message
        assert "netuid 0" in confirm_message or "root network" in confirm_message

        # Assert: Function returned None (early exit) because user declined
        assert result is None


@patch("bittensor_cli.cli.Confirm")
@patch("bittensor_cli.cli.console")
def test_swap_hotkey_netuid_0_proceeds_with_confirmation(mock_console, mock_confirm):
    """
    Test that swap_hotkey proceeds when netuid=0 and user confirms
    """
    # Setup
    cli_manager = CLIManager()
    mock_confirm.ask.return_value = True  # User confirms

    # Mock dependencies
    with (
        patch.object(cli_manager, "verbosity_handler"),
        patch.object(cli_manager, "wallet_ask") as mock_wallet_ask,
        patch.object(cli_manager, "initialize_chain"),
        patch.object(cli_manager, "_run_command") as mock_run_command,
    ):
        mock_wallet = Mock()
        mock_wallet_ask.return_value = mock_wallet

        # Call the method
        cli_manager.wallet_swap_hotkey(
            wallet_name="test_wallet",
            wallet_path="/tmp/test",
            wallet_hotkey="old_hotkey",
            netuid=0,
            all_netuids=False,
            network=None,
            destination_hotkey_name="new_hotkey",
            quiet=False,
            verbose=False,
            prompt=True,
            json_output=False,
        )

        # Assert: Warning was shown and confirmed
        mock_confirm.ask.assert_called_once()

        # Assert: Command execution proceeded
        mock_run_command.assert_called_once()


@patch("bittensor_cli.cli.console")
def test_swap_hotkey_netuid_0_no_warning_with_no_prompt(mock_console):
    """
    Test that swap_hotkey does NOT show warning when prompt=False
    """
    # Setup
    cli_manager = CLIManager()

    # Mock dependencies
    with (
        patch.object(cli_manager, "verbosity_handler"),
        patch.object(cli_manager, "wallet_ask") as mock_wallet_ask,
        patch.object(cli_manager, "initialize_chain"),
        patch.object(cli_manager, "_run_command"),
    ):
        mock_wallet = Mock()
        mock_wallet_ask.return_value = mock_wallet

        # Call the method with prompt=False
        cli_manager.wallet_swap_hotkey(
            wallet_name="test_wallet",
            wallet_path="/tmp/test",
            wallet_hotkey="old_hotkey",
            netuid=0,
            all_netuids=False,
            network=None,
            destination_hotkey_name="new_hotkey",
            quiet=False,
            verbose=False,
            prompt=False,  # No prompt
            json_output=False,
        )

        # Assert: No warning messages about netuid 0
        warning_calls = [str(call) for call in mock_console.print.call_args_list]
        assert not any(
            "WARNING" in str(call) and "netuid 0" in str(call) for call in warning_calls
        )


@patch("bittensor_cli.cli.console")
def test_swap_hotkey_netuid_1_no_warning(mock_console):
    """
    Test that swap_hotkey does NOT show warning when netuid != 0
    """
    # Setup
    cli_manager = CLIManager()

    # Mock dependencies
    with (
        patch.object(cli_manager, "verbosity_handler"),
        patch.object(cli_manager, "wallet_ask") as mock_wallet_ask,
        patch.object(cli_manager, "initialize_chain"),
        patch.object(cli_manager, "_run_command"),
    ):
        mock_wallet = Mock()
        mock_wallet_ask.return_value = mock_wallet

        # Call the method with netuid=1
        cli_manager.wallet_swap_hotkey(
            wallet_name="test_wallet",
            wallet_path="/tmp/test",
            wallet_hotkey="old_hotkey",
            netuid=1,  # Not 0
            all_netuids=False,
            network=None,
            destination_hotkey_name="new_hotkey",
            quiet=False,
            verbose=False,
            prompt=True,
            json_output=False,
        )

        # Assert: No warning messages about netuid 0
        warning_calls = [str(call) for call in mock_console.print.call_args_list]
        assert not any(
            "WARNING" in str(call) and "netuid 0" in str(call) for call in warning_calls
        )
