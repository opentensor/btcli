import importlib.metadata
import re


def version_as_int(version):
    match = re.match(r"^\d+\.\d+\.\d+", version)
    if not match:
        raise ValueError(f"Invalid version format: {version}")
    core_version = match.group(0)
    version_split = core_version.split(".")
    version_info = tuple(int(part) for part in version_split)
    version_int_base = 1000
    assert max(version_info) < version_int_base

    version_as_int_: int = sum(
        e * (version_int_base**i) for i, e in enumerate(reversed(version_info))
    )
    assert version_as_int_ < 2**31  # fits in int32
    return version_as_int_


__version__ = importlib.metadata.version("bittensor-cli")
__version_as_int__ = version_as_int(__version__)
