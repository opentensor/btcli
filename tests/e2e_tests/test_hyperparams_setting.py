import json
import re

from bittensor_cli.src import HYPERPARAMS

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
    assert result_output["netuid"] == netuid

    # Fetch the hyperparameters of the subnet
    hyperparams = exec_command_alice(
        command="sudo",
        sub_command="get",
        extra_args=["--chain", "ws://127.0.0.1:9945", "--netuid", netuid, "--json-out"],
    )

    # Parse all hyperparameters and single out max_burn in TAO
    all_hyperparams = json.loads(hyperparams.stdout)
    hp = {}
    for hyperparam in all_hyperparams:
        hp[hyperparam["hyperparameter"]] = hyperparam["value"]
    for key, (_, sudo_only) in HYPERPARAMS.items():
        if key in hp.keys() and not sudo_only:
            if isinstance(hp[key], bool):
                new_val = not hp[key]
            elif isinstance(hp[key], int):
                new_val = hp[key] - 1
            else:
                raise ValueError(f"Unrecognized hyperparameter value type: {key}: {hp[key]}")
            cmd = exec_command_alice(
                command="sudo",
                sub_command="set",
                extra_args=["--chain", "ws://127.0.0.1:9945", "--netuid", netuid, "--json-out", "--no-prompt",
                            "--param", key, "--value", str(new_val)],
            )
            cmd_json = json.loads(cmd.stdout)
            assert cmd_json["success"] is True, (
                cmd.stdout, cmd.stderr
            )
            print(f"Successfully set hyperparameter {key} to value {new_val}")
