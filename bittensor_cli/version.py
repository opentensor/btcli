import re

def version_as_int(version):
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

__version__ = "9.0.2"
__version_as_int__ = version_as_int(__version__)
