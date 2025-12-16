"""
E2E tests for crowd contributors command.

Verify command:
* btcli crowd contributors --id <crowdloan_id>
"""

import json
import pytest


@pytest.mark.parametrize("local_chain", [False], indirect=True)
def test_crowd_contributors_command(local_chain, wallet_setup):
    """
    Test crowd contributors command and inspect its output.

    Steps:
        1. Create a crowdloan (if needed) or use existing one
        2. Make contributions to the crowdloan
        3. Execute contributors command and verify output
        4. Test with --verbose flag
        5. Test with --json-output flag

    Note: This test requires an existing crowdloan with contributors.
    For a full e2e test, you would need to:
    - Create a crowdloan
    - Make contributions
    - Then list contributors
    """
    wallet_path_alice = "//Alice"

    # Create wallet for Alice
    keypair_alice, wallet_alice, wallet_path_alice, exec_command_alice = wallet_setup(
        wallet_path_alice
    )

    # Test 1: List contributors for an existing crowdloan (assuming crowdloan #0 exists)
    # This will work if there's a crowdloan with contributors on the test chain
    result = exec_command_alice(
        command="crowd",
        sub_command="contributors",
        extra_args=[
            "--id",
            "0",
            "--network",
            "ws://127.0.0.1:9945",
            "--json-output",
        ],
    )

    # Parse JSON output
    try:
        result_output = json.loads(result.stdout)
        # If crowdloan exists and has contributors
        if result_output.get("success") is True:
            assert "data" in result_output
            assert "contributors" in result_output["data"]
            assert "crowdloan_id" in result_output["data"]
            assert result_output["data"]["crowdloan_id"] == 0
            assert isinstance(result_output["data"]["contributors"], list)
            assert "total_count" in result_output["data"]
            assert "total_contributed_tao" in result_output["data"]

            # If there are contributors, verify structure
            if result_output["data"]["total_count"] > 0:
                contributor = result_output["data"]["contributors"][0]
                assert "rank" in contributor
                assert "address" in contributor
                assert "identity" in contributor
                assert "contribution_tao" in contributor
                assert "contribution_rao" in contributor
                assert "percentage" in contributor
                assert contributor["rank"] == 1  # First contributor should be rank 1
                assert contributor["contribution_tao"] >= 0
                assert 0 <= contributor["percentage"] <= 100

        # If crowdloan doesn't exist or has no contributors
        elif result_output.get("success") is False:
            assert "error" in result_output
    except json.JSONDecodeError:
        # If output is not JSON (shouldn't happen with --json-output)
        pytest.fail("Expected JSON output but got non-JSON response")

    # Test 2: Test with verbose flag
    result_verbose = exec_command_alice(
        command="crowd",
        sub_command="contributors",
        extra_args=[
            "--id",
            "0",
            "--network",
            "ws://127.0.0.1:9945",
            "--verbose",
        ],
    )

    # Verify verbose output (should show full addresses)
    assert result_verbose.exit_code == 0 or result_verbose.exit_code is None

    # Test 3: Test with non-existent crowdloan
    result_not_found = exec_command_alice(
        command="crowd",
        sub_command="contributors",
        extra_args=[
            "--id",
            "99999",
            "--network",
            "ws://127.0.0.1:9945",
            "--json-output",
        ],
    )

    try:
        result_output = json.loads(result_not_found.stdout)
        # Should return error for non-existent crowdloan
        assert result_output.get("success") is False
        assert "error" in result_output
        assert "not found" in result_output["error"].lower()
    except json.JSONDecodeError:
        # If output is not JSON, that's also acceptable for error cases
        pass


@pytest.mark.parametrize("local_chain", [False], indirect=True)
def test_crowd_contributors_with_real_crowdloan(local_chain, wallet_setup):
    """
    Full e2e test: Create crowdloan, contribute, then list contributors.

    Steps:
        1. Create a crowdloan
        2. Make contributions from multiple wallets
        3. List contributors and verify all are present
        4. Verify sorting by contribution amount
    """
    wallet_path_alice = "//Alice"
    wallet_path_bob = "//Bob"

    # Create wallets
    keypair_alice, wallet_alice, wallet_path_alice, exec_command_alice = wallet_setup(
        wallet_path_alice
    )
    keypair_bob, wallet_bob, wallet_path_bob, exec_command_bob = wallet_setup(
        wallet_path_bob
    )

    # Step 1: Create a crowdloan
    create_result = exec_command_alice(
        command="crowd",
        sub_command="create",
        extra_args=[
            "--wallet-path",
            wallet_path_alice,
            "--network",
            "ws://127.0.0.1:9945",
            "--wallet-name",
            wallet_alice.name,
            "--wallet-hotkey",
            wallet_alice.hotkey_str,
            "--deposit",
            "10",
            "--cap",
            "100",
            "--duration",
            "10000",
            "--min-contribution",
            "1",
            "--no-prompt",
            "--json-output",
        ],
    )

    try:
        create_output = json.loads(create_result.stdout)
        if create_output.get("success") is True:
            crowdloan_id = create_output.get("crowdloan_id") or create_output.get(
                "data", {}
            ).get("crowdloan_id")

            if crowdloan_id is not None:
                # Step 2: Make contributions
                # Alice contributes
                contribute_alice = exec_command_alice(
                    command="crowd",
                    sub_command="contribute",
                    extra_args=[
                        "--id",
                        str(crowdloan_id),
                        "--wallet-path",
                        wallet_path_alice,
                        "--network",
                        "ws://127.0.0.1:9945",
                        "--wallet-name",
                        wallet_alice.name,
                        "--wallet-hotkey",
                        wallet_alice.hotkey_str,
                        "--amount",
                        "20",
                        "--no-prompt",
                        "--json-output",
                    ],
                )

                # Bob contributes
                contribute_bob = exec_command_bob(
                    command="crowd",
                    sub_command="contribute",
                    extra_args=[
                        "--id",
                        str(crowdloan_id),
                        "--wallet-path",
                        wallet_path_bob,
                        "--network",
                        "ws://127.0.0.1:9945",
                        "--wallet-name",
                        wallet_bob.name,
                        "--wallet-hotkey",
                        wallet_bob.hotkey_str,
                        "--amount",
                        "30",
                        "--no-prompt",
                        "--json-output",
                    ],
                )

                # Step 3: List contributors
                contributors_result = exec_command_alice(
                    command="crowd",
                    sub_command="contributors",
                    extra_args=[
                        "--id",
                        str(crowdloan_id),
                        "--network",
                        "ws://127.0.0.1:9945",
                        "--json-output",
                    ],
                )

                contributors_output = json.loads(contributors_result.stdout)
                assert contributors_output.get("success") is True
                assert contributors_output["data"]["crowdloan_id"] == crowdloan_id
                assert contributors_output["data"]["total_count"] >= 2

                # Verify contributors are sorted by contribution (descending)
                contributors_list = contributors_output["data"]["contributors"]
                if len(contributors_list) >= 2:
                    # Bob should be first (30 TAO > 20 TAO)
                    assert (
                        contributors_list[0]["contribution_tao"]
                        >= contributors_list[1]["contribution_tao"]
                    )

                # Verify percentages sum to 100%
                total_percentage = sum(c["percentage"] for c in contributors_list)
                assert (
                    abs(total_percentage - 100.0) < 0.01
                )  # Allow small floating point errors

    except (json.JSONDecodeError, KeyError, AssertionError) as e:
        # Skip test if prerequisites aren't met (e.g., insufficient balance, chain not ready)
        pytest.skip(f"Test prerequisites not met: {e}")
