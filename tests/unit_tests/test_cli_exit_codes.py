"""Regression tests pinning CLI error paths to a non-zero exit code.

Several validation sites previously called ``raise typer.Exit()`` (default
exit code 0) after ``print_error(...)``, so error conditions reported success
to the shell. These tests pin the corrected behavior at representative sites.
"""

import pytest
import typer

from bittensor_cli.cli import parse_mnemonic


class TestParseMnemonicExitCode:
    def test_numbered_mnemonic_not_starting_at_1_exits_nonzero(self):
        # cli.py:588 — "Numbered mnemonics must begin with 1"
        with pytest.raises(typer.Exit) as exc_info:
            parse_mnemonic("2-hello 3-how 4-are 5-you")
        assert exc_info.value.exit_code == 1

    def test_numbered_mnemonic_with_missing_numbers_exits_nonzero(self):
        # cli.py:596 — "Missing or duplicate numbers in a numbered mnemonic"
        with pytest.raises(typer.Exit) as exc_info:
            parse_mnemonic("1-hello 3-are 4-you")
        assert exc_info.value.exit_code == 1

    def test_numbered_mnemonic_with_duplicate_numbers_exits_nonzero(self):
        # cli.py:596 — duplicate numbers branch
        with pytest.raises(typer.Exit) as exc_info:
            parse_mnemonic("1-hello 1-how 2-are 3-you")
        assert exc_info.value.exit_code == 1
