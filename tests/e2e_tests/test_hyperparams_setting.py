import asyncio
import json

from bittensor_cli.src import HYPERPARAMS, RootSudoOnly
from .utils import turn_off_hyperparam_freeze_window

"""
Verify commands:

* btcli subnets create
* btcli sudo set
* btcli sudo get
"""


def test_hyperparams_setting(local_chain, wallet_setup):
    netuid = 2
    wallet_path_alice = "//Alice"
    # Create wallet for Alice
    keypair_alice, wallet_alice, wallet_path_alice, exec_command_alice = wallet_setup(
        wallet_path_alice
    )
    try:
        asyncio.run(turn_off_hyperparam_freeze_window(local_chain, wallet_alice))
    except ValueError:
        print(
            "Skipping turning off hyperparams freeze window. This indicates the call does not exist on the chain you are testing."
        )
    # Register a subnet with sudo as Alice
    result = exec_command_alice(
        command="subnets",
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
    assert result_output["netuid"] == netuid
    assert isinstance(result_output["extrinsic_identifier"], str)

    # Fetch the hyperparameters of the subnet
    hyperparams = exec_command_alice(
        command="sudo",
        sub_command="get",
        extra_args=[
            "--network",
            "ws://127.0.0.1:9945",
            "--netuid",
            netuid,
            "--json-out",
        ],
    )

    # Parse all hyperparameters and single out max_burn in TAO
    all_hyperparams = json.loads(hyperparams.stdout)
    hp = {}
    for hyperparam in all_hyperparams:
        hp[hyperparam["hyperparameter"]] = hyperparam["value"]
    for key, (_, sudo_only) in HYPERPARAMS.items():
        if key in hp.keys() and sudo_only == RootSudoOnly.FALSE:
            if isinstance(hp[key], bool):
                new_val = not hp[key]
            elif isinstance(hp[key], int):
                if hp[key] < 100:
                    new_val = hp[key] + 1
                else:
                    new_val = hp[key] - 1
            else:
                raise ValueError(
                    f"Unrecognized hyperparameter value type: {key}: {hp[key]}"
                )
            cmd = exec_command_alice(
                command="sudo",
                sub_command="set",
                extra_args=[
                    "--wallet-path",
                    wallet_path_alice,
                    "--network",
                    "ws://127.0.0.1:9945",
                    "--wallet-name",
                    wallet_alice.name,
                    "--wallet-hotkey",
                    wallet_alice.hotkey_str,
                    "--netuid",
                    netuid,
                    "--json-out",
                    "--no-prompt",
                    "--param",
                    key,
                    "--value",
                    new_val,
                ],
            )
            cmd_json = json.loads(cmd.stdout)
            assert cmd_json["success"] is True, (key, new_val, cmd.stdout, cmd_json)
            assert isinstance(cmd_json["extrinsic_identifier"], str)
            print(f"Successfully set hyperparameter {key} to value {new_val}")
    # also test hidden hyperparam
    cmd = exec_command_alice(
        command="sudo",
        sub_command="set",
        extra_args=[
            "--wallet-path",
            wallet_path_alice,
            "--network",
            "ws://127.0.0.1:9945",
            "--wallet-name",
            wallet_alice.name,
            "--wallet-hotkey",
            wallet_alice.hotkey_str,
            "--netuid",
            netuid,
            "--json-out",
            "--no-prompt",
            "--param",
            "min_allowed_uids",
            "--value",
            "110",
        ],
    )
    cmd_json = json.loads(cmd.stdout)
    assert cmd_json["success"] is True, (cmd.stdout, cmd_json)
    assert isinstance(cmd_json["extrinsic_identifier"], str)
    print("Successfully set hyperparameters")
    print("Testing trimming UIDs")
    cmd = exec_command_alice(
        command="sudo",
        sub_command="trim",
        extra_args=[
            "--wallet-path",
            wallet_path_alice,
            "--network",
            "ws://127.0.0.1:9945",
            "--wallet-name",
            wallet_alice.name,
            "--wallet-hotkey",
            wallet_alice.hotkey_str,
            "--netuid",
            netuid,
            "--max",
            "120",
            "--json-out",
            "--no-prompt",
        ],
    )
    cmd_json = json.loads(cmd.stdout)
    assert cmd_json["success"] is True, (cmd.stdout, cmd_json)
    assert isinstance(cmd_json["extrinsic_identifier"], str)
    print("Successfully trimmed UIDs")
