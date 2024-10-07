import pytest
import typer

from bittensor_cli.cli import parse_mnemonic


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
