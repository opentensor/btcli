import asyncio

from array import array

from bittensor_cli.src.bittensor.chain_data import NeuronInfo, SubnetState
from bittensor_cli.src.bittensor.subtensor_interface import SubtensorInterface


class MiniGraph:
    def __init__(
        self,
        netuid: int,
        neurons: list[NeuronInfo],
        subtensor: "SubtensorInterface",
        subnet_state: "SubnetState",
        block: int,
    ):
        self.neurons = neurons
        self.netuid = netuid
        self.weights = None
        self.subtensor = subtensor
        self.network = subtensor.network

        self.axons = [n.axon_info for n in self.neurons]
        self.n = self._create_tensor([len(self.neurons)], ctype="q")
        self.block = self._create_tensor([block], "q")
        self.uids = self._create_tensor([neuron.uid for neuron in self.neurons], "q")
        self.trust = self._create_tensor(
            [neuron.trust for neuron in self.neurons], ctype="f"
        )
        self.consensus = self._create_tensor(
            [neuron.consensus for neuron in self.neurons], ctype="f"
        )
        self.incentive = self._create_tensor(
            [neuron.incentive for neuron in self.neurons], ctype="f"
        )
        self.dividends = self._create_tensor(
            [neuron.dividends for neuron in self.neurons], ctype="f"
        )
        self.ranks = self._create_tensor(
            [neuron.rank for neuron in self.neurons], ctype="f"
        )
        self.emission = self._create_tensor(
            [neuron.emission for neuron in self.neurons], ctype="f"
        )
        self.active = self._create_tensor(
            [neuron.active for neuron in self.neurons], ctype="q"
        )
        self.last_update = self._create_tensor(
            [neuron.last_update for neuron in self.neurons], ctype="q"
        )
        self.validator_permit = self._create_tensor(
            [neuron.validator_permit for neuron in self.neurons], ctype="B"
        )
        self.validator_trust = self._create_tensor(
            [neuron.validator_trust for neuron in self.neurons], ctype="f"
        )

        # Fetch stakes from subnet_state until we get updated data in NeuronInfo
        global_stake_list, local_stake_list, stake_weights_list = self._process_stakes(
            neurons, subnet_state
        )
        self.global_stake = self._create_tensor(global_stake_list, ctype="f")
        self.local_stake = self._create_tensor(local_stake_list, ctype="f")
        self.stake_weights = self._create_tensor(stake_weights_list, ctype="f")

    async def __aenter__(self):
        if not self.weights:
            await self._set_weights_and_bonds()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        pass

    @property
    def hotkeys(self):
        return [axon.hotkey for axon in self.axons]

    @staticmethod
    def _create_tensor(data, ctype) -> array:
        """
        Creates an array of the given data.

        Args:
            data: The data to be included in the tensor. This could be any numeric data, like stakes, ranks, etc.
            ctype: The data type for the tensor, see the docstring for array.ArrayType

        Returns:
            A tensor parameter encapsulating the provided data.

        Internal Usage:
            Used internally to create tensor parameters for various metagraph attributes::

                self.stake = self._create_tensor(neuron_stakes, dtype="f")
        """
        return array(ctype, data)

    async def _set_weights_and_bonds(self):
        """
        Computes and sets the weights and bonds for each neuron in the metagraph. This method is responsible for
        processing the raw weight and bond data obtained from the network and converting it into a structured format
        suitable for the metagraph model.
        """
        # TODO: Check and test the computation of weights and bonds
        if self.netuid == 0:
            self.weights = await self._process_root_weights(
                [neuron.weights for neuron in self.neurons], "weights"
            )
        else:
            self.weights = self._process_weights_or_bonds(
                [neuron.weights for neuron in self.neurons], "weights"
            )
            self.bonds = self._process_weights_or_bonds(
                [neuron.bonds for neuron in self.neurons], "bonds"
            )

    def _process_stakes(
        self,
        neurons: list[NeuronInfo],
        subnet_state: SubnetState,
    ) -> tuple[list[float], list[float], list[float]]:
        """
        Processes the global_stake, local_stake, and stake_weights based on the neuron's hotkey.

        Args:
            neurons (List[NeuronInfo]): List of neurons.
            subnet_state (SubnetState): The subnet state containing stake information.

        Returns:
            tuple[list[float], list[float], list[float]]: Lists of global_stake, local_stake, and stake_weights.
        """
        global_stake_list = []
        local_stake_list = []
        stake_weights_list = []
        hotkey_to_index = {
            hotkey: idx for idx, hotkey in enumerate(subnet_state.hotkeys)
        }

        for neuron in neurons:
            idx = hotkey_to_index.get(neuron.hotkey)
            if idx is not None:
                global_stake_list.append(subnet_state.global_stake[idx].tao)
                local_stake_list.append(subnet_state.local_stake[idx].tao)
                stake_weights_list.append(subnet_state.stake_weight[idx])
            else:
                global_stake_list.append(0.0)
                local_stake_list.append(0.0)
                stake_weights_list.append(0.0)

        return global_stake_list, local_stake_list, stake_weights_list

    def _process_weights_or_bonds(self, data, attribute: str) -> list[array]:
        """
        Processes the raw weights or bonds data and converts it into a list of per-neuron float32 rows.

        :param data: The raw weights or bonds data to be processed. This data typically comes from the subtensor.
        :param attribute: ``"weights"`` (normalized to sum to 1.0) or ``"bonds"`` (no normalization).

        :return: One ``array("f", ...)`` row per input item, each of length ``len(self.neurons)``.
        """
        n = len(self.neurons)
        data_array: list[array] = []
        for item in data:
            row = array("f", bytes(4 * n))
            if len(item) == 0:
                data_array.append(row)
                continue

            uids, values = zip(*item)
            if attribute == "weights":
                for uid_j, wij in zip(uids, values):
                    row[uid_j] = float(wij)
                row_sum = sum(row)
                if row_sum > 0:
                    row = array("f", (v / row_sum for v in row))
            else:  # bonds
                for uid_j, bij in zip(uids, values):
                    row[uid_j] = float(int(bij))
            data_array.append(row)
        return data_array

    async def _process_root_weights(self, data, attribute: str) -> list[array]:
        """
        Specifically processes the root weights data for the metagraph. This method is similar to
        `_process_weights_or_bonds` but is tailored for processing root weights, which have a different structure and
        significance in the network.

        :param data: The raw root weights data to be processed.
        :param attribute: A string indicating the attribute type, here it's typically `weights`.

        :return: One ``array("f", ...)`` row per input item, each of length ``n_subnets``.
        """

        async def get_total_subnets():
            _result = await self.subtensor.query(
                module="SubtensorModule",
                storage_function="TotalNetworks",
                params=[],
            )
            return _result

        async def get_subnets():
            _result = await self.subtensor.query(
                module="SubtensorModule",
                storage_function="TotalNetworks",
            )
            return [i for i in range(_result)]

        n_subnets, subnets = await asyncio.gather(get_total_subnets(), get_subnets())
        data_array: list[array] = []
        for item in data:
            row = array("f", bytes(4 * n_subnets))
            if len(item) == 0:
                data_array.append(row)
                continue

            uids, values = zip(*item)
            for uid_j, wij in zip(uids, values):
                if uid_j in subnets:
                    index_s = subnets.index(uid_j)
                    row[index_s] = float(wij)
            row_sum = sum(row)
            if row_sum > 0:
                row = array("f", (v / row_sum for v in row))
            data_array.append(row)
        return data_array
