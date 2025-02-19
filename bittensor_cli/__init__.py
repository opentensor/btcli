# The MIT License (MIT)
# Copyright © 2024 Opentensor Foundation
#
# Permission is hereby granted, free of charge, to any person obtaining a copy of this software and associated
# documentation files (the “Software”), to deal in the Software without restriction, including without limitation
# the rights to use, copy, modify, merge, publish, distribute, sublicense, and/or sell copies of the Software,
# and to permit persons to whom the Software is furnished to do so, subject to the following conditions:
#
# The above copyright notice and this permission notice shall be included in all copies or substantial portions of
# the Software.
#
# THE SOFTWARE IS PROVIDED “AS IS”, WITHOUT WARRANTY OF ANY KIND, EXPRESS OR IMPLIED, INCLUDING BUT NOT LIMITED TO
# THE WARRANTIES OF MERCHANTABILITY, FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL
# THE AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER LIABILITY, WHETHER IN AN ACTION
# OF CONTRACT, TORT OR OTHERWISE, ARISING FROM, OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER
# DEALINGS IN THE SOFTWARE.

from .cli import CLIManager

def version_as_int(version):
    import re
    _core_version = re.match(r"^\d+\.\d+\.\d+", version).group(0)
    _version_split = _core_version.split(".")
    __version_info__ = tuple(int(part) for part in _version_split)
    _version_int_base = 1000
    assert max(__version_info__) < _version_int_base

    __version_as_int__: int = sum(
        e * (_version_int_base**i) for i, e in enumerate(reversed(__version_info__))
    )
    assert __version_as_int__ < 2**31  # fits in int32
    __new_signature_version__ = 360
    return __version_as_int__

__version__ = "9.0.1"
__version_as_int__ = version_as_int(__version__)

__all__ = ["CLIManager", "__version__", "__version_as_int__"]
