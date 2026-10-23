# ledgerkit

Turn raw EVM logs into a per-wallet ETH/NFT ledger — then **prove it**, instead of
trusting the spreadsheet.

Built for the "give us a CSV of who earned what from our contracts" class of data
bounty. Those requests look trivial and are not: escrow contracts take a fee at
settlement, cancelled bounties never pay, one transaction can settle several
claims, public RPCs return the same log twice when a page is retried, and NFT
ownership is a *last-transfer* problem, not a sum. Each of those has produced a
wrong CSV on a real board.

```
fetch  ->  build  ->  verify
logs      ledger     reconciliation
```

## Quickstart

```bash
pip install eth-abi

# 1. download every log the contract ever emitted
python -m ledgerkit fetch --chain arbitrum \
    --address 0xdffe8a4a4103f968ffd61fd082d08c41dcf9b940 \
    --from-block 0 --out logs.json

# 2. fold them into a per-wallet ledger
python -m ledgerkit build --logs logs.json --fee-bps 250 \
    --csv wallets.csv --summary summary.json

# 3. reconcile against a second, independent recount
python -m ledgerkit verify --logs logs.json --fee-bps 250 \
    --expect-earned 3.726923002 --expect-paid 3.63374992695
```

`verify` exits non-zero on any mismatch, so it drops straight into CI:

```yaml
- run: python -m ledgerkit verify --logs logs.json --fee-bps 250 --expect-earned 3.726923002
```

## Output columns

| column | meaning |
|---|---|
| `wallet` | address |
| `eth_paid_out_wei` / `eth_paid_out` | ETH that actually reached the wallet (gross minus protocol fee) |
| `eth_earned_wei` / `eth_earned` | gross value of every bounty the wallet won |
| `nfts_held` | tokens owned *now*, from the last `Transfer` per token id |
| `eth_escrowed_for_completed_bounties_wei` | what the wallet put up for bounties that settled |
| `bounties_created`, `bounties_won`, `claims_submitted`, `nfts_minted` | counts |
| `fees_paid_wei` | protocol fee charged on that wallet's settled bounties |

Amounts are integers in wei; the ETH strings are derived with integer arithmetic
only, so `3.726923002` is exact to the last wei and never a float artefact.

## Rules the engine enforces

1. **Earned is gross; paid out is net.** The fee is read from the settlement
   event, never recomputed from a percentage — protocols change fees, and old
   settlements keep the old rate. `--fee-bps` is a *check*, and a mismatch is
   reported rather than silently applied.
2. **Cancelled bounties pay nobody.** A settlement on a cancelled bounty is
   surfaced as a warning, because it means one of the two events is wrong.
3. **A claim without a bounty is not guessed.** If the creation event is outside
   the fetched range, the claim is counted in `claims_accepted` but excluded from
   money columns (`claims_valued`) and reported. Inventing an amount is how
   ledgers drift.
4. **Duplicate `(tx, logIndex)` pairs are dropped.** Retried `eth_getLogs` pages
   are the most common source of double counting.
5. **Explicit exclusions.** `--exclude-tx 0x…` removes known-bad settlements
   (exploits, test transactions) before aggregation, and the verifier applies the
   same list, so the two sides cannot disagree about what was excluded.

## What `verify` actually checks

Every check is a second computation, not a re-run of the builder:

| check | method |
|---|---|
| `conservation` | `earned == paid_out + fees`, wei-exact |
| `raw_recount_earned` / `_fees` | the money columns re-derived by slicing raw `data` words with `int(hex, 16)`, bypassing the ABI decoder entirely |
| `raw_recount_settlements` | settlement count from raw topics vs the ledger's `claims_valued` |
| `no_negative_values`, `paid_out_within_earned` | per-wallet sanity |
| `no_empty_rows` | every row carries activity (no phantom wallets) |
| `fee_rate_matches` | total fees against `--fee-bps`, within rounding |
| `nft_balances` | ERC-721 balances rebuilt from transfer **deltas** (mint `+1`, burn `-1`, transfer `-1/+1`) and compared per holder |
| optional `--nft … --chain …` | `balanceOf` on chain for a sample of holders |

## Golden dataset

`tests/fixtures/poidh_v1_logs.json` is every log (3,467 entries, fetched from
block 0) of poidh v1 on Arbitrum,
`0xdffe8a4a4103f968ffd61fd082d08c41dcf9b940`. The suite asserts the engine
reproduces the published ledger exactly:

| | |
|---|---|
| bounties created | 496 |
| claims accepted | 278 |
| gross earned | `3.726923002` ETH |
| protocol fees (2.5%) | `0.09317307505` ETH |
| net paid out | `3.63374992695` ETH |
| wallets | 415 |
| NFTs held | 722 |

That is the point of the tool: anyone can re-fetch the logs and check those
numbers without trusting this repository.

## Scope and limits

* Works for event-sourced escrow/bounty contracts with an explicit settlement
  event. Protocols that keep balances only in storage need a state snapshot
  adapter (`eth_getStorageAt` / `balanceOf` sweeps) — the verifier's optional
  on-chain check is the seam for that.
* `fetch` uses public RPCs with rotation and retry, and halves the block window
  when a range is rejected; it does not verify that a provider returned *all*
  logs. Cross-check totals with `verify` before publishing anything.
* The decoder table in `ledgerkit/events.py` is protocol-specific on purpose:
  topic hashes are written out literally so they can be checked against an
  explorer.

## Development

```bash
pip install eth-abi pytest
python -m pytest -q
```

Python 3.9+. Runtime dependency: `eth-abi` only; HTTP is `urllib`.

## License

MIT
