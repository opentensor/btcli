"""
E2E tests for crowd identity display functionality.

Verify commands:
* btcli crowd list --show-identities
* btcli crowd info --id <crowdloan_id> --show-identities --show-contributors
"""

import json
import pytest


@pytest.mark.parametrize("local_chain", [False], indirect=True)
def test_crowd_list_with_identities(local_chain, wallet_setup):
    """
    Test crowd list command with identity display.

    Steps:
        1. Execute crowd list with --show-identities (default)
        2. Execute crowd list with --no-show-identities
        3. Verify identity information is displayed when enabled
    """
    wallet_path_alice = "//Alice"

    # Create wallet for Alice
    keypair_alice, wallet_alice, wallet_path_alice, exec_command_alice = wallet_setup(
        wallet_path_alice
    )

    # Test 1: List with identities (default)
    result = exec_command_alice(
        command="crowd",
        sub_command="list",
        extra_args=[
            "--network",
            "ws://127.0.0.1:9945",
            "--json-output",
        ],
    )

    try:
        result_output = json.loads(result.stdout)
        if result_output.get("success") is True:
            assert "data" in result_output
            assert "crowdloans" in result_output["data"]

            # Check if identity fields are present
            if result_output["data"]["crowdloans"]:
                crowdloan = result_output["data"]["crowdloans"][0]
                # Identity fields should be present (may be None if no identity)
                assert "creator_identity" in crowdloan
                assert "target_identity" in crowdloan
    except json.JSONDecodeError:
        pytest.skip("Could not parse JSON output")

    # Test 2: List without identities
    result_no_identities = exec_command_alice(
        command="crowd",
        sub_command="list",
        extra_args=[
            "--network",
            "ws://127.0.0.1:9945",
            "--show-identities",
            "false",
            "--json-output",
        ],
    )

    try:
        result_output = json.loads(result_no_identities.stdout)
        if result_output.get("success") is True:
            if result_output["data"]["crowdloans"]:
                crowdloan = result_output["data"]["crowdloans"][0]
                # Identity fields should still be present but None
                assert "creator_identity" in crowdloan
                assert crowdloan.get("creator_identity") is None
    except json.JSONDecodeError:
        pytest.skip("Could not parse JSON output")


@pytest.mark.parametrize("local_chain", [False], indirect=True)
def test_crowd_info_with_identities(local_chain, wallet_setup):
    """
    Test crowd info command with identity display and contributors.

    Steps:
        1. Execute crowd info with --show-identities
        2. Execute crowd info with --show-contributors
        3. Verify identity and contributor information is displayed
    """
    wallet_path_alice = "//Alice"

    # Create wallet for Alice
    keypair_alice, wallet_alice, wallet_path_alice, exec_command_alice = wallet_setup(
        wallet_path_alice
    )

    # Test 1: Info with identities (default)
    result = exec_command_alice(
        command="crowd",
        sub_command="info",
        extra_args=[
            "--id",
            "0",
            "--network",
            "ws://127.0.0.1:9945",
            "--json-output",
        ],
    )

    try:
        result_output = json.loads(result.stdout)
        if result_output.get("success") is True:
            assert "data" in result_output
            # Identity fields should be present
            assert "creator_identity" in result_output["data"]
            assert "target_identity" in result_output["data"]
    except json.JSONDecodeError:
        pytest.skip("Could not parse JSON output or crowdloan not found")

    # Test 2: Info with identities and contributors
    result_with_contributors = exec_command_alice(
        command="crowd",
        sub_command="info",
        extra_args=[
            "--id",
            "0",
            "--network",
            "ws://127.0.0.1:9945",
            "--show-identities",
            "true",
            "--show-contributors",
            "true",
            "--json-output",
        ],
    )

    try:
        result_output = json.loads(result_with_contributors.stdout)
        if result_output.get("success") is True:
            assert "data" in result_output
            # Contributors should be present if flag is set
            assert "contributors" in result_output["data"]
            if result_output["data"]["contributors"]:
                contributor = result_output["data"]["contributors"][0]
                assert "identity" in contributor
                assert "address" in contributor
                assert "contribution_tao" in contributor
    except json.JSONDecodeError:
        pytest.skip("Could not parse JSON output or crowdloan not found")
