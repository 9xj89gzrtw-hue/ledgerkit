"""ledgerkit — turn raw EVM logs into a verified per-wallet ETH/NFT ledger.

The problem this solves: a bounty issuer asks "who earned what from our
contracts". The easy answer (scrape the explorer, sum a column) is wrong for
escrow protocols, because the amount a winner receives is not the amount the
bounty carried: a protocol fee is taken at settlement, cancelled bounties never
pay, and a single transaction can settle an arbitrary number of claims.

ledgerkit rebuilds the ledger from the events themselves and then *reconciles*
it, so the CSV it emits can be checked against the chain instead of trusted.

    python -m ledgerkit build --logs logs.json --fee-bps 250 --csv out.csv
    python -m ledgerkit verify --logs logs.json --fee-bps 250

Protocol specifics live in `adapters.py`. The engine itself is protocol
agnostic: give it a fee rate and a topic table and it will produce the ledger.
"""
from .events import BountyCancelled, BountyCreated, ClaimAccepted, ClaimCreated, NftTransfer, decode
from .ledger import Ledger, WalletRow, build_ledger
from .verify import VerificationError, verify_ledger

__all__ = [
    'BountyCancelled', 'BountyCreated', 'ClaimAccepted', 'ClaimCreated', 'NftTransfer', 'decode',
    'Ledger', 'WalletRow', 'build_ledger',
    'VerificationError', 'verify_ledger',
]
__version__ = '0.1.0'
