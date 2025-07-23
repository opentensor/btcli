from bittensor_cli.src.bittensor import utils
import pytest


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
