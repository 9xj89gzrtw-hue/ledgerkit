"""Aggregation tests on a hand-built scenario.

Every expected number below is written out arithmetically in the test, not
copied from a previous run: a test that only re-reads yesterday's output cannot
catch a bug that was there yesterday.
"""
import itertools

from eth_abi import encode

from ledgerkit import build_ledger
from ledgerkit.events import (TOPIC_BOUNTY_CANCELLED, TOPIC_BOUNTY_CREATED,
                              TOPIC_CLAIM_ACCEPTED, TOPIC_CLAIM_CREATED, TOPIC_TRANSFER)

ISSUER = '0x' + '11' * 20
ALICE = '0x' + 'aa' * 20
BOB = '0x' + 'bb' * 20
ZERO = '0x' + '00' * 20
ETH = 10 ** 18

_counter = itertools.count()


def log(topic0, topic1=None, data='0x', tx=None):
    topics = [topic0] + ([topic1] if topic1 else [])
    if topic1 and not topic1.startswith('0x'):
        topics[1] = '0x' + topic1.rjust(64, '0')
    n = next(_counter)
    return {'topics': topics, 'data': data,
            'transactionHash': tx or f'0x{n:064x}', 'logIndex': hex(n)}


def bounty_created(bounty_id, issuer, amount, title='t', desc='d', created=1):
    data = '0x' + encode(['uint256', 'string', 'string', 'uint256', 'uint256'],
                         [bounty_id, title, desc, amount, created]).hex()
    return log(TOPIC_BOUNTY_CREATED, issuer, data)


def claim_created(claim_id, bounty_id, claim_issuer, bounty_issuer):
    data = '0x' + encode(['uint256', 'uint256', 'address', 'string', 'string',
                          'uint256', 'uint256'],
                         [claim_id, bounty_id, bounty_issuer, 'c', 'd', claim_id, 2]).hex()
    return log(TOPIC_CLAIM_CREATED, claim_issuer, data)


def claim_accepted(bounty_id, claim_id, claim_issuer, bounty_issuer, fee):
    data = '0x' + encode(['uint256', 'uint256', 'address', 'address', 'uint256'],
                         [bounty_id, claim_id, claim_issuer, bounty_issuer, fee]).hex()
    return log(TOPIC_CLAIM_ACCEPTED, data=data)


def bounty_cancelled(bounty_id, issuer):
    data = '0x' + encode(['uint256', 'address'], [bounty_id, issuer]).hex()
    return log(TOPIC_BOUNTY_CANCELLED, data=data)


def transfer(token_id, sender, recipient, tx=None):
    return {
        'topics': [TOPIC_TRANSFER,
                   '0x' + sender[2:].rjust(64, '0'),
                   '0x' + recipient[2:].rjust(64, '0'),
                   '0x' + hex(token_id)[2:].rjust(64, '0')],
        'data': '0x',
        'transactionHash': tx or f'0x{next(_counter):064x}',
        'logIndex': '0x0',
    }


def scenario():
    """Issuer opens three bounties; Alice wins two; the third is cancelled."""
    return [
        bounty_created(1, ISSUER, 1 * ETH),
        bounty_created(2, ISSUER, ETH // 2),
        bounty_created(3, ISSUER, ETH // 5),
        claim_created(10, 1, ALICE, ISSUER),
        claim_created(11, 2, ALICE, ISSUER),
        claim_accepted(1, 10, ALICE, ISSUER, 25 * 10 ** 15),      # 2.5% of 1 ETH
        claim_accepted(2, 11, ALICE, ISSUER, 125 * 10 ** 14),     # 2.5% of 0.5 ETH
        bounty_cancelled(3, ISSUER),
        transfer(10, ZERO, ALICE),
        transfer(11, ZERO, ALICE),
        transfer(10, ALICE, BOB),
    ]


def test_winners_are_credited_gross_and_net():
    ledger = build_ledger(scenario(), fee_bps=250)
    alice = ledger.rows[ALICE]
    assert alice.bounties_won == 2
    assert alice.eth_earned_wei == 1 * ETH + ETH // 2
    assert alice.eth_paid_out_wei == alice.eth_earned_wei - (25 * 10 ** 15 + 125 * 10 ** 14)
    assert alice.claims_submitted == 2


def test_issuer_carries_escrow_and_fees():
    ledger = build_ledger(scenario(), fee_bps=250)
    issuer = ledger.rows[ISSUER]
    assert issuer.bounties_created == 3
    assert issuer.eth_escrowed_for_completed_bounties_wei == 1 * ETH + ETH // 2
    assert issuer.fees_paid_wei == 25 * 10 ** 15 + 125 * 10 ** 14


def test_cancelled_bounty_pays_nobody():
    ledger = build_ledger(scenario(), fee_bps=250)
    assert ledger.stats['bounties_cancelled'] == 1
    assert ledger.summary()['total_earned_wei'] == 1 * ETH + ETH // 2


def test_nft_ownership_follows_last_transfer():
    ledger = build_ledger(scenario(), fee_bps=250)
    assert ledger.rows[ALICE].nfts_held == 1          # token 10 moved to Bob
    assert ledger.rows[ALICE].nfts_minted == 2
    assert ledger.rows[BOB].nfts_held == 1


def test_duplicate_logs_are_dropped():
    logs = scenario()
    duplicated = logs + [logs[5]]                     # same settlement twice
    ledger = build_ledger(duplicated, fee_bps=250)
    assert ledger.stats['duplicate_logs_dropped'] == 1
    assert ledger.summary()['total_earned_wei'] == 1 * ETH + ETH // 2


def test_excluded_transaction_is_skipped():
    logs = scenario()
    settlement_tx = logs[5]['transactionHash']
    ledger = build_ledger(logs, fee_bps=250, exclude_txs=[settlement_tx])
    assert ledger.stats['excluded_logs_dropped'] == 1
    assert ledger.summary()['total_earned_wei'] == ETH // 2      # only bounty 2 counts
    assert ledger.stats['claims_accepted'] == 1


def test_missing_bounty_creation_is_reported_not_guessed():
    logs = [claim_created(10, 99, ALICE, ISSUER), claim_accepted(99, 10, ALICE, ISSUER, 1)]
    ledger = build_ledger(logs, fee_bps=250)
    assert ledger.stats['claims_accepted'] == 1
    assert ledger.stats['claims_valued'] == 0
    assert ledger.summary()['total_earned_wei'] == 0
    assert any('no creation event' in w for w in ledger.warnings)


def test_fee_mismatch_is_reported():
    logs = [bounty_created(1, ISSUER, ETH), claim_accepted(1, 10, ALICE, ISSUER, 1)]
    ledger = build_ledger(logs, fee_bps=250)
    assert ledger.stats['fee_mismatches'] == 1
    assert any('fee_bps' in w for w in ledger.warnings)


def test_exact_eth_formatting_never_uses_floats():
    from ledgerkit.ledger import eth
    assert eth(0) == '0'
    assert eth(1) == '0.000000000000000001'
    assert eth(10 ** 18) == '1'
    assert eth(3_726_923_002_000_000_000) == '3.726923002'
    assert eth(93_173_075_050_000_000) == '0.09317307505'
