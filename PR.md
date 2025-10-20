# Add Warning for `swap_hotkey --netuid 0` to Prevent Accidental Misuse

## Problem

Users accidentally using `btcli wallet swap_hotkey --netuid 0` may not realize that this command only swaps the hotkey on the root network (netuid 0) and does NOT move child hotkey delegation mappings. This is NOT a full hotkey swap across all subnets, which can lead to unexpected behavior and confusion.

### What Happens with `--netuid 0`
- ❌ Only swaps on root network (netuid 0)
- ❌ Does NOT move child hotkey delegation mappings
- ❌ Does NOT swap across all other subnets

### Expected Behavior (Without `--netuid`)
- ✅ Swaps hotkey across ALL subnets
- ✅ Complete hotkey migration
- ✅ Recommended for most users

## Solution

This PR adds a prominent warning and confirmation prompt when users attempt to use `--netuid 0` with the `swap_hotkey` command. The warning clearly explains:
1. What `--netuid 0` actually does (only root network swap)
2. What it does NOT do (move child delegation, full swap)
3. The recommended command to use instead

## Changes Made

### 1. `bittensor_cli/cli.py`
- Added warning check for `netuid == 0` in `wallet_swap_hotkey()` method
- Warning displays:
  - Clear explanation of `--netuid 0` behavior
  - Statement that it won't move child hotkey delegation mappings
  - Recommended command without `--netuid` flag
  - Requires explicit user confirmation to proceed
- Updated docstring to clarify netuid behavior
- Only shows warning when `prompt=True` (skips for automated scripts)

### 2. `tests/unit_tests/test_cli.py`
Added 4 comprehensive unit tests:
- `test_swap_hotkey_netuid_0_warning_with_prompt`: Verifies warning is shown and user can decline
- `test_swap_hotkey_netuid_0_proceeds_with_confirmation`: Verifies operation proceeds when user confirms
- `test_swap_hotkey_netuid_0_no_warning_with_no_prompt`: Verifies no warning when `--no-prompt` is used
- `test_swap_hotkey_netuid_1_no_warning`: Verifies no warning for other netuids

### 3. `CHANGELOG.md`
- Documented the fix in version 9.13.2

## Warning Example

When a user runs:
```bash
btcli wallet swap_hotkey new_hotkey \
  --wallet-name wallet \
  --wallet-hotkey old_hotkey \
  --netuid 0
```

They now see:
```
⚠️  WARNING: Using --netuid 0 for swap_hotkey

Specifying --netuid 0 will ONLY swap the hotkey on the root network (netuid 0).

It will NOT move child hotkey delegation mappings on root.

btcli wallet swap_hotkey new_hotkey --wallet-name wallet --wallet-hotkey old_hotkey

Are you SURE you want to proceed with --netuid 0 (only root network swap)? [y/n] (n):
```

## Testing

### Unit Tests
All 4 new unit tests pass:
```bash
pytest tests/unit_tests/test_cli.py -k "swap_hotkey" -v
# ✅ 4 passed
```

### Manual CLI Testing
- ✅ `--netuid 0` with prompt: Shows warning, requires confirmation
- ✅ `--netuid 1` (normal): No warning shown
- ✅ `--netuid 0 --no-prompt`: No warning (automation support)
- ✅ No `--netuid` flag: No warning (recommended usage)

## Behavior

| Command | Warning Shown? | Behavior |
|---------|----------------|----------|
| `swap_hotkey ... --netuid 0` | ⚠️ YES | Shows warning, requires confirmation |
| `swap_hotkey ... --netuid 1` | ✅ NO | Swaps on netuid 1 only (as expected) |
| `swap_hotkey ...` (no netuid) | ✅ NO | Full swap across all subnets (recommended) |
| `swap_hotkey ... --netuid 0 --no-prompt` | ✅ NO | Skips warning for automation |

## Related Context

This fix addresses user confusion discovered when a user accidentally ran `swap_hotkey` with `--netuid 0` expecting a full swap but only got a root network swap without child delegation movement. The warning prevents this mistake and guides users to the correct usage.

## Checklist

- [x] Code follows existing patterns in the codebase
- [x] Uses `Confirm.ask()` consistent with other warnings
- [x] Added comprehensive unit tests (4 tests)
- [x] Updated CHANGELOG.md
- [x] Updated docstring documentation
- [x] Tested manually with CLI
- [x] Warning only shows when appropriate (not for automation)
- [x] No new linting errors introduced

