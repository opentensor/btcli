import pytest

from bittensor_cli.src.bittensor.utils import format_error_message


@pytest.mark.parametrize(
    "err_name,expected_output",
    [
        (
            "SubtokenDisabled",
            "This subnet is not yet activated. You must wait for it to activate to peform this action.",
        )
    ],
)
def test_format_error_message_custom_error_message(err_name, expected_output):
    error = {"name": err_name, "type": "error type", "docs": "docs"}
    formatted_out = format_error_message(error)
    assert (
        f"Subtensor returned `{err_name}(error type)` error. This means: `{expected_output}`."
        == formatted_out
    )
