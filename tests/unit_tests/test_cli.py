import asyncio
import numpy as np
import pytest
import typer
from async_substrate_interface import AsyncSubstrateInterface

from bittensor_cli.cli import parse_mnemonic, CLIManager
from bittensor_cli.src import HYPERPARAMS, HYPERPARAMS_METADATA, RootSudoOnly
from bittensor_cli.src.bittensor.extrinsics.root import (
    get_current_weights_for_uid,
    set_root_weights_extrinsic,
)
from bittensor_cli.src.commands import proxy as proxy_commands
from bittensor_cli.src.commands.proxy import _parse_proxy_storage
from unittest.mock import AsyncMock, patch, MagicMock, Mock

from bittensor_cli.src.bittensor.subtensor_interface import SubtensorInterface


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


@patch("bittensor_cli.cli.confirm_action")
@patch("bittensor_cli.cli.console")
def test_swap_hotkey_netuid_0_warning_with_prompt(mock_console, mock_confirm):
    """
    Test that swap_hotkey shows warning when netuid=0 and prompt=True,
    and exits when user declines confirmation
    """
    # Setup
    cli_manager = CLIManager()
    cli_manager.subtensor = MagicMock(spec=SubtensorInterface)
    cli_manager.subtensor.substrate = MagicMock(spec=AsyncSubstrateInterface)
    mock_confirm.return_value = False  # User declines

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
            proxy=None,
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
        mock_confirm.assert_called_once()
        confirm_message = mock_confirm.call_args[0][0]
        assert "SURE" in confirm_message
        assert "netuid 0" in confirm_message or "root network" in confirm_message

        # Assert: Function returned None (early exit) because user declined
        assert result is None


@patch("bittensor_cli.cli.confirm_action")
@patch("bittensor_cli.cli.console")
def test_swap_hotkey_netuid_0_proceeds_with_confirmation(mock_console, mock_confirm):
    """
    Test that swap_hotkey proceeds when netuid=0 and user confirms
    """
    # Setup
    cli_manager = CLIManager()
    cli_manager.subtensor = MagicMock(spec=SubtensorInterface)
    cli_manager.subtensor.substrate = MagicMock(spec=AsyncSubstrateInterface)
    mock_confirm.return_value = True  # User confirms

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
            proxy=None,
        )

        # Assert: Warning was shown and confirmed
        mock_confirm.assert_called_once()

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
            proxy=None,
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
            proxy=None,
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
# Tests for root weights difference display
# ============================================================================


@pytest.mark.asyncio
async def test_get_current_weights_for_uid_success():
    """Test fetching current weights for a specific UID."""
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
    mock_subtensor = MagicMock()
    mock_subtensor.weights = AsyncMock(return_value=[])

    result = await get_current_weights_for_uid(mock_subtensor, netuid=0, uid=0)

    assert result == {}


@pytest.mark.asyncio
async def test_set_root_weights_fetches_current_weights_with_prompt():
    """Test that set_root_weights fetches current weights when prompt=True."""
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
        patch(
            "bittensor_cli.src.bittensor.extrinsics.root.confirm_action"
        ) as mock_confirm,
    ):
        mock_unlock.return_value = MagicMock(success=True)
        mock_limits.return_value = (1, 0.5)
        mock_get_current.return_value = {0: 0.5, 1: 0.3, 2: 0.2}
        mock_confirm.return_value = False

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


# ============================================================================
# Tests for proxy list, reject, remove --all (issue #742)
# ============================================================================


def test_parse_proxy_storage_empty():
    """_parse_proxy_storage returns empty list for None or empty input."""
    rows, dep = _parse_proxy_storage(None)
    assert rows == []
    assert dep is None
    rows, dep = _parse_proxy_storage([])
    assert rows == []
    assert dep is None


def test_parse_proxy_storage_one_row():
    """_parse_proxy_storage decodes one proxy row when decode_account_id works."""
    with patch(
        "bittensor_cli.src.commands.proxy.decode_account_id",
        return_value="5GrwvaEF5zXb26Fz9rcQpDWS57CtERHpNehXCPcNoHGKutQY",
    ):
        raw = ([(tuple(range(32)), "Any", 0)], 100)
        rows, dep = _parse_proxy_storage(raw)
    assert len(rows) == 1
    assert rows[0]["delegate"] == "5GrwvaEF5zXb26Fz9rcQpDWS57CtERHpNehXCPcNoHGKutQY"
    assert rows[0]["proxy_type"] == "Any"
    assert rows[0]["delay"] == 0
    assert dep == 100


def test_parse_proxy_storage_delegate_as_list():
    """_parse_proxy_storage converts list delegate to tuple for decode_account_id."""
    with patch(
        "bittensor_cli.src.commands.proxy.decode_account_id",
        return_value="5GrwvaEF5zXb26Fz9rcQpDWS57CtERHpNehXCPcNoHGKutQY",
    ) as mock_decode:
        raw = ([(list(range(32)), "Transfer", 1)], None)
        rows, dep = _parse_proxy_storage(raw)
    assert len(rows) == 1
    assert rows[0]["delegate"] == "5GrwvaEF5zXb26Fz9rcQpDWS57CtERHpNehXCPcNoHGKutQY"
    assert rows[0]["proxy_type"] == "Transfer"
    assert rows[0]["delay"] == 1
    mock_decode.assert_called_once()
    call_arg = mock_decode.call_args[0][0]
    assert isinstance(call_arg, tuple)
    assert len(call_arg) == 32


def test_parse_proxy_storage_substrate_nested_format():
    """_parse_proxy_storage handles actual substrate response with nested tuples and dict proxy_type."""
    with patch(
        "bittensor_cli.src.commands.proxy.decode_account_id",
        return_value="5DAAnrj7VHTznn2AWBemMuyBwZWs6FNFjdyVXUeYum3PTXFy",
    ) as mock_decode:
        # Actual substrate format: items wrapped in extra tuples, delegate nested, proxy_type as dict
        raw = (
            (
                (
                    {
                        "delegate": (tuple(range(32)),),
                        "proxy_type": {"Any": ()},
                        "delay": 0,
                    },
                ),
            ),
            93000000,
        )
        rows, dep = _parse_proxy_storage(raw)
    assert len(rows) == 1
    assert rows[0]["delegate"] == "5DAAnrj7VHTznn2AWBemMuyBwZWs6FNFjdyVXUeYum3PTXFy"
    assert rows[0]["proxy_type"] == "Any"
    assert rows[0]["delay"] == 0
    assert dep == 93000000
    mock_decode.assert_called_once()
    call_arg = mock_decode.call_args[0][0]
    assert isinstance(call_arg, tuple)
    assert len(call_arg) == 32


def test_proxy_remove_all_and_delegate_mutually_exclusive():
    """proxy remove: --all and --delegate cannot be used together."""
    cli = CLIManager()
    with (
        patch.object(cli, "verbosity_handler"),
        patch.object(cli, "wallet_ask") as mock_wallet,
        patch("bittensor_cli.cli.print_error"),
    ):
        mock_wallet.return_value = Mock()
        mock_wallet.return_value.coldkeypub = Mock()
        mock_wallet.return_value.coldkeypub.ss58_address = (
            "5GrwvaEF5zXb26Fz9rcQpDWS57CtERHpNehXCPcNoHGKutQY"
        )
        with pytest.raises(typer.Exit):
            cli.proxy_remove(
                delegate="5FHneW46xGXgs5mUiveU4sbTyGBzmstUspZC92UhjJM694ty",
                remove_all=True,
                network=None,
                wallet_name="default",
                wallet_path="/tmp",
                wallet_hotkey="default",
                prompt=False,
                decline=False,
                quiet=True,
                verbose=False,
                json_output=False,
            )


def test_proxy_remove_requires_delegate_or_all():
    """proxy remove: one of --delegate or --all is required."""
    cli = CLIManager()
    with (
        patch.object(cli, "verbosity_handler"),
        patch("bittensor_cli.cli.print_error"),
    ):
        with pytest.raises(typer.Exit):
            cli.proxy_remove(
                delegate=None,
                remove_all=False,
                network=None,
                wallet_name="default",
                wallet_path="/tmp",
                wallet_hotkey="default",
                prompt=False,
                decline=False,
                quiet=True,
                verbose=False,
                json_output=False,
            )


def test_proxy_remove_with_all_calls_remove_all_proxies():
    """proxy remove --all invokes remove_all_proxies."""
    cli = CLIManager()
    mock_subtensor = Mock()
    mock_wallet = Mock()
    with (
        patch.object(cli, "verbosity_handler"),
        patch.object(cli, "wallet_ask", return_value=mock_wallet),
        patch.object(cli, "initialize_chain", return_value=mock_subtensor),
        patch.object(cli, "_run_command", return_value=None) as mock_run,
        patch.object(proxy_commands, "remove_all_proxies", new_callable=AsyncMock),
    ):
        cli.proxy_remove(
            delegate=None,
            remove_all=True,
            network=None,
            wallet_name="default",
            wallet_path="/tmp",
            wallet_hotkey="default",
            prompt=False,
            decline=False,
            wait_for_inclusion=False,
            wait_for_finalization=False,
            period=16,
            quiet=True,
            verbose=False,
            json_output=False,
        )
        mock_run.assert_called_once()
        call_arg = mock_run.call_args[0][0]
        assert asyncio.iscoroutine(call_arg)
        proxy_commands.remove_all_proxies.assert_called_once()
        proxy_commands.remove_all_proxies.assert_called_with(
            subtensor=mock_subtensor,
            wallet=mock_wallet,
            prompt=False,
            decline=False,
            quiet=True,
            wait_for_inclusion=False,
            wait_for_finalization=False,
            period=16,
            json_output=False,
        )


def test_proxy_remove_with_delegate_calls_remove_proxy():
    """proxy remove --delegate invokes remove_proxy (single)."""
    cli = CLIManager()
    mock_subtensor = Mock()
    mock_wallet = Mock()
    delegate = "5FHneW46xGXgs5mUiveU4sbTyGBzmstUspZC92UhjJM694ty"
    with (
        patch.object(cli, "verbosity_handler"),
        patch.object(cli, "wallet_ask", return_value=mock_wallet),
        patch.object(cli, "initialize_chain", return_value=mock_subtensor),
        patch.object(cli, "_run_command", return_value=None),
        patch.object(proxy_commands, "remove_proxy", new_callable=AsyncMock),
    ):
        cli.proxy_remove(
            delegate=delegate,
            remove_all=False,
            network=None,
            proxy_type=proxy_commands.ProxyType.Any,
            delay=0,
            wallet_name="default",
            wallet_path="/tmp",
            wallet_hotkey="default",
            prompt=False,
            decline=False,
            wait_for_inclusion=False,
            wait_for_finalization=False,
            period=16,
            quiet=True,
            verbose=False,
            json_output=False,
        )
        proxy_commands.remove_proxy.assert_called_once_with(
            subtensor=mock_subtensor,
            wallet=mock_wallet,
            delegate=delegate,
            proxy_type=proxy_commands.ProxyType.Any,
            delay=0,
            prompt=False,
            decline=False,
            quiet=True,
            wait_for_inclusion=False,
            wait_for_finalization=False,
            period=16,
            json_output=False,
        )


def test_proxy_list_with_address_calls_list_proxies():
    """proxy list --address calls list_proxies with that address."""
    cli = CLIManager()
    mock_subtensor = Mock()
    addr = "5GrwvaEF5zXb26Fz9rcQpDWS57CtERHpNehXCPcNoHGKutQY"
    with (
        patch.object(cli, "verbosity_handler"),
        patch.object(cli, "initialize_chain", return_value=mock_subtensor),
        patch.object(cli, "_run_command", return_value=None),
        patch.object(proxy_commands, "list_proxies", new_callable=AsyncMock),
    ):
        cli.proxy_list(
            address=addr,
            network=None,
            wallet_name=None,
            wallet_path=None,
            wallet_hotkey=None,
            quiet=True,
            verbose=False,
            json_output=False,
        )
        proxy_commands.list_proxies.assert_called_once_with(
            subtensor=mock_subtensor,
            address=addr,
            prompt=False,
            json_output=False,
        )


def test_proxy_list_without_address_uses_wallet():
    """proxy list without --address uses wallet coldkey and calls list_proxies."""
    cli = CLIManager()
    mock_subtensor = Mock()
    mock_wallet = Mock()
    mock_wallet.coldkeypub = Mock()
    mock_wallet.coldkeypub.ss58_address = (
        "5GrwvaEF5zXb26Fz9rcQpDWS57CtERHpNehXCPcNoHGKutQY"
    )
    with (
        patch.object(cli, "verbosity_handler"),
        patch.object(cli, "wallet_ask", return_value=mock_wallet),
        patch.object(cli, "initialize_chain", return_value=mock_subtensor),
        patch.object(cli, "_run_command", return_value=None),
        patch.object(proxy_commands, "list_proxies", new_callable=AsyncMock),
    ):
        cli.proxy_list(
            address=None,
            network=None,
            wallet_name="default",
            wallet_path="/tmp",
            wallet_hotkey=None,
            quiet=True,
            verbose=False,
            json_output=False,
        )
        proxy_commands.list_proxies.assert_called_once_with(
            subtensor=mock_subtensor,
            address=mock_wallet.coldkeypub.ss58_address,
            prompt=False,
            json_output=False,
        )


def test_proxy_reject_announced_calls_reject_announcement():
    """proxy reject invokes reject_announcement with delegate and call_hash."""
    cli = CLIManager()
    mock_subtensor = Mock()
    mock_wallet = Mock()
    mock_wallet.coldkeypub = Mock()
    mock_wallet.coldkeypub.ss58_address = (
        "5GrwvaEF5zXb26Fz9rcQpDWS57CtERHpNehXCPcNoHGKutQY"
    )
    delegate = "5FHneW46xGXgs5mUiveU4sbTyGBzmstUspZC92UhjJM694ty"
    call_hash = "0x1234abcd"
    with (
        patch.object(cli, "verbosity_handler"),
        patch.object(cli, "wallet_ask", return_value=mock_wallet),
        patch.object(cli, "initialize_chain", return_value=mock_subtensor),
        patch.object(cli, "_run_command", return_value=True),
        patch.object(proxy_commands, "reject_announcement", new_callable=AsyncMock),
        patch("bittensor_cli.cli.ProxyAnnouncements") as mock_pa,
    ):
        mock_pa.get_db.return_value.__enter__ = Mock(return_value=(Mock(), Mock()))
        mock_pa.get_db.return_value.__exit__ = Mock(return_value=False)
        mock_pa.read_rows.return_value = []
        cli.proxy_reject_announced(
            delegate=delegate,
            call_hash=call_hash,
            network=None,
            wallet_name="default",
            wallet_path="/tmp",
            wallet_hotkey="default",
            prompt=False,
            decline=False,
            wait_for_inclusion=False,
            wait_for_finalization=False,
            period=16,
            quiet=True,
            verbose=False,
            json_output=False,
        )
        proxy_commands.reject_announcement.assert_called_once_with(
            subtensor=mock_subtensor,
            wallet=mock_wallet,
            delegate=delegate,
            call_hash=call_hash,
            prompt=False,
            decline=False,
            quiet=True,
            wait_for_inclusion=False,
            wait_for_finalization=False,
            period=16,
            json_output=False,
        )


def test_proxy_reject_announced_requires_delegate_without_prompt():
    """proxy reject requires --delegate in non-interactive mode."""
    cli = CLIManager()
    mock_wallet = Mock()
    mock_wallet.coldkeypub = Mock()
    mock_wallet.coldkeypub.ss58_address = (
        "5GrwvaEF5zXb26Fz9rcQpDWS57CtERHpNehXCPcNoHGKutQY"
    )
    with (
        patch.object(cli, "verbosity_handler"),
        patch.object(cli, "wallet_ask", return_value=mock_wallet),
        patch.object(cli, "_run_command") as mock_run_command,
        patch("bittensor_cli.cli.print_error"),
    ):
        with pytest.raises(typer.Exit):
            cli.proxy_reject_announced(
                delegate=None,
                call_hash="0x1234abcd",
                network=None,
                wallet_name="default",
                wallet_path="/tmp",
                wallet_hotkey="default",
                prompt=False,
                decline=False,
                wait_for_inclusion=False,
                wait_for_finalization=False,
                period=16,
                quiet=True,
                verbose=False,
                json_output=False,
            )
        mock_run_command.assert_not_called()


def test_proxy_reject_announced_prompts_for_delegate_when_missing():
    """proxy reject prompts for delegate in interactive mode when not provided."""
    cli = CLIManager()
    mock_subtensor = Mock()
    mock_wallet = Mock()
    mock_wallet.coldkeypub = Mock()
    mock_wallet.coldkeypub.ss58_address = (
        "5GrwvaEF5zXb26Fz9rcQpDWS57CtERHpNehXCPcNoHGKutQY"
    )
    delegate = "5FHneW46xGXgs5mUiveU4sbTyGBzmstUspZC92UhjJM694ty"
    call_hash = "0x1234abcd"
    with (
        patch.object(cli, "verbosity_handler"),
        patch.object(cli, "wallet_ask", return_value=mock_wallet),
        patch.object(cli, "initialize_chain", return_value=mock_subtensor),
        patch.object(cli, "_run_command", return_value=True),
        patch.object(proxy_commands, "reject_announcement", new_callable=AsyncMock),
        patch("bittensor_cli.cli.Prompt.ask", return_value=delegate),
        patch("bittensor_cli.cli.ProxyAnnouncements") as mock_pa,
    ):
        mock_pa.get_db.return_value.__enter__ = Mock(return_value=(Mock(), Mock()))
        mock_pa.get_db.return_value.__exit__ = Mock(return_value=False)
        mock_pa.read_rows.return_value = []
        cli.proxy_reject_announced(
            delegate=None,
            call_hash=call_hash,
            network=None,
            wallet_name="default",
            wallet_path="/tmp",
            wallet_hotkey="default",
            prompt=True,
            decline=False,
            wait_for_inclusion=False,
            wait_for_finalization=False,
            period=16,
            quiet=True,
            verbose=False,
            json_output=False,
        )
        proxy_commands.reject_announcement.assert_called_once_with(
            subtensor=mock_subtensor,
            wallet=mock_wallet,
            delegate=delegate,
            call_hash=call_hash,
            prompt=True,
            decline=False,
            quiet=True,
            wait_for_inclusion=False,
            wait_for_finalization=False,
            period=16,
            json_output=False,
        )


def test_proxy_reject_announced_marks_executed_in_db():
    """proxy reject marks announcement as executed in ProxyAnnouncements on success."""
    cli = CLIManager()
    mock_subtensor = Mock()
    mock_wallet = Mock()
    mock_wallet.coldkeypub = Mock()
    mock_wallet.coldkeypub.ss58_address = (
        "5GrwvaEF5zXb26Fz9rcQpDWS57CtERHpNehXCPcNoHGKutQY"
    )
    delegate = "5FHneW46xGXgs5mUiveU4sbTyGBzmstUspZC92UhjJM694ty"
    call_hash = "0xdeadbeef"
    other_wallet_row = (
        41,
        "5FHneW46xGXgs5mUiveU4sbTyGBzmstUspZC92UhjJM694ty",
        1,
        100,
        "0xdeadbeef",
        "0xCAFE",
        "{}",
        0,
    )
    matching_wallet_row = (
        42,
        "5GrwvaEF5zXb26Fz9rcQpDWS57CtERHpNehXCPcNoHGKutQY",
        2,
        101,
        "0xdeadbeef",
        "0xCAFF",
        "{}",
        0,
    )
    with (
        patch.object(cli, "verbosity_handler"),
        patch.object(cli, "wallet_ask", return_value=mock_wallet),
        patch.object(cli, "initialize_chain", return_value=mock_subtensor),
        patch.object(cli, "_run_command", return_value=True),
        patch.object(proxy_commands, "reject_announcement", new_callable=AsyncMock),
        patch("bittensor_cli.cli.ProxyAnnouncements") as mock_pa,
    ):
        mock_conn = Mock()
        mock_cursor = Mock()
        mock_pa.get_db.return_value.__enter__ = Mock(
            return_value=(mock_conn, mock_cursor)
        )
        mock_pa.get_db.return_value.__exit__ = Mock(return_value=False)
        mock_pa.read_rows.return_value = [other_wallet_row, matching_wallet_row]
        cli.proxy_reject_announced(
            delegate=delegate,
            call_hash=call_hash,
            network=None,
            wallet_name="default",
            wallet_path="/tmp",
            wallet_hotkey="default",
            prompt=False,
            decline=False,
            wait_for_inclusion=False,
            wait_for_finalization=False,
            period=16,
            quiet=True,
            verbose=False,
            json_output=False,
        )
        mock_pa.mark_as_executed.assert_called_once_with(mock_conn, mock_cursor, 42)


def test_proxy_reject_announced_ambiguous_db_entries_skip_mark_no_prompt():
    """proxy reject does not mark DB executed when call hash matches multiple rows for same wallet."""
    cli = CLIManager()
    mock_subtensor = Mock()
    mock_wallet = Mock()
    mock_wallet.coldkeypub = Mock()
    mock_wallet.coldkeypub.ss58_address = (
        "5GrwvaEF5zXb26Fz9rcQpDWS57CtERHpNehXCPcNoHGKutQY"
    )
    delegate = "5FHneW46xGXgs5mUiveU4sbTyGBzmstUspZC92UhjJM694ty"
    call_hash = "0xdeadbeef"
    db_rows = [
        (
            41,
            "5GrwvaEF5zXb26Fz9rcQpDWS57CtERHpNehXCPcNoHGKutQY",
            1,
            100,
            "0xdeadbeef",
            "0xCAFE",
            "{}",
            0,
        ),
        (
            42,
            "5GrwvaEF5zXb26Fz9rcQpDWS57CtERHpNehXCPcNoHGKutQY",
            2,
            101,
            "0xdeadbeef",
            "0xCAFF",
            "{}",
            0,
        ),
    ]
    with (
        patch.object(cli, "verbosity_handler"),
        patch.object(cli, "wallet_ask", return_value=mock_wallet),
        patch.object(cli, "initialize_chain", return_value=mock_subtensor),
        patch.object(cli, "_run_command", return_value=True),
        patch.object(proxy_commands, "reject_announcement", new_callable=AsyncMock),
        patch("bittensor_cli.cli.ProxyAnnouncements") as mock_pa,
    ):
        mock_conn = Mock()
        mock_cursor = Mock()
        mock_pa.get_db.return_value.__enter__ = Mock(
            return_value=(mock_conn, mock_cursor)
        )
        mock_pa.get_db.return_value.__exit__ = Mock(return_value=False)
        mock_pa.read_rows.return_value = db_rows
        cli.proxy_reject_announced(
            delegate=delegate,
            call_hash=call_hash,
            network=None,
            wallet_name="default",
            wallet_path="/tmp",
            wallet_hotkey="default",
            prompt=False,
            decline=False,
            wait_for_inclusion=False,
            wait_for_finalization=False,
            period=16,
            quiet=True,
            verbose=False,
            json_output=False,
        )
        proxy_commands.reject_announcement.assert_called_once_with(
            subtensor=mock_subtensor,
            wallet=mock_wallet,
            delegate=delegate,
            call_hash=call_hash,
            prompt=False,
            decline=False,
            quiet=True,
            wait_for_inclusion=False,
            wait_for_finalization=False,
            period=16,
            json_output=False,
        )
        mock_pa.mark_as_executed.assert_not_called()


# HYPERPARAMS / HYPERPARAMS_METADATA (issue #826)
NEW_HYPERPARAMS_826 = {"sn_owner_hotkey", "subnet_owner_hotkey", "recycle_or_burn"}


def test_new_hyperparams_in_hyperparams():
    for key in NEW_HYPERPARAMS_826:
        assert key in HYPERPARAMS, f"{key} should be in HYPERPARAMS"
        extrinsic, root_only = HYPERPARAMS[key]
        assert extrinsic, f"{key} must have non-empty extrinsic name"
        assert root_only is RootSudoOnly.FALSE


def test_subnet_owner_hotkey_alias_maps_to_same_extrinsic():
    ext_sn, _ = HYPERPARAMS["sn_owner_hotkey"]
    ext_subnet, _ = HYPERPARAMS["subnet_owner_hotkey"]
    assert ext_sn == ext_subnet == "sudo_set_sn_owner_hotkey"


def test_new_hyperparams_have_metadata():
    required = {"description", "side_effects", "owner_settable", "docs_link"}
    for key in NEW_HYPERPARAMS_826:
        assert key in HYPERPARAMS_METADATA, f"{key} should be in HYPERPARAMS_METADATA"
        meta = HYPERPARAMS_METADATA[key]
        for field in required:
            assert field in meta, f"{key} metadata missing '{field}'"
        assert isinstance(meta["description"], str)
        assert isinstance(meta["owner_settable"], bool)


def test_new_hyperparams_owner_settable_true():
    for key in NEW_HYPERPARAMS_826:
        assert HYPERPARAMS_METADATA[key]["owner_settable"] is True
