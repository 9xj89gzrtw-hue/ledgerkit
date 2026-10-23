"""Command line entry point: fetch -> build -> verify.

Each step writes a file, so the whole pipeline is reproducible and the middle
step can be audited without touching the network.
"""
from __future__ import annotations

import argparse
import json
import sys

from .ledger import build_ledger, eth, load_logs
from .rpc import RpcPool
from .verify import VerificationError, verify_ledger, verify_nft_onchain


def _cmd_fetch(args: argparse.Namespace) -> int:
    pool = RpcPool.for_chain(args.chain)
    to_block = args.to_block if args.to_block is not None else pool.block_number()
    logs = pool.get_logs(args.address, args.from_block, to_block, page=args.page)
    with open(args.out, 'w') as fh:
        json.dump(logs, fh)
    print(f'{len(logs)} logs  {args.chain}  {args.address}  '
          f'[{args.from_block}, {to_block}]  -> {args.out}')
    return 0


def _cmd_build(args: argparse.Namespace) -> int:
    logs = load_logs(args.logs)
    ledger = build_ledger(logs, fee_bps=args.fee_bps, exclude_txs=args.exclude_tx)
    summary = ledger.summary()
    if args.csv:
        wallets = ledger.write_csv(args.csv)
        print(f'{wallets} wallets -> {args.csv}')
    if args.summary:
        with open(args.summary, 'w') as fh:
            json.dump(summary, fh, indent=1)
        print(f'summary -> {args.summary}')
    print(f'earned   {summary["total_earned_eth"]} ETH')
    print(f'paid out {summary["total_paid_out_eth"]} ETH')
    print(f'fees     {summary["total_fees_eth"]} ETH')
    print(f'{summary["claims_accepted"]} settlements, {summary["bounties"]} bounties, '
          f'{summary["nfts_held"]} NFTs held')
    for warning in summary['warnings']:
        print(f'warning: {warning}', file=sys.stderr)
    return 0


def _cmd_verify(args: argparse.Namespace) -> int:
    logs = load_logs(args.logs)
    ledger = build_ledger(logs, fee_bps=args.fee_bps, exclude_txs=args.exclude_tx)
    try:
        report = verify_ledger(ledger, logs, fee_bps=args.fee_bps,
                               exclude_txs=args.exclude_tx)
    except VerificationError as exc:
        print(f'FAILED {exc}', file=sys.stderr)
        return 1

    summary = ledger.summary()
    failures = 0
    for label, expected in (('earned', args.expect_earned),
                            ('paid', args.expect_paid)):
        if expected is None:
            continue
        actual = summary['total_earned_eth'] if label == 'earned' else summary['total_paid_out_eth']
        ok = actual == expected
        failures += 0 if ok else 1
        print(f'{"ok  " if ok else "FAIL"} expected {label} {expected} ETH, got {actual}')

    if args.nft and args.chain:
        pool = RpcPool.for_chain(args.chain)
        onchain = verify_nft_onchain(ledger, pool.call, args.nft, sample=args.nft_sample)
        for mismatch in onchain['mismatches']:
            print(f'FAIL nft {mismatch}', file=sys.stderr)
        failures += len(onchain['mismatches'])
        print(f'ok   nft balanceOf sample: {onchain["checked"]} holder(s) checked')

    for name, result in report['checks'].items():
        print(f'{"ok  " if result["ok"] else "FAIL"} {name}: {result["detail"]}')
    return 0 if failures == 0 else 1


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog='ledgerkit', description=__doc__)
    sub = parser.add_subparsers(dest='command', required=True)

    fetch = sub.add_parser('fetch', help='download raw logs to JSON')
    fetch.add_argument('--chain', required=True)
    fetch.add_argument('--address', required=True)
    fetch.add_argument('--from-block', type=int, default=0)
    fetch.add_argument('--to-block', type=int, default=None)
    fetch.add_argument('--page', type=int, default=2_000_000)
    fetch.add_argument('--out', required=True)
    fetch.set_defaults(func=_cmd_fetch)

    build = sub.add_parser('build', help='fold logs into a per-wallet ledger')
    build.add_argument('--logs', required=True)
    build.add_argument('--csv')
    build.add_argument('--summary')
    build.add_argument('--fee-bps', type=int, default=None)
    build.add_argument('--exclude-tx', action='append', default=[],
                       help='settlement transaction to ignore (repeatable)')
    build.set_defaults(func=_cmd_build)

    verify = sub.add_parser('verify', help='reconcile a ledger against its logs')
    verify.add_argument('--logs', required=True)
    verify.add_argument('--fee-bps', type=int, default=None)
    verify.add_argument('--exclude-tx', action='append', default=[])
    verify.add_argument('--expect-earned', help='exact ETH string the ledger must reproduce')
    verify.add_argument('--expect-paid', help='exact ETH string the ledger must reproduce')
    verify.add_argument('--nft', help='ERC-721 address for an on-chain balanceOf spot check')
    verify.add_argument('--chain', help='chain for the on-chain check')
    verify.add_argument('--nft-sample', type=int, default=10)
    verify.set_defaults(func=_cmd_verify)

    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == '__main__':  # pragma: no cover
    raise SystemExit(main())
