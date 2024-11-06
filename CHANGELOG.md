# Changelog

## 8.3.0 /2024-11-06

## What's Changed

* Better handle incorrect password by @thewhaleking in https://github.com/opentensor/btcli/pull/187
* Fixes success path of pow register by @ibraheem-opentensor in https://github.com/opentensor/btcli/pull/189
* Adds `--all` flag to transfer by @thewhaleking in https://github.com/opentensor/btcli/pull/181
* Various fixes by @thewhaleking in https://github.com/opentensor/btcli/pull/199
* Fix wallets in overview by @thewhaleking in https://github.com/opentensor/btcli/pull/197
* fix handling null neurons by @thewhaleking in https://github.com/opentensor/btcli/pull/214
* Fix cuda pow registration by @thewhaleking in https://github.com/opentensor/btcli/pull/215
* Adds confirmation after each successful regen by @ibraheem-opentensor in https://github.com/opentensor/btcli/pull/203
* Removes wallet path prompt by @ibraheem-opentensor in https://github.com/opentensor/btcli/pull/205
* Support hotkey names for include/exclude in st add/remove by @thewhaleking in https://github.com/opentensor/btcli/pull/216
* Subvortex network added by @thewhaleking  in https://github.com/opentensor/btcli/pull/223
* Add prompt option to all commands which use Confirm prompts by @thewhaleking in https://github.com/opentensor/btcli/pull/227
* Update local subtensor port by @distributedstatemachine in https://github.com/opentensor/btcli/pull/228

**Full Changelog**: https://github.com/opentensor/btcli/compare/v8.2.0...v8.3.0

## 8.2.0 /2024-10-10

## What's Changed
* Handle git not installed by @thewhaleking in https://github.com/opentensor/btcli/pull/164
* Handle receiving task cancellation by @thewhaleking in https://github.com/opentensor/btcli/pull/166
* Change network option to a list so that it can be correctly parsed if multiple options are given by @thewhaleking in https://github.com/opentensor/btcli/pull/165
* Receiving task cancellation improvement by @thewhaleking in https://github.com/opentensor/btcli/pull/168
* mnemonic change: support numbered mnemonic by @thewhaleking in https://github.com/opentensor/btcli/pull/167
* Backmerge release 8.1.1 by @ibraheem-opentensor in https://github.com/opentensor/btcli/pull/169
* Handle custom errors from subtensor by @thewhaleking in https://github.com/opentensor/btcli/pull/79
* Removes check for port in chain endpoint by @ibraheem-opentensor in https://github.com/opentensor/btcli/pull/170
* Shifts Tao conversion to correct place in stake remove by @ibraheem-opentensor in https://github.com/opentensor/btcli/pull/172
* Adds support for ss58 addresses in wallet balance by @ibraheem-opentensor in https://github.com/opentensor/btcli/pull/171
* Fixes network instantiation in root list-delegates by @ibraheem-opentensor in https://github.com/opentensor/btcli/pull/173
* Utils App with convert command by @thewhaleking in https://github.com/opentensor/btcli/pull/174
* Fixes for rpc request error handler, root list default empty values, prev delegate fetching by @thewhaleking in https://github.com/opentensor/btcli/pull/175
* Bumps version, updates requirement for 8.1.2 by @ibraheem-opentensor in https://github.com/opentensor/btcli/pull/176

**Full Changelog**: https://github.com/opentensor/btcli/compare/v8.1.1...v8.2.0

## 8.1.1 /2024-10-04

## What's Changed

* Handles missing hotkey file when traversing wallet by @ibraheem-opentensor in https://github.com/opentensor/btcli/pull/161
* Backmerge/8.1.0 by @ibraheem-opentensor in https://github.com/opentensor/btcli/pull/162

**Full Changelog**: https://github.com/opentensor/btcli/compare/v8.0.0...v8.1.1

## 8.1.0 /2024-10-03

## What's Changed
* Allow for delegate take between 0 and 18% by @garrett-opentensor in https://github.com/opentensor/btcli/pull/123
* Fixed: wallet balance check when undelegating the stake by @the-mx in https://github.com/opentensor/btcli/pull/124
* `root my-delegates` ask for path instead of name when using `--all` by @thewhaleking in https://github.com/opentensor/btcli/pull/126
* Fix/delegate all by @the-mx in https://github.com/opentensor/btcli/pull/125
* Handle SSL errors and avoid unnecessary chain head calls by @thewhaleking in https://github.com/opentensor/btcli/pull/127
* Deprecate: Remove chain config by @ibraheem-opentensor in https://github.com/opentensor/btcli/pull/128
* Update staging by @thewhaleking in https://github.com/opentensor/btcli/pull/130
* set archive node properly by @thewhaleking in https://github.com/opentensor/btcli/pull/143
* Randomise rpc request ID by @thewhaleking in https://github.com/opentensor/btcli/pull/131
* update help text in the BTCLI by @dougsillars in https://github.com/opentensor/btcli/pull/139
* Backmerge/main to staging - 1st oct by @ibraheem-opentensor in https://github.com/opentensor/btcli/pull/145
* Backmerge main to staging by @ibraheem-opentensor in https://github.com/opentensor/btcli/pull/147
* Updates "btcli w set-identity" by @ibraheem-opentensor in https://github.com/opentensor/btcli/pull/146
* Give recent commit in version by @thewhaleking in https://github.com/opentensor/btcli/pull/156
* Rename `not_subtensor` to `subtensor` by @thewhaleking in https://github.com/opentensor/btcli/pull/157
* Integrate Rust Wallet — tests by @thewhaleking @opendansor @roman-opentensor @ibraheem-opentensor @camfairchild  in https://github.com/opentensor/btcli/pull/158

## New Contributors
* @the-mx made their first contribution in https://github.com/opentensor/btcli/pull/124
* @dougsillars made their first contribution in https://github.com/opentensor/btcli/pull/139

**Full Changelog**: https://github.com/opentensor/btcli/compare/v8.0.0...v8.1.0

## 8.0.0 /2024-09-25

## What's Changed

New Async Bittensor CLI from the ground-up

* UI enhancements, fixes by @ibraheem-opentensor in https://github.com/opentensor/btcli/pull/116
* Adds contrib guidelines by @ibraheem-opentensor in https://github.com/opentensor/btcli/pull/115
* Adds release pre-reqs by @ibraheem-opentensor in https://github.com/opentensor/btcli/pull/114
* Revising README by @rajkaramchedu in https://github.com/opentensor/btcli/pull/113
* Adds improvements and minor fixes by @ibraheem-opentensor in https://github.com/opentensor/btcli/pull/112
* Speedups by @thewhaleking in https://github.com/opentensor/btcli/pull/111
* Don't check size of PGP fingerprint if it's not set by @thewhaleking in https://github.com/opentensor/btcli/pull/110
* Give user their UID immediately after root/sn registration. by @thewhaleking in https://github.com/opentensor/btcli/pull/108
* Ninth and final set of Typer docstrings by @rajkaramchedu in https://github.com/opentensor/btcli/pull/107
* Eighth set of Typer docstrings by @rajkaramchedu in https://github.com/opentensor/btcli/pull/106
* Enhancement: max-stake and table tweak by @ibraheem-opentensor in https://github.com/opentensor/btcli/pull/105
* Seventh set of Typer docstrings by @rajkaramchedu in https://github.com/opentensor/btcli/pull/104
* Adds support for list type inputs by @ibraheem-opentensor in https://github.com/opentensor/btcli/pull/103
* Sixth set of Typer docstrings by @rajkaramchedu in https://github.com/opentensor/btcli/pull/102
* Query_Multi method by @thewhaleking in https://github.com/opentensor/btcli/pull/101
* Table fixes / E2E Test  - Senate command fix by @ibraheem-opentensor in https://github.com/opentensor/btcli/pull/100
* Fifth set of Typer docstrings by @rajkaramchedu in https://github.com/opentensor/btcli/pull/99
* Fourth set of Typer docstrings by @rajkaramchedu in https://github.com/opentensor/btcli/pull/98
* Update help language for swap command. by @thewhaleking in https://github.com/opentensor/btcli/pull/97
* Tests/senate e2e by @ibraheem-opentensor in https://github.com/opentensor/btcli/pull/96
* Decode CHK SS58 by @thewhaleking in https://github.com/opentensor/btcli/pull/95
* Third set of Typer docstrings by @rajkaramchedu in https://github.com/opentensor/btcli/pull/94
* E2E tests + fixes by @ibraheem-opentensor in https://github.com/opentensor/btcli/pull/92
* Second set of Typer docstrings by @rajkaramchedu in https://github.com/opentensor/btcli/pull/91
* First set of Typer docstrings by @rajkaramchedu in https://github.com/opentensor/btcli/pull/90
* Doc Creation Assistance by @thewhaleking in https://github.com/opentensor/btcli/pull/89
* Use on chain identities rather than github by @thewhaleking in https://github.com/opentensor/btcli/pull/88
* Enhances tables & other fixes by @ibraheem-opentensor in https://github.com/opentensor/btcli/pull/87
* Fixes subnets create not parsing hotkey by @ibraheem-opentensor in https://github.com/opentensor/btcli/pull/86
* fix set-id prompts by @thewhaleking in https://github.com/opentensor/btcli/pull/85
* Adds guard rails for take value by @ibraheem-opentensor in https://github.com/opentensor/btcli/pull/84
* Adds alias for hotkey by @ibraheem-opentensor in https://github.com/opentensor/btcli/pull/83
* Better config input/output by @thewhaleking in https://github.com/opentensor/btcli/pull/82
* _get_vote_data => subtensor.get_vote_data by @thewhaleking in https://github.com/opentensor/btcli/pull/81
* Param decls reused in `btcli config clear` by @thewhaleking in https://github.com/opentensor/btcli/pull/80
* Adds fixes and improvements by @ibraheem-opentensor in https://github.com/opentensor/btcli/pull/78
* Validate proposal hashes in `root senate-vote` by @thewhaleking in https://github.com/opentensor/btcli/pull/77
* Prevent self-assignment as a child hotkey by @opendansor in https://github.com/opentensor/btcli/pull/76
* Adds enhancements and fixes by @ibraheem-opentensor in https://github.com/opentensor/btcli/pull/75
* Fixes root table + subnet list total calculations by @ibraheem-opentensor in https://github.com/opentensor/btcli/pull/74
* Enhances sudo set and fixes root boost by @ibraheem-opentensor in https://github.com/opentensor/btcli/pull/73
* Feat/thewhaleking/galina fixes by @ibraheem-opentensor in https://github.com/opentensor/btcli/pull/72
* Revert "Feat/thewhaleking/galina fixes" by @ibraheem-opentensor in https://github.com/opentensor/btcli/pull/71
* Feat/thewhaleking/galina fixes by @thewhaleking in https://github.com/opentensor/btcli/pull/70
* Enhancements, better UX, bug fixes by @ibraheem-opentensor in https://github.com/opentensor/btcli/pull/69
* Update README.md by @thewhaleking in https://github.com/opentensor/btcli/pull/68
* Add --all functions for managing child hotkeys and take. by @opendansor in https://github.com/opentensor/btcli/pull/65
* Fixes subnets pow register by @ibraheem-opentensor in https://github.com/opentensor/btcli/pull/64
* Raj/Galina Fixes by @thewhaleking in https://github.com/opentensor/btcli/pull/63
* Torch and registration fixes by @thewhaleking in https://github.com/opentensor/btcli/pull/62
* Handle KeyFileError when unlocking coldkey/hotkey by @thewhaleking in https://github.com/opentensor/btcli/pull/61
* Fixes for root + enhancements by @ibraheem-opentensor in https://github.com/opentensor/btcli/pull/60
* Fixes processors and update_interval flags by @ibraheem-opentensor in https://github.com/opentensor/btcli/pull/59
* Fixes/Enhancements for wallets, faucet, network info by @ibraheem-opentensor in https://github.com/opentensor/btcli/pull/58
* Fix: wallets looking for default addresses in inspect, overview, balance by @ibraheem-opentensor in https://github.com/opentensor/btcli/pull/57
* Feat/thewhaleking/verbosity by @ibraheem-opentensor in https://github.com/opentensor/btcli/pull/56
* Updates regen command string to fix regen test by @ibraheem-opentensor in https://github.com/opentensor/btcli/pull/54
* Enhancement to staking by @ibraheem-opentensor in https://github.com/opentensor/btcli/pull/51
* Enhances root list-delegates by @ibraheem-opentensor in https://github.com/opentensor/btcli/pull/49
* Child Hotkey Refactor Update by @opendansor in https://github.com/opentensor/btcli/pull/48
* Remove Py-Substrate-Interface class entirely by @thewhaleking in https://github.com/opentensor/btcli/pull/47
* Correctly create just the config directory path. by @thewhaleking in https://github.com/opentensor/btcli/pull/46
* Enhances tests according to changes by @ibraheem-opentensor in https://github.com/opentensor/btcli/pull/45
* Adds table.j2 for --html by @ibraheem-opentensor in https://github.com/opentensor/btcli/pull/44
* Root alias + enhancements by @ibraheem-opentensor in https://github.com/opentensor/btcli/pull/43
* Move subtensor_interface and utils to under the bittensor/ dir by @thewhaleking in https://github.com/opentensor/btcli/pull/42
* btcli fixes by @thewhaleking in https://github.com/opentensor/btcli/pull/41
* Enhances help sections of all commands by @ibraheem-opentensor in https://github.com/opentensor/btcli/pull/40
* UI Enhancements + fixes by @ibraheem-opentensor in https://github.com/opentensor/btcli/pull/39
* Adds fixes and improvements by @ibraheem-opentensor in https://github.com/opentensor/btcli/pull/38
* setup fixes by @thewhaleking in https://github.com/opentensor/btcli/pull/37
* Fix delegate info type by @thewhaleking in https://github.com/opentensor/btcli/pull/36
* Adds python version dependency + title changes by @ibraheem-opentensor in https://github.com/opentensor/btcli/pull/35
* Revamps help text UI and messages by @ibraheem-opentensor in https://github.com/opentensor/btcli/pull/34
* Integrate bt decoder by @thewhaleking in https://github.com/opentensor/btcli/pull/33
* Enhances UI of commands by @ibraheem-opentensor in https://github.com/opentensor/btcli/pull/32
* Adds --no-prompt, fixes bugs + tests by @ibraheem-opentensor in https://github.com/opentensor/btcli/pull/31
* Fixes output string in wallet transfer by @ibraheem-opentensor in https://github.com/opentensor/btcli/pull/30
* root get weights: html, caching, slicing by @thewhaleking in https://github.com/opentensor/btcli/pull/29
* Fix DeprecationWarning from pkg_tools by @thewhaleking in https://github.com/opentensor/btcli/pull/28
* Package up BTCLI by @roman-opentensor in https://github.com/opentensor/btcli/pull/27
* Removes subnets template dependency by @ibraheem-opentensor in https://github.com/opentensor/btcli/pull/26
* Metagraph Config by @thewhaleking in https://github.com/opentensor/btcli/pull/25
* UI improvements, bug fixes, root coverage by @ibraheem-opentensor in https://github.com/opentensor/btcli/pull/24
* Child Hotkey + Takes by @opendansor in https://github.com/opentensor/btcli/pull/23
* Config command improvements by @thewhaleking in https://github.com/opentensor/btcli/pull/22
* Feedback/Improvements to HTML output by @thewhaleking in https://github.com/opentensor/btcli/pull/21
* HTML Additions: Stake Show and general Improvements by @thewhaleking in https://github.com/opentensor/btcli/pull/20
* Fixes + coverage for staking + sudo by @ibraheem-opentensor in https://github.com/opentensor/btcli/pull/19
* Initial support for HTML table outputs by @thewhaleking in https://github.com/opentensor/btcli/pull/17
* Fixes + E2E coverage for Root commands by @ibraheem-opentensor in https://github.com/opentensor/btcli/pull/14
* Fix of the weights commands by @thewhaleking in https://github.com/opentensor/btcli/pull/13
* weights commands by @thewhaleking in https://github.com/opentensor/btcli/pull/12
* E2E Setup + wallet commands by @ibraheem-opentensor in https://github.com/opentensor/btcli/pull/11
* subnets commands by @thewhaleking in https://github.com/opentensor/btcli/pull/9
* Sudo Commands by @thewhaleking in https://github.com/opentensor/btcli/pull/8
* SubtensorInterface built-in substrate.close by @thewhaleking in https://github.com/opentensor/btcli/pull/7
* Restore functionality for `stake remove` by @thewhaleking in https://github.com/opentensor/btcli/pull/6
* Feat/opendansor/revoke children by @opendansor in https://github.com/opentensor/btcli/pull/5
* stake commands by @thewhaleking in https://github.com/opentensor/btcli/pull/4
* Root commands by @thewhaleking in https://github.com/opentensor/btcli/pull/3
* Initial commit for Typer (wallet commands) by @thewhaleking in https://github.com/opentensor/btcli/pull/1
