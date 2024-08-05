import asyncio

import numpy as np
from numpy.typing import NDArray

from src.bittensor.chain_data import NeuronInfo
from src.subtensor_interface import SubtensorInterface
from src.utils import (
    convert_root_weight_uids_and_vals_to_tensor,
    convert_weight_uids_and_vals_to_tensor,
    convert_bond_uids_and_vals_to_tensor,
)


class MiniGraph:
    def __init__(
        self, netuid: int, neurons: list[NeuronInfo], subtensor: "SubtensorInterface"
    ):
        self.neurons = neurons
        self.netuid = netuid
        self.axons = [n.axon_info for n in self.neurons]
        self.n = np.array(len(neurons), dtype=np.int64)
        self.weights = None
        self.subtensor = subtensor

    async def __aenter__(self):
        if not self.weights:
            await self._set_weights_and_bonds()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        pass

    @property
    def hotkeys(self):
        return [axon.hotkey for axon in self.axons]

    async def _set_weights_and_bonds(self):
        """
        Computes and sets the weights and bonds for each neuron in the metagraph. This method is responsible for
        processing the raw weight and bond data obtained from the network and converting it into a structured format
        suitable for the metagraph model.
        """
        # TODO: Check and test the computation of weights and bonds
        if self.netuid == 0:
            self.weights = self._process_root_weights(
                [neuron.weights for neuron in self.neurons], "weights"
            )
        else:
            self.weights = self._process_weights_or_bonds(
                [neuron.weights for neuron in self.neurons], "weights"
            )
            self.bonds = self._process_weights_or_bonds(
                [neuron.bonds for neuron in self.neurons], "bonds"
            )

    def _process_weights_or_bonds(self, data, attribute: str) -> NDArray:
        """
        Processes the raw weights or bonds data and converts it into a structured tensor format. This method handles
        the transformation of neuron connection data (`weights` or `bonds`) from a list or other unstructured
        format into a tensor that can be utilized within the metagraph model.

        :param data: The raw weights or bonds data to be processed. This data typically comes from the subtensor.
                     attribute: A string indicating whether the data is `weights` or `bonds`, which determines the
                     specific processing steps to be applied.

        :return: A tensor parameter encapsulating the processed weights or bonds data.
        """
        data_array = []
        for item in data:
            if len(item) == 0:
                data_array.append(np.zeros(len(self.neurons), dtype=np.float32))  # type: ignore
            else:
                uids, values = zip(*item)
                # TODO: Validate and test the conversion of uids and values to tensor
                if attribute == "weights":
                    data_array.append(
                        convert_weight_uids_and_vals_to_tensor(
                            len(self.neurons),
                            list(uids),
                            list(values),  # type: ignore
                        )
                    )
                else:
                    data_array.append(
                        convert_bond_uids_and_vals_to_tensor(  # type: ignore
                            len(self.neurons), list(uids), list(values)
                        ).astype(np.float32)
                    )
        tensor_param: NDArray = (
            np.stack(data_array) if len(data_array) else np.array([], dtype=np.float32)
        )
        if len(data_array) == 0:
            # bittensor.logging.warning(
            #     f"Empty {attribute}_array on metagraph.sync(). The '{attribute}' tensor is empty."
            # )
            pass
        return tensor_param

    async def _process_root_weights(self, data, attribute: str) -> NDArray:
        """
        Specifically processes the root weights data for the metagraph. This method is similar to
        `_process_weights_or_bonds` but is tailored for processing root weights, which have a different structure and
        significance in the network.

        Args:
        :param data: The raw root weights data to be processed.
        :param attribute: A string indicating the attribute type, here it's typically `weights`.

        :return: A tensor parameter encapsulating the processed root weights data.
        """

        async def get_total_subnets():
            _result = self.subtensor.substrate.query(
                module="SubtensorModule",
                storage_function="TotalNetworks",
                params=[],
                reuse_block_hash=True,
            )
            return getattr(_result, "value", 0)

        async def get_subnets():
            _result = await self.subtensor.substrate.query_map(
                module="SubtensorModule",
                storage_function="NetworksAdded",
                params=[],
                reuse_block_hash=True,
            )
            return (
                [network[0].value for network in _result.records]
                if _result and hasattr(_result, "records")
                else []
            )

        data_array = []
        n_subnets, subnets = await asyncio.gather(get_total_subnets(), get_subnets())
        for item in data:
            if len(item) == 0:
                data_array.append(np.zeros(n_subnets, dtype=np.float32))  # type: ignore
            else:
                uids, values = zip(*item)
                data_array.append(
                    convert_root_weight_uids_and_vals_to_tensor(  # type: ignore
                        n_subnets, list(uids), list(values), subnets
                    )
                )

        tensor_param: NDArray = (
            np.stack(data_array) if len(data_array) else np.array([], dtype=np.float32)
        )
        if len(data_array) == 0:
            pass
            # bittensor.logging.warning(
            #     f"Empty {attribute}_array on metagraph.sync(). The '{attribute}' tensor is empty."
            # )
        return tensor_param
