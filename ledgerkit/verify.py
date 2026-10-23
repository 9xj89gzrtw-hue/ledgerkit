"""Reconciliation: prove the ledger, do not trust it.

A ledger is only useful if it can be checked by someone who does not trust the
code that produced it. Every check here is deliberately a *second* computation:

* conservation   - what winners received plus what the protocol took must equal
                  the gross value of the bounties that settled;
* recount        - the headline numbers are re-derived by slicing the raw hex
                  data words directly, bypassing the dataclass decoder entirely;
* NFT recount    - ERC-721 balances are rebuilt with a running-balance loop
                  (mint +1, transfer -1 / +1, burn -1) and compared per wallet;
* optional chain - if an RPC is supplied, `balanceOf` for a sample of holders
                  is compared against the ledger.

Any disagreement raises `VerificationError` with the numbers, so a wrong ledger
fails loudly instead of shipping a plausible CSV.
"""
from __future__ import annotations

from typing import Any, Iterable

from .events import (TOPIC_BOUNTY_CREATED, TOPIC_CLAIM_ACCEPTED, TOPIC_TRANSFER,
                     ZERO_ADDRESS, to_address)
from .ledger import Ledger


class VerificationError(AssertionError):
    """Raised when a ledger cannot be reconciled against its logs."""


def _words(data: str) -> list[int]:
    body = data[2:] if data.startswith('0x') else data
    return [int(body[i:i + 64], 16) for i in range(0, len(body), 64)]


def _recount(logs: Iterable[dict[str, Any]], exclude_txs: Iterable[str] = ()) -> dict[str, int]:
    """Independent recount of the money columns, straight from raw hex.

    BountyCreated data words:    [id, title_off, desc_off, amount, created]
    ClaimAccepted data words:    [bounty_id, claim_id, claim_issuer, bounty_issuer, fee]
    """
    excluded = {t.lower() for t in exclude_txs}
    amounts: dict[int, int] = {}
    earned = 0
    fees = 0
    settled = 0
    seen: set[tuple[str, str]] = set()

    for log in logs:
        tx = (log.get('transactionHash') or '').lower()
        if tx and tx in excluded:
            continue
        key = (tx, str(log.get('logIndex')))
        if tx and key in seen:
            continue
        seen.add(key)

        topics = log.get('topics') or []
        if not topics:
            continue
        data = log.get('data') or '0x'
        if topics[0].lower() == TOPIC_BOUNTY_CREATED:
            w = _words(data)
            amounts[w[0]] = w[3]
        elif topics[0].lower() == TOPIC_CLAIM_ACCEPTED:
            w = _words(data)
            bounty = amounts.get(w[0])
            if bounty is None:
                continue
            earned += bounty
            fees += w[4]
            settled += 1

    return {'earned_wei': earned, 'fees_wei': fees, 'settled': settled}


def _recount_nft(logs: Iterable[dict[str, Any]], exclude_txs: Iterable[str] = ()) -> tuple[dict[str, int], set[int]]:
    """Rebuild ERC-721 balances from transfer deltas, per token.

    Returns ``(balances, complete_tokens)``. A token only counts as complete if
    the first transfer ever seen for it is a mint; tokens that were already in
    circulation when the scrape started are reported separately so the caller
    can exclude them instead of silently comparing apples to oranges.
    """
    excluded = {t.lower() for t in exclude_txs}
    history: dict[int, list[tuple[str, str]]] = {}

    for log in logs:
        tx = (log.get('transactionHash') or '').lower()
        if tx and tx in excluded:
            continue
        topics = log.get('topics') or []
        if len(topics) != 4 or topics[0].lower() != TOPIC_TRANSFER:
            continue
        history.setdefault(int(topics[3], 16), []).append(
            (to_address(topics[1]), to_address(topics[2])))

    balances: dict[str, int] = {}
    complete: set[int] = set()
    for token, moves in history.items():
        if moves[0][0] != ZERO_ADDRESS:
            continue
        complete.add(token)
        for sender, recipient in moves:
            if sender != ZERO_ADDRESS:
                balances[sender] = balances.get(sender, 0) - 1
            if recipient != ZERO_ADDRESS:
                balances[recipient] = balances.get(recipient, 0) + 1

    return {a: n for a, n in balances.items() if n}, complete


def verify_ledger(ledger: Ledger, logs: list[dict[str, Any]], *,
                  fee_bps: int | None = None,
                  exclude_txs: Iterable[str] = (),
                  strict: bool = True) -> dict[str, Any]:
    """Run every reconciliation check. Returns a report; raises on failure."""
    summary = ledger.summary()
    report: dict[str, Any] = {'checks': {}, 'errors': []}

    def check(name: str, ok: bool, detail: str) -> None:
        report['checks'][name] = {'ok': ok, 'detail': detail}
        if not ok:
            report['errors'].append(f'{name}: {detail}')

    earned = summary['total_earned_wei']
    paid = summary['total_paid_out_wei']
    fees = summary['total_fees_wei']

    check('conservation', earned == paid + fees,
          f'earned={earned} paid_out={paid} fees={fees} diff={earned - paid - fees}')

    raw = _recount(logs, exclude_txs)
    check('raw_recount_earned', raw['earned_wei'] == earned,
          f'raw={raw["earned_wei"]} ledger={earned}')
    check('raw_recount_fees', raw['fees_wei'] == fees,
          f'raw={raw["fees_wei"]} ledger={fees}')
    check('raw_recount_settlements',
          raw['settled'] == ledger.stats.get('claims_valued'),
          f'raw={raw["settled"]} ledger={ledger.stats.get("claims_valued")}')

    negative = [r.wallet for r in ledger.rows.values()
                if min(r.eth_paid_out_wei, r.eth_earned_wei, r.nfts_held,
                       r.fees_paid_wei) < 0]
    check('no_negative_values', not negative, f'{len(negative)} wallet(s) below zero')

    overpaid = [r.wallet for r in ledger.rows.values()
                if r.eth_paid_out_wei > r.eth_earned_wei]
    check('paid_out_within_earned', not overpaid, f'{len(overpaid)} wallet(s) paid more than earned')

    zero_rows = [r.wallet for r in ledger.rows.values()
                 if not any((r.eth_paid_out_wei, r.eth_earned_wei, r.nfts_held,
                             r.bounties_created, r.claims_submitted, r.nfts_minted))]
    check('no_empty_rows', not zero_rows, f'{len(zero_rows)} wallet(s) carry no activity')

    if fee_bps is not None:
        expected = earned * fee_bps // 10_000
        check('fee_rate_matches', abs(expected - fees) <= max(1, len(ledger.rows)),
              f'expected={expected} (at {fee_bps} bps) actual={fees}')

    nft_raw, complete = _recount_nft(logs, exclude_txs)
    all_complete = len(complete) == len(ledger.nft_owner)
    if all_complete:
        # the comparison the CSV reader cares about: what the rows claim
        nft_ledger = {w: r.nfts_held for w, r in ledger.rows.items() if r.nfts_held}
    else:
        # partial history: compare only tokens whose full transfer chain is known
        nft_ledger = {}
        for token, owner in ledger.nft_owner.items():
            if token in complete and owner != ZERO_ADDRESS:
                nft_ledger[owner] = nft_ledger.get(owner, 0) + 1
    check('nft_balances', nft_raw == nft_ledger,
          f'{len(nft_raw)} holder(s) from deltas vs {len(nft_ledger)} in ledger, '
          f'{sum(nft_raw.values())} vs {sum(nft_ledger.values())} tokens '
          f'({len(ledger.nft_owner) - len(complete)} token(s) with unseen history skipped)')

    if strict and report['errors']:
        raise VerificationError('; '.join(report['errors']))
    report['ok'] = not report['errors']
    return report


def verify_nft_onchain(ledger: Ledger, rpc_call, nft_address: str, *,
                       sample: int = 10) -> dict[str, Any]:
    """Compare a sample of ledger NFT balances with `balanceOf` on chain.

    ``rpc_call(method, params)`` is injected so the check stays transport
    agnostic (see `rpc.RpcPool.call`).
    """
    holders = [(w, r.nfts_held) for w, r in sorted(ledger.rows.items()) if r.nfts_held]
    checked, mismatches = 0, []
    for wallet, expected in holders[:sample]:
        data = '0x70a08231' + wallet[2:].rjust(64, '0')      # balanceOf(address)
        result = rpc_call('eth_call', [{'to': nft_address, 'data': data}, 'latest'])
        actual = int(result, 16) if isinstance(result, str) and result != '0x' else 0
        checked += 1
        if actual != expected:
            mismatches.append({'wallet': wallet, 'ledger': expected, 'chain': actual})
    return {'checked': checked, 'mismatches': mismatches, 'ok': not mismatches}
