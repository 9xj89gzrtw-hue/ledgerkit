"""Event decoding for escrow-bounty protocols.

Only four event shapes matter for a ledger: a bounty was opened, a claim was
filed, a claim was accepted (which is where money moves), and a bounty was
cancelled (which is where money does not move). NFT ownership comes from ERC-721
`Transfer`.

Every topic hash below is the keccak of the canonical signature, so the table is
self-documenting and can be checked against any explorer.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Union

try:  # eth_abi is the only hard dependency of the decoder
    from eth_abi import decode as abi_decode
except ImportError as exc:  # pragma: no cover - exercised only without deps
    raise ImportError('ledgerkit needs `eth-abi` (pip install eth-abi)') from exc

ZERO_ADDRESS = '0x' + '0' * 40

# keccak256(BountyCreated(uint256,address,string,string,uint256,uint256))
TOPIC_BOUNTY_CREATED = '0xd00fa07781d3060308d3f5da95be7929ceef8a74a9bf989b48a216ce85f73e25'
# keccak256(ClaimCreated(uint256,address,uint256,address,string,string,uint256,uint256))
TOPIC_CLAIM_CREATED = '0xad535e15626f184e9ff1e309eb44c0e44d147a797b6e9783980bbb419fd9aba1'
# keccak256(ClaimAccepted(uint256,uint256,address,address,uint256))
TOPIC_CLAIM_ACCEPTED = '0x68669d605f9b1ca0cb82bb6221846a66f289b2f075ad7be1df396d335da38e5a'
# keccak256(BountyCancelled(uint256,address))
TOPIC_BOUNTY_CANCELLED = '0xbe34663bc2803ca9be398afdbd7e0bd537378360b743b76b170e3421fbe38450'
# keccak256(Transfer(address,address,uint256))
TOPIC_TRANSFER = '0xddf252ad1be2c89b69c2b068fc378daa952ba7f163c4a11628f55a4df523b3ef'


def to_address(topic: str) -> str:
    """A 32-byte topic holding an address -> a 20-byte hex address."""
    return '0x' + topic[-40:].lower()


def _bytes(hexstr: str) -> bytes:
    return bytes.fromhex(hexstr[2:] if hexstr.startswith('0x') else hexstr)


@dataclass(frozen=True)
class BountyCreated:
    bounty_id: int
    issuer: str
    title: str
    description: str
    amount: int          # wei, gross (what the issuer escrowed)
    created_at: int


@dataclass(frozen=True)
class ClaimCreated:
    claim_id: int
    bounty_id: int
    issuer: str
    bounty_issuer: str
    title: str
    description: str
    created_at: int


@dataclass(frozen=True)
class ClaimAccepted:
    bounty_id: int
    claim_id: int
    claim_issuer: str
    bounty_issuer: str
    fee: int             # wei, protocol fee taken out of the bounty amount


@dataclass(frozen=True)
class BountyCancelled:
    bounty_id: int
    issuer: str


@dataclass(frozen=True)
class NftTransfer:
    sender: str
    recipient: str
    token_id: int


Event = Union[BountyCreated, ClaimCreated, ClaimAccepted, BountyCancelled, NftTransfer]


def decode(log: dict[str, Any]) -> Event | None:
    """Decode one raw log. Returns None for events a ledger does not use.

    Malformed logs raise ``ValueError``: silently skipping them is how ledgers
    end up off by a bounty.
    """
    topics = log.get('topics') or []
    if not topics:
        return None
    topic0 = topics[0].lower()
    data = log.get('data') or '0x'

    try:
        if topic0 == TOPIC_TRANSFER:
            if len(topics) != 4:
                return None
            return NftTransfer(
                sender=to_address(topics[1]),
                recipient=to_address(topics[2]),
                token_id=int(topics[3], 16),
            )
        if topic0 == TOPIC_BOUNTY_CREATED:
            bounty_id, title, desc, amount, created = abi_decode(
                ['uint256', 'string', 'string', 'uint256', 'uint256'], _bytes(data))
            return BountyCreated(int(bounty_id), to_address(topics[1]), title, desc,
                                 int(amount), int(created))
        if topic0 == TOPIC_CLAIM_CREATED:
            claim_id, bounty_id, bounty_issuer, title, desc, _token_id, created = abi_decode(
                ['uint256', 'uint256', 'address', 'string', 'string', 'uint256', 'uint256'],
                _bytes(data))
            return ClaimCreated(int(claim_id), int(bounty_id), to_address(topics[1]),
                                bounty_issuer.lower(), title, desc, int(created))
        if topic0 == TOPIC_CLAIM_ACCEPTED:
            bounty_id, claim_id, claim_issuer, bounty_issuer, fee = abi_decode(
                ['uint256', 'uint256', 'address', 'address', 'uint256'], _bytes(data))
            return ClaimAccepted(int(bounty_id), int(claim_id), claim_issuer.lower(),
                                 bounty_issuer.lower(), int(fee))
        if topic0 == TOPIC_BOUNTY_CANCELLED:
            bounty_id, issuer = abi_decode(['uint256', 'address'], _bytes(data))
            return BountyCancelled(int(bounty_id), issuer.lower())
    except Exception as exc:  # pragma: no cover - defensive
        raise ValueError(f'cannot decode log {topic0} in tx {log.get("transactionHash")}: {exc}') from exc
    return None
