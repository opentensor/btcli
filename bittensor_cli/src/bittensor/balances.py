# The MIT License (MIT)
# Copyright © 2021-2022 Yuma Rao
# Copyright © 2022 Opentensor Foundation
# Copyright © 2023 Opentensor Technologies Inc

# Permission is hereby granted, free of charge, to any person obtaining a copy of this software and associated
# documentation files (the “Software”), to deal in the Software without restriction, including without limitation
# the rights to use, copy, modify, merge, publish, distribute, sublicense, and/or sell copies of the Software,
# and to permit persons to whom the Software is furnished to do so, subject to the following conditions:

# The above copyright notice and this permission notice shall be included in all copies or substantial portions of
# the Software.

# THE SOFTWARE IS PROVIDED “AS IS”, WITHOUT WARRANTY OF ANY KIND, EXPRESS OR IMPLIED, INCLUDING BUT NOT LIMITED TO
# THE WARRANTIES OF MERCHANTABILITY, FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL
# THE AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER LIABILITY, WHETHER IN AN ACTION
# OF CONTRACT, TORT OR OTHERWISE, ARISING FROM, OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER
# DEALINGS IN THE SOFTWARE.

from typing import Union
from bittensor_cli.src import UNITS


class Balance:
    """
    Represents the bittensor balance of the wallet, stored as rao (int).
    This class provides a way to interact with balances in two different units: rao and tao.
    It provides methods to convert between these units, as well as to perform arithmetic and comparison operations.

    :var unit: A string representing the symbol for the tao unit.
    :var rao_unit: A string representing the symbol for the rao unit.
    :var rao: An integer that stores the balance in rao units.
    :var tao: A float property that gives the balance in tao units.
    """

    unit: str = chr(0x03C4)  # This is the tao unit
    rao_unit: str = chr(0x03C1)  # This is the rao unit
    rao: int
    tao: float

    def __init__(self, balance: Union[int, float]):
        """
        Initialize a Balance object. If balance is an int, it's assumed to be in rao.
        If balance is a float, it's assumed to be in tao.

        :param balance: The initial balance, in either rao (if an int) or tao (if a float).
        """
        if isinstance(balance, int):
            self.rao = balance
        elif isinstance(balance, float):
            # Assume tao value for the float
            self.rao = int(balance * pow(10, 9))
        else:
            raise TypeError("balance must be an int (rao) or a float (tao)")

    @property
    def tao(self):
        return self.rao / pow(10, 9)

    def __int__(self):
        """
        Convert the Balance object to an int. The resulting value is in rao.
        """
        return self.rao

    def __float__(self):
        """
        Convert the Balance object to a float. The resulting value is in tao.
        """
        return self.tao

    def __str__(self):
        """
        Returns the Balance object as a string in the format "symbolvalue", where the value is in tao.
        """
        if self.unit == UNITS[0]:
            return f"{self.unit} {float(self.tao):,.4f}"
        else:
            return f"\u200e{float(self.tao):,.4f} {self.unit}\u200e"

    def __rich__(self):
        return "[green]{}[/green][green]{}[/green][green].[/green][dim green]{}[/dim green]".format(
            self.unit,
            format(float(self.tao), "f").split(".")[0],
            format(float(self.tao), "f").split(".")[1],
        )

    def __str_rao__(self):
        return f"{self.rao_unit}{int(self.rao)}"

    def __rich_rao__(self):
        return f"[green]{self.rao_unit}{int(self.rao)}[/green]"

    def __repr__(self):
        return self.__str__()

    def __bool__(self):
        return self.rao != 0

    def __eq__(self, other: Union[int, float, "Balance"]):
        if other is None:
            return False

        if hasattr(other, "rao"):
            return self.rao == other.rao
        else:
            try:
                # Attempt to cast to int from rao
                other_rao = int(other)
                return self.rao == other_rao
            except (TypeError, ValueError):
                raise NotImplementedError("Unsupported type")

    def __ne__(self, other: Union[int, float, "Balance"]):
        return not self == other

    def __gt__(self, other: Union[int, float, "Balance"]):
        if hasattr(other, "rao"):
            return self.rao > other.rao
        else:
            try:
                # Attempt to cast to int from rao
                other_rao = int(other)
                return self.rao > other_rao
            except ValueError:
                raise NotImplementedError("Unsupported type")

    def __lt__(self, other: Union[int, float, "Balance"]):
        if hasattr(other, "rao"):
            return self.rao < other.rao
        else:
            try:
                # Attempt to cast to int from rao
                other_rao = int(other)
                return self.rao < other_rao
            except ValueError:
                raise NotImplementedError("Unsupported type")

    def __le__(self, other: Union[int, float, "Balance"]):
        try:
            return self < other or self == other
        except TypeError:
            raise NotImplementedError("Unsupported type")

    def __ge__(self, other: Union[int, float, "Balance"]):
        try:
            return self > other or self == other
        except TypeError:
            raise NotImplementedError("Unsupported type")

    def __add__(self, other: Union[int, float, "Balance"]):
        if hasattr(other, "rao"):
            return Balance.from_rao(int(self.rao + other.rao))
        else:
            try:
                # Attempt to cast to int from rao
                return Balance.from_rao(int(self.rao + other))
            except (ValueError, TypeError):
                raise NotImplementedError("Unsupported type")

    def __radd__(self, other: Union[int, float, "Balance"]):
        try:
            return self + other
        except TypeError:
            raise NotImplementedError("Unsupported type")

    def __sub__(self, other: Union[int, float, "Balance"]):
        try:
            return self + -other
        except TypeError:
            raise NotImplementedError("Unsupported type")

    def __rsub__(self, other: Union[int, float, "Balance"]):
        try:
            return -self + other
        except TypeError:
            raise NotImplementedError("Unsupported type")

    def __mul__(self, other: Union[int, float, "Balance"]):
        if hasattr(other, "rao"):
            return Balance.from_rao(int(self.rao * other.rao))
        else:
            try:
                # Attempt to cast to int from rao
                return Balance.from_rao(int(self.rao * other))
            except (ValueError, TypeError):
                raise NotImplementedError("Unsupported type")

    def __rmul__(self, other: Union[int, float, "Balance"]):
        return self * other

    def __truediv__(self, other: Union[int, float, "Balance"]):
        if hasattr(other, "rao"):
            return Balance.from_rao(int(self.rao / other.rao))
        else:
            try:
                # Attempt to cast to int from rao
                return Balance.from_rao(int(self.rao / other))
            except (ValueError, TypeError):
                raise NotImplementedError("Unsupported type")

    def __rtruediv__(self, other: Union[int, float, "Balance"]):
        if hasattr(other, "rao"):
            return Balance.from_rao(int(other.rao / self.rao))
        else:
            try:
                # Attempt to cast to int from rao
                return Balance.from_rao(int(other / self.rao))
            except (ValueError, TypeError):
                raise NotImplementedError("Unsupported type")

    def __floordiv__(self, other: Union[int, float, "Balance"]):
        if hasattr(other, "rao"):
            return Balance.from_rao(int(self.tao // other.tao))
        else:
            try:
                # Attempt to cast to int from rao
                return Balance.from_rao(int(self.rao // other))
            except (ValueError, TypeError):
                raise NotImplementedError("Unsupported type")

    def __rfloordiv__(self, other: Union[int, float, "Balance"]):
        if hasattr(other, "rao"):
            return Balance.from_rao(int(other.rao // self.rao))
        else:
            try:
                # Attempt to cast to int from rao
                return Balance.from_rao(int(other // self.rao))
            except (ValueError, TypeError):
                raise NotImplementedError("Unsupported type")

    def __nonzero__(self) -> bool:
        return bool(self.rao)

    def __neg__(self):
        return Balance.from_rao(-self.rao)

    def __pos__(self):
        return Balance.from_rao(self.rao)

    def __abs__(self):
        return Balance.from_rao(abs(self.rao))

    def to_dict(self) -> dict:
        return {"rao": self.rao, "tao": self.tao}

    @staticmethod
    def from_float(amount: float):
        """
        Given tao (float), return Balance object with rao(int) and tao(float), where rao = int(tao*pow(10,9))
        :param amount: The amount in tao.

        :return: A Balance object representing the given amount.
        """
        rao = int(amount * pow(10, 9))
        return Balance(rao)

    @staticmethod
    def from_tao(amount: float):
        """
        Given tao (float), return Balance object with rao(int) and tao(float), where rao = int(tao*pow(10,9))

        :param amount: The amount in tao.

        :return: A Balance object representing the given amount.
        """
        rao = int(amount * pow(10, 9))
        return Balance(rao)

    @staticmethod
    def from_rao(amount: int):
        """
        Given rao (int), return Balance object with rao(int) and tao(float), where rao = int(tao*pow(10,9))

        :param amount: The amount in rao.

        :return: A Balance object representing the given amount.
        """
        return Balance(int(amount))

    @staticmethod
    def get_unit(netuid: int):
        units = UNITS
        base = len(units)
        if netuid < base:
            return units[netuid]
        else:
            result = ""
            while netuid > 0:
                result = units[netuid % base] + result
                netuid //= base
            return result

    def set_unit(self, netuid: int):
        self.unit = Balance.get_unit(netuid)
        self.rao_unit = Balance.get_unit(netuid)
        return self


def fixed_to_float(fixed, frac_bits: int = 64, total_bits: int = 128) -> float:
    # By default, this is a U64F64
    # which is 64 bits of integer and 64 bits of fractional

    data: int = fixed["bits"]

    # Logical and to get the fractional part; remaining is the integer part
    fractional_part = data & (2**frac_bits - 1)
    # Shift to get the integer part from the remaining bits
    integer_part = data >> (total_bits - frac_bits)

    frac_float = fractional_part / (2**frac_bits)

    return integer_part + frac_float
