from bittensor_cli.src.bittensor import utils
import pytest
from unittest.mock import AsyncMock, patch, MagicMock

from bittensor_cli.src.bittensor.utils import check_img_mimetype


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
