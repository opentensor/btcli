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


# ============================================================================
# Tests for proxy parameter handling
# ============================================================================


def test_is_valid_proxy_name_or_ss58_with_none_proxy():
    """Test that None proxy is accepted when announce_only is False"""
    cli_manager = CLIManager()
    result = cli_manager.is_valid_proxy_name_or_ss58(None, announce_only=False)
    assert result is None


def test_is_valid_proxy_name_or_ss58_raises_with_announce_only_without_proxy():
    """Test that announce_only=True without proxy raises BadParameter"""
    cli_manager = CLIManager()
    with pytest.raises(typer.BadParameter) as exc_info:
        cli_manager.is_valid_proxy_name_or_ss58(None, announce_only=True)
    assert "Cannot supply '--announce-only' without supplying '--proxy'" in str(
        exc_info.value
    )


def test_is_valid_proxy_name_or_ss58_with_valid_ss58():
    """Test that a valid SS58 address is accepted"""
    cli_manager = CLIManager()
    valid_ss58 = "5FHneW46xGXgs5mUiveU4sbTyGBzmstUspZC92UhjJM694ty"
    result = cli_manager.is_valid_proxy_name_or_ss58(valid_ss58, announce_only=False)
    assert result == valid_ss58


def test_is_valid_proxy_name_or_ss58_with_invalid_ss58():
    """Test that an invalid SS58 address raises BadParameter"""
    cli_manager = CLIManager()
    invalid_ss58 = "invalid_address"
    with pytest.raises(typer.BadParameter) as exc_info:
        cli_manager.is_valid_proxy_name_or_ss58(invalid_ss58, announce_only=False)
    assert "Invalid SS58 address" in str(exc_info.value)


def test_is_valid_proxy_name_or_ss58_with_proxy_from_config():
    """Test that a proxy name from config is resolved to SS58 address"""
    cli_manager = CLIManager()
    valid_ss58 = "5FHneW46xGXgs5mUiveU4sbTyGBzmstUspZC92UhjJM694ty"
    cli_manager.proxies = {"my_proxy": {"address": valid_ss58}}

    result = cli_manager.is_valid_proxy_name_or_ss58("my_proxy", announce_only=False)
    assert result == valid_ss58


def test_is_valid_proxy_name_or_ss58_with_invalid_proxy_from_config():
    """Test that an invalid SS58 in config raises BadParameter"""
    cli_manager = CLIManager()
    cli_manager.proxies = {"my_proxy": {"address": "invalid_address"}}

    with pytest.raises(typer.BadParameter) as exc_info:
        cli_manager.is_valid_proxy_name_or_ss58("my_proxy", announce_only=False)
    assert "Invalid SS58 address" in str(exc_info.value)
    assert "from config" in str(exc_info.value)


@patch("bittensor_cli.cli.is_valid_ss58_address")
def test_wallet_transfer_calls_proxy_validation(mock_is_valid_ss58):
    """Test that wallet_transfer calls is_valid_proxy_name_or_ss58"""
    cli_manager = CLIManager()
    mock_is_valid_ss58.return_value = True
    valid_proxy = "5FHneW46xGXgs5mUiveU4sbTyGBzmstUspZC92UhjJM694ty"

    with (
        patch.object(cli_manager, "verbosity_handler"),
        patch.object(cli_manager, "wallet_ask") as mock_wallet_ask,
        patch.object(cli_manager, "initialize_chain"),
        patch.object(cli_manager, "_run_command"),
        patch.object(
            cli_manager, "is_valid_proxy_name_or_ss58", return_value=valid_proxy
        ) as mock_proxy_validation,
    ):
        mock_wallet_ask.return_value = Mock()

        cli_manager.wallet_transfer(
            destination_ss58_address="5FHneW46xGXgs5mUiveU4sbTyGBzmstUspZC92UhjJM694ty",
            amount=10.0,
            transfer_all=False,
            allow_death=False,
            period=100,
            proxy=valid_proxy,
            announce_only=False,
            wallet_name="test_wallet",
            wallet_path="/tmp/test",
            wallet_hotkey="test_hotkey",
            network=None,
            prompt=False,
            quiet=True,
            verbose=False,
            json_output=False,
        )

        # Assert that proxy validation was called
        mock_proxy_validation.assert_called_once_with(valid_proxy, False)


@patch("bittensor_cli.cli.is_valid_ss58_address")
def test_wallet_transfer_with_announce_only_requires_proxy(mock_is_valid_ss58):
    """Test that wallet_transfer with announce_only=True requires proxy"""
    cli_manager = CLIManager()
    mock_is_valid_ss58.return_value = True

    with (
        patch.object(cli_manager, "verbosity_handler"),
        patch.object(cli_manager, "wallet_ask") as mock_wallet_ask,
        patch.object(cli_manager, "initialize_chain"),
    ):
        mock_wallet_ask.return_value = Mock()

        with pytest.raises(typer.BadParameter) as exc_info:
            cli_manager.wallet_transfer(
                destination_ss58_address="5FHneW46xGXgs5mUiveU4sbTyGBzmstUspZC92UhjJM694ty",
                amount=10.0,
                transfer_all=False,
                allow_death=False,
                period=100,
                proxy=None,
                announce_only=True,  # announce_only without proxy should fail
                wallet_name="test_wallet",
                wallet_path="/tmp/test",
                wallet_hotkey="test_hotkey",
                network=None,
                prompt=False,
                quiet=True,
                verbose=False,
                json_output=False,
            )

        assert "Cannot supply '--announce-only' without supplying '--proxy'" in str(
            exc_info.value
        )


def test_stake_add_calls_proxy_validation():
    """Test that stake_add calls is_valid_proxy_name_or_ss58"""
    cli_manager = CLIManager()
    valid_proxy = "5FHneW46xGXgs5mUiveU4sbTyGBzmstUspZC92UhjJM694ty"

    with (
        patch.object(cli_manager, "verbosity_handler"),
        patch.object(cli_manager, "wallet_ask") as mock_wallet_ask,
        patch.object(cli_manager, "initialize_chain"),
        patch.object(cli_manager, "_run_command"),
        patch.object(cli_manager, "ask_safe_staking", return_value=False),
        patch.object(
            cli_manager, "is_valid_proxy_name_or_ss58", return_value=valid_proxy
        ) as mock_proxy_validation,
    ):
        mock_wallet_ask.return_value = Mock()

        cli_manager.stake_add(
            stake_all=False,
            amount=10.0,
            include_hotkeys="",
            exclude_hotkeys="",
            all_hotkeys=False,
            netuids="1",
            all_netuids=False,
            wallet_name="test_wallet",
            wallet_path="/tmp/test",
            wallet_hotkey="test_hotkey",
            proxy=valid_proxy,
            announce_only=False,
            network=None,
            rate_tolerance=None,
            safe_staking=False,
            allow_partial_stake=None,
            period=100,
            prompt=False,
            quiet=True,
            verbose=False,
            json_output=False,
        )

        # Assert that proxy validation was called
        mock_proxy_validation.assert_called_once_with(valid_proxy, False)


def test_stake_remove_calls_proxy_validation():
    """Test that stake_remove calls is_valid_proxy_name_or_ss58"""
    cli_manager = CLIManager()
    valid_proxy = "5FHneW46xGXgs5mUiveU4sbTyGBzmstUspZC92UhjJM694ty"

    with (
        patch.object(cli_manager, "verbosity_handler"),
        patch.object(cli_manager, "wallet_ask") as mock_wallet_ask,
        patch.object(cli_manager, "initialize_chain"),
        patch.object(cli_manager, "_run_command"),
        patch.object(cli_manager, "ask_safe_staking", return_value=False),
        patch.object(
            cli_manager, "is_valid_proxy_name_or_ss58", return_value=valid_proxy
        ) as mock_proxy_validation,
    ):
        mock_wallet_ask.return_value = Mock()

        cli_manager.stake_remove(
            network=None,
            wallet_name="test_wallet",
            wallet_path="/tmp/test",
            wallet_hotkey="test_hotkey",
            netuid=1,
            all_netuids=False,
            unstake_all=False,
            unstake_all_alpha=False,
            amount=10.0,
            hotkey_ss58_address="",
            include_hotkeys="",
            exclude_hotkeys="",
            all_hotkeys=False,
            proxy=valid_proxy,
            announce_only=False,
            rate_tolerance=None,
            safe_staking=False,
            allow_partial_stake=None,
            period=100,
            prompt=False,
            quiet=True,
            verbose=False,
            json_output=False,
        )

        # Assert that proxy validation was called
        mock_proxy_validation.assert_called_once_with(valid_proxy, False)


def test_wallet_associate_hotkey_calls_proxy_validation():
    """Test that wallet_associate_hotkey calls is_valid_proxy_name_or_ss58"""
    cli_manager = CLIManager()
    valid_proxy = "5FHneW46xGXgs5mUiveU4sbTyGBzmstUspZC92UhjJM694ty"
    valid_hotkey = "5FHneW46xGXgs5mUiveU4sbTyGBzmstUspZC92UhjJM694ty"

    with (
        patch.object(cli_manager, "verbosity_handler"),
        patch.object(cli_manager, "wallet_ask") as mock_wallet_ask,
        patch.object(cli_manager, "initialize_chain"),
        patch.object(cli_manager, "_run_command"),
        patch("bittensor_cli.cli.is_valid_ss58_address", return_value=True),
        patch.object(
            cli_manager, "is_valid_proxy_name_or_ss58", return_value=valid_proxy
        ) as mock_proxy_validation,
    ):
        mock_wallet = Mock()
        mock_wallet.name = "test_wallet"
        mock_wallet_ask.return_value = mock_wallet

        cli_manager.wallet_associate_hotkey(
            wallet_name="test_wallet",
            wallet_path="/tmp/test",
            wallet_hotkey=valid_hotkey,
            network=None,
            proxy=valid_proxy,
            announce_only=False,
            prompt=False,
            quiet=True,
            verbose=False,
        )

        # Assert that proxy validation was called
        mock_proxy_validation.assert_called_once_with(valid_proxy, False)


def test_wallet_set_id_calls_proxy_validation():
    """Test that wallet_set_id calls is_valid_proxy_name_or_ss58"""
    cli_manager = CLIManager()
    valid_proxy = "5FHneW46xGXgs5mUiveU4sbTyGBzmstUspZC92UhjJM694ty"

    with (
        patch.object(cli_manager, "verbosity_handler"),
        patch.object(cli_manager, "wallet_ask") as mock_wallet_ask,
        patch.object(cli_manager, "initialize_chain"),
        patch.object(cli_manager, "_run_command"),
        patch.object(
            cli_manager, "is_valid_proxy_name_or_ss58", return_value=valid_proxy
        ) as mock_proxy_validation,
    ):
        mock_wallet_ask.return_value = Mock()

        cli_manager.wallet_set_id(
            wallet_name="test_wallet",
            wallet_path="/tmp/test",
            wallet_hotkey="test_hotkey",
            network=None,
            name="Test Name",
            web_url="https://example.com",
            image_url="https://example.com/image.png",
            discord="testuser",
            description="Test description",
            additional="Additional info",
            github_repo="test/repo",
            proxy=valid_proxy,
            announce_only=False,
            quiet=True,
            verbose=False,
            prompt=False,
            json_output=False,
        )

        # Assert that proxy validation was called
        mock_proxy_validation.assert_called_once_with(valid_proxy, False)


def test_wallet_swap_coldkey_calls_proxy_validation():
    """Test that wallet_swap_coldkey calls is_valid_proxy_name_or_ss58"""
    cli_manager = CLIManager()
    valid_proxy = "5FHneW46xGXgs5mUiveU4sbTyGBzmstUspZC92UhjJM694ty"
    new_coldkey = "5FHneW46xGXgs5mUiveU4sbTyGBzmstUspZC92UhjJM694ty"

    with (
        patch.object(cli_manager, "verbosity_handler"),
        patch.object(cli_manager, "wallet_ask") as mock_wallet_ask,
        patch.object(cli_manager, "initialize_chain"),
        patch.object(cli_manager, "_run_command"),
        patch("bittensor_cli.cli.is_valid_ss58_address", return_value=True),
        patch.object(
            cli_manager, "is_valid_proxy_name_or_ss58", return_value=valid_proxy
        ) as mock_proxy_validation,
    ):
        mock_wallet = Mock()
        mock_wallet.coldkeypub = Mock()
        mock_wallet.coldkeypub.ss58_address = (
            "5FHneW46xGXgs5mUiveU4sbTyGBzmstUspZC92UhjJM694ty"
        )
        mock_wallet_ask.return_value = mock_wallet

        cli_manager.wallet_swap_coldkey(
            wallet_name="test_wallet",
            wallet_path="/tmp/test",
            wallet_hotkey="test_hotkey",
            new_wallet_or_ss58=new_coldkey,
            network=None,
            proxy=valid_proxy,
            announce_only=False,
            quiet=True,
            verbose=False,
            force_swap=False,
        )

        # Assert that proxy validation was called
        mock_proxy_validation.assert_called_once_with(valid_proxy, False)


def test_stake_move_calls_proxy_validation():
    """Test that stake_move calls is_valid_proxy_name_or_ss58"""
    cli_manager = CLIManager()
    valid_proxy = "5FHneW46xGXgs5mUiveU4sbTyGBzmstUspZC92UhjJM694ty"
    dest_hotkey = "5FHneW46xGXgs5mUiveU4sbTyGBzmstUspZC92UhjJM694ty"

    with (
        patch.object(cli_manager, "verbosity_handler"),
        patch.object(cli_manager, "wallet_ask") as mock_wallet_ask,
        patch.object(cli_manager, "initialize_chain"),
        patch.object(cli_manager, "_run_command", return_value=(None, None)),
        patch("bittensor_cli.cli.is_valid_ss58_address", return_value=True),
        patch.object(
            cli_manager, "is_valid_proxy_name_or_ss58", return_value=valid_proxy
        ) as mock_proxy_validation,
    ):
        mock_wallet = Mock()
        mock_wallet.hotkey_str = "test_hotkey"
        mock_wallet_ask.return_value = mock_wallet

        cli_manager.stake_move(
            network=None,
            wallet_name="test_wallet",
            wallet_path="/tmp/test",
            wallet_hotkey="test_hotkey",
            origin_netuid=1,
            destination_netuid=2,
            destination_hotkey=dest_hotkey,
            amount=10.0,
            stake_all=False,
            proxy=valid_proxy,
            announce_only=False,
            period=100,
            prompt=False,
            quiet=True,
            verbose=False,
            json_output=False,
        )

        # Assert that proxy validation was called
        mock_proxy_validation.assert_called_once_with(valid_proxy, False)


def test_stake_transfer_calls_proxy_validation():
    """Test that stake_transfer calls is_valid_proxy_name_or_ss58"""
    cli_manager = CLIManager()
    valid_proxy = "5FHneW46xGXgs5mUiveU4sbTyGBzmstUspZC92UhjJM694ty"
    dest_ss58 = "5FHneW46xGXgs5mUiveU4sbTyGBzmstUspZC92UhjJM694ty"

    with (
        patch.object(cli_manager, "verbosity_handler"),
        patch.object(cli_manager, "wallet_ask") as mock_wallet_ask,
        patch.object(cli_manager, "initialize_chain"),
        patch.object(cli_manager, "_run_command", return_value=(None, None)),
        patch("bittensor_cli.cli.is_valid_ss58_address", return_value=True),
        patch.object(
            cli_manager, "is_valid_proxy_name_or_ss58", return_value=valid_proxy
        ) as mock_proxy_validation,
    ):
        mock_wallet = Mock()
        mock_wallet.hotkey_str = "test_hotkey"
        mock_wallet_ask.return_value = mock_wallet

        cli_manager.stake_transfer(
            network=None,
            wallet_name="test_wallet",
            wallet_path="/tmp/test",
            wallet_hotkey="test_hotkey",
            origin_netuid=1,
            dest_netuid=2,
            dest_ss58=dest_ss58,
            amount=10.0,
            stake_all=False,
            period=100,
            proxy=valid_proxy,
            announce_only=False,
            prompt=False,
            quiet=True,
            verbose=False,
            json_output=False,
        )

        # Assert that proxy validation was called
        mock_proxy_validation.assert_called_once_with(valid_proxy, False)


# ============================================================================
# Tests for root weights difference display (Issue #183)
# ============================================================================


@pytest.mark.asyncio
async def test_get_current_weights_for_uid_success():
    """Test fetching current weights for a specific UID."""
    from bittensor_cli.src.bittensor.extrinsics.root import get_current_weights_for_uid

    mock_subtensor = MagicMock()

    # Mock weights data: [(uid, [(dest_netuid, raw_weight), ...]), ...]
    mock_weights_data = [
        (0, [(0, 32768), (1, 16384), (2, 16384)]),
        (1, [(0, 65535), (1, 0), (2, 0)]),
    ]
    mock_subtensor.weights = AsyncMock(return_value=mock_weights_data)

    result = await get_current_weights_for_uid(mock_subtensor, netuid=0, uid=0)

    mock_subtensor.weights.assert_called_once_with(netuid=0)
    assert 0 in result
    assert 1 in result
    assert 2 in result
    # 32768 / 65535 ≈ 0.5
    assert abs(result[0] - 0.5) < 0.01


@pytest.mark.asyncio
async def test_get_current_weights_for_uid_not_found():
    """Test fetching weights for a UID that doesn't exist."""
    from bittensor_cli.src.bittensor.extrinsics.root import get_current_weights_for_uid

    mock_subtensor = MagicMock()
    mock_weights_data = [
        (0, [(0, 32768), (1, 16384)]),
        (1, [(0, 65535)]),
    ]
    mock_subtensor.weights = AsyncMock(return_value=mock_weights_data)

    result = await get_current_weights_for_uid(mock_subtensor, netuid=0, uid=5)

    assert result == {}


@pytest.mark.asyncio
async def test_get_current_weights_for_uid_empty():
    """Test fetching weights when the network has no weights set."""
    from bittensor_cli.src.bittensor.extrinsics.root import get_current_weights_for_uid

    mock_subtensor = MagicMock()
    mock_subtensor.weights = AsyncMock(return_value=[])

    result = await get_current_weights_for_uid(mock_subtensor, netuid=0, uid=0)

    assert result == {}


@pytest.mark.asyncio
async def test_set_root_weights_fetches_current_weights_with_prompt():
    """Test that set_root_weights fetches current weights when prompt=True."""
    import numpy as np
    from bittensor_cli.src.bittensor.extrinsics.root import set_root_weights_extrinsic

    mock_subtensor = MagicMock()
    mock_wallet = MagicMock()
    mock_subtensor.query = AsyncMock(return_value=0)

    with (
        patch("bittensor_cli.src.bittensor.extrinsics.root.unlock_key") as mock_unlock,
        patch("bittensor_cli.src.bittensor.extrinsics.root.get_limits") as mock_limits,
        patch(
            "bittensor_cli.src.bittensor.extrinsics.root.get_current_weights_for_uid"
        ) as mock_get_current,
        patch("bittensor_cli.src.bittensor.extrinsics.root.console"),
        patch("bittensor_cli.src.bittensor.extrinsics.root.Confirm") as mock_confirm,
    ):
        mock_unlock.return_value = MagicMock(success=True)
        mock_limits.return_value = (1, 0.5)
        mock_get_current.return_value = {0: 0.5, 1: 0.3, 2: 0.2}
        mock_confirm.ask.return_value = False

        netuids = np.array([0, 1, 2], dtype=np.int64)
        weights = np.array([0.4, 0.3, 0.3], dtype=np.float32)

        await set_root_weights_extrinsic(
            subtensor=mock_subtensor,
            wallet=mock_wallet,
            netuids=netuids,
            weights=weights,
            prompt=True,
        )

        mock_get_current.assert_called_once_with(mock_subtensor, netuid=0, uid=0)


@pytest.mark.asyncio
async def test_set_root_weights_skips_current_weights_without_prompt():
    """Test that set_root_weights skips fetching current weights when prompt=False."""
    import numpy as np
    from bittensor_cli.src.bittensor.extrinsics.root import set_root_weights_extrinsic

    mock_subtensor = MagicMock()
    mock_wallet = MagicMock()
    mock_subtensor.query = AsyncMock(return_value=0)
    mock_subtensor.substrate = MagicMock()
    mock_subtensor.substrate.compose_call = AsyncMock()
    mock_subtensor.substrate.create_signed_extrinsic = AsyncMock()
    mock_response = MagicMock()
    mock_response.is_success = True
    mock_subtensor.substrate.submit_extrinsic = AsyncMock(return_value=mock_response)

    with (
        patch("bittensor_cli.src.bittensor.extrinsics.root.unlock_key") as mock_unlock,
        patch("bittensor_cli.src.bittensor.extrinsics.root.get_limits") as mock_limits,
        patch(
            "bittensor_cli.src.bittensor.extrinsics.root.get_current_weights_for_uid"
        ) as mock_get_current,
        patch("bittensor_cli.src.bittensor.extrinsics.root.console"),
    ):
        mock_unlock.return_value = MagicMock(success=True)
        mock_limits.return_value = (1, 0.5)

        netuids = np.array([0, 1, 2], dtype=np.int64)
        weights = np.array([0.4, 0.3, 0.3], dtype=np.float32)

        await set_root_weights_extrinsic(
            subtensor=mock_subtensor,
            wallet=mock_wallet,
            netuids=netuids,
            weights=weights,
            prompt=False,
            wait_for_inclusion=False,
            wait_for_finalization=False,
        )

        mock_get_current.assert_not_called()
