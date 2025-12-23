from bittensor_cli.src.bittensor import utils
import pytest
from unittest.mock import AsyncMock, patch, MagicMock

from bittensor_cli.src.bittensor.utils import (
    check_img_mimetype,
    confirm_action,
    create_table,
)
from rich.table import Column, Table
from bittensor_cli.src import COLOR_PALETTE


@pytest.mark.parametrize(
    "input_dict,expected_result",
    [
        (
            {
                "name": {"value": "0x6a6f686e"},
                "additional": [{"data1": "0x64617461"}, ("data2", "0x64617461")],
            },
            {"name": "john", "additional": [("data1", "data"), ("data2", "data")]},
        ),
        (
            {"name": {"value": "0x6a6f686e"}, "additional": [("data2", "0x64617461")]},
            {"name": "john", "additional": [("data2", "data")]},
        ),
        (
            {
                "name": {"value": "0x6a6f686e"},
                "additional": [(None, None)],
            },
            {"name": "john", "additional": [("", "")]},
        ),
    ],
)
def test_decode_hex_identity_dict(input_dict, expected_result):
    assert utils.decode_hex_identity_dict(input_dict) == expected_result


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "img_url,status,content_type,expected_result",
    [
        (
            "https://github.com/dougsillars/dougsillars/blob/main/twitter.jpg",
            200,
            "text/html",
            (False, "text/html", ""),
        ),
        (
            "https://raw.githubusercontent.com/dougsillars/dougsillars/refs/heads/main/twitter.jpg",
            200,
            "image/jpeg",
            (True, "image/jpeg", ""),
        ),
        (
            "https://abs-0.twimg.com/emoji/v2/svg/1f5fv.svg",
            404,
            "",
            (False, "", "Could not fetch image"),
        ),
    ],
)
async def test_get_image_url(img_url, status, content_type, expected_result):
    mock_response = MagicMock()
    mock_response.status = status
    mock_response.content_type = content_type
    mock_response.__aenter__ = AsyncMock(return_value=mock_response)
    mock_response.__aexit__ = AsyncMock(return_value=None)

    # Create mock session
    mock_session = MagicMock()
    mock_session.get = MagicMock(return_value=mock_response)
    mock_session.__aenter__ = AsyncMock(return_value=mock_session)
    mock_session.__aexit__ = AsyncMock(return_value=None)

    # Patch ClientSession
    with patch("aiohttp.ClientSession", return_value=mock_session):
        assert await check_img_mimetype(img_url) == expected_result


class TestConfirmAction:
    """Tests for the confirm_action helper function and --no flag behavior."""

    def test_confirm_action_interactive_mode_yes(self):
        """Test confirm_action in interactive mode when user confirms."""
        with patch("bittensor_cli.src.bittensor.utils.Confirm.ask", return_value=True):
            result = confirm_action("Do you want to proceed?")
            assert result is True

    def test_confirm_action_interactive_mode_no(self):
        """Test confirm_action in interactive mode when user declines."""
        with patch("bittensor_cli.src.bittensor.utils.Confirm.ask", return_value=False):
            result = confirm_action("Do you want to proceed?")
            assert result is False

    def test_confirm_action_decline_flag_returns_false(self):
        """Test that confirm_action returns False when decline=True."""
        with patch("bittensor_cli.src.bittensor.utils.console.print") as mock_print:
            result = confirm_action("Do you want to proceed?", decline=True)
            assert result is False
            mock_print.assert_called_once()
            assert "Auto-declined via --no flag" in str(mock_print.call_args)

    def test_confirm_action_decline_flag_quiet_mode(self):
        """Test that confirm_action suppresses message when decline=True and quiet=True."""
        with patch("bittensor_cli.src.bittensor.utils.console.print") as mock_print:
            result = confirm_action("Do you want to proceed?", decline=True, quiet=True)
            assert result is False
            mock_print.assert_not_called()

    def test_confirm_action_decline_flag_does_not_call_confirm_ask(self):
        """Test that Confirm.ask is not called when decline=True."""
        with patch("bittensor_cli.src.bittensor.utils.Confirm.ask") as mock_ask:
            result = confirm_action("Do you want to proceed?", decline=True)
            assert result is False
            mock_ask.assert_not_called()

    def test_confirm_action_default_parameter(self):
        """Test that default parameter is passed to Confirm.ask."""
        with patch(
            "bittensor_cli.src.bittensor.utils.Confirm.ask", return_value=True
        ) as mock_ask:
            confirm_action("Do you want to proceed?", default=True)
            mock_ask.assert_called_once_with("Do you want to proceed?", default=True)

    def test_confirm_action_default_values(self):
        """Test that decline and quiet default to False."""
        with patch(
            "bittensor_cli.src.bittensor.utils.Confirm.ask", return_value=True
        ) as mock_ask:
            # When decline=False (default), Confirm.ask should be called
            result = confirm_action("Do you want to proceed?")
            assert result is True
            mock_ask.assert_called_once()


class TestCreateTable:
    """Tests for the create_table utility function."""

    def test_simple_table_creation(self):
        """Test creating a simple table with default styling."""
        table = create_table(title="My Subnets")

        # Verify it returns a Table instance
        assert isinstance(table, Table)
        assert table.title == "My Subnets"

        # Verify default styling is applied
        assert table.show_footer is True
        assert table.show_edge is False
        assert table.header_style == "bold white"
        assert table.border_style == "bright_black"
        assert table.title_justify == "center"
        assert table.show_lines is False
        assert table.pad_edge is True

    def test_table_with_columns_added_later(self):
        """Test adding columns after table creation."""
        table = create_table(title="Test Table")

        # Add columns dynamically
        table.add_column("Column1", justify="center")
        table.add_column("Column2", justify="left")

        assert len(table.columns) == 2
        assert table.columns[0].header == "Column1"
        assert table.columns[1].header == "Column2"

        # Add rows
        table.add_row("Value1", "Value2")
        assert len(table.rows) == 1

    def test_table_with_column_objects(self):
        """Test creating table with Column objects upfront (identity table pattern)."""
        table = create_table(
            Column(
                "Item",
                justify="right",
                style=COLOR_PALETTE["GENERAL"]["SUBHEADING_MAIN"],
                no_wrap=True,
            ),
            Column("Value", style=COLOR_PALETTE["GENERAL"]["SUBHEADING"]),
            title="Identity",
        )

        # Verify columns were added
        assert len(table.columns) == 2
        assert table.columns[0].header == "Item"
        assert table.columns[1].header == "Value"
        assert table.columns[0].justify == "right"
        assert table.columns[0].no_wrap is True

        # Verify default styling still applied
        assert table.show_footer is True
        assert table.show_edge is False

    def test_custom_overrides(self):
        """Test overriding default parameters."""
        table = create_table(
            title="Custom Table",
            show_footer=False,
            border_style="blue",
            show_lines=True,
        )

        # Verify overrides applied
        assert table.show_footer is False
        assert table.border_style == "blue"
        assert table.show_lines is True

        # Verify non-overridden defaults preserved
        assert table.show_edge is False
        assert table.header_style == "bold white"

    def test_subnets_list_pattern(self):
        """Test actual pattern from subnets_list() function."""
        table = create_table(
            title=f"[{COLOR_PALETTE['GENERAL']['HEADER']}]Subnets\n"
            f"Network: [{COLOR_PALETTE['GENERAL']['SUBHEADING']}]finney\n",
        )

        # Add columns as in actual code
        table.add_column("[bold white]Netuid", style="grey89", justify="center")
        table.add_column("[bold white]Name", style="cyan", justify="left")
        table.add_column("[bold white]Price", style="dark_sea_green2", justify="left")

        assert len(table.columns) == 3

        # Add sample row
        table.add_row("1", "Alpha", "0.0025")
        assert len(table.rows) == 1

    def test_registration_pattern(self):
        """Test registration confirmation table pattern."""
        table = create_table(
            title=(
                f"[{COLOR_PALETTE.G.HEADER}]"
                f"Register to [{COLOR_PALETTE.G.SUBHEAD}]netuid: 1[/{COLOR_PALETTE.G.SUBHEAD}]\n"
                f"Network: [{COLOR_PALETTE.G.SUBHEAD}]finney[/{COLOR_PALETTE.G.SUBHEAD}]\n"
            ),
        )

        table.add_column("Netuid", style="rgb(253,246,227)", no_wrap=True, justify="center")
        table.add_column("Symbol", style=COLOR_PALETTE["GENERAL"]["SYMBOL"], no_wrap=True)
        table.add_column("Cost (τ)", style=COLOR_PALETTE["POOLS"]["TAO"], justify="center")

        assert len(table.columns) == 3

        # Add sample row
        table.add_row("1", "α", "τ 0.5000")
        assert len(table.rows) == 1

    def test_advanced_rich_features(self):
        """Test advanced Rich features with custom box and expand."""
        from rich import box

        table = create_table(
            Column("Command", overflow="fold", ratio=2),
            Column("Description", overflow="fold", ratio=3),
            title="Commands",
            box=box.ROUNDED,
            expand=True,
            padding=(0, 1),
        )

        assert table.box == box.ROUNDED
        assert table.expand is True
        assert len(table.columns) == 2
        assert table.columns[0].ratio == 2
        assert table.columns[1].ratio == 3

    def test_empty_table_minimal_config(self):
        """Test creating empty table with minimal configuration."""
        table = create_table()

        assert isinstance(table, Table)
        assert table.title == ""
        assert table.show_footer is True
        assert len(table.columns) == 0

    def test_multiple_column_objects_with_styling(self):
        """Test multiple Column objects with various styling options."""
        table = create_table(
            Column("Col1", style="cyan", justify="left"),
            Column("Col2", style="green", justify="center", no_wrap=True),
            Column("Col3", style="yellow", justify="right", overflow="fold"),
            title="Multi-Column Test",
        )

        assert len(table.columns) == 3
        assert table.columns[0].style == "cyan"
        assert table.columns[1].justify == "center"
        assert table.columns[2].overflow == "fold"

    def test_rich_markup_in_title(self):
        """Test that rich markup in title is preserved."""
        table = create_table(
            title="[bold cyan]Test[/bold cyan] [dim]subtitle[/dim]"
        )

        assert "[bold cyan]Test[/bold cyan]" in table.title
        assert "[dim]subtitle[/dim]" in table.title
