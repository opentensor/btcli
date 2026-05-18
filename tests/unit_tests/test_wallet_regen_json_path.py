"""Tests for json_path handling in regen_coldkey() and regen_hotkey().

Two regressions are pinned here:

1. ``regen_coldkey`` used to ``raise ValueError`` on a missing ``--json-path``,
   which escaped the command and surfaced as a generic "An unknown error has
   occurred" stack trace via ``_run_command``'s catch-all. ``regen_hotkey``
   already handled this with ``print_error(...) + return False``. The two
   sibling commands are now consistent.

2. Neither function expanded ``~`` in the supplied path before
   ``os.path.exists``, so ``--json-path ~/wallet.json`` always failed with
   "File ... does not exist" even when the file was there. Both now call
   ``os.path.expanduser`` first.
"""

import json

import pytest


MODULE = "bittensor_cli.src.commands.wallets"


# ---------------------------------------------------------------------------
# regen_coldkey — missing json_path file
# ---------------------------------------------------------------------------


class TestRegenColdkeyMissingJsonPath:
    """Regression: regen_coldkey must NOT raise ValueError on missing file."""

    @pytest.mark.asyncio
    async def test_returns_false_on_missing_json_path(self, mock_wallet):
        """Previously raised ValueError; now matches regen_hotkey's behaviour."""
        from bittensor_cli.src.commands.wallets import regen_coldkey

        result = await regen_coldkey(
            wallet=mock_wallet,
            mnemonic=None,
            seed=None,
            json_path="/nonexistent/wallet.json",
            json_password="password",
            use_password=False,
            overwrite=False,
            json_output=False,
        )

        assert result is False
        mock_wallet.regenerate_coldkey.assert_not_called()

    @pytest.mark.asyncio
    async def test_does_not_raise_value_error_on_missing_json_path(self, mock_wallet):
        """Explicit: previously raised ValueError, must not raise now."""
        from bittensor_cli.src.commands.wallets import regen_coldkey

        # The bug: this used to raise ValueError(...) and escape the command.
        try:
            await regen_coldkey(
                wallet=mock_wallet,
                mnemonic=None,
                seed=None,
                json_path="/nonexistent/wallet.json",
                json_password="password",
                use_password=False,
                overwrite=False,
                json_output=False,
            )
        except ValueError as e:
            pytest.fail(f"regen_coldkey unexpectedly raised ValueError: {e}")


# ---------------------------------------------------------------------------
# regen_coldkey — tilde expansion in json_path
# ---------------------------------------------------------------------------


class TestRegenColdkeyTildeExpansion:
    """Regression: ``--json-path ~/wallet.json`` must expand the tilde."""

    @pytest.mark.asyncio
    async def test_expands_tilde_in_json_path(self, mock_wallet, tmp_path, monkeypatch):
        """A real file at ~/wallet.json must be found when --json-path is ~/wallet.json."""
        from bittensor_cli.src.commands.wallets import regen_coldkey

        # Redirect $HOME so ~/wallet.json resolves under tmp_path
        monkeypatch.setenv("HOME", str(tmp_path))

        json_file = tmp_path / "wallet.json"
        json_file.write_text(json.dumps({"encoded": "fake"}))

        mock_wallet.regenerate_coldkey.return_value = None
        await regen_coldkey(
            wallet=mock_wallet,
            mnemonic=None,
            seed=None,
            json_path="~/wallet.json",
            json_password="password",
            use_password=False,
            overwrite=False,
            json_output=False,
        )

        # If tilde was not expanded, regenerate_coldkey would never be reached
        # because os.path.exists("~/wallet.json") returns False.
        mock_wallet.regenerate_coldkey.assert_called_once()


# ---------------------------------------------------------------------------
# regen_hotkey — missing json_path file (existing behaviour, now also expands ~)
# ---------------------------------------------------------------------------


class TestRegenHotkeyMissingJsonPath:
    """regen_hotkey already returned False on missing file. Pin that behaviour."""

    @pytest.mark.asyncio
    async def test_returns_false_on_missing_json_path(self, mock_wallet):
        from bittensor_cli.src.commands.wallets import regen_hotkey

        result = await regen_hotkey(
            wallet=mock_wallet,
            mnemonic=None,
            seed=None,
            json_path="/nonexistent/hotkey.json",
            json_password="password",
            use_password=False,
            overwrite=False,
            json_output=False,
        )

        assert result is False
        mock_wallet.regenerate_hotkey.assert_not_called()


# ---------------------------------------------------------------------------
# regen_hotkey — tilde expansion in json_path
# ---------------------------------------------------------------------------


class TestRegenHotkeyTildeExpansion:
    """Regression: ``--json-path ~/hotkey.json`` must expand the tilde."""

    @pytest.mark.asyncio
    async def test_expands_tilde_in_json_path(self, mock_wallet, tmp_path, monkeypatch):
        from bittensor_cli.src.commands.wallets import regen_hotkey

        monkeypatch.setenv("HOME", str(tmp_path))

        json_file = tmp_path / "hotkey.json"
        json_file.write_text(json.dumps({"encoded": "fake"}))

        mock_wallet.regenerate_hotkey.return_value = None
        await regen_hotkey(
            wallet=mock_wallet,
            mnemonic=None,
            seed=None,
            json_path="~/hotkey.json",
            json_password="password",
            use_password=False,
            overwrite=False,
            json_output=False,
        )

        mock_wallet.regenerate_hotkey.assert_called_once()
