"""Tests for wallet creation safety in new_coldkey() and wallet_create()."""

import json

import pytest
from unittest.mock import MagicMock, patch
from bittensor_wallet import Keypair
from bittensor_wallet.errors import KeyFileError


MODULE = "bittensor_cli.src.commands.wallets"


def _mock_wallet():
    wallet = MagicMock()
    wallet.name = "test_wallet"
    wallet.path = "/tmp/wallets"
    wallet.hotkey_str = "default"
    wallet.coldkeypub.ss58_address = "5GrwvaEF5zXb26Fz9rcQpDWS57CtERHpNehXCPcNoHGKutQY"
    wallet.hotkeypub.ss58_address = "5HGjWAeFDfFCWPsjFQdVV2Msvz2XtMktvgocEZcCj68kUMaw"
    return wallet


# ---------------------------------------------------------------------------
# new_coldkey — URI path: missing return after TypeError
# ---------------------------------------------------------------------------


class TestNewColdkeyUriFailure:
    """Regression tests for new_coldkey() when create_from_uri raises TypeError."""

    @pytest.mark.asyncio
    async def test_returns_early_on_invalid_uri(self):
        """new_coldkey must return without calling set_coldkey when URI is invalid."""
        from bittensor_cli.src.commands.wallets import new_coldkey

        wallet = _mock_wallet()
        with patch.object(Keypair, "create_from_uri", side_effect=TypeError("bad uri")):
            await new_coldkey(
                wallet=wallet,
                n_words=12,
                use_password=False,
                uri="//bad",
                json_output=False,
            )

        wallet.set_coldkey.assert_not_called()
        wallet.set_coldkeypub.assert_not_called()

    @pytest.mark.asyncio
    async def test_emits_json_error_on_invalid_uri(self):
        """new_coldkey must emit JSON error output when URI fails and json_output is on."""
        from bittensor_cli.src.commands.wallets import new_coldkey

        wallet = _mock_wallet()
        with (
            patch.object(Keypair, "create_from_uri", side_effect=TypeError("bad uri")),
            patch(f"{MODULE}.json_console") as mock_json,
        ):
            await new_coldkey(
                wallet=wallet,
                n_words=12,
                use_password=False,
                uri="//bad",
                json_output=True,
            )

        mock_json.print.assert_called_once()
        output = json.loads(mock_json.print.call_args[0][0])
        assert output["success"] is False
        assert "bad uri" in output["error"]
        assert output["data"] is None

    @pytest.mark.asyncio
    async def test_uses_overwrite_parameter_on_valid_uri(self):
        """new_coldkey must pass the overwrite parameter to set_coldkey, not hardcode False."""
        from bittensor_cli.src.commands.wallets import new_coldkey

        wallet = _mock_wallet()
        fake_keypair = MagicMock(spec=Keypair)
        with patch.object(Keypair, "create_from_uri", return_value=fake_keypair):
            await new_coldkey(
                wallet=wallet,
                n_words=12,
                use_password=False,
                uri="//Alice",
                overwrite=True,
                json_output=False,
            )

        wallet.set_coldkey.assert_called_once_with(
            keypair=fake_keypair, encrypt=False, overwrite=True
        )
        wallet.set_coldkeypub.assert_called_once_with(
            keypair=fake_keypair, encrypt=False, overwrite=True
        )


# ---------------------------------------------------------------------------
# wallet_create — URI path: duplicate set_coldkeypub + success msg after failure
# ---------------------------------------------------------------------------


class TestWalletCreateUri:
    """Tests for wallet_create() URI code path."""

    @pytest.mark.asyncio
    async def test_set_coldkeypub_called_once_on_success(self):
        """wallet_create must call set_coldkeypub exactly once, not twice."""
        from bittensor_cli.src.commands.wallets import wallet_create

        wallet = _mock_wallet()
        fake_keypair = MagicMock(spec=Keypair)
        with patch.object(Keypair, "create_from_uri", return_value=fake_keypair):
            await wallet_create(
                wallet=wallet,
                uri="//Alice",
                json_output=False,
            )

        assert wallet.set_coldkeypub.call_count == 1

    @pytest.mark.asyncio
    async def test_no_success_message_on_uri_failure(self):
        """wallet_create must not print success message when URI creation fails."""
        from bittensor_cli.src.commands.wallets import wallet_create

        wallet = _mock_wallet()
        with (
            patch.object(Keypair, "create_from_uri", side_effect=TypeError("bad")),
            patch(f"{MODULE}.console") as mock_console,
        ):
            await wallet_create(wallet=wallet, uri="//bad", json_output=False)

        for c in mock_console.print.call_args_list:
            assert "Wallet created" not in str(c)

    @pytest.mark.asyncio
    async def test_json_reports_failure_on_uri_error(self):
        """wallet_create JSON output must report failure when URI is invalid."""
        from bittensor_cli.src.commands.wallets import wallet_create

        wallet = _mock_wallet()
        with (
            patch.object(Keypair, "create_from_uri", side_effect=ValueError("invalid")),
            patch(f"{MODULE}.json_console") as mock_json,
        ):
            await wallet_create(wallet=wallet, uri="//bad", json_output=True)

        mock_json.print.assert_called_once()
        output = json.loads(mock_json.print.call_args[0][0])
        assert output["success"] is False
        assert output["error"] != ""


# ---------------------------------------------------------------------------
# wallet_create — mnemonic path: orphan hotkey on coldkey failure
# ---------------------------------------------------------------------------


class TestWalletCreateMnemonicColdkeyFailure:
    """Tests for wallet_create() when coldkey creation fails in the mnemonic path."""

    @pytest.mark.asyncio
    async def test_no_hotkey_created_when_coldkey_fails(self):
        """wallet_create must not attempt hotkey creation if coldkey creation fails."""
        from bittensor_cli.src.commands.wallets import wallet_create

        wallet = _mock_wallet()
        wallet.create_new_coldkey = MagicMock(side_effect=KeyFileError("not writable"))
        wallet.create_new_hotkey = MagicMock()

        await wallet_create(wallet=wallet, json_output=False)

        wallet.create_new_coldkey.assert_called_once()
        wallet.create_new_hotkey.assert_not_called()

    @pytest.mark.asyncio
    async def test_json_reports_failure_when_coldkey_fails(self):
        """wallet_create JSON must report failure, not success, when coldkey fails."""
        from bittensor_cli.src.commands.wallets import wallet_create

        wallet = _mock_wallet()
        wallet.create_new_coldkey = MagicMock(side_effect=KeyFileError("not writable"))

        with patch(f"{MODULE}.json_console") as mock_json:
            await wallet_create(wallet=wallet, json_output=True)

        mock_json.print.assert_called_once()
        output = json.loads(mock_json.print.call_args[0][0])
        assert output["success"] is False
        assert "not writable" in output["error"]

    @pytest.mark.asyncio
    async def test_json_reports_success_when_both_keys_created(self):
        """wallet_create JSON must report success only when both keys succeed."""
        from bittensor_cli.src.commands.wallets import wallet_create

        wallet = _mock_wallet()
        wallet.create_new_coldkey = MagicMock()
        wallet.create_new_hotkey = MagicMock()

        with patch(f"{MODULE}.json_console") as mock_json:
            await wallet_create(wallet=wallet, json_output=True)

        mock_json.print.assert_called_once()
        output = json.loads(mock_json.print.call_args[0][0])
        assert output["success"] is True
        assert output["data"]["coldkey_ss58"] == wallet.coldkeypub.ss58_address
        assert output["data"]["hotkey_ss58"] == wallet.hotkeypub.ss58_address

    @pytest.mark.asyncio
    async def test_hotkey_failure_reports_error(self):
        """wallet_create must report error when hotkey creation fails after coldkey succeeds."""
        from bittensor_cli.src.commands.wallets import wallet_create

        wallet = _mock_wallet()
        wallet.create_new_coldkey = MagicMock()
        wallet.create_new_hotkey = MagicMock(
            side_effect=KeyFileError("hotkey not writable")
        )

        with patch(f"{MODULE}.json_console") as mock_json:
            await wallet_create(wallet=wallet, json_output=True)

        output = json.loads(mock_json.print.call_args[0][0])
        assert output["success"] is False
        assert "hotkey not writable" in output["error"]
