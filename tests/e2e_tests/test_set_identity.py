import json
from unittest.mock import MagicMock, AsyncMock, patch


"""
Verify commands:
* btcli s create
* btcli s set-identity
* btcli s get-identity
"""


def test_set_id(local_chain, wallet_setup):
    """
    Tests that the user is prompted to confirm that the incorrect text/html URL is
    indeed the one they wish to set as their logo URL, and that when the MIME type is 'image/jpeg'
    they are not given this prompt.
    """
    wallet_path_alice = "//Alice"
    netuid = 2

    # Create wallet for Alice
    keypair_alice, wallet_alice, wallet_path_alice, exec_command_alice = wallet_setup(
        wallet_path_alice
    )
    # Register a subnet with sudo as Alice
    result = exec_command_alice(
        command="subnets",
        sub_command="create",
        extra_args=[
            "--wallet-path",
            wallet_path_alice,
            "--chain",
            "ws://127.0.0.1:9945",
            "--wallet-name",
            wallet_alice.name,
            "--wallet-hotkey",
            wallet_alice.hotkey_str,
            "--subnet-name",
            "Test Subnet",
            "--repo",
            "https://github.com/username/repo",
            "--contact",
            "alice@opentensor.dev",
            "--url",
            "https://testsubnet.com",
            "--discord",
            "alice#1234",
            "--description",
            "A test subnet for e2e testing",
            "--additional-info",
            "Created by Alice",
            "--logo-url",
            "https://testsubnet.com/logo.png",
            "--no-prompt",
            "--json-output",
        ],
    )
    result_output = json.loads(result.stdout)
    assert result_output["success"] is True

    mock_response = MagicMock()
    mock_response.status = 200
    mock_response.content_type = "text/html"  # bad MIME type
    mock_response.__aenter__ = AsyncMock(return_value=mock_response)
    mock_response.__aexit__ = AsyncMock(return_value=None)

    mock_session = MagicMock()
    mock_session.get = MagicMock(return_value=mock_response)
    mock_session.__aenter__ = AsyncMock(return_value=mock_session)
    mock_session.__aexit__ = AsyncMock(return_value=None)

    with patch("aiohttp.ClientSession", return_value=mock_session):
        set_identity = exec_command_alice(
            "subnets",
            "set-identity",
            extra_args=[
                "--wallet-path",
                wallet_path_alice,
                "--wallet-name",
                wallet_alice.name,
                "--hotkey",
                wallet_alice.hotkey_str,
                "--chain",
                "ws://127.0.0.1:9945",
                "--netuid",
                str(netuid),
                "--subnet-name",
                sn_name := "Test Subnet",
                "--github-repo",
                sn_github := "https://github.com/username/repo",
                "--subnet-contact",
                sn_contact := "alice@opentensor.dev",
                "--subnet-url",
                sn_url := "https://testsubnet.com",
                "--discord",
                sn_discord := "alice#1234",
                "--description",
                sn_description := "A test subnet for e2e testing",
                "--logo-url",
                sn_logo_url := "https://testsubnet.com/logo.png",
                "--additional-info",
                sn_add_info := "Created by Alice",
                "--prompt",
            ],
            inputs=["Y", "Y"],
        )
    assert (
        f"Are you sure you want to use {sn_logo_url} as your image URL?"
        in set_identity.stdout
    )
    get_identity = exec_command_alice(
        "subnets",
        "get-identity",
        extra_args=[
            "--chain",
            "ws://127.0.0.1:9945",
            "--netuid",
            netuid,
            "--json-output",
        ],
    )
    get_identity_output = json.loads(get_identity.stdout)
    assert get_identity_output["subnet_name"] == sn_name
    assert get_identity_output["github_repo"] == sn_github
    assert get_identity_output["subnet_contact"] == sn_contact
    assert get_identity_output["subnet_url"] == sn_url
    assert get_identity_output["discord"] == sn_discord
    assert get_identity_output["description"] == sn_description
    assert get_identity_output["logo_url"] == sn_logo_url
    assert get_identity_output["additional"] == sn_add_info

    mock_response = MagicMock()
    mock_response.status = 200
    mock_response.content_type = "image/jpeg"  # good MIME type
    mock_response.__aenter__ = AsyncMock(return_value=mock_response)
    mock_response.__aexit__ = AsyncMock(return_value=None)

    mock_session = MagicMock()
    mock_session.get = MagicMock(return_value=mock_response)
    mock_session.__aenter__ = AsyncMock(return_value=mock_session)
    mock_session.__aexit__ = AsyncMock(return_value=None)
    with patch("aiohttp.ClientSession", return_value=mock_session):
        set_identity = exec_command_alice(
            "subnets",
            "set-identity",
            extra_args=[
                "--wallet-path",
                wallet_path_alice,
                "--wallet-name",
                wallet_alice.name,
                "--hotkey",
                wallet_alice.hotkey_str,
                "--chain",
                "ws://127.0.0.1:9945",
                "--netuid",
                str(netuid),
                "--subnet-name",
                sn_name := "Test Subnet",
                "--github-repo",
                sn_github := "https://github.com/username/repo",
                "--subnet-contact",
                sn_contact := "alice@opentensor.dev",
                "--subnet-url",
                sn_url := "https://testsubnet.com",
                "--discord",
                sn_discord := "alice#1234",
                "--description",
                sn_description := "A test subnet for e2e testing",
                "--logo-url",
                sn_logo_url := "https://testsubnet.com/logo.png",
                "--additional-info",
                sn_add_info := "Created by Alice",
                "--prompt",
            ],
            inputs=["Y"],
        )
    assert (
        f"Are you sure you want to use {sn_logo_url} as your image URL?"
        not in set_identity.stdout
    )
    get_identity = exec_command_alice(
        "subnets",
        "get-identity",
        extra_args=[
            "--chain",
            "ws://127.0.0.1:9945",
            "--netuid",
            netuid,
            "--json-output",
        ],
    )
    get_identity_output = json.loads(get_identity.stdout)
    assert get_identity_output["subnet_name"] == sn_name
    assert get_identity_output["github_repo"] == sn_github
    assert get_identity_output["subnet_contact"] == sn_contact
    assert get_identity_output["subnet_url"] == sn_url
    assert get_identity_output["discord"] == sn_discord
    assert get_identity_output["description"] == sn_description
    assert get_identity_output["logo_url"] == sn_logo_url
    assert get_identity_output["additional"] == sn_add_info
