"""Verification tests: a tampered ledger must fail loudly."""
import json
import pathlib

import pytest

from ledgerkit import build_ledger, verify_ledger
from ledgerkit.verify import VerificationError, _recount, _recount_nft
from ledgerkit.events import TOPIC_BOUNTY_CREATED

from .test_ledger import (ALICE, ETH, ISSUER, bounty_created, claim_accepted, scenario,
                          transfer, ZERO)

FIXTURE = pathlib.Path(__file__).parent / 'fixtures' / 'poidh_v1_logs.json'


def test_clean_scenario_passes():
    logs = scenario()
    ledger = build_ledger(logs, fee_bps=250)
    report = verify_ledger(ledger, logs, fee_bps=250)
    assert report['ok'], report['errors']
    assert report['checks']['conservation']['ok']


def test_tampered_payout_is_caught():
    logs = scenario()
    ledger = build_ledger(logs)
    ledger.rows[ALICE].eth_paid_out_wei += 1
    with pytest.raises(VerificationError, match='conservation'):
        verify_ledger(ledger, logs, fee_bps=250)


def test_inflated_nft_count_is_caught():
    logs = scenario()
    ledger = build_ledger(logs)
    ledger.rows[ALICE].nfts_held += 1
    with pytest.raises(VerificationError, match='nft_balances'):
        verify_ledger(ledger, logs)


def test_wrong_fee_rate_is_caught():
    logs = scenario()
    ledger = build_ledger(logs)
    with pytest.raises(VerificationError, match='fee_rate_matches'):
        verify_ledger(ledger, logs, fee_bps=300)


def test_empty_wallets_are_caught():
    logs = scenario()
    ledger = build_ledger(logs)
    ledger.rows['0x' + '99' * 20] = type(next(iter(ledger.rows.values())))(
        wallet='0x' + '99' * 20)
    with pytest.raises(VerificationError, match='no_empty_rows'):
        verify_ledger(ledger, logs)


def test_recount_reads_raw_hex_independently():
    logs = [bounty_created(7, ISSUER, ETH), claim_accepted(7, 1, ALICE, ISSUER, 25 * 10 ** 15)]
    raw = _recount(logs)
    assert raw == {'earned_wei': ETH, 'fees_wei': 25 * 10 ** 15, 'settled': 1}


def test_recount_nft_flags_tokens_with_unseen_history():
    # a transfer from a wallet we never saw mint: incomplete history
    logs = [transfer(1, ALICE, ISSUER)]
    balances, complete = _recount_nft(logs)
    assert balances == {}
    assert complete == set()


@pytest.mark.skipif(not FIXTURE.exists(), reason='fixture not present')
def test_real_v1_logs_reconcile():
    logs = json.loads(FIXTURE.read_text())
    ledger = build_ledger(logs, fee_bps=250)
    report = verify_ledger(ledger, logs, fee_bps=250)
    assert report['ok'], report['errors']
    summary = ledger.summary()
    # published figures for poidh v1 on Arbitrum
    assert summary['total_earned_eth'] == '3.726923002'
    assert summary['total_fees_eth'] == '0.09317307505'
    assert summary['total_paid_out_eth'] == '3.63374992695'
    assert summary['bounties'] == 496
    assert summary['claims_accepted'] == 278
    assert summary['nfts_held'] == 722
