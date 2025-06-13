import asyncio
import logging
import os
import re
import shlex
import shutil
import signal
import subprocess
import sys
import time

import pytest
from async_substrate_interface.async_substrate import AsyncSubstrateInterface

from .utils import setup_wallet

LOCALNET_IMAGE_NAME = "ghcr.io/opentensor/subtensor-localnet:devnet-ready"


def wait_for_node_start(process, pattern, timestamp: int = None):
    for line in process.stdout:
        print(line.strip())
        # 20 min as timeout
        timestamp = timestamp or int(time.time())
        if int(time.time()) - timestamp > 20 * 60:
            pytest.fail("Subtensor not started in time")
        if pattern.search(line):
            print("Node started!")
            break


# Fixture for setting up and tearing down a localnet.sh chain between tests
@pytest.fixture(scope="function")
def local_chain(request):
    """Determines whether to run the localnet.sh script in a subprocess or a Docker container."""
    args = request.param if hasattr(request, "param") else None
    params = "" if args is None else f"{args}"
    if shutil.which("docker") and not os.getenv("USE_DOCKER") == "0":
        yield from docker_runner(params)
    else:
        if not os.getenv("USE_DOCKER") == "0":
            if sys.platform.startswith("linux"):
                docker_command = (
                    "Install docker with command "
                    "[blue]sudo apt-get update && sudo apt-get install docker.io -y[/blue]"
                    " or use documentation [blue]https://docs.docker.com/engine/install/[/blue]"
                )
            elif sys.platform == "darwin":
                docker_command = (
                    "Install docker with command [blue]brew install docker[/blue]"
                )
            else:
                docker_command = "[blue]Unknown OS, install Docker manually: https://docs.docker.com/get-docker/[/blue]"

            logging.warning("Docker not found in the operating system!")
            logging.warning(docker_command)
            logging.warning("Tests are run in legacy mode.")
        yield from legacy_runner(request)


def legacy_runner(request):
    param = request.param if hasattr(request, "param") else None
    # Get the environment variable for the script path
    script_path = os.getenv("LOCALNET_SH_PATH")

    if not script_path:
        # Skip the test if the localhost.sh path is not set
        logging.warning("LOCALNET_SH_PATH env variable is not set, e2e test skipped.")
        pytest.skip("LOCALNET_SH_PATH environment variable is not set.")

    # Check if param is None, and handle it accordingly
    args = "" if param is None else f"{param}"

    # Compile commands to send to process
    cmds = shlex.split(f"{script_path} {args}")
    # Start new node process
    process = subprocess.Popen(
        cmds, stdout=subprocess.PIPE, text=True, preexec_fn=os.setsid
    )

    # Pattern match indicates node is compiled and ready
    pattern = re.compile(r"Imported #1")

    # Install neuron templates
    logging.info("Downloading and installing neuron templates from github")

    wait_for_node_start(process, pattern)

    # Run the test, passing in substrate interface
    yield AsyncSubstrateInterface(url="ws://127.0.0.1:9945")

    # Terminate the process group (includes all child processes)
    os.killpg(os.getpgid(process.pid), signal.SIGTERM)

    # Give some time for the process to terminate
    time.sleep(1)

    # If the process is not terminated, send SIGKILL
    if process.poll() is None:
        os.killpg(os.getpgid(process.pid), signal.SIGKILL)

    # Ensure the process has terminated
    process.wait()


def docker_runner(params):
    """Starts a Docker container before tests and gracefully terminates it after."""

    def is_docker_running():
        """Check if Docker is running and optionally skip pulling the image."""
        try:
            subprocess.run(
                ["docker", "info"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                check=True,
            )

            skip_pull = os.getenv("SKIP_PULL", "0") == "1"
            if not skip_pull:
                subprocess.run(["docker", "pull", LOCALNET_IMAGE_NAME], check=True)
            else:
                print(f"[SKIP_PULL=1] Skipping 'docker pull {LOCALNET_IMAGE_NAME}'")

            return True
        except subprocess.CalledProcessError:
            return False

    def try_start_docker():
        """Run docker based on OS."""
        try:
            subprocess.run(["open", "-a", "Docker"], check=True)  # macOS
        except (FileNotFoundError, subprocess.CalledProcessError):
            try:
                subprocess.run(["systemctl", "start", "docker"], check=True)  # Linux
            except (FileNotFoundError, subprocess.CalledProcessError):
                try:
                    subprocess.run(
                        ["sudo", "service", "docker", "start"], check=True
                    )  # Linux alternative
                except (FileNotFoundError, subprocess.CalledProcessError):
                    print("Failed to start Docker. Manual start may be required.")
                    return False

        # Wait Docker run 10 attempts with 3 sec waits
        for _ in range(10):
            if is_docker_running():
                return True
            time.sleep(3)

        print("Docker wasn't run. Manual start may be required.")
        return False

    container_name = f"test_local_chain_{str(time.time()).replace('.', '_')}"

    # Command to start container
    cmds = [
        "docker",
        "run",
        "--rm",
        "--name",
        container_name,
        "-p",
        "9944:9944",
        "-p",
        "9945:9945",
        LOCALNET_IMAGE_NAME,
        params,
    ]

    try_start_docker()

    # Start container
    with subprocess.Popen(
        cmds,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        start_new_session=True,
    ) as process:
        try:
            substrate = None
            try:
                pattern = re.compile(r"Imported #1")
                wait_for_node_start(process, pattern, int(time.time()))
            except TimeoutError:
                raise

            result = subprocess.run(
                ["docker", "ps", "-q", "-f", f"name={container_name}"],
                capture_output=True,
                text=True,
            )
            if not result.stdout.strip():
                raise RuntimeError("Docker container failed to start.")
            substrate = AsyncSubstrateInterface(url="ws://127.0.0.1:9944")
            yield substrate

        finally:
            try:
                if substrate:
                    asyncio.run(substrate.close())
            except Exception:
                logging.warning("Failed to close substrate connection.")

            try:
                subprocess.run(["docker", "kill", container_name])
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                os.killpg(os.getpgid(process.pid), signal.SIGKILL)


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
