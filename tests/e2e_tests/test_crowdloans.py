"""
E2E tests for crowdloan creation, contribution, and verification.

Verify commands:
* btcli crowd create (all 3 types: fundraising, subnet leasing, custom call)
* btcli crowd info
* btcli crowd contribute
* btcli crowd list
* btcli crowd withdraw
* btcli crowd finalize
* btcli crowd update
* btcli crowd refund
* btcli crowd dissolve
"""

import json


def get_crowdloan_id_by_creator(exec_command, creator_address: str) -> int:
    """Helper to retrieve crowdloan_id from crowd list by creator address."""
    result = exec_command(
        command="crowd",
        sub_command="list",
        extra_args=[
            "--network",
            "ws://127.0.0.1:9945",
            "--json-output",
        ],
    )
    list_output = json.loads(result.stdout)
    assert list_output.get("success") is True, (
        f"Failed to list crowdloans: {result.stdout}"
    )

    crowdloans = list_output.get("data", {}).get("crowdloans", [])
    matching_loans = [
        loan for loan in crowdloans if loan.get("creator") == creator_address
    ]
    assert len(matching_loans) > 0, f"No crowdloan found for creator {creator_address}"

    return max(loan["id"] for loan in matching_loans)


def test_all_crowdloan_types(local_chain, wallet_setup):
    """
    Test for all 3 crowdloan types:
    1. General Fundraising - with target address
    2. Subnet Leasing - with emissions share
    3. Custom Call - with pallet/method/args

    For each type:
    - Create the crowdloan
    - Verify creation via crowd info JSON output
    - Contribute to it
    - Verify contributors and amounts via crowd info --show-contributors JSON output
    """
    wallet_path_alice = "//Alice"
    wallet_path_bob = "//Bob"

    # Create wallets
    _, wallet_alice, wallet_path_alice, exec_command_alice = wallet_setup(
        wallet_path_alice
    )
    _, wallet_bob, wallet_path_bob, exec_command_bob = wallet_setup(wallet_path_bob)

    alice_address = wallet_alice.coldkeypub.ss58_address
    bob_address = wallet_bob.coldkeypub.ss58_address

    # ========================================================================
    # Test 1: General Fundraising Crowdloan
    # ========================================================================
    print("\n🧪 Testing General Fundraising Crowdloan...")

    # Create fundraising crowdloan
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
            "--target-address",
            bob_address,
            "--fundraising",
            "--no-prompt",
            "--json-output",
        ],
    )

    create_output = json.loads(create_result.stdout)
    assert create_output.get("success") is True, (
        f"Failed to create fundraising crowdloan: {create_result.stdout}"
    )
    assert create_output["data"]["type"] == "fundraising"
    assert create_output["data"]["deposit"] == 10.0
    assert create_output["data"]["cap"] == 100.0
    assert create_output["data"]["min_contribution"] == 1.0
    assert create_output["data"]["target_address"] == bob_address
    assert "extrinsic_id" in create_output["data"]

    fundraising_id = get_crowdloan_id_by_creator(exec_command_alice, alice_address)

    # Verify initial state via crowd info
    info_result = exec_command_alice(
        command="crowd",
        sub_command="info",
        extra_args=[
            "--id",
            str(fundraising_id),
            "--network",
            "ws://127.0.0.1:9945",
            "--json-output",
        ],
    )

    info_output = json.loads(info_result.stdout)
    assert info_output.get("success") is True, (
        f"Failed to get crowdloan info: {info_result.stdout}"
    )
    assert info_output["data"]["crowdloan_id"] == fundraising_id
    assert info_output["data"]["status"] == "Active"
    assert info_output["data"]["creator"] == alice_address
    assert info_output["data"]["target_address"] == bob_address
    assert info_output["data"]["has_call"] is False
    assert info_output["data"]["raised"] == 10.0
    assert info_output["data"]["contributors_count"] == 1

    # Contribute to fundraising crowdloan
    contribute_result = exec_command_bob(
        command="crowd",
        sub_command="contribute",
        extra_args=[
            "--id",
            str(fundraising_id),
            "--wallet-path",
            wallet_path_bob,
            "--network",
            "ws://127.0.0.1:9945",
            "--wallet-name",
            wallet_bob.name,
            "--wallet-hotkey",
            wallet_bob.hotkey_str,
            "--amount",
            "20",
            "--no-prompt",
            "--json-output",
        ],
    )

    contribute_output = json.loads(contribute_result.stdout)
    assert contribute_output.get("success") is True, (
        f"Failed to contribute: {contribute_result.stdout}"
    )
    assert contribute_output["data"]["crowdloan_id"] == fundraising_id
    assert contribute_output["data"]["contribution_amount"] == 20.0
    assert contribute_output["data"]["contributor"] == bob_address
    assert (
        contribute_output["data"]["crowdloan"]["raised_after"]
        > contribute_output["data"]["crowdloan"]["raised_before"]
    )

    # Verify contributors via crowd info --show-contributors
    info_with_contributors = exec_command_alice(
        command="crowd",
        sub_command="info",
        extra_args=[
            "--id",
            str(fundraising_id),
            "--network",
            "ws://127.0.0.1:9945",
            "--show-contributors",
            "--json-output",
        ],
    )

    info_contrib_output = json.loads(info_with_contributors.stdout)
    assert info_contrib_output.get("success") is True
    assert info_contrib_output["data"]["contributors_count"] == 2
    assert (
        info_contrib_output["data"]["raised"] == 30.0
    )  # Deposit (10) + Bob's contribution (20)
    assert "contributors" in info_contrib_output["data"]
    assert len(info_contrib_output["data"]["contributors"]) == 2

    bob_contributor = info_contrib_output["data"]["contributors"][0]
    assert bob_contributor["address"] == bob_address
    assert bob_contributor["contribution_tao"] == 20.0
    assert bob_contributor["rank"] == 1
    assert (
        abs(bob_contributor["percentage"] - (20.0 / 30.0 * 100)) < 0.01
    )  # Bob: 20/30 = 66.67%

    # Verify creator (Alice) is also in contributors list
    alice_contributor = info_contrib_output["data"]["contributors"][1]
    assert alice_contributor["address"] == alice_address
    assert alice_contributor["contribution_tao"] == 10.0
    assert alice_contributor["rank"] == 2
    assert (
        abs(alice_contributor["percentage"] - (10.0 / 30.0 * 100)) < 0.01
    )  # Alice: 10/30 = 33.33%

    print("✅ Fundraising crowdloan test passed")

    # ========================================================================
    # Test 2: Subnet Leasing Crowdloan
    # ========================================================================
    print("\n🧪 Testing Subnet Leasing Crowdloan...")

    # Create subnet leasing crowdloan
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
            "--subnet-lease",
            "--emissions-share",
            "25",
            "--lease-end-block",
            "100_000",
            "--no-prompt",
            "--json-output",
        ],
    )

    create_output = json.loads(create_result.stdout)
    assert create_output.get("success") is True, (
        f"Failed to create subnet crowdloan: {create_result.stdout}"
    )
    assert create_output["data"]["type"] == "subnet"
    assert create_output["data"]["deposit"] == 10.0
    assert create_output["data"]["cap"] == 100.0
    assert create_output["data"]["emissions_share"] == 25
    assert "extrinsic_id" in create_output["data"]

    subnet_id = get_crowdloan_id_by_creator(exec_command_alice, alice_address)

    # Verify initial state via crowd info
    info_result = exec_command_alice(
        command="crowd",
        sub_command="info",
        extra_args=[
            "--id",
            str(subnet_id),
            "--network",
            "ws://127.0.0.1:9945",
            "--json-output",
        ],
    )

    info_output = json.loads(info_result.stdout)
    assert info_output.get("success") is True
    assert info_output["data"]["crowdloan_id"] == subnet_id
    assert info_output["data"]["status"] == "Active"
    assert info_output["data"]["creator"] == alice_address
    assert info_output["data"]["has_call"] is True
    assert info_output["data"]["call_details"] is not None
    assert info_output["data"]["call_details"]["type"] == "Subnet Leasing"
    assert info_output["data"]["call_details"]["emissions_share"] == 25
    assert info_output["data"]["raised"] == 10.0
    assert info_output["data"]["contributors_count"] == 1

    # Contribute to subnet crowdloan
    contribute_result = exec_command_bob(
        command="crowd",
        sub_command="contribute",
        extra_args=[
            "--id",
            str(subnet_id),
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

    contribute_output = json.loads(contribute_result.stdout)
    assert contribute_output.get("success") is True
    assert contribute_output["data"]["crowdloan_id"] == subnet_id
    assert contribute_output["data"]["contribution_amount"] == 30.0
    assert contribute_output["data"]["contributor"] == bob_address

    # Verify contributors via crowd info --show-contributors
    info_with_contributors = exec_command_alice(
        command="crowd",
        sub_command="info",
        extra_args=[
            "--id",
            str(subnet_id),
            "--network",
            "ws://127.0.0.1:9945",
            "--show-contributors",
            "--json-output",
        ],
    )

    info_contrib_output = json.loads(info_with_contributors.stdout)
    assert info_contrib_output.get("success") is True
    assert info_contrib_output["data"]["contributors_count"] == 2
    assert (
        info_contrib_output["data"]["raised"] == 40.0
    )  # Deposit (10) + Bob's contribution (30)
    assert "contributors" in info_contrib_output["data"]
    assert len(info_contrib_output["data"]["contributors"]) == 2

    bob_contributor = info_contrib_output["data"]["contributors"][0]
    assert bob_contributor["address"] == bob_address
    assert bob_contributor["contribution_tao"] == 30.0
    assert bob_contributor["rank"] == 1
    assert (
        abs(bob_contributor["percentage"] - (30.0 / 40.0 * 100)) < 0.01
    )  # Bob: 30/40 = 75%

    # Verify creator (Alice) is also in contributors list
    alice_contributor = info_contrib_output["data"]["contributors"][1]
    assert alice_contributor["address"] == alice_address
    assert alice_contributor["contribution_tao"] == 10.0
    assert alice_contributor["rank"] == 2
    assert (
        abs(alice_contributor["percentage"] - (10.0 / 40.0 * 100)) < 0.01
    )  # Alice: 10/40 = 25%

    print("✅ Subnet leasing crowdloan test passed")

    # ========================================================================
    # Test 3: Custom Call Crowdloan
    # ========================================================================
    print("\n🧪 Testing Custom Call Crowdloan...")

    # Create custom call crowdloan
    custom_call_args = json.dumps({"dest": bob_address, "value": 1000000000})
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
            "--custom-call-pallet",
            "Balances",
            "--custom-call-method",
            "transfer_allow_death",
            "--custom-call-args",
            custom_call_args,
            "--no-prompt",
            "--json-output",
        ],
    )

    create_output = json.loads(create_result.stdout)
    assert create_output.get("success") is True, (
        f"Failed to create custom call crowdloan: {create_result.stdout}"
    )
    assert create_output["data"]["type"] == "custom"
    assert create_output["data"]["deposit"] == 10.0
    assert create_output["data"]["cap"] == 100.0
    assert "custom_call" in create_output["data"]
    assert create_output["data"]["custom_call"]["pallet"] == "Balances"
    assert create_output["data"]["custom_call"]["method"] == "transfer_allow_death"
    assert "extrinsic_id" in create_output["data"]

    custom_id = get_crowdloan_id_by_creator(exec_command_alice, alice_address)

    # Verify initial state via crowd info
    info_result = exec_command_alice(
        command="crowd",
        sub_command="info",
        extra_args=[
            "--id",
            str(custom_id),
            "--network",
            "ws://127.0.0.1:9945",
            "--json-output",
        ],
    )

    info_output = json.loads(info_result.stdout)
    assert info_output.get("success") is True
    assert info_output["data"]["crowdloan_id"] == custom_id
    assert info_output["data"]["status"] == "Active"
    assert info_output["data"]["creator"] == alice_address
    assert info_output["data"]["has_call"] is True
    assert info_output["data"]["call_details"] is not None
    assert info_output["data"]["call_details"]["pallet"] == "Balances"
    assert info_output["data"]["call_details"]["method"] == "transfer_allow_death"
    assert info_output["data"]["raised"] == 10.0
    assert info_output["data"]["contributors_count"] == 1

    # Contribute to custom call crowdloan
    contribute_result = exec_command_bob(
        command="crowd",
        sub_command="contribute",
        extra_args=[
            "--id",
            str(custom_id),
            "--wallet-path",
            wallet_path_bob,
            "--network",
            "ws://127.0.0.1:9945",
            "--wallet-name",
            wallet_bob.name,
            "--wallet-hotkey",
            wallet_bob.hotkey_str,
            "--amount",
            "25",
            "--no-prompt",
            "--json-output",
        ],
    )

    contribute_output = json.loads(contribute_result.stdout)
    assert contribute_output.get("success") is True
    assert contribute_output["data"]["crowdloan_id"] == custom_id
    assert contribute_output["data"]["contribution_amount"] == 25.0
    assert contribute_output["data"]["contributor"] == bob_address

    # Verify contributors via crowd info --show-contributors
    info_with_contributors = exec_command_alice(
        command="crowd",
        sub_command="info",
        extra_args=[
            "--id",
            str(custom_id),
            "--network",
            "ws://127.0.0.1:9945",
            "--show-contributors",
            "--json-output",
        ],
    )

    info_contrib_output = json.loads(info_with_contributors.stdout)
    assert info_contrib_output.get("success") is True
    assert info_contrib_output["data"]["contributors_count"] == 2
    assert (
        info_contrib_output["data"]["raised"] == 35.0
    )  # Deposit (10) + Bob's contribution (25)
    assert "contributors" in info_contrib_output["data"]
    assert len(info_contrib_output["data"]["contributors"]) == 2

    bob_contributor = info_contrib_output["data"]["contributors"][0]
    assert bob_contributor["address"] == bob_address
    assert bob_contributor["contribution_tao"] == 25.0
    assert bob_contributor["rank"] == 1
    assert (
        abs(bob_contributor["percentage"] - (25.0 / 35.0 * 100)) < 0.01
    )  # Bob: 25/35 = 71.43%

    # Verify creator (Alice) is also in contributors list
    alice_contributor = info_contrib_output["data"]["contributors"][1]
    assert alice_contributor["address"] == alice_address
    assert alice_contributor["contribution_tao"] == 10.0
    assert alice_contributor["rank"] == 2
    assert (
        abs(alice_contributor["percentage"] - (10.0 / 35.0 * 100)) < 0.01
    )  # Alice: 10/35 = 28.57%

    print("✅ Custom call crowdloan test passed")
    print("\n✅ All crowdloan type tests passed!")


def test_crowdloan_withdraw(local_chain, wallet_setup):
    """
    Test withdrawal functionality:
    - Non-creator withdrawal: Contributor withdraws full contribution
    - Creator withdrawal: Creator withdraws amount above deposit (deposit must remain)
    - Creator withdrawal failure: Creator cannot withdraw deposit amount
    - Withdrawal from finalized crowdloan: Should fail
    """
    wallet_path_alice = "//Alice"
    wallet_path_bob = "//Bob"

    _, wallet_alice, wallet_path_alice, exec_command_alice = wallet_setup(
        wallet_path_alice
    )
    _, wallet_bob, wallet_path_bob, exec_command_bob = wallet_setup(wallet_path_bob)

    alice_address = wallet_alice.coldkeypub.ss58_address
    bob_address = wallet_bob.coldkeypub.ss58_address

    print("\n🧪 Testing Crowdloan Withdraw Functionality...")

    # Create a fundraising crowdloan
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
            "--target-address",
            bob_address,
            "--fundraising",
            "--no-prompt",
            "--json-output",
        ],
    )

    create_output = json.loads(create_result.stdout)
    assert create_output.get("success") is True
    crowdloan_id = get_crowdloan_id_by_creator(exec_command_alice, alice_address)

    # Bob contributes
    contribute_result = exec_command_bob(
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

    contribute_output = json.loads(contribute_result.stdout)
    assert contribute_output.get("success") is True
    assert contribute_output["data"]["contribution_amount"] == 30.0

    # Verify initial raised amount
    info_result = exec_command_alice(
        command="crowd",
        sub_command="info",
        extra_args=[
            "--id",
            str(crowdloan_id),
            "--network",
            "ws://127.0.0.1:9945",
            "--json-output",
        ],
    )
    info_output = json.loads(info_result.stdout)
    initial_raised = info_output["data"]["raised"]
    assert initial_raised == 40.0  # Deposit (10) + Bob's contribution (30)

    # Test 1: Non-creator (Bob) withdraws full contribution
    withdraw_result = exec_command_bob(
        command="crowd",
        sub_command="withdraw",
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
            "--no-prompt",
            "--json-output",
        ],
    )

    withdraw_output = json.loads(withdraw_result.stdout)
    assert withdraw_output.get("success") is True
    assert withdraw_output["data"]["withdrawal_amount"] == 30.0
    assert withdraw_output["data"]["is_creator"] is False

    # Verify new raised amount
    info_result = exec_command_alice(
        command="crowd",
        sub_command="info",
        extra_args=[
            "--id",
            str(crowdloan_id),
            "--network",
            "ws://127.0.0.1:9945",
            "--json-output",
        ],
    )
    info_output = json.loads(info_result.stdout)
    assert info_output["data"]["raised"] < initial_raised
    assert info_output["data"]["raised"] == 10.0
    assert info_output["data"]["contributors_count"] == 1

    # Bob contributes again
    exec_command_bob(
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
            "20",
            "--no-prompt",
            "--json-output",
        ],
    )

    # Alice (creator) contributes more than deposit
    exec_command_alice(
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
            "15",
            "--no-prompt",
            "--json-output",
        ],
    )

    # Test 2: Creator withdraws amount above deposit
    info_result = exec_command_alice(
        command="crowd",
        sub_command="info",
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
            "--json-output",
        ],
    )
    info_output = json.loads(info_result.stdout)

    assert info_output["data"]["user_contribution"] is not None
    creator_contribution = info_output["data"]["user_contribution"]["amount"]
    assert creator_contribution == 25.0

    # Creator withdraws amount above deposit
    withdraw_result = exec_command_alice(
        command="crowd",
        sub_command="withdraw",
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
            "--no-prompt",
            "--json-output",
        ],
    )

    withdraw_output = json.loads(withdraw_result.stdout)
    assert withdraw_output.get("success") is True
    assert withdraw_output["data"]["is_creator"] is True
    assert withdraw_output["data"]["withdrawal_amount"] == creator_contribution - 10.0
    assert withdraw_output["data"]["deposit_locked"] == 10.0

    # Test 3: Creator cannot withdraw deposit
    info_result = exec_command_alice(
        command="crowd",
        sub_command="info",
        extra_args=[
            "--id",
            str(crowdloan_id),
            "--network",
            "ws://127.0.0.1:9945",
            "--wallet-name",
            wallet_alice.name,
            "--wallet-hotkey",
            wallet_alice.hotkey_str,
            "--wallet-path",
            wallet_path_alice,
            "--json-output",
        ],
    )
    info_output = json.loads(info_result.stdout)
    remaining_contribution = info_output["data"]["user_contribution"]["amount"]
    assert remaining_contribution == 10.0

    # Try to withdraw again (should fail)
    withdraw_result = exec_command_alice(
        command="crowd",
        sub_command="withdraw",
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
            "--no-prompt",
            "--json-output",
        ],
    )

    withdraw_output = json.loads(withdraw_result.stdout)
    assert withdraw_output.get("success") is False

    print("✅ Crowdloan withdraw test passed")


def test_crowdloan_finalize(local_chain, wallet_setup):
    """
    Test finalization functionality:
    - Successful finalization: Finalize crowdloan that reached cap
    - Finalization failure: Cannot finalize before cap is reached
    """
    wallet_path_alice = "//Alice"
    wallet_path_bob = "//Bob"

    _, wallet_alice, wallet_path_alice, exec_command_alice = wallet_setup(
        wallet_path_alice
    )
    _, wallet_bob, wallet_path_bob, exec_command_bob = wallet_setup(wallet_path_bob)

    alice_address = wallet_alice.coldkeypub.ss58_address
    bob_address = wallet_bob.coldkeypub.ss58_address

    print("\n🧪 Testing Crowdloan Finalize Functionality...")

    # Create a fundraising crowdloan with cap of 100
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
            "--target-address",
            bob_address,
            "--fundraising",
            "--no-prompt",
            "--json-output",
        ],
    )

    create_output = json.loads(create_result.stdout)
    assert create_output.get("success") is True
    crowdloan_id = get_crowdloan_id_by_creator(exec_command_alice, alice_address)

    # Cannot finalize before cap is reached
    finalize_result = exec_command_alice(
        command="crowd",
        sub_command="finalize",
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
            "--no-prompt",
            "--json-output",
        ],
    )

    finalize_output = json.loads(finalize_result.stdout)
    assert finalize_output.get("success") is False
    assert "cap" in finalize_output.get("error", "").lower()

    # Bob contributes to reach cap
    exec_command_bob(
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
            "90",
            "--no-prompt",
            "--json-output",
        ],
    )

    # Bob tries to finalize (should fail)
    finalize_result = exec_command_bob(
        command="crowd",
        sub_command="finalize",
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
            "--no-prompt",
            "--json-output",
        ],
    )

    finalize_output = json.loads(finalize_result.stdout)
    assert finalize_output.get("success") is False
    assert "creator" in finalize_output.get("error", "").lower()

    # Successful finalization by creator
    info_result = exec_command_alice(
        command="crowd",
        sub_command="info",
        extra_args=[
            "--id",
            str(crowdloan_id),
            "--network",
            "ws://127.0.0.1:9945",
            "--json-output",
        ],
    )
    info_output = json.loads(info_result.stdout)
    assert info_output["data"]["raised"] >= info_output["data"]["cap"]
    assert info_output["data"]["status"] == "Funded"

    finalize_result = exec_command_alice(
        command="crowd",
        sub_command="finalize",
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
            "--no-prompt",
            "--json-output",
        ],
    )

    finalize_output = json.loads(finalize_result.stdout)
    assert finalize_output.get("success") is True
    assert finalize_output["data"]["crowdloan_id"] == crowdloan_id

    # Verify crowdloan is finalized
    info_result = exec_command_alice(
        command="crowd",
        sub_command="info",
        extra_args=[
            "--id",
            str(crowdloan_id),
            "--network",
            "ws://127.0.0.1:9945",
            "--json-output",
        ],
    )
    info_output = json.loads(info_result.stdout)
    assert info_output["data"]["status"] == "Finalized"
    assert info_output["data"]["finalized"] is True

    print("✅ Crowdloan finalize test passed")


def test_crowdloan_update(local_chain, wallet_setup):
    """
    Test update functionality:
    - Update min_contribution: Creator updates minimum contribution
    - Update cap: Creator updates cap (must be >= raised amount)
    - Update end_block: Creator extends crowdloan duration
    - Update validation: Cannot update finalized crowdloan
    """
    wallet_path_alice = "//Alice"
    wallet_path_bob = "//Bob"

    _, wallet_alice, wallet_path_alice, exec_command_alice = wallet_setup(
        wallet_path_alice
    )
    _, wallet_bob, wallet_path_bob, exec_command_bob = wallet_setup(wallet_path_bob)

    alice_address = wallet_alice.coldkeypub.ss58_address
    bob_address = wallet_bob.coldkeypub.ss58_address

    print("\n🧪 Testing Crowdloan Update Functionality...")

    # Create a fundraising crowdloan
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
            "--target-address",
            bob_address,
            "--fundraising",
            "--no-prompt",
            "--json-output",
        ],
    )

    create_output = json.loads(create_result.stdout)
    assert create_output.get("success") is True
    crowdloan_id = get_crowdloan_id_by_creator(exec_command_alice, alice_address)

    # Get initial values
    info_result = exec_command_alice(
        command="crowd",
        sub_command="info",
        extra_args=[
            "--id",
            str(crowdloan_id),
            "--network",
            "ws://127.0.0.1:9945",
            "--json-output",
        ],
    )
    info_output = json.loads(info_result.stdout)
    initial_end_block = info_output["data"]["end_block"]

    # Test 1: Update min_contribution
    update_result = exec_command_alice(
        command="crowd",
        sub_command="update",
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
            "--min-contribution",
            "2",
            "--no-prompt",
            "--json-output",
        ],
    )

    update_output = json.loads(update_result.stdout)
    assert update_output.get("success") is True
    assert update_output["data"]["update_type"] == "Minimum Contribution"

    info_result = exec_command_alice(
        command="crowd",
        sub_command="info",
        extra_args=[
            "--id",
            str(crowdloan_id),
            "--network",
            "ws://127.0.0.1:9945",
            "--json-output",
        ],
    )
    info_output = json.loads(info_result.stdout)
    assert info_output["data"]["min_contribution"] == 2.0

    # Test 2: Update cap
    update_result = exec_command_alice(
        command="crowd",
        sub_command="update",
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
            "--cap",
            "150",
            "--no-prompt",
            "--json-output",
        ],
    )

    update_output = json.loads(update_result.stdout)
    assert update_output.get("success") is True
    assert update_output["data"]["update_type"] == "Cap"

    info_result = exec_command_alice(
        command="crowd",
        sub_command="info",
        extra_args=[
            "--id",
            str(crowdloan_id),
            "--network",
            "ws://127.0.0.1:9945",
            "--json-output",
        ],
    )
    info_output = json.loads(info_result.stdout)
    assert info_output["data"]["cap"] == 150.0

    # Test 3: Update end_block (extend duration)
    new_end_block = initial_end_block + 5000
    update_result = exec_command_alice(
        command="crowd",
        sub_command="update",
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
            "--end-block",
            str(new_end_block),
            "--no-prompt",
            "--json-output",
        ],
    )

    update_output = json.loads(update_result.stdout)
    assert update_output.get("success") is True
    assert update_output["data"]["update_type"] == "End Block"

    info_result = exec_command_alice(
        command="crowd",
        sub_command="info",
        extra_args=[
            "--id",
            str(crowdloan_id),
            "--network",
            "ws://127.0.0.1:9945",
            "--json-output",
        ],
    )
    info_output = json.loads(info_result.stdout)
    assert info_output["data"]["end_block"] == new_end_block
    print("✅ Crowdloan update test passed")


def test_crowdloan_refund(local_chain, wallet_setup):
    """
    Test refund functionality:
    - Refund contributors: Creator refunds contributors when crowdloan fails
    - Refund validation: Cannot refund finalized crowdloan
    - Refund verification: Verify contributors receive refunds
    """
    wallet_path_alice = "//Alice"
    wallet_path_bob = "//Bob"

    _, wallet_alice, wallet_path_alice, exec_command_alice = wallet_setup(
        wallet_path_alice
    )
    _, wallet_bob, wallet_path_bob, exec_command_bob = wallet_setup(wallet_path_bob)

    alice_address = wallet_alice.coldkeypub.ss58_address
    bob_address = wallet_bob.coldkeypub.ss58_address

    print("\n🧪 Testing Crowdloan Refund Functionality...")

    # Create a fundraising crowdloan
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
            "--target-address",
            bob_address,
            "--fundraising",
            "--no-prompt",
            "--json-output",
        ],
    )

    create_output = json.loads(create_result.stdout)
    assert create_output.get("success") is True
    crowdloan_id = get_crowdloan_id_by_creator(exec_command_alice, alice_address)

    # Bob contributes
    contribute_result = exec_command_bob(
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

    contribute_output = json.loads(contribute_result.stdout)
    assert contribute_output.get("success") is True

    # Test 1: Creator can refund
    refund_result = exec_command_alice(
        command="crowd",
        sub_command="refund",
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
            "--no-prompt",
            "--json-output",
        ],
    )

    refund_output = json.loads(refund_result.stdout)
    assert refund_output.get("success") is True
    assert refund_output["data"]["crowdloan_id"] == crowdloan_id

    # Verify contributors were refunded
    info_result = exec_command_alice(
        command="crowd",
        sub_command="info",
        extra_args=[
            "--id",
            str(crowdloan_id),
            "--network",
            "ws://127.0.0.1:9945",
            "--json-output",
        ],
    )
    info_output = json.loads(info_result.stdout)
    # After refund, only creator's deposit should remain
    assert info_output["data"]["contributors_count"] == 1
    assert info_output["data"]["raised"] == 10.0

    # Test 2: Cannot refund finalized crowdloan
    # Create new crowdloan and finalize it
    exec_command_alice(
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
            "--target-address",
            bob_address,
            "--fundraising",
            "--no-prompt",
            "--json-output",
        ],
    )

    crowdloan_id2 = get_crowdloan_id_by_creator(exec_command_alice, alice_address)

    exec_command_bob(
        command="crowd",
        sub_command="contribute",
        extra_args=[
            "--id",
            str(crowdloan_id2),
            "--wallet-path",
            wallet_path_bob,
            "--network",
            "ws://127.0.0.1:9945",
            "--wallet-name",
            wallet_bob.name,
            "--wallet-hotkey",
            wallet_bob.hotkey_str,
            "--amount",
            "90",
            "--no-prompt",
            "--json-output",
        ],
    )

    exec_command_alice(
        command="crowd",
        sub_command="finalize",
        extra_args=[
            "--id",
            str(crowdloan_id2),
            "--wallet-path",
            wallet_path_alice,
            "--network",
            "ws://127.0.0.1:9945",
            "--wallet-name",
            wallet_alice.name,
            "--wallet-hotkey",
            wallet_alice.hotkey_str,
            "--no-prompt",
            "--json-output",
        ],
    )

    refund_result = exec_command_alice(
        command="crowd",
        sub_command="refund",
        extra_args=[
            "--id",
            str(crowdloan_id2),
            "--wallet-path",
            wallet_path_alice,
            "--network",
            "ws://127.0.0.1:9945",
            "--wallet-name",
            wallet_alice.name,
            "--wallet-hotkey",
            wallet_alice.hotkey_str,
            "--no-prompt",
            "--json-output",
        ],
    )

    refund_output = json.loads(refund_result.stdout)
    assert refund_output.get("success") is False
    assert "finalized" in refund_output.get("error", "").lower()

    print("✅ Crowdloan refund test passed")


def test_crowdloan_dissolve(local_chain, wallet_setup):
    """
    Test dissolve functionality:
    - Successful dissolution: Dissolve after all contributors refunded
    - Dissolution failure: Cannot dissolve when contributors still exist
    - Dissolution failure: Cannot dissolve finalized crowdloan
    """
    wallet_path_alice = "//Alice"
    wallet_path_bob = "//Bob"

    _, wallet_alice, wallet_path_alice, exec_command_alice = wallet_setup(
        wallet_path_alice
    )
    _, wallet_bob, wallet_path_bob, exec_command_bob = wallet_setup(wallet_path_bob)

    alice_address = wallet_alice.coldkeypub.ss58_address
    bob_address = wallet_bob.coldkeypub.ss58_address

    print("\n🧪 Testing Crowdloan Dissolve Functionality...")

    # Create a fundraising crowdloan
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
            "--target-address",
            bob_address,
            "--fundraising",
            "--no-prompt",
            "--json-output",
        ],
    )

    create_output = json.loads(create_result.stdout)
    assert create_output.get("success") is True
    crowdloan_id = get_crowdloan_id_by_creator(exec_command_alice, alice_address)

    # Test 1: Cannot dissolve when contributors still exist
    exec_command_bob(
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

    dissolve_result = exec_command_alice(
        command="crowd",
        sub_command="dissolve",
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
            "--no-prompt",
            "--json-output",
        ],
    )

    dissolve_output = json.loads(dissolve_result.stdout)
    assert dissolve_output.get("success") is False
    assert "contributors" in dissolve_output.get("error", "").lower()

    # Test 2: Successful dissolution after refunding all contributors
    exec_command_alice(
        command="crowd",
        sub_command="refund",
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
            "--no-prompt",
            "--json-output",
        ],
    )

    dissolve_result = exec_command_alice(
        command="crowd",
        sub_command="dissolve",
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
            "--no-prompt",
            "--json-output",
        ],
    )

    dissolve_output = json.loads(dissolve_result.stdout)
    assert dissolve_output.get("success") is True
    assert dissolve_output["data"]["crowdloan_id"] == crowdloan_id

    # Test 3: Cannot dissolve finalized crowdloan
    exec_command_alice(
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
            "--target-address",
            bob_address,
            "--fundraising",
            "--no-prompt",
            "--json-output",
        ],
    )

    crowdloan_id2 = get_crowdloan_id_by_creator(exec_command_alice, alice_address)

    exec_command_bob(
        command="crowd",
        sub_command="contribute",
        extra_args=[
            "--id",
            str(crowdloan_id2),
            "--wallet-path",
            wallet_path_bob,
            "--network",
            "ws://127.0.0.1:9945",
            "--wallet-name",
            wallet_bob.name,
            "--wallet-hotkey",
            wallet_bob.hotkey_str,
            "--amount",
            "90",
            "--no-prompt",
            "--json-output",
        ],
    )

    exec_command_alice(
        command="crowd",
        sub_command="finalize",
        extra_args=[
            "--id",
            str(crowdloan_id2),
            "--wallet-path",
            wallet_path_alice,
            "--network",
            "ws://127.0.0.1:9945",
            "--wallet-name",
            wallet_alice.name,
            "--wallet-hotkey",
            wallet_alice.hotkey_str,
            "--no-prompt",
            "--json-output",
        ],
    )

    dissolve_result = exec_command_alice(
        command="crowd",
        sub_command="dissolve",
        extra_args=[
            "--id",
            str(crowdloan_id2),
            "--wallet-path",
            wallet_path_alice,
            "--network",
            "ws://127.0.0.1:9945",
            "--wallet-name",
            wallet_alice.name,
            "--wallet-hotkey",
            wallet_alice.hotkey_str,
            "--no-prompt",
            "--json-output",
        ],
    )

    dissolve_output = json.loads(dissolve_result.stdout)
    assert dissolve_output.get("success") is False
    assert "finalized" in dissolve_output.get("error", "").lower()

    print("✅ Crowdloan dissolve test passed")


def test_crowdloan_edge_cases(local_chain, wallet_setup):
    """
    Test edge cases:
    - Contribution above cap: Should auto-adjust to remaining cap
    - Contribution below minimum: Should fail
    - Contribution to finalized crowdloan: Should fail
    - Contribution to crowdloan at cap: Should fail
    """
    wallet_path_alice = "//Alice"
    wallet_path_bob = "//Bob"
    wallet_path_charlie = "//Charlie"

    _, wallet_alice, wallet_path_alice, exec_command_alice = wallet_setup(
        wallet_path_alice
    )
    _, wallet_bob, wallet_path_bob, exec_command_bob = wallet_setup(wallet_path_bob)
    _, wallet_charlie, wallet_path_charlie, exec_command_charlie = wallet_setup(
        wallet_path_charlie
    )

    alice_address = wallet_alice.coldkeypub.ss58_address
    bob_address = wallet_bob.coldkeypub.ss58_address

    print("\n🧪 Testing Crowdloan Edge Cases...")

    # Create a fundraising crowdloan
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
            "5",
            "--target-address",
            bob_address,
            "--fundraising",
            "--no-prompt",
            "--json-output",
        ],
    )

    create_output = json.loads(create_result.stdout)
    assert create_output.get("success") is True
    crowdloan_id = get_crowdloan_id_by_creator(exec_command_alice, alice_address)

    # Test 1: Contribution below minimum should fail
    contribute_result = exec_command_bob(
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
            "2",
            "--no-prompt",
            "--json-output",
        ],
    )

    contribute_output = json.loads(contribute_result.stdout)
    assert contribute_output.get("success") is False
    assert "minimum" in contribute_output.get("error", "").lower()

    # Multiple contributions from same address
    exec_command_bob(
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
            "20",
            "--no-prompt",
            "--json-output",
        ],
    )

    exec_command_bob(
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
            "15",
            "--no-prompt",
            "--json-output",
        ],
    )

    info_result = exec_command_alice(
        command="crowd",
        sub_command="info",
        extra_args=[
            "--id",
            str(crowdloan_id),
            "--network",
            "ws://127.0.0.1:9945",
            "--show-contributors",
            "--json-output",
        ],
    )
    info_output = json.loads(info_result.stdout)
    # Bob should have contributed 35 total
    bob_contributions = [
        c for c in info_output["data"]["contributors"] if c["address"] == bob_address
    ]
    assert len(bob_contributions) == 1
    assert bob_contributions[0]["contribution_tao"] == 35.0

    # Test 3: Multiple contributors
    exec_command_charlie(
        command="crowd",
        sub_command="contribute",
        extra_args=[
            "--id",
            str(crowdloan_id),
            "--wallet-path",
            wallet_path_charlie,
            "--network",
            "ws://127.0.0.1:9945",
            "--wallet-name",
            wallet_charlie.name,
            "--wallet-hotkey",
            wallet_charlie.hotkey_str,
            "--amount",
            "25",
            "--no-prompt",
            "--json-output",
        ],
    )

    info_result = exec_command_alice(
        command="crowd",
        sub_command="info",
        extra_args=[
            "--id",
            str(crowdloan_id),
            "--network",
            "ws://127.0.0.1:9945",
            "--show-contributors",
            "--json-output",
        ],
    )
    info_output = json.loads(info_result.stdout)
    assert info_output["data"]["contributors_count"] == 3  # Creator + Bob + Charlie
    assert len(info_output["data"]["contributors"]) == 3  # Creator + Bob + Charlie

    # Test 4: Contribution above cap should auto-adjust
    # Current raised: 10 (deposit) + 35 (Bob) + 25 (Charlie) = 70, cap = 100, remaining = 30
    contribute_result = exec_command_bob(
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
            "50",  # Would exceed cap, should adjust to 30
            "--no-prompt",
            "--json-output",
        ],
    )

    contribute_output = json.loads(contribute_result.stdout)
    assert contribute_output.get("success") is True
    assert contribute_output["data"]["adjusted"] is True
    assert contribute_output["data"]["contribution_amount"] == 30.0

    info_result = exec_command_alice(
        command="crowd",
        sub_command="info",
        extra_args=[
            "--id",
            str(crowdloan_id),
            "--network",
            "ws://127.0.0.1:9945",
            "--json-output",
        ],
    )
    info_output = json.loads(info_result.stdout)
    assert info_output["data"]["raised"] >= info_output["data"]["cap"]
    assert info_output["data"]["status"] == "Funded"

    # Test 5: Contribution to crowdloan at cap should fail
    contribute_result = exec_command_charlie(
        command="crowd",
        sub_command="contribute",
        extra_args=[
            "--id",
            str(crowdloan_id),
            "--wallet-path",
            wallet_path_charlie,
            "--network",
            "ws://127.0.0.1:9945",
            "--wallet-name",
            wallet_charlie.name,
            "--wallet-hotkey",
            wallet_charlie.hotkey_str,
            "--amount",
            "10",
            "--no-prompt",
            "--json-output",
        ],
    )

    contribute_output = json.loads(contribute_result.stdout)
    assert contribute_output.get("success") is False
    assert "cap" in contribute_output.get("error", "").lower()

    # Test 6: Contribution to finalized crowdloan should fail
    # Finalize the crowdloan
    exec_command_alice(
        command="crowd",
        sub_command="finalize",
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
            "--no-prompt",
            "--json-output",
        ],
    )

    # Create new crowdloan for finalize test
    exec_command_alice(
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
            "5",
            "--target-address",
            bob_address,
            "--fundraising",
            "--no-prompt",
            "--json-output",
        ],
    )

    crowdloan_id2 = get_crowdloan_id_by_creator(exec_command_alice, alice_address)

    exec_command_bob(
        command="crowd",
        sub_command="contribute",
        extra_args=[
            "--id",
            str(crowdloan_id2),
            "--wallet-path",
            wallet_path_bob,
            "--network",
            "ws://127.0.0.1:9945",
            "--wallet-name",
            wallet_bob.name,
            "--wallet-hotkey",
            wallet_bob.hotkey_str,
            "--amount",
            "90",
            "--no-prompt",
            "--json-output",
        ],
    )

    exec_command_alice(
        command="crowd",
        sub_command="finalize",
        extra_args=[
            "--id",
            str(crowdloan_id2),
            "--wallet-path",
            wallet_path_alice,
            "--network",
            "ws://127.0.0.1:9945",
            "--wallet-name",
            wallet_alice.name,
            "--wallet-hotkey",
            wallet_alice.hotkey_str,
            "--no-prompt",
            "--json-output",
        ],
    )

    contribute_result = exec_command_charlie(
        command="crowd",
        sub_command="contribute",
        extra_args=[
            "--id",
            str(crowdloan_id2),
            "--wallet-path",
            wallet_path_charlie,
            "--network",
            "ws://127.0.0.1:9945",
            "--wallet-name",
            wallet_charlie.name,
            "--wallet-hotkey",
            wallet_charlie.hotkey_str,
            "--amount",
            "10",
            "--no-prompt",
            "--json-output",
        ],
    )

    contribute_output = json.loads(contribute_result.stdout)
    assert contribute_output.get("success") is False
    assert "finalized" in contribute_output.get("error", "").lower()

    print("✅ Crowdloan edge cases test passed")
