# Changelog

## 9.7.0/2025-06-16

## What's Changed
* Add `SKIP_PULL` variable for conftest.py by @basfroman in https://github.com/opentensor/btcli/pull/502
* Feat: Adds netuid support in swap_hotkeys by @ibraheem-abe in https://github.com/opentensor/btcli/pull/505

**Full Changelog**: https://github.com/opentensor/btcli/compare/v9.6.0...v9.7.0

## 9.6.0/2025-06-12

## What's Changed
* Allows for staking to multiple netuids in one btcli command by @thewhaleking in https://github.com/opentensor/btcli/pull/481
* improve stake add json output by @thewhaleking in https://github.com/opentensor/btcli/pull/482
* Apply bittensor error formatting to btcli by @thewhaleking in https://github.com/opentensor/btcli/pull/483
* Add Yuma3 Enabled for Sudo Set/Get by @thewhaleking in https://github.com/opentensor/btcli/pull/487
* Adds `alpha_sigmoid_steepness` call for hyperparams set/get by @thewhaleking in https://github.com/opentensor/btcli/pull/488
* unstaking test fix by @thewhaleking in https://github.com/opentensor/btcli/pull/489
* Merge issue: 488 by @thewhaleking in https://github.com/opentensor/btcli/pull/490
* subnets check-start formatting blocks by @thewhaleking in https://github.com/opentensor/btcli/pull/491
* Str vs Tuple by @thewhaleking in https://github.com/opentensor/btcli/pull/492
* Add Homebrew Install to README by @thewhaleking in https://github.com/opentensor/btcli/pull/493
* Update staking test for new subtensor by @thewhaleking in https://github.com/opentensor/btcli/pull/494


**Full Changelog**: https://github.com/opentensor/btcli/compare/v9.5.1...v9.6.0

## 9.5.1 /2025-06-02

## What's Changed
* Declare templates in MANIFEST and include package data by @thewhaleking in https://github.com/opentensor/btcli/pull/477


**Full Changelog**: https://github.com/opentensor/btcli/compare/v9.5.0...v9.5.1

## 9.5.0 /2025-06-02

## What's Changed
* Replace PyWry by @thewhaleking in https://github.com/opentensor/btcli/pull/472
* Remove fuzzywuzzy by @thewhaleking in https://github.com/opentensor/btcli/pull/473
* Add ruff formatter by @thewhaleking in https://github.com/opentensor/btcli/pull/474

**Full Changelog**: https://github.com/opentensor/btcli/compare/v9.4.4...v9.5.0

## 9.4.4 /2025-04-29

## What's Changed
* Replace `transfer_allow_death` with `transfer_keep_alive` by @basfroman in https://github.com/opentensor/btcli/pull/466

**Full Changelog**: https://github.com/opentensor/btcli/compare/v9.4.3...v9.4.4

## 9.4.3 /2025-04-29

## What's Changed
* Avoid scientific notation output by @thewhaleking in https://github.com/opentensor/btcli/pull/459
* Use generic types by @thewhaleking in https://github.com/opentensor/btcli/pull/458
* Suppress async substrate warning by @thewhaleking in https://github.com/opentensor/btcli/pull/463
* Remove unused dependency by @thewhaleking in https://github.com/opentensor/btcli/pull/460
* fix: fix typo "accross" by @gap-editor in https://github.com/opentensor/btcli/pull/461

## New Contributors
* @gap-editor made their first contribution in https://github.com/opentensor/btcli/pull/461

**Full Changelog**: https://github.com/opentensor/btcli/compare/v9.4.2...v9.4.3

## 9.4.2 /2025-04-22

## What's Changed
* Subnets Register Improvements by @thewhaleking in https://github.com/opentensor/btcli/pull/450
* Fix `KeyFileError: File is not writable` during `btcli wallet create` command by @basfroman in https://github.com/opentensor/btcli/pull/452

**Full Changelog**: https://github.com/opentensor/btcli/compare/v9.4.1...v9.4.2

## 9.4.1 /2025-04-17

## What's Changed
* Fixes `test_staking_sudo` setting `max_burn` by @thewhaleking in https://github.com/opentensor/btcli/pull/440
* Fixes Error Formatter by @thewhaleking in https://github.com/opentensor/btcli/pull/439
* Pulls shares in a gather rather than one-at-a-time by @thewhaleking in https://github.com/opentensor/btcli/pull/438
* Pull emission start schedule dynamically by @thewhaleking in https://github.com/opentensor/btcli/pull/442
* Lengthen default era period + rename "era" to "period" by @thewhaleking in https://github.com/opentensor/btcli/pull/443
* docs: fixed redundant "from" by @mdqst in https://github.com/opentensor/btcli/pull/429
* click version 8.2.0 broken by @thewhaleking in https://github.com/opentensor/btcli/pull/447
* JSON Name shadowing bug by @thewhaleking in https://github.com/opentensor/btcli/pull/445
* Stop Parsing, Start Asking by @thewhaleking in https://github.com/opentensor/btcli/pull/446

**Full Changelog**: https://github.com/opentensor/btcli/compare/v9.4.0...v9.4.1

## 9.4.0 /2025-04-17

## What's Changed
* Formatting/ruff fixes by @thewhaleking in https://github.com/opentensor/btcli/pull/426
* Allows for torch 2.6+ by @thewhaleking in https://github.com/opentensor/btcli/pull/427
* chore: fixed version format error and improved readability by @mdqst in https://github.com/opentensor/btcli/pull/428
* Fixes help msg of safe staking help (in stake add etc) by @ibraheem-abe in https://github.com/opentensor/btcli/pull/432
* Feat/start call by @ibraheem-abe in https://github.com/opentensor/btcli/pull/434

## New Contributors
* @mdqst made their first contribution in https://github.com/opentensor/btcli/pull/428

**Full Changelog**: https://github.com/opentensor/btcli/compare/v9.3.0...v9.4.0

## 9.3.0 /2025-04-09

## What's Changed
* Fix e2e test by @basfroman in https://github.com/opentensor/btcli/pull/396
* Btwallet e2e test -  verbose printing by @ibraheem-abe in https://github.com/opentensor/btcli/pull/397
* Feat/swap coldkey by @ibraheem-abe in https://github.com/opentensor/btcli/pull/399
* Add logic for keep docker image up to date by @basfroman in https://github.com/opentensor/btcli/pull/400
* Feat/associate hotkey by @ibraheem-abe in https://github.com/opentensor/btcli/pull/401
* Fixes staking/unstaking e2e tests by @ibraheem-abe in https://github.com/opentensor/btcli/pull/404
* Adds `era` param for stake transactions by @thewhaleking in https://github.com/opentensor/btcli/pull/406
* Fix: Removes name conflict in Sn create by @ibraheem-abe in https://github.com/opentensor/btcli/pull/405
* Pull version.py version from package metadata by @thewhaleking in https://github.com/opentensor/btcli/pull/409
* json output for commands by @thewhaleking in https://github.com/opentensor/btcli/pull/369
* General code cleanup by @thewhaleking in https://github.com/opentensor/btcli/pull/411
* More json outputs by @thewhaleking in https://github.com/opentensor/btcli/pull/412
* new color palette by @thewhaleking in https://github.com/opentensor/btcli/pull/413
* bump versions by @thewhaleking in https://github.com/opentensor/btcli/pull/410
* spelling fix "Received" by @dougsillars in https://github.com/opentensor/btcli/pull/414
* Updates Subnet symbols by @ibraheem-abe in https://github.com/opentensor/btcli/pull/416
* Fix calculation for childkey set by @thewhaleking in https://github.com/opentensor/btcli/pull/418
* Revoke children msg by @thewhaleking in https://github.com/opentensor/btcli/pull/419
* Update revoke children language by @thewhaleking in https://github.com/opentensor/btcli/pull/417
* Revert "new color palette" by @thewhaleking in https://github.com/opentensor/btcli/pull/420

**Full Changelog**: https://github.com/opentensor/btcli/compare/v9.2.0...v9.3.0

## 9.2.0 /2025-03-18

## What's Changed
* Improve e2e tests' workflow by @roman-opentensor in https://github.com/opentensor/btcli/pull/393
* Updates to E2E suubtensor tests to devnet ready by @ibraheem-opentensor in https://github.com/opentensor/btcli/pull/390
* Allow Py 3.13 install by @thewhaleking in https://github.com/opentensor/btcli/pull/392
* pip install readme by @thewhaleking in https://github.com/opentensor/btcli/pull/391
* Feat/dynamic staking fee by @ibraheem-opentensor in https://github.com/opentensor/btcli/pull/389

**Full Changelog**: https://github.com/opentensor/btcli/compare/v9.1.4...v9.2.0

## 9.1.4 /2025-03-13

## What's Changed
* Disk-Cache Async-Substrate-Interface Calls by @thewhaleking in https://github.com/opentensor/btcli/pull/368
* COLOR_PALETTE refactor by @thewhaleking in https://github.com/opentensor/btcli/pull/386
* Code Cleanup by @thewhaleking in https://github.com/opentensor/btcli/pull/381
* Adds rate-tolerance alias by @ibraheem-opentensor in https://github.com/opentensor/btcli/pull/387

**Full Changelog**: https://github.com/opentensor/btcli/compare/v9.1.3...v9.1.4

## 9.1.3 /2025-03-12

## What's Changed
* Allows childkey take of 0 by @thewhaleking in https://github.com/opentensor/btcli/pull/376
* Passes prompt for pow_register by @thewhaleking in https://github.com/opentensor/btcli/pull/379
* Updates staking test by @ibraheem-opentensor in https://github.com/opentensor/btcli/pull/382

**Full Changelog**: https://github.com/opentensor/btcli/compare/v9.1.2...v9.1.3

## 9.1.2 /2025-03-07

## What's Changed
* Updates subnet and neuron identity by @ibraheem-opentensor in https://github.com/opentensor/btcli/pull/370

**Full Changelog**: https://github.com/opentensor/btcli/compare/v9.1.1...v9.1.2

## 9.1.1 /2025-03-06

## What's Changed
* fix: int() argument must be a string, a bytes-like object or a real n… by @0xxfu in https://github.com/opentensor/btcli/pull/352
* Change to pyproject toml by @thewhaleking in https://github.com/opentensor/btcli/pull/357
* Feat: Dashboard improvements by @ibraheem-opentensor in https://github.com/opentensor/btcli/pull/350
* Improves stake transfer, adds interactive selection of delegates by @ibraheem-opentensor in https://github.com/opentensor/btcli/pull/358
* Removes hidden flags for unstaking all by @ibraheem-opentensor in https://github.com/opentensor/btcli/pull/359
* Removes `typer.Exit` exceptions in commands by @thewhaleking in https://github.com/opentensor/btcli/pull/353
* Add transaction fee check inter-subnet movement by @ibraheem-opentensor in https://github.com/opentensor/btcli/pull/361
* Backmerge main to staging 910 by @ibraheem-opentensor in https://github.com/opentensor/btcli/pull/362

## New Contributors
* @0xxfu made their first contribution in https://github.com/opentensor/btcli/pull/352

**Full Changelog**: https://github.com/opentensor/btcli/compare/v9.1.0...v9.1.1

## 9.1.0 /2025-03-01

## What's Changed
* Hotkey SS58 in stake transfer interactive selection by @thewhaleking in https://github.com/opentensor/btcli/pull/345
* Backmerge main staging 903 by @ibraheem-opentensor in https://github.com/opentensor/btcli/pull/346
* Feat/btcli view dashboard by @ibraheem-opentensor in https://github.com/opentensor/btcli/pull/348

**Full Changelog**: https://github.com/opentensor/btcli/compare/v9.0.3...v9.1.0

## 9.0.3 /2025-02-26

## What's Changed
* Update wording for burn for sn registration by @thewhaleking in https://github.com/opentensor/btcli/pull/333
* [fix] use chk_take = 0 if None by @camfairchild in https://github.com/opentensor/btcli/pull/335
* Use `unlock_key` fn globally by @thewhaleking in https://github.com/opentensor/btcli/pull/336
* Updates Rust version to stable by @ibraheem-opentensor in https://github.com/opentensor/btcli/pull/339
* Warn Users When Setting Root-Only Hyperparams by @thewhaleking in https://github.com/opentensor/btcli/pull/337
* st transfer allow hotkey ss58 by @thewhaleking in https://github.com/opentensor/btcli/pull/338
* Git not required by @thewhaleking in https://github.com/opentensor/btcli/pull/341
* Adds limit of ss58 addresses per call when fetching total_stake by @ibraheem-opentensor in https://github.com/opentensor/btcli/pull/340
* Backmerge/main staging 902 by @ibraheem-opentensor in https://github.com/opentensor/btcli/pull/342

**Full Changelog**: https://github.com/opentensor/btcli/compare/v9.0.2...v9.0.3

## 9.0.2 /2025-02-20

## What's Changed
* Fix stake child get by @thewhaleking in https://github.com/opentensor/btcli/pull/321
* Edge case alpha formatting by @thewhaleking in https://github.com/opentensor/btcli/pull/318
* Adds Tao emissions to stake list by @ibraheem-opentensor in https://github.com/opentensor/btcli/pull/300
* Updates balance command by @ibraheem-opentensor in https://github.com/opentensor/btcli/pull/322
* Backmerge main to staging 101 by @ibraheem-opentensor in https://github.com/opentensor/btcli/pull/326
* Updates stake list (with swap value) by @ibraheem-opentensor in https://github.com/opentensor/btcli/pull/327
* Adds unstaking from all hotkeys + tests by @ibraheem-opentensor in https://github.com/opentensor/btcli/pull/325
* Mnemonic helper text by @thewhaleking in https://github.com/opentensor/btcli/pull/329
* fix: remove double conversion in stake swap functionality [--swap_all] by @ashikshafi08 in https://github.com/opentensor/btcli/pull/328
* Arbitrary Hyperparams Setting by @thewhaleking in https://github.com/opentensor/btcli/pull/320
* Bumps deps for btcli by @ibraheem-opentensor in https://github.com/opentensor/btcli/pull/330
* SubtensorInterface async with logic by @thewhaleking in https://github.com/opentensor/btcli/pull/331
* remove __version__ from cli.py by @igorsyl in https://github.com/opentensor/btcli/pull/323

## New Contributors
* @ashikshafi08 made their first contribution in https://github.com/opentensor/btcli/pull/328
* @igorsyl made their first contribution in https://github.com/opentensor/btcli/pull/323

**Full Changelog**: https://github.com/opentensor/btcli/compare/v9.0.1...v9.0.2

## 9.0.1 /2025-02-13

## What's Changed
* Fixes root tempo being 0 by @ibraheem-opentensor in https://github.com/opentensor/btcli/pull/312
* Backmerge main to staging 900 by @ibraheem-opentensor in https://github.com/opentensor/btcli/pull/313
* Fixes fmt err msg by @ibraheem-opentensor in https://github.com/opentensor/btcli/pull/314
* Adds subnet identities set/get by @ibraheem-opentensor in https://github.com/opentensor/btcli/pull/316
* Fix return type annotation for `alpha_to_tao_with_slippage` by @thewhaleking in https://github.com/opentensor/btcli/pull/311
* Updates live view of btcli stake list 

**Full Changelog**: https://github.com/opentensor/btcli/compare/v9.0.0...v9.0.1

## 9.0.0 /2025-02-13

## What's Changed
* Btcli ported to Rao by @ibraheem-opentensor & @thewhaleking in https://github.com/opentensor/btcli/tree/rao-games/pools
* fix netuid from str to int by @roman-opentensor in https://github.com/opentensor/btcli/pull/195
* add runtime apis to reg by @ibraheem-opentensor in https://github.com/opentensor/btcli/pull/196
* Updated tables (st list, s list) by @ibraheem-opentensor in https://github.com/opentensor/btcli/pull/200
* Modifying descriptions and links in stake and subnets dot py files by @rajkaramchedu in https://github.com/opentensor/btcli/pull/246
* Fixes Identity Lookup (Rao Games Pools) by @thewhaleking in https://github.com/opentensor/btcli/pull/279
* Show encrypted hotkeys in w list by @thewhaleking in https://github.com/opentensor/btcli/pull/288
* Backmerge rao branch to decoding branch by @ibraheem-opentensor in https://github.com/opentensor/btcli/pull/290
* Updates identity, sn identity, and other chain stuff by @ibraheem-opentensor in https://github.com/opentensor/btcli/pull/292
* Updates Rao to decode using chain by @ibraheem-opentensor in https://github.com/opentensor/btcli/pull/286
* Fix/rao remove mention of cost by @camfairchild in https://github.com/opentensor/btcli/pull/293
* Uses uvloop if it's installed by @thewhaleking in https://github.com/opentensor/btcli/pull/294
* Feat: Safe staking by @ibraheem-opentensor in https://github.com/opentensor/btcli/pull/299
* Removes stake from w balances by @ibraheem-opentensor in https://github.com/opentensor/btcli/pull/301
* Updates docstrings for commands by @ibraheem-opentensor in https://github.com/opentensor/btcli/pull/303
* Release/9.0.0rc4 by @ibraheem-opentensor in https://github.com/opentensor/btcli/pull/306
* Rao to staging merge (new branch) by @thewhaleking in https://github.com/opentensor/btcli/pull/305
* [WIP] Rao by @thewhaleking in https://github.com/opentensor/btcli/pull/129
* Updates e2e tests for rao by @ibraheem-opentensor in https://github.com/opentensor/btcli/pull/307
* Update dividends, adds sort by @ibraheem-opentensor in https://github.com/opentensor/btcli/pull/308
* Final cleanups for Rao by @ibraheem-opentensor in https://github.com/opentensor/btcli/pull/309

## New Contributors
* @camfairchild made their first contribution in https://github.com/opentensor/btcli/pull/293

**Full Changelog**: https://github.com/opentensor/btcli/compare/v8.4.4...v9.0.0

## 8.4.4 /2025-02-07 - 18:30 PST

## What's Changed
* Proposals info fix (for dtao governance vote) by @ibraheem-opentensor 

**Full Changelog**: https://github.com/opentensor/btcli/compare/v8.4.3...v8.4.4

## 8.4.3 /2025-01-23

## What's Changed
* Backmerge main to staging 842 by @ibraheem-opentensor in https://github.com/opentensor/btcli/pull/273
* Fix arg order for set-identity by @thewhaleking in https://github.com/opentensor/btcli/pull/282
* Adds updates to btwallet3, adds overwrite flag and updates tests by @ibraheem-opentensor in https://github.com/opentensor/btcli/pull/275

**Full Changelog**: https://github.com/opentensor/btcli/compare/v8.4.2...v8.4.3

## 8.4.2 /2024-12-12

## What's Changed
* Removes the `.value` checks as we no longer use SCALE objects. by @thewhaleking in https://github.com/opentensor/btcli/pull/270
* Backmerge main to staging 842 by @ibraheem-opentensor in https://github.com/opentensor/btcli/pull/273

**Full Changelog**: https://github.com/opentensor/btcli/compare/v8.4.1...v8.4.2

## 8.4.1 /2024-12-05

## What's Changed
* Sometimes err_docs is a string. We want to handle this properly. by @thewhaleking in https://github.com/opentensor/btcli/pull/260
* Sudo Hyperparams by @thewhaleking in https://github.com/opentensor/btcli/pull/261
* Sorted netuids in `btcli r get-weights` by @thewhaleking in https://github.com/opentensor/btcli/pull/258
* Show hyperparams during `sudo set` only sometimes by @thewhaleking in https://github.com/opentensor/btcli/pull/262
* Update stake children help menu by @thewhaleking in https://github.com/opentensor/btcli/pull/264
* Updates bt-decode to 0.4.0 by @ibraheem-opentensor in https://github.com/opentensor/btcli/pull/265
* Backmerge main to staging for 8.4.1 by @ibraheem-opentensor in https://github.com/opentensor/btcli/pull/267

**Full Changelog**: https://github.com/opentensor/btcli/compare/v8.4.0...v8.4.1

## 8.4.0 /2024-11-27

## What's Changed
* Use hex to bytes function by @thewhaleking in https://github.com/opentensor/btcli/pull/244
* Remove deprecated Typer options by @thewhaleking in https://github.com/opentensor/btcli/pull/248
* Upgrade websockets by @thewhaleking in https://github.com/opentensor/btcli/pull/247
* Fast block improvements by @thewhaleking in https://github.com/opentensor/btcli/pull/245
* Fixed overview message discrepancy by @ibraheem-opentensor in https://github.com/opentensor/btcli/pull/251
* Fix hyperparams setting. by @thewhaleking in https://github.com/opentensor/btcli/pull/252
* Bumps btwallet to 2.1.2 by @ibraheem-opentensor in https://github.com/opentensor/btcli/pull/255
* Bumps btwallet to 2.1.3 by @ibraheem-opentensor in https://github.com/opentensor/btcli/pull/256

**Full Changelog**: https://github.com/opentensor/btcli/compare/v8.3.1...v8.4.0

## 8.3.1 /2024-11-13

## What's Changed
* Better handle incorrect file path for wallets. by @thewhaleking in https://github.com/opentensor/btcli/pull/230
* Handle websockets version 14, verbose error output by @thewhaleking in https://github.com/opentensor/btcli/pull/236
* Handles the new PasswordError from bt-wallet by @thewhaleking in https://github.com/opentensor/btcli/pull/232

**Full Changelog**: https://github.com/opentensor/btcli/compare/v8.3.0...v.8.3.1

## 8.3.0 /2024-11-06

## What's Changed
* Better handle incorrect password by @thewhaleking in https://github.com/opentensor/btcli/pull/187
* Fixes success path of pow register by @ibraheem-opentensor in https://github.com/opentensor/btcli/pull/189
* Adds `--all` flag to transfer by @thewhaleking in https://github.com/opentensor/btcli/pull/181
* In `do_transfer`, we check the balance with coldkeypub.ss58, but then retrieve it from the dict with coldkey.ss58. Resolve this. by @thewhaleking in https://github.com/opentensor/btcli/pull/199
* Handle KeyboardInterrupt in CLI to gracefully exit (no traceback) by @thewhaleking in https://github.com/opentensor/btcli/pull/199
* Handle race conditions where self.metadata may not be set before finishing initialising runtime (this may need optimised in the future) by @thewhaleking in https://github.com/opentensor/btcli/pull/199
* Error description output by @thewhaleking in https://github.com/opentensor/btcli/pull/199
* Taostats link fixed by @thewhaleking in https://github.com/opentensor/btcli/pull/199
* Fixes not showing confirmation if --no-prompt is specified on stake remove by @thewhaleking in https://github.com/opentensor/btcli/pull/199
* Fix wallets in overview by @thewhaleking in https://github.com/opentensor/btcli/pull/197
* fix handling null neurons by @thewhaleking in https://github.com/opentensor/btcli/pull/214
* Fix cuda pow registration by @thewhaleking in https://github.com/opentensor/btcli/pull/215
* Adds confirmation after each successful regen by @ibraheem-opentensor in https://github.com/opentensor/btcli/pull/203
* Removes wallet path prompt by @ibraheem-opentensor in https://github.com/opentensor/btcli/pull/205
* Support hotkey names for include/exclude in st add/remove by @thewhaleking in https://github.com/opentensor/btcli/pull/216
* Subvortex network added by @thewhaleking  in https://github.com/opentensor/btcli/pull/223
* Add prompt option to all commands which use Confirm prompts by @thewhaleking in https://github.com/opentensor/btcli/pull/227
* fix: local subtensor port by @distributedstatemachine in https://github.com/opentensor/btcli/pull/228
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
