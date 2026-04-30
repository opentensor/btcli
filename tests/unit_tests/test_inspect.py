from unittest.mock import MagicMock, patch

from rich.table import Table

from bittensor_cli.src.bittensor.balances import Balance
from bittensor_cli.src.bittensor.chain_data import DelegateInfo
from bittensor_cli.src.commands.wallets import (
    _build_coldkey_table,
    _build_hotkey_table,
    _calculate_daily_return,
    _format_hotkey_label,
    _make_delegate_rows,
    _populate_coldkey_table,
    _populate_hotkey_table,
    _resolve_delegate_name,
)


def _make_mock_delegate(
    hotkey_ss58: str,
    total_stake_tao: float,
    total_daily_return_tao: float,
) -> DelegateInfo:
    """Create a mock DelegateInfo with the specified stake and return values."""
    delegate = MagicMock(spec=DelegateInfo)
    delegate.hotkey_ss58 = hotkey_ss58
    delegate.total_stake = Balance.from_tao(total_stake_tao)
    delegate.total_daily_return = Balance.from_tao(total_daily_return_tao)
    return delegate


def _make_mock_neuron(coldkey: str, hotkey: str, stake_tao: float, emission: float):
    """Create a mock NeuronInfoLite with the specified fields."""
    neuron = MagicMock()
    neuron.coldkey = coldkey
    neuron.hotkey = hotkey
    neuron.stake = Balance.from_tao(stake_tao)
    neuron.emission = emission
    return neuron


class TestBuildColdkeyTable:
    def test_returns_table_with_correct_columns(self):
        table = _build_coldkey_table("finney")
        assert isinstance(table, Table)
        column_names = [col.header for col in table.columns]
        assert "[bold white]Coldkey" in column_names
        assert "[bold white]Balance" in column_names
        assert "[bold white]Delegate" in column_names
        assert "[bold white]Stake" in column_names
        assert "[bold white]Emission" in column_names
        assert len(table.columns) == 5

    def test_title_contains_network(self):
        table = _build_coldkey_table("test")
        assert "test" in table.title


class TestBuildHotkeyTable:
    def test_returns_table_with_correct_columns(self):
        table = _build_hotkey_table("finney")
        assert isinstance(table, Table)
        column_names = [col.header for col in table.columns]
        assert "[bold white]Coldkey" in column_names
        assert "[bold white]Netuid" in column_names
        assert "[bold white]Hotkey" in column_names
        assert "[bold white]Stake" in column_names
        assert "[bold white]Emission" in column_names
        assert len(table.columns) == 5

    def test_title_contains_network(self):
        table = _build_hotkey_table("test")
        assert "test" in table.title


class TestResolveDelegateName:
    def _identity_map_with_hotkey_name(hotkey_ss58: str, name: str) -> dict:
    """Shape returned by fetch_coldkey_hotkey_identities (see get_hotkey_identity_name)."""
    return {
        "hotkeys": {hotkey_ss58: {"identity": {"name": name}}},
        "coldkeys": {},
    }

    def test_known_delegate_returns_display_name(self):
        info = _identity_map_with_hotkey_name("5abc", "MyDelegate")
        assert _resolve_delegate_name("5abc", info) == "MyDelegate"

    def test_unknown_delegate_returns_ss58(self):
        assert _resolve_delegate_name("5xyz", {}) == "5xyz"


class TestCalculateDailyReturn:
    def test_positive_stake_returns_proportional_return(self):
        delegate = _make_mock_delegate("5abc", 100.0, 10.0)
        staked = Balance.from_tao(50.0)
        result = _calculate_daily_return(delegate, staked)
        assert result == 5.0

    def test_zero_total_stake_returns_zero(self):
        delegate = _make_mock_delegate("5abc", 0.0, 10.0)
        staked = Balance.from_tao(50.0)
        result = _calculate_daily_return(delegate, staked)
        assert result == 0


class TestMakeDelegateRows:
    def test_yields_rows_for_positive_stakes(self):
        delegate = _make_mock_delegate("5abc", 100.0, 10.0)
        delegates = [(delegate, Balance.from_tao(50.0))]
        info = _identity_map_with_hotkey_name("5abc", "MyDelegate")
        rows = list(_make_delegate_rows(delegates, info))
        assert len(rows) == 1
        assert rows[0][2] == "MyDelegate"

    def test_skips_zero_stake_delegates(self):
        delegate = _make_mock_delegate("5abc", 100.0, 10.0)
        delegates = [(delegate, Balance.from_tao(0.0))]
        rows = list(_make_delegate_rows(delegates, {}))
        assert len(rows) == 0

    def test_multiple_delegates(self):
        d1 = _make_mock_delegate("5aaa", 100.0, 10.0)
        d2 = _make_mock_delegate("5bbb", 200.0, 20.0)
        delegates = [
            (d1, Balance.from_tao(10.0)),
            (d2, Balance.from_tao(20.0)),
        ]
        rows = list(_make_delegate_rows(delegates, {}))
        assert len(rows) == 2


class TestFormatHotkeyLabel:
    def test_known_hotkey_includes_wallet_name(self):
        mock_wallet = MagicMock()
        mock_wallet.hotkey_str = "myhk"
        with patch(
            "bittensor_cli.src.commands.wallets.get_hotkey_pub_ss58",
            return_value="5hotkey",
        ):
            result = _format_hotkey_label("5hotkey", [mock_wallet])
        assert result == "myhk-5hotkey"

    def test_unknown_hotkey_returns_ss58(self):
        with patch(
            "bittensor_cli.src.commands.wallets.get_hotkey_pub_ss58",
            return_value="5other",
        ):
            result = _format_hotkey_label("5hotkey", [MagicMock()])
        assert result == "5hotkey"


class TestPopulateColdkeyTable:
    def test_adds_rows_to_table(self):
        table = _build_coldkey_table("finney")
        rows = [
            ["alice", "100.0", "", "", ""],
            ["", "", "Delegate1", "50.0", "1.0"],
        ]
        _populate_coldkey_table(table, rows)
        assert table.row_count == 3

    def test_empty_rows_noop(self):
        table = _build_coldkey_table("finney")
        _populate_coldkey_table(table, [])
        assert table.row_count == 0


class TestPopulateHotkeyTable:
    def test_adds_rows_to_table(self):
        table = _build_hotkey_table("finney")
        rows = [
            ["alice", "1", "5hotkey", "10.0", "0.5"],
        ]
        _populate_hotkey_table(table, rows)
        assert table.row_count == 2

    def test_empty_rows_noop(self):
        table = _build_hotkey_table("finney")
        _populate_hotkey_table(table, [])
        assert table.row_count == 0
