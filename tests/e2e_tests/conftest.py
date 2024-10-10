import logging
import os
import re
import shlex
import shutil
import signal
import socket
import subprocess
import time

import pytest
from bittensor_cli.src.bittensor.async_substrate_interface import (
    AsyncSubstrateInterface,
)

from .utils import setup_wallet


# Function to check if the process is running by port
def is_chain_running(port):
    """Check if a node is running on the given port."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        try:
            # Attempt to connect to the given port on localhost
            s.connect(("127.0.0.1", port))
            return True
        except (ConnectionRefusedError, OSError):
            # If the connection is refused or there's an OS error, the node is not running
            return False


# Fixture for setting up and tearing down a localnet.sh chain between tests
@pytest.fixture(scope="function")
def local_chain(request):
    param = request.param if hasattr(request, "param") else None
    # Get the environment variable for the script path
    script_path = os.getenv("LOCALNET_SH_PATH")

    if not script_path:
        # Skip the test if the localhost.sh path is not set
        logging.warning("LOCALNET_SH_PATH env variable is not set, e2e test skipped.")
        pytest.skip("LOCALNET_SH_PATH environment variable is not set.")

    # Check if param is None, and handle it accordingly
    args = "" if param is None else f"{param}"

    # Determine the port to check based on `param`
    port = 9945  # Default port if `param` is None

    already_running = False
    if is_chain_running(port):
        already_running = True
        logging.info(f"Chain already running on port {port}, skipping start.")
        print(f"Chain already running on port {port}, skipping start.")
    else:
        logging.info(f"Starting new chain on port {port}...")
        print(f"Starting new chain on port {port}...")
        # compile commands to send to process
        cmds = shlex.split(f"{script_path} {param}")
        # Start new node process
        process = subprocess.Popen(
            cmds, stdout=subprocess.PIPE, text=True, preexec_fn=os.setsid
        )

        # Wait for the node to start using the existing pattern match
        pattern = re.compile(r"Imported #1")
        timestamp = int(time.time())

        def wait_for_node_start(process, pattern):
            for line in process.stdout:
                print(line.strip())
                # 20 min as timeout
                if int(time.time()) - timestamp > 20 * 60:
                    pytest.fail("Subtensor not started in time")
                if pattern.search(line):
                    print("Node started!")
                    break

        wait_for_node_start(process, pattern)

    # Run the test, passing in substrate interface
    yield AsyncSubstrateInterface(chain_endpoint="ws://127.0.0.1:9945")

    if not already_running:
        # Terminate the process group (includes all child processes)
        os.killpg(os.getpgid(process.pid), signal.SIGTERM)

        # Give some time for the process to terminate
        time.sleep(1)

        # If the process is not terminated, send SIGKILL
        if process.poll() is None:
            os.killpg(os.getpgid(process.pid), signal.SIGKILL)

        # Ensure the process has terminated
        process.wait()


@pytest.fixture(scope="function")
def wallet_setup():
    wallet_paths = []

    def _setup_wallet(uri: str):
        keypair, wallet, wallet_path, exec_command = setup_wallet(uri)
        wallet_paths.append(wallet_path)
        return keypair, wallet, wallet_path, exec_command

    yield _setup_wallet

    # Cleanup after the test
    for path in wallet_paths:
        shutil.rmtree(path, ignore_errors=True)
