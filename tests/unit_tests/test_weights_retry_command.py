from bittensor_cli.src.commands.weights import _build_reveal_retry_command


class _NumpyArrayLikeRepr:
    """Iterable whose ``str()`` mimics ``numpy.ndarray.__str__`` (space-separated,
    bracketed, no commas), so we can pin the regression where the historical
    code formatted ``self.weights`` via ``str(...)`` and emitted ``[0.5 0.3 0.2]``
    into the retry command. The helper iterates element-by-element, so a plain
    iterable is enough to exercise the same code path without pulling numpy in
    as a unit-test dependency.
    """

    def __init__(self, values):
        self._values = list(values)

    def __iter__(self):
        return iter(self._values)

    def __str__(self):
        return "[" + " ".join(str(v) for v in self._values) + "]"


def test_builds_runnable_btcli_weights_reveal_command():
    """The retry message printed after `btcli weights commit` must be a
    command the user can copy-paste. That means:

    - Starts with `btcli weights reveal` so it is self-contained.
    - List args are comma-separated (what cli.parse_to_list expects), not
      Python list repr or numpy array repr.
    - The flag is `--salt`, which is the one defined on `weights reveal`.
      The historical name `--reveal-using-salt` is not a real flag.
    """
    cmd = _build_reveal_retry_command(
        netuid=1,
        uids=[1, 2, 3],
        weights=_NumpyArrayLikeRepr([0.5, 0.3, 0.2]),
        salt=[42, 17, 8, 234, 113, 250, 91, 180],
    )

    assert cmd.startswith("btcli weights reveal ")
    assert "--netuid 1" in cmd
    assert "--uids 1,2,3" in cmd
    assert "--weights 0.5,0.3,0.2" in cmd
    assert "--salt 42,17,8,234,113,250,91,180" in cmd

    # Regressions: never print Python list / numpy repr or the wrong flag.
    assert "[" not in cmd and "]" not in cmd
    assert "--reveal-using-salt" not in cmd


def test_handles_int_uids_int_weights_and_list_salt():
    # _set_weights_without_commit_reveal-style inputs should also format cleanly.
    cmd = _build_reveal_retry_command(
        netuid=7,
        uids=[0],
        weights=[1.0],
        salt=[0],
    )

    assert cmd == ("btcli weights reveal --netuid 7 --uids 0 --weights 1.0 --salt 0")
