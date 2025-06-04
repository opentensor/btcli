import json
import re

from bittensor_cli.src.bittensor.balances import Balance

"""
Verify commands:

* btcli s burn-cost
* btcli subnets create
* btcli subnets set-identity
* btcli subnets get-identity
* btcli subnets register
* btcli stake add
* btcli stake remove
* btcli stake show
* btcli sudo set
* btcli sudo get
"""


def test_staking(local_chain, wallet_setup):
    """
    Test staking & sudo commands and inspect their output

    Steps:
        1. Create wallets for Alice and create a subnet & register
        2. Add 100 TAO stake to Alice's hotkey and verify
        3. Execute stake show and assert stake is present
        4. Execute stake remove and assert removal
        5. Fetch current subnet hyperparameters
        6. Change the max_burn hyperparameter and assert it changed.

    Raises:
        AssertionError: If any of the checks or verifications fail
    """
    print("Testing staking and sudo commands🧪")
    netuid = 2
    multiple_netuids = [2, 3]
    wallet_path_alice = "//Alice"

    # Create wallet for Alice
    keypair_alice, wallet_alice, wallet_path_alice, exec_command_alice = wallet_setup(
        wallet_path_alice
    )

    burn_cost = exec_command_alice(
        "subnets",
        "burn-cost",
        extra_args=[
            "--network",
            "ws://127.0.0.1:9945",
            "--json-output",
        ],
    )
    burn_cost_output = json.loads(burn_cost.stdout)
    expected_burn_cost = Balance.from_tao(1000.0)
    assert burn_cost_output["error"] == ""
    assert burn_cost_output["burn_cost"]["rao"] == expected_burn_cost.rao
    assert burn_cost_output["burn_cost"]["tao"] == expected_burn_cost.tao

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
            "--no-prompt",
            "--json-output",
        ],
    )
    result_output = json.loads(result.stdout)
    assert result_output["success"] is True
    assert result_output["netuid"] == netuid

    # Register another subnet with sudo as Alice
    result_for_second_repo = exec_command_alice(
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
            "--no-prompt",
            "--json-output",
        ],
    )
    result_output_second = json.loads(result_for_second_repo.stdout)
    assert result_output_second["success"] is True
    assert result_output_second["netuid"] == multiple_netuids[1]

    # Register Alice in netuid = 1 using her hotkey
    register_subnet = exec_command_alice(
        command="subnets",
        sub_command="register",
        extra_args=[
            "--wallet-path",
            wallet_path_alice,
            "--wallet-name",
            wallet_alice.name,
            "--hotkey",
            wallet_alice.hotkey_str,
            "--netuid",
            netuid,
            "--chain",
            "ws://127.0.0.1:9945",
            "--no-prompt",
        ],
    )
    assert "✅ Already Registered" in register_subnet.stdout

    register_subnet_json = exec_command_alice(
        command="subnets",
        sub_command="register",
        extra_args=[
            "--wallet-path",
            wallet_path_alice,
            "--wallet-name",
            wallet_alice.name,
            "--hotkey",
            wallet_alice.hotkey_str,
            "--netuid",
            netuid,
            "--chain",
            "ws://127.0.0.1:9945",
            "--no-prompt",
            "--json-output",
        ],
    )
    register_subnet_json_output = json.loads(register_subnet_json.stdout)
    assert register_subnet_json_output["success"] is True
    assert register_subnet_json_output["msg"] == "Already registered"

    # set identity
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
            netuid,
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
            "--additional-info",
            sn_add_info := "Created by Alice",
            "--json-output",
            "--no-prompt",
        ],
    )
    set_identity_output = json.loads(set_identity.stdout)
    assert set_identity_output["success"] is True

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
    assert get_identity_output["additional"] == sn_add_info

    # Add stake to Alice's hotkey
    add_stake_single = exec_command_alice(
        command="stake",
        sub_command="add",
        extra_args=[
            "--netuid",
            netuid,
            "--wallet-path",
            wallet_path_alice,
            "--wallet-name",
            wallet_alice.name,
            "--hotkey",
            wallet_alice.hotkey_str,
            "--chain",
            "ws://127.0.0.1:9945",
            "--amount",
            "100",
            "--tolerance",
            "0.1",
            "--partial",
            "--no-prompt",
            "--era",
            "144",
        ],
    )
    assert "✅ Finalized" in add_stake_single.stdout, add_stake_single.stderr

    # Execute stake show for Alice's wallet
    show_stake_adding_single = exec_command_alice(
        command="stake",
        sub_command="list",
        extra_args=[
            "--wallet-path",
            wallet_path_alice,
            "--wallet-name",
            wallet_alice.name,
            "--chain",
            "ws://127.0.0.1:9945",
            "--verbose",
        ],
    )

    # Assert correct stake is added
    cleaned_stake = [
        re.sub(r"\s+", " ", line)
        for line in show_stake_adding_single.stdout.splitlines()
    ]
    stake_added = cleaned_stake[8].split("│")[3].strip().split()[0]
    assert Balance.from_tao(float(stake_added)) >= Balance.from_tao(90)

    show_stake_json = exec_command_alice(
        command="stake",
        sub_command="list",
        extra_args=[
            "--wallet-path",
            wallet_path_alice,
            "--wallet-name",
            wallet_alice.name,
            "--chain",
            "ws://127.0.0.1:9945",
            "--json-output",
        ],
    )
    show_stake_json_output = json.loads(show_stake_json.stdout)
    alice_stake = show_stake_json_output["stake_info"][keypair_alice.ss58_address][0]
    assert Balance.from_tao(alice_stake["stake_value"]) > Balance.from_tao(90.0)

    # Execute remove_stake command and remove all alpha stakes from Alice
    remove_stake = exec_command_alice(
        command="stake",
        sub_command="remove",
        extra_args=[
            "--netuid",
            netuid,
            "--wallet-path",
            wallet_path_alice,
            "--wallet-name",
            wallet_alice.name,
            "--hotkey",
            wallet_alice.hotkey_str,
            "--chain",
            "ws://127.0.0.1:9945",
            "--amount",
            str(float(stake_added) - 1),
            "--tolerance",
            "0.1",
            "--partial",
            "--no-prompt",
            "--era",
            "144",
        ],
    )
    assert "✅ Finalized" in remove_stake.stdout

    add_stake_multiple = exec_command_alice(
        command="stake",
        sub_command="add",
        extra_args=[
            "--netuids",
            ",".join(str(x) for x in multiple_netuids),
            "--wallet-path",
            wallet_path_alice,
            "--wallet-name",
            wallet_alice.name,
            "--hotkey",
            wallet_alice.hotkey_str,
            "--chain",
            "ws://127.0.0.1:9945",
            "--amount",
            "100",
            "--tolerance",
            "0.1",
            "--partial",
            "--no-prompt",
            "--era",
            "144",
        ],
    )
    assert "✅ Finalized" in add_stake_multiple.stdout, add_stake_multiple.stderr
    for netuid_ in multiple_netuids:
        assert f"Stake added to netuid: {netuid_}" in add_stake_multiple.stdout, (
            add_stake_multiple.stderr
        )

    # Fetch the hyperparameters of the subnet
    hyperparams = exec_command_alice(
        command="sudo",
        sub_command="get",
        extra_args=[
            "--chain",
            "ws://127.0.0.1:9945",
            "--netuid",
            netuid,
        ],
    )

    # Parse all hyperparameters and single out max_burn in TAO
    all_hyperparams = hyperparams.stdout.splitlines()
    max_burn_tao = all_hyperparams[22].split()[2].strip("\u200e")

    # Assert max_burn is 100 TAO from default
    assert Balance.from_tao(float(max_burn_tao)) == Balance.from_tao(100.0)

    hyperparams_json = exec_command_alice(
        command="sudo",
        sub_command="get",
        extra_args=[
            "--chain",
            "ws://127.0.0.1:9945",
            "--netuid",
            netuid,
            "--json-output",
        ],
    )
    hyperparams_json_output = json.loads(hyperparams_json.stdout)
    max_burn_tao_from_json = next(
        filter(lambda x: x["hyperparameter"] == "max_burn", hyperparams_json_output)
    )["value"]
    assert Balance.from_rao(max_burn_tao_from_json) == Balance.from_tao(100.0)

    # Change max_burn hyperparameter to 10 TAO
    change_hyperparams = exec_command_alice(
        command="sudo",
        sub_command="set",
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
            netuid,
            "--param",
            "max_burn",
            "--value",
            "10000000000",  # In RAO, TAO = 10
            "--no-prompt",
        ],
    )
    assert (
        "✅ Hyperparameter max_burn changed to 10000000000" in change_hyperparams.stdout
    )

    # Fetch the hyperparameters again to verify
    updated_hyperparams = exec_command_alice(
        command="sudo",
        sub_command="get",
        extra_args=[
            "--chain",
            "ws://127.0.0.1:9945",
            "--netuid",
            netuid,
        ],
    )

    # Parse updated hyperparameters
    all_updated_hyperparams = updated_hyperparams.stdout.splitlines()
    updated_max_burn_tao = all_updated_hyperparams[22].split()[2].strip("\u200e")

    # Assert max_burn is now 10 TAO
    assert Balance.from_tao(float(updated_max_burn_tao)) == Balance.from_tao(10)

    updated_hyperparams_json = exec_command_alice(
        command="sudo",
        sub_command="get",
        extra_args=[
            "--chain",
            "ws://127.0.0.1:9945",
            "--netuid",
            netuid,
            "--json-output",
        ],
    )
    updated_hyperparams_json_output = json.loads(updated_hyperparams_json.stdout)
    max_burn_tao_from_json = next(
        filter(
            lambda x: x["hyperparameter"] == "max_burn", updated_hyperparams_json_output
        )
    )["value"]
    assert Balance.from_rao(max_burn_tao_from_json) == Balance.from_tao(10.0)

    print("✅ Passed staking and sudo commands")
