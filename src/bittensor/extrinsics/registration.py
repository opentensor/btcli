import math
from dataclasses import dataclass
import functools
from multiprocessing.queues import Queue
from multiprocessing import Process, Event, Lock
import os
import time
import typing
from typing import Optional

from bittensor_wallet import Wallet
from rich.prompt import Confirm

from src.subtensor_interface import SubtensorInterface
from src.utils import console, err_console, format_error_message


def use_torch() -> bool:
    """Force the use of torch over numpy for certain operations."""
    return True if os.getenv("USE_TORCH") == "1" else False


def legacy_torch_api_compat(func):
    """
    Convert function operating on numpy Input&Output to legacy torch Input&Output API if `use_torch()` is True.

    Args:
        func (function):
            Function with numpy Input/Output to be decorated.
    Returns:
        decorated (function):
            Decorated function.
    """

    @functools.wraps(func)
    def decorated(*args, **kwargs):
        if use_torch():
            # if argument is a Torch tensor, convert it to numpy
            args = [
                arg.cpu().numpy() if isinstance(arg, torch.Tensor) else arg
                for arg in args
            ]
            kwargs = {
                key: value.cpu().numpy() if isinstance(value, torch.Tensor) else value
                for key, value in kwargs.items()
            }
        ret = func(*args, **kwargs)
        if use_torch():
            # if return value is a numpy array, convert it to Torch tensor
            if isinstance(ret, numpy.ndarray):
                ret = torch.from_numpy(ret)
        return ret

    return decorated


@functools.cache
def _get_real_torch():
    try:
        import torch as _real_torch
    except ImportError:
        _real_torch = None
    return _real_torch


def log_no_torch_error():
    err_console.print(
        "This command requires torch. You can install torch for bittensor"
        ' with `pip install bittensor[torch]` or `pip install ".[torch]"`'
        " if installing from source, and then run the command with USE_TORCH=1 {command}"
    )


@dataclass
class POWSolution:
    """A solution to the registration PoW problem."""

    nonce: int
    block_number: int
    difficulty: int
    seal: bytes

    def is_stale(self, subtensor: "bittensor.subtensor") -> bool:
        """Returns True if the POW is stale.
        This means the block the POW is solved for is within 3 blocks of the current block.
        """
        return self.block_number < subtensor.get_current_block() - 3


class LazyLoadedTorch:
    def __bool__(self):
        return bool(_get_real_torch())

    def __getattr__(self, name):
        if real_torch := _get_real_torch():
            return getattr(real_torch, name)
        else:
            log_no_torch_error()
            raise ImportError("torch not installed")


if typing.TYPE_CHECKING:
    import torch
else:
    torch = LazyLoadedTorch()


class MaxSuccessException(Exception):
    pass


class MaxAttemptsException(Exception):
    pass


async def run_faucet_extrinsic(
    subtensor: SubtensorInterface,
    wallet: Wallet,
    wait_for_inclusion: bool = False,
    wait_for_finalization: bool = True,
    prompt: bool = False,
    max_allowed_attempts: int = 3,
    output_in_place: bool = True,
    cuda: bool = False,
    dev_id: int = 0,
    tpb: int = 256,
    num_processes: Optional[int] = None,
    update_interval: Optional[int] = None,
    log_verbose: bool = False,
    max_successes: int = 3,
) -> tuple[bool, str]:
    r"""Runs a continual POW to get a faucet of TAO on the test net.

    :param subtensor: The subtensor interface object used to run the extrinsic
    :param wallet: Bittensor wallet object.
    :param prompt: If `True`, the call waits for confirmation from the user before proceeding.
    :param wait_for_inclusion: If set, waits for the extrinsic to enter a block before returning `True`,
                               or returns `False` if the extrinsic fails to enter the block within the timeout.
    :param wait_for_finalization: If set, waits for the extrinsic to be finalized on the chain before returning `True`,
                                  or returns `False` if the extrinsic fails to be finalized within the timeout.
    :param max_allowed_attempts: Maximum number of attempts to register the wallet.
    :param output_in_place: Whether to output logging data as the process runs.
    :param cuda: If `True`, the wallet should be registered using CUDA device(s).
    :param dev_id: The CUDA device id to use
    :param tpb: The number of threads per block (CUDA).
    :param num_processes: The number of processes to use to register.
    :param update_interval: The number of nonces to solve between updates.
    :param log_verbose: If `True`, the registration process will log more information.
    :param max_successes: The maximum number of successful faucet runs for the wallet.

    :return: `True` if extrinsic was finalized or included in the block. If we did not wait for
                    finalization/inclusion, the response is also `True`
    """
    if prompt:
        if not Confirm.ask(
            "Run Faucet ?\n"
            f" coldkey:    [bold white]{wallet.coldkeypub.ss58_address}[/bold white]\n"
            f" network:    [bold white]{subtensor}[/bold white]"
        ):
            return False, ""

    if not torch:
        log_no_torch_error()
        return False, "Requires torch"

    # Unlock coldkey
    wallet.unlock_coldkey()

    # Get previous balance.
    old_balance = await subtensor.get_balance(wallet.coldkeypub.ss58_address)

    # Attempt rolling registration.
    attempts = 1
    successes = 1
    while True:
        async with subtensor:
            try:
                pow_result = None
                while pow_result is None or pow_result.is_stale(subtensor=subtensor):
                    # Solve latest POW.
                    if cuda:
                        if not torch.cuda.is_available():
                            if prompt:
                                err_console.print("CUDA is not available.")
                            return False, "CUDA is not available."
                        pow_result: Optional[POWSolution] = create_pow(
                            subtensor,
                            wallet,
                            -1,
                            output_in_place,
                            cuda=cuda,
                            dev_id=dev_id,
                            tpb=tpb,
                            num_processes=num_processes,
                            update_interval=update_interval,
                            log_verbose=log_verbose,
                        )
                    else:
                        pow_result: Optional[POWSolution] = create_pow(
                            subtensor,
                            wallet,
                            -1,
                            output_in_place,
                            cuda=cuda,
                            num_processes=num_processes,
                            update_interval=update_interval,
                            log_verbose=log_verbose,
                        )
                call = subtensor.substrate.compose_call(
                    call_module="SubtensorModule",
                    call_function="faucet",
                    call_params={
                        "block_number": pow_result.block_number,
                        "nonce": pow_result.nonce,
                        "work": [int(byte_) for byte_ in pow_result.seal],
                    },
                )
                extrinsic = subtensor.substrate.create_signed_extrinsic(
                    call=call, keypair=wallet.coldkey
                )
                response = subtensor.substrate.submit_extrinsic(
                    extrinsic,
                    wait_for_inclusion=wait_for_inclusion,
                    wait_for_finalization=wait_for_finalization,
                )

                # process if registration successful, try again if pow is still valid
                response.process_events()
                if not response.is_success:
                    err_console.print(
                        f":cross_mark: [red]Failed[/red]: {format_error_message(response.error_message)}"
                    )
                    if attempts == max_allowed_attempts:
                        raise MaxAttemptsException
                    attempts += 1
                    # Wait a bit before trying again
                    time.sleep(1)

                # Successful registration
                else:
                    new_balance = subtensor.get_balance(wallet.coldkeypub.ss58_address)
                    console.print(
                        f"Balance: [blue]{old_balance}[/blue] :arrow_right: [green]{new_balance}[/green]"
                    )
                    old_balance = new_balance

                    if successes == max_successes:
                        raise MaxSuccessException

                    attempts = 1  # Reset attempts on success
                    successes += 1

            except KeyboardInterrupt:
                return True, "Done"

            except MaxSuccessException:
                return True, f"Max successes reached: {3}"

            except MaxAttemptsException:
                return False, f"Max attempts reached: {max_allowed_attempts}"


def _check_for_newest_block_and_update(
    subtensor: "bittensor.subtensor",
    netuid: int,
    old_block_number: int,
    hotkey_bytes: bytes,
    curr_diff: multiprocessing.Array,
    curr_block: multiprocessing.Array,
    curr_block_num: multiprocessing.Value,
    update_curr_block: Callable,
    check_block: "multiprocessing.Lock",
    solvers: List[_Solver],
    curr_stats: RegistrationStatistics,
) -> int:
    """
    Checks for a new block and updates the current block information if a new block is found.

    Args:
        subtensor (:obj:`bittensor.subtensor`, `required`):
            The subtensor object to use for getting the current block.
        netuid (:obj:`int`, `required`):
            The netuid to use for retrieving the difficulty.
        old_block_number (:obj:`int`, `required`):
            The old block number to check against.
        hotkey_bytes (:obj:`bytes`, `required`):
            The bytes of the hotkey's pubkey.
        curr_diff (:obj:`multiprocessing.Array`, `required`):
            The current difficulty as a multiprocessing array.
        curr_block (:obj:`multiprocessing.Array`, `required`):
            Where the current block is stored as a multiprocessing array.
        curr_block_num (:obj:`multiprocessing.Value`, `required`):
            Where the current block number is stored as a multiprocessing value.
        update_curr_block (:obj:`Callable`, `required`):
            A function that updates the current block.
        check_block (:obj:`multiprocessing.Lock`, `required`):
            A mp lock that is used to check for a new block.
        solvers (:obj:`List[_Solver]`, `required`):
            A list of solvers to update the current block for.
        curr_stats (:obj:`RegistrationStatistics`, `required`):
            The current registration statistics to update.

    Returns:
        (int) The current block number.
    """
    block_number = subtensor.get_current_block()
    if block_number != old_block_number:
        old_block_number = block_number
        # update block information
        block_number, difficulty, block_hash = _get_block_with_retry(
            subtensor=subtensor, netuid=netuid
        )
        block_bytes = bytes.fromhex(block_hash[2:])

        update_curr_block(
            curr_diff,
            curr_block,
            curr_block_num,
            block_number,
            block_bytes,
            difficulty,
            hotkey_bytes,
            check_block,
        )
        # Set new block events for each solver

        for worker in solvers:
            worker.newBlockEvent.set()

        # update stats
        curr_stats.block_number = block_number
        curr_stats.block_hash = block_hash
        curr_stats.difficulty = difficulty

    return old_block_number


def _block_solver(
    subtensor: SubtensorInterface,
    wallet: Wallet,
    num_processes: int,
    netuid: int,
    dev_id: list[int],
    tpb: int,
    update_interval: int,
    curr_block,
    curr_block_num,
    curr_diff,
    n_samples,
    cuda: bool,
):
    limit = int(math.pow(2, 256)) - 1

    # Establish communication queues
    ## See the _Solver class for more information on the queues.
    stop_event = Event()
    stop_event.clear()

    solution_queue = Queue()
    finished_queues = [Queue() for _ in range(num_processes)]
    check_block = Lock()

    hotkey_bytes = (
        wallet.coldkeypub.public_key if netuid == -1 else wallet.hotkey.public_key
    )

    if cuda:
        ## Create a worker per CUDA device
        num_processes = len(dev_id)
        solvers = [
            _CUDASolver(
                i,
                num_processes,
                update_interval,
                finished_queues[i],
                solution_queue,
                stop_event,
                curr_block,
                curr_block_num,
                curr_diff,
                check_block,
                limit,
                dev_id[i],
                tpb,
            )
            for i in range(num_processes)
        ]
    else:
        # Start consumers
        solvers = [
            _Solver(
                i,
                num_processes,
                update_interval,
                finished_queues[i],
                solution_queue,
                stop_event,
                curr_block,
                curr_block_num,
                curr_diff,
                check_block,
                limit,
            )
            for i in range(num_processes)
        ]

    # Get first block
    block_number, difficulty, block_hash = _get_block_with_retry(
        subtensor=subtensor, netuid=netuid
    )

    block_bytes = bytes.fromhex(block_hash[2:])
    old_block_number = block_number
    # Set to current block
    _update_curr_block(
        curr_diff,
        curr_block,
        curr_block_num,
        block_number,
        block_bytes,
        difficulty,
        hotkey_bytes,
        check_block,
    )

    # Set new block events for each solver to start at the initial block
    for worker in solvers:
        worker.newBlockEvent.set()

    for worker in solvers:
        worker.start()  # start the solver processes

    start_time = time.time()  # time that the registration started
    time_last = start_time  # time that the last work blocks completed

    curr_stats = RegistrationStatistics(
        time_spent_total=0.0,
        time_average=0.0,
        rounds_total=0,
        time_spent=0.0,
        hash_rate_perpetual=0.0,
        hash_rate=0.0,
        difficulty=difficulty,
        block_number=block_number,
        block_hash=block_hash,
    )

    start_time_perpetual = time.time()

    logger = RegistrationStatisticsLogger(console, output_in_place)
    logger.start()

    solution = None

    hash_rates = [0] * n_samples  # The last n true hash_rates
    weights = [alpha_**i for i in range(n_samples)]  # weights decay by alpha

    timeout = 0.15 if cuda else 0.15

    while netuid == -1 or not subtensor.is_hotkey_registered(
        netuid=netuid, hotkey_ss58=wallet.hotkey.ss58_address
    ):
        # Wait until a solver finds a solution
        try:
            solution = solution_queue.get(block=True, timeout=timeout)
            if solution is not None:
                break
        except Empty:
            # No solution found, try again
            pass

        # check for new block
        old_block_number = _check_for_newest_block_and_update(
            subtensor=subtensor,
            netuid=netuid,
            hotkey_bytes=hotkey_bytes,
            old_block_number=old_block_number,
            curr_diff=curr_diff,
            curr_block=curr_block,
            curr_block_num=curr_block_num,
            curr_stats=curr_stats,
            update_curr_block=_update_curr_block,
            check_block=check_block,
            solvers=solvers,
        )

        num_time = 0
        for finished_queue in finished_queues:
            try:
                proc_num = finished_queue.get(timeout=0.1)
                num_time += 1

            except Empty:
                continue

        time_now = time.time()  # get current time
        time_since_last = time_now - time_last  # get time since last work block(s)
        if num_time > 0 and time_since_last > 0.0:
            # create EWMA of the hash_rate to make measure more robust

            if cuda:
                hash_rate_ = (num_time * tpb * update_interval) / time_since_last
            else:
                hash_rate_ = (num_time * update_interval) / time_since_last
            hash_rates.append(hash_rate_)
            hash_rates.pop(0)  # remove the 0th data point
            curr_stats.hash_rate = sum(
                [hash_rates[i] * weights[i] for i in range(n_samples)]
            ) / (sum(weights))

            # update time last to now
            time_last = time_now

            curr_stats.time_average = (
                curr_stats.time_average * curr_stats.rounds_total
                + curr_stats.time_spent
            ) / (curr_stats.rounds_total + num_time)
            curr_stats.rounds_total += num_time

        # Update stats
        curr_stats.time_spent = time_since_last
        new_time_spent_total = time_now - start_time_perpetual
        if cuda:
            curr_stats.hash_rate_perpetual = (
                curr_stats.rounds_total * (tpb * update_interval)
            ) / new_time_spent_total
        else:
            curr_stats.hash_rate_perpetual = (
                curr_stats.rounds_total * update_interval
            ) / new_time_spent_total
        curr_stats.time_spent_total = new_time_spent_total

        # Update the logger
        logger.update(curr_stats, verbose=log_verbose)

    # exited while, solution contains the nonce or wallet is registered
    stop_event.set()  # stop all other processes
    logger.stop()

    # terminate and wait for all solvers to exit
    _terminate_workers_and_wait_for_exit(solvers)

    return solution


def _solve_for_difficulty_fast_cuda(
    subtensor: "bittensor.subtensor",
    wallet: "bittensor.wallet",
    netuid: int,
    output_in_place: bool = True,
    update_interval: int = 50_000,
    tpb: int = 512,
    dev_id: typing.Union[list[int], int] = 0,
    n_samples: int = 10,
    alpha_: float = 0.80,
    log_verbose: bool = False,
) -> Optional[POWSolution]:
    """
    Solves the registration fast using CUDA
    Args:
        subtensor: bittensor.subtensor
            The subtensor node to grab blocks
        wallet: bittensor.wallet
            The wallet to register
        netuid: int
            The netuid of the subnet to register to.
        output_in_place: bool
            If true, prints the output in place, otherwise prints to new lines
        update_interval: int
            The number of nonces to try before checking for more blocks
        tpb: int
            The number of threads per block. CUDA param that should match the GPU capability
        dev_id: Union[List[int], int]
            The CUDA device IDs to execute the registration on, either a single device or a list of devices
        n_samples: int
            The number of samples of the hash_rate to keep for the EWMA
        alpha_: float
            The alpha for the EWMA for the hash_rate calculation
        log_verbose: bool
            If true, prints more verbose logging of the registration metrics.
    Note: The hash rate is calculated as an exponentially weighted moving average in order to make the measure more robust.
    """
    if isinstance(dev_id, int):
        dev_id = [dev_id]
    elif dev_id is None:
        dev_id = [0]

    if update_interval is None:
        update_interval = 50_000

    if not torch.cuda.is_available():
        raise Exception("CUDA not available")

    # Set mp start to use spawn so CUDA doesn't complain
    with _UsingSpawnStartMethod(force=True):
        curr_block, curr_block_num, curr_diff = _CUDASolver.create_shared_memory()

        solution = _block_solver(
            subtensor=subtensor,
            wallet=wallet,
            num_processes=None,
            netuid=netuid,
            dev_id=dev_id,
            tpb=tpb,
            update_interval=update_interval,
            curr_block=curr_block,
            curr_block_num=curr_block_num,
            curr_diff=curr_diff,
            n_samples=n_samples,
            cuda=True,
        )

        return solution


def _solve_for_difficulty_fast(
    subtensor,
    wallet: "bittensor.wallet",
    netuid: int,
    output_in_place: bool = True,
    num_processes: Optional[int] = None,
    update_interval: Optional[int] = None,
    n_samples: int = 10,
    alpha_: float = 0.80,
    log_verbose: bool = False,
) -> Optional[POWSolution]:
    """
    Solves the POW for registration using multiprocessing.
    Args:
        subtensor
            Subtensor to connect to for block information and to submit.
        wallet:
            wallet to use for registration.
        netuid: int
            The netuid of the subnet to register to.
        output_in_place: bool
            If true, prints the status in place. Otherwise, prints the status on a new line.
        num_processes: int
            Number of processes to use.
        update_interval: int
            Number of nonces to solve before updating block information.
        n_samples: int
            The number of samples of the hash_rate to keep for the EWMA
        alpha_: float
            The alpha for the EWMA for the hash_rate calculation
        log_verbose: bool
            If true, prints more verbose logging of the registration metrics.
    Note: The hash rate is calculated as an exponentially weighted moving average in order to make the measure more robust.
    Note:
    - We can also modify the update interval to do smaller blocks of work,
        while still updating the block information after a different number of nonces,
        to increase the transparency of the process while still keeping the speed.
    """
    if not num_processes:
        # get the number of allowed processes for this process
        num_processes = min(1, get_cpu_count())

    if update_interval is None:
        update_interval = 50_000

    curr_block, curr_block_num, curr_diff = _Solver.create_shared_memory()

    solution = _block_solver(
        subtensor=subtensor,
        wallet=wallet,
        num_processes=num_processes,
        netuid=netuid,
        dev_id=None,
        tpb=None,
        update_interval=update_interval,
        curr_block=curr_block,
        curr_block_num=curr_block_num,
        curr_diff=curr_diff,
        n_samples=n_samples,
        cuda=True,
    )

    return solution


def _terminate_workers_and_wait_for_exit(
    workers: list[typing.Union[Process, Queue]],
) -> None:
    for worker in workers:
        if isinstance(worker, Queue):
            worker.join_thread()
        else:
            worker.join()
        worker.close()


@backoff.on_exception(backoff.constant, Exception, interval=1, max_tries=3)
def _get_block_with_retry(
    subtensor: SubtensorInterface, netuid: int
) -> tuple[int, int, bytes]:
    """
    Gets the current block number, difficulty, and block hash from the substrate node.

    Args:
        subtensor (:obj:`bittensor.subtensor`, `required`):
            The subtensor object to use to get the block number, difficulty, and block hash.

        netuid (:obj:`int`, `required`):
            The netuid of the network to get the block number, difficulty, and block hash from.

    Returns:
        block_number (:obj:`int`):
            The current block number.

        difficulty (:obj:`int`):
            The current difficulty of the subnet.

        block_hash (:obj:`bytes`):
            The current block hash.

    Raises:
        Exception: If the block hash is None.
        ValueError: If the difficulty is None.
    """
    block_number = subtensor.get_current_block()
    difficulty = 1_000_000 if netuid == -1 else subtensor.difficulty(netuid=netuid)
    block_hash = subtensor.get_block_hash(block_number)
    if block_hash is None:
        raise Exception(
            "Network error. Could not connect to substrate to get block hash"
        )
    if difficulty is None:
        raise ValueError("Chain error. Difficulty is None")
    return block_number, difficulty, block_hash


class _UsingSpawnStartMethod:
    def __init__(self, force: bool = False):
        self._old_start_method = None
        self._force = force

    def __enter__(self):
        self._old_start_method = multiprocessing.get_start_method(allow_none=True)
        if self._old_start_method == None:
            self._old_start_method = "spawn"  # default to spawn

        multiprocessing.set_start_method("spawn", force=self._force)

    def __exit__(self, *args):
        # restore the old start method
        multiprocessing.set_start_method(self._old_start_method, force=True)


def create_pow(
    subtensor,
    wallet,
    netuid: int,
    output_in_place: bool = True,
    cuda: bool = False,
    dev_id: Union[List[int], int] = 0,
    tpb: int = 256,
    num_processes: int = None,
    update_interval: int = None,
    log_verbose: bool = False,
) -> Optional[Dict[str, Any]]:
    """
    Creates a proof of work for the given subtensor and wallet.
    Args:
        subtensor (:obj:`bittensor.subtensor.subtensor`, `required`):
            The subtensor to create a proof of work for.
        wallet (:obj:`bittensor.wallet.wallet`, `required`):
            The wallet to create a proof of work for.
        netuid (:obj:`int`, `required`):
            The netuid for the subnet to create a proof of work for.
        output_in_place (:obj:`bool`, `optional`, defaults to :obj:`True`):
            If true, prints the progress of the proof of work to the console
                in-place. Meaning the progress is printed on the same lines.
        cuda (:obj:`bool`, `optional`, defaults to :obj:`False`):
            If true, uses CUDA to solve the proof of work.
        dev_id (:obj:`Union[List[int], int]`, `optional`, defaults to :obj:`0`):
            The CUDA device id(s) to use. If cuda is true and dev_id is a list,
                then multiple CUDA devices will be used to solve the proof of work.
        tpb (:obj:`int`, `optional`, defaults to :obj:`256`):
            The number of threads per block to use when solving the proof of work.
            Should be a multiple of 32.
        num_processes (:obj:`int`, `optional`, defaults to :obj:`None`):
            The number of processes to use when solving the proof of work.
            If None, then the number of processes is equal to the number of
                CPU cores.
        update_interval (:obj:`int`, `optional`, defaults to :obj:`None`):
            The number of nonces to run before checking for a new block.
        log_verbose (:obj:`bool`, `optional`, defaults to :obj:`False`):
            If true, prints the progress of the proof of work more verbosely.
    Returns:
        :obj:`Optional[Dict[str, Any]]`: The proof of work solution or None if
            the wallet is already registered or there is a different error.

    Raises:
        :obj:`ValueError`: If the subnet does not exist.
    """
    if netuid != -1:
        if not subtensor.subnet_exists(netuid=netuid):
            raise ValueError(f"Subnet {netuid} does not exist")

    if cuda:
        solution: Optional[POWSolution] = _solve_for_difficulty_fast_cuda(
            subtensor,
            wallet,
            netuid=netuid,
            output_in_place=output_in_place,
            dev_id=dev_id,
            tpb=tpb,
            update_interval=update_interval,
            log_verbose=log_verbose,
        )
    else:
        solution: Optional[POWSolution] = _solve_for_difficulty_fast(
            subtensor,
            wallet,
            netuid=netuid,
            output_in_place=output_in_place,
            num_processes=num_processes,
            update_interval=update_interval,
            log_verbose=log_verbose,
        )

    return solution
