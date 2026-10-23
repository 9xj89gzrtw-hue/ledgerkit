"""Decoding tests against real logs pulled from Arbitrum.

The fixtures are verbatim `eth_getLogs` entries for poidh v1
(0xdffe8a4a4103f968ffd61fd082d08c41dcf9b940). Expected values are readable by
hand: 0x0aa87bee538000 is 3e15 wei, 0x1aa535d3d0c000 is 7.5e15 wei.
"""
from ledgerkit.events import (BountyCancelled, BountyCreated, ClaimAccepted, ClaimCreated,
                              NftTransfer, decode, to_address)

BOUNTY_CREATED = {
    'transactionHash': '0x1f7e6d29a5eb43d4b58e3b355c5af96e3619188ca2f6ad535f72464452ad07ca',
    'logIndex': '0x1',
    'topics': [
        '0xd00fa07781d3060308d3f5da95be7929ceef8a74a9bf989b48a216ce85f73e25',
        '0x000000000000000000000000bed82560c39c133a3d64516ecda82c71b72f3cd7',
    ],
    'data': (
        '0x'
        '0000000000000000000000000000000000000000000000000000000000000008'
        '00000000000000000000000000000000000000000000000000000000000000a0'
        '00000000000000000000000000000000000000000000000000000000000000e0'
        '000000000000000000000000000000000000000000000000000aa87bee538000'
        '0000000000000000000000000000000000000000000000000000000064cd3210'
        '000000000000000000000000000000000000000000000000000000000000001b'
        '6561742061206b69776920776974682074686520736b696e206f6e0000000000'
        '000000000000000000000000000000000000000000000000000000000000006b'
        '6561742061206b69776920772f2074686520736b696e206f6e20616e6420706f'
        '73742074686520706963206f6e204661726361737465722c206c696e6b207468'
        '652046617263617374657220706f737420696e20796f757220636c61696d2064'
        '65736372697074696f6e20000000000000000000000000000000000000000000'
    ),
}

CLAIM_CREATED = {
    'transactionHash': '0x0272d8bc1206a3cf7beab39dea0032ce1dc1d118ce50b3f79276465a33c8a9fc',
    'logIndex': '0xf',
    'topics': [
        '0xad535e15626f184e9ff1e309eb44c0e44d147a797b6e9783980bbb419fd9aba1',
        '0x0000000000000000000000006c0ab067b18f9249fde6e88ac60398379d00b77d',
    ],
    'data': (
        '0x'
        '0000000000000000000000000000000000000000000000000000000000000003'
        '0000000000000000000000000000000000000000000000000000000000000005'
        '000000000000000000000000bed82560c39c133a3d64516ecda82c71b72f3cd7'
        '00000000000000000000000000000000000000000000000000000000000000e0'
        '0000000000000000000000000000000000000000000000000000000000000120'
        '0000000000000000000000000000000000000000000000000000000000000003'
        '0000000000000000000000000000000000000000000000000000000064cd42e6'
        '0000000000000000000000000000000000000000000000000000000000000007'
        '72686f7669616e00000000000000000000000000000000000000000000000000'
        '000000000000000000000000000000000000000000000000000000000000000b'
        '6920616d207a6520646576000000000000000000000000000000000000000000'
    ),
}

CLAIM_ACCEPTED = {
    'transactionHash': '0x14ef33512856125e762843d617d4e04196fa3080bcde88502d9da3de71465565',
    'logIndex': '0x2',
    'topics': [
        '0x68669d605f9b1ca0cb82bb6221846a66f289b2f075ad7be1df396d335da38e5a',
    ],
    'data': (
        '0x'
        '0000000000000000000000000000000000000000000000000000000000000005'
        '0000000000000000000000000000000000000000000000000000000000000003'
        '0000000000000000000000006c0ab067b18f9249fde6e88ac60398379d00b77d'
        '000000000000000000000000bed82560c39c133a3d64516ecda82c71b72f3cd7'
        '000000000000000000000000000000000000000000000000001aa535d3d0c000'
    ),
}

CANCELLED = {
    'transactionHash': '0xb3dc79cc68724307cb9b9889bb1e9b9be1e4b1a6507fc7378c9516f61b61e829',
    'logIndex': '0x0',
    'topics': [
        '0xbe34663bc2803ca9be398afdbd7e0bd537378360b743b76b170e3421fbe38450',
    ],
    'data': (
        '0x'
        '000000000000000000000000000000000000000000000000000000000000000a'
        '000000000000000000000000edf6619a30ce482450fc53d52afabc29a0c947df'
    ),
}

MINT = {
    'transactionHash': '0xabc',
    'logIndex': '0x0',
    'topics': [
        '0xddf252ad1be2c89b69c2b068fc378daa952ba7f163c4a11628f55a4df523b3ef',
        '0x0000000000000000000000000000000000000000000000000000000000000000',
        '0x000000000000000000000000dffe8a4a4103f968ffd61fd082d08c41dcf9b940',
        '0x0000000000000000000000000000000000000000000000000000000000000003',
    ],
    'data': '0x',
}


def test_address_from_topic():
    assert to_address('0x' + '0' * 24 + 'bed82560c39c133a3d64516ecda82c71b72f3cd7') == \
        '0xbed82560c39c133a3d64516ecda82c71b72f3cd7'


def test_decode_bounty_created():
    event = decode(BOUNTY_CREATED)
    assert isinstance(event, BountyCreated)
    assert event.bounty_id == 8
    assert event.issuer == '0xbed82560c39c133a3d64516ecda82c71b72f3cd7'
    assert event.amount == 3_000_000_000_000_000          # 0.003 ETH
    assert event.created_at == 1691169296
    assert event.title == 'eat a kiwi with the skin on'


def test_decode_claim_created():
    event = decode(CLAIM_CREATED)
    assert isinstance(event, ClaimCreated)
    assert event.claim_id == 3
    assert event.bounty_id == 5
    assert event.issuer == '0x6c0ab067b18f9249fde6e88ac60398379d00b77d'
    assert event.bounty_issuer == '0xbed82560c39c133a3d64516ecda82c71b72f3cd7'
    assert event.title == 'rhovian'
    assert event.description == 'i am ze dev'
    # the seventh data word is the timestamp, not the sixth (which repeats the
    # claim id as the claim-NFT token id)
    assert event.created_at == 1691173606


def test_decode_claim_accepted():
    event = decode(CLAIM_ACCEPTED)
    assert isinstance(event, ClaimAccepted)
    assert (event.bounty_id, event.claim_id) == (5, 3)
    assert event.claim_issuer == '0x6c0ab067b18f9249fde6e88ac60398379d00b77d'
    assert event.bounty_issuer == '0xbed82560c39c133a3d64516ecda82c71b72f3cd7'
    assert event.fee == 7_500_000_000_000_000             # 0.0075 ETH == 2.5% of 0.3


def test_decode_cancelled():
    event = decode(CANCELLED)
    assert isinstance(event, BountyCancelled)
    assert (event.bounty_id, event.issuer) == (10, '0xedf6619a30ce482450fc53d52afabc29a0c947df')


def test_decode_transfer():
    event = decode(MINT)
    assert isinstance(event, NftTransfer)
    assert event.sender == '0x0000000000000000000000000000000000000000'
    assert event.recipient == '0xdffe8a4a4103f968ffd61fd082d08c41dcf9b940'
    assert event.token_id == 3


def test_unknown_event_is_ignored():
    assert decode({'topics': ['0x' + '11' * 32], 'data': '0x'}) is None
    assert decode({'topics': [], 'data': '0x'}) is None
