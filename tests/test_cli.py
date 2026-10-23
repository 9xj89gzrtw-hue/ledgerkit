"""End-to-end CLI tests: build writes a CSV, verify reconciles it."""
import json
import pathlib

from ledgerkit.cli import main

from .test_ledger import ETH, ISSUER, scenario


def test_build_then_verify(tmp_path):
    logs_path = tmp_path / 'logs.json'
    logs_path.write_text(json.dumps(scenario()))
    csv_path = tmp_path / 'wallets.csv'
    summary_path = tmp_path / 'summary.json'

    assert main(['build', '--logs', str(logs_path), '--csv', str(csv_path),
                 '--summary', str(summary_path), '--fee-bps', '250']) == 0

    header = csv_path.read_text().splitlines()[0].split(',')
    assert header[:3] == ['wallet', 'eth_paid_out_wei', 'eth_paid_out']
    summary = json.loads(summary_path.read_text())
    assert summary['total_earned_eth'] == '1.5'
    assert summary['claims_accepted'] == 2

    assert main(['verify', '--logs', str(logs_path), '--fee-bps', '250',
                 '--expect-earned', '1.5', '--expect-paid', '1.4625']) == 0


def test_verify_fails_on_wrong_expectation(tmp_path):
    logs_path = tmp_path / 'logs.json'
    logs_path.write_text(json.dumps(scenario()))
    assert main(['verify', '--logs', str(logs_path), '--fee-bps', '250',
                 '--expect-earned', '9.99']) == 1
