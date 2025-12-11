from bittensor_cli.src.bittensor import utils
import pytest
from unittest.mock import AsyncMock, patch, MagicMock

from bittensor_cli.src.bittensor.utils import (
    check_img_mimetype,
    confirm_action,
    set_decline_confirmations,
    get_decline_confirmations,
    set_quiet_mode,
    get_quiet_mode,
)


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

    def setup_method(self):
        """Reset the global flags before each test."""
        set_decline_confirmations(False)
        set_quiet_mode(False)

    def teardown_method(self):
        """Reset the global flags after each test."""
        set_decline_confirmations(False)
        set_quiet_mode(False)

    def test_get_set_decline_confirmations(self):
        """Test that set/get decline_confirmations work correctly."""
        assert get_decline_confirmations() is False
        set_decline_confirmations(True)
        assert get_decline_confirmations() is True
        set_decline_confirmations(False)
        assert get_decline_confirmations() is False

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
        """Test that confirm_action returns False when --no flag is set."""
        set_decline_confirmations(True)
        with patch("bittensor_cli.src.bittensor.utils.console.print") as mock_print:
            result = confirm_action("Do you want to proceed?")
            assert result is False
            mock_print.assert_called_once()
            assert "Auto-declined via --no flag" in str(mock_print.call_args)

    def test_confirm_action_decline_flag_quiet_mode(self):
        """Test that confirm_action suppresses message when --no and --quiet are set."""
        set_decline_confirmations(True)
        set_quiet_mode(True)
        with patch("bittensor_cli.src.bittensor.utils.console.print") as mock_print:
            result = confirm_action("Do you want to proceed?")
            assert result is False
            mock_print.assert_not_called()

    def test_get_set_quiet_mode(self):
        """Test that set/get quiet_mode work correctly."""
        assert get_quiet_mode() is False
        set_quiet_mode(True)
        assert get_quiet_mode() is True
        set_quiet_mode(False)
        assert get_quiet_mode() is False

    def test_confirm_action_decline_flag_does_not_call_confirm_ask(self):
        """Test that Confirm.ask is not called when --no flag is set."""
        set_decline_confirmations(True)
        with patch("bittensor_cli.src.bittensor.utils.Confirm.ask") as mock_ask:
            result = confirm_action("Do you want to proceed?")
            assert result is False
            mock_ask.assert_not_called()

    def test_confirm_action_default_parameter(self):
        """Test that default parameter is passed to Confirm.ask."""
        with patch(
            "bittensor_cli.src.bittensor.utils.Confirm.ask", return_value=True
        ) as mock_ask:
            confirm_action("Do you want to proceed?", default=True)
            mock_ask.assert_called_once_with("Do you want to proceed?", default=True)
