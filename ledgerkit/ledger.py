"""The aggregation engine.

Rules, stated once so they can be argued with:

* A wallet's **earned** ETH is the gross amount of every bounty it won.
* A wallet's **paid out** ETH is what actually reached it: earned minus the
  protocol fee charged at settlement. The fee is read from the settlement event,
  never guessed from a percentage, because a protocol may change its fee.
* A bounty that was created and never accepted pays nobody. A cancelled bounty
  pays nobody. Neither is a loss, so neither appears as a negative row.
* NFT ownership is the *last* Transfer seen for a token id. A transfer to the
  zero address burns the token, so it stops being held.
* Duplicate (tx, logIndex) pairs are dropped: public RPCs happily return the
  same log twice when a page boundary is retried, and counting twice is the
  single most common way a hand-built ledger goes wrong.

Exploit exclusions are explicit: pass the settlement transactions that should
not count and every log inside them is skipped before aggregation.
"""
from __future__ import annotations

import csv
import json
from collections import Counter
from dataclasses import dataclass, field
from typing import Any, Iterable

from .events import (ZERO_ADDRESS, BountyCancelled, BountyCreated, ClaimAccepted,
                     ClaimCreated, NftTransfer, decode)


@dataclass
class WalletRow:
    wallet: str
    eth_paid_out_wei: int = 0
    eth_earned_wei: int = 0
    nfts_held: int = 0
    eth_escrowed_for_completed_bounties_wei: int = 0
    bounties_created: int = 0
    bounties_won: int = 0
    claims_submitted: int = 0
    nfts_minted: int = 0
    fees_paid_wei: int = 0

    def as_dict(self) -> dict[str, str]:
        return {
            'wallet': self.wallet,
            'eth_paid_out_wei': str(self.eth_paid_out_wei),
            'eth_paid_out': eth(self.eth_paid_out_wei),
            'eth_earned_wei': str(self.eth_earned_wei),
            'eth_earned': eth(self.eth_earned_wei),
            'nfts_held': str(self.nfts_held),
            'eth_escrowed_for_completed_bounties_wei': str(self.eth_escrowed_for_completed_bounties_wei),
            'eth_escrowed_for_completed_bounties': eth(self.eth_escrowed_for_completed_bounties_wei),
            'bounties_created': str(self.bounties_created),
            'bounties_won': str(self.bounties_won),
            'claims_submitted': str(self.claims_submitted),
            'nfts_minted': str(self.nfts_minted),
            'fees_paid_wei': str(self.fees_paid_wei),
        }


def eth(wei: int) -> str:
    """Exact wei -> ETH string. Integer arithmetic only: float would lose wei."""
    if not wei:
        return '0'
    sign = '-' if wei < 0 else ''
    wei = abs(wei)
    whole, frac = divmod(wei, 10**18)
    if not frac:
        return f'{sign}{whole}'
    return f'{sign}{whole}.{frac:018d}'.rstrip('0')


@dataclass
class Ledger:
    rows: dict[str, WalletRow]
    stats: dict[str, Any] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)
    nft_owner: dict[int, str] = field(default_factory=dict)

    def csv_rows(self) -> list[dict[str, str]]:
        return [self.rows[w].as_dict() for w in sorted(self.rows)]

    def write_csv(self, path: str) -> int:
        rows = self.csv_rows()
        if not rows:
            raise ValueError('refusing to write an empty ledger')
        with open(path, 'w', newline='') as fh:
            writer = csv.DictWriter(fh, fieldnames=list(rows[0]))
            writer.writeheader()
            writer.writerows(rows)
        return len(rows)

    def summary(self) -> dict[str, Any]:
        return {
            'wallets': len(self.rows),
            'total_paid_out_wei': sum(r.eth_paid_out_wei for r in self.rows.values()),
            'total_paid_out_eth': eth(sum(r.eth_paid_out_wei for r in self.rows.values())),
            'total_earned_wei': sum(r.eth_earned_wei for r in self.rows.values()),
            'total_earned_eth': eth(sum(r.eth_earned_wei for r in self.rows.values())),
            'total_fees_wei': sum(r.fees_paid_wei for r in self.rows.values()),
            'total_fees_eth': eth(sum(r.fees_paid_wei for r in self.rows.values())),
            'nfts_held': sum(r.nfts_held for r in self.rows.values()),
            'nfts_minted': sum(r.nfts_minted for r in self.rows.values()),
            **self.stats,
            'warnings': self.warnings,
        }


def build_ledger(logs: Iterable[dict[str, Any]], *,
                 fee_bps: int | None = None,
                 exclude_txs: Iterable[str] = ()) -> Ledger:
    """Fold raw logs into a per-wallet ledger.

    ``fee_bps`` is only used to *check* the fee carried by each settlement event
    (2.5% -> 250). The ledger itself always uses the fee the chain recorded.
    """
    excluded = {t.lower() for t in exclude_txs}
    seen: set[tuple[str, int]] = set()

    bounty_amount: dict[int, int] = {}
    bounty_issuer: dict[int, str] = {}
    claim_issuer: dict[int, str] = {}
    accepted: list[ClaimAccepted] = []
    cancelled: set[int] = set()
    nft_owner: dict[int, str] = {}
    nft_minted: Counter[str] = Counter()
    warnings: list[str] = []
    fee_mismatch = 0
    duplicate_logs = 0
    skipped_excluded = 0

    for log in logs:
        tx = (log.get('transactionHash') or '').lower()
        if tx and tx in excluded:
            skipped_excluded += 1
            continue
        key = (tx, int(log.get('logIndex') or 0, 16) if isinstance(log.get('logIndex'), str) else int(log.get('logIndex') or 0))
        if key[0] and key in seen:
            duplicate_logs += 1
            continue
        seen.add(key)

        event = decode(log)
        if event is None:
            continue

        if isinstance(event, BountyCreated):
            bounty_amount[event.bounty_id] = event.amount
            bounty_issuer[event.bounty_id] = event.issuer
        elif isinstance(event, ClaimCreated):
            claim_issuer[event.claim_id] = event.issuer
            bounty_issuer.setdefault(event.bounty_id, event.bounty_issuer)
        elif isinstance(event, ClaimAccepted):
            accepted.append(event)
            if fee_bps is not None:
                amount = bounty_amount.get(event.bounty_id)
                if amount is not None:
                    expected = amount * fee_bps // 10_000
                    if abs(expected - event.fee) > 1:      # allow 1 wei of rounding
                        fee_mismatch += 1
        elif isinstance(event, BountyCancelled):
            cancelled.add(event.bounty_id)
        elif isinstance(event, NftTransfer):
            nft_owner[event.token_id] = event.recipient
            if event.sender == ZERO_ADDRESS:
                nft_minted[event.recipient] += 1

    rows: dict[str, WalletRow] = {}

    def row(addr: str) -> WalletRow:
        if addr not in rows:
            rows[addr] = WalletRow(wallet=addr)
        return rows[addr]

    for bid, issuer in bounty_issuer.items():
        row(issuer).bounties_created += 1
    for addr in claim_issuer.values():
        row(addr).claims_submitted += 1

    missing_amount = 0
    valued = 0
    for event in accepted:
        if event.bounty_id in cancelled:
            warnings.append(f'claim {event.claim_id} accepted on cancelled bounty {event.bounty_id}')
        amount = bounty_amount.get(event.bounty_id)
        if amount is None:
            missing_amount += 1
            continue
        valued += 1
        winner = row(event.claim_issuer)
        winner.eth_earned_wei += amount
        winner.eth_paid_out_wei += amount - event.fee
        winner.bounties_won += 1
        issuer = row(event.bounty_issuer)
        issuer.eth_escrowed_for_completed_bounties_wei += amount
        issuer.fees_paid_wei += event.fee

    holdings = Counter(owner for owner in nft_owner.values() if owner != ZERO_ADDRESS)
    for addr, count in holdings.items():
        row(addr).nfts_held = count
    for addr, count in nft_minted.items():
        row(addr).nfts_minted = count

    if missing_amount:
        warnings.append(f'{missing_amount} accepted claim(s) point at a bounty with no creation event')

    stats = {
        'bounties': len(bounty_amount),
        'bounties_cancelled': len(cancelled),
        'claims': len(claim_issuer),
        'claims_accepted': len(accepted),
        'claims_valued': valued,
        'fee_bps_checked': fee_bps,
        'fee_mismatches': fee_mismatch,
        'duplicate_logs_dropped': duplicate_logs,
        'excluded_logs_dropped': skipped_excluded,
    }
    if fee_mismatch:
        warnings.append(f'{fee_mismatch} settlement(s) do not match fee_bps={fee_bps}')
    return Ledger(rows=rows, stats=stats, warnings=warnings, nft_owner=dict(nft_owner))


def load_logs(path: str) -> list[dict[str, Any]]:
    with open(path) as fh:
        return json.load(fh)
