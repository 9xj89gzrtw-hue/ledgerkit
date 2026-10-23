"""Minimal JSON-RPC client: endpoint rotation, retries, paged `eth_getLogs`.

Public RPCs rate-limit, time out, and occasionally return a range they only
partly served. All three are handled here, because a log scrape that silently
drops a page produces a ledger that is wrong in a way nobody notices.

No third-party HTTP library: `urllib` keeps the package dependency-free and
runs identically on CI and on a laptop.
"""
from __future__ import annotations

import json
import time
import urllib.error
import urllib.request
from typing import Any, Iterable

DEFAULT_CHAINS = {
    'base': [
        'https://base-mainnet.public.blastapi.io',
        'https://base.drpc.org',
        'https://base.gateway.tenderly.co',
    ],
    'arbitrum': [
        'https://arb1.arbitrum.io/rpc',
        'https://arbitrum-one-rpc.publicnode.com',
        'https://arbitrum.drpc.org',
    ],
    'mainnet': [
        'https://eth.llamarpc.com',
        'https://rpc.ankr.com/eth',
        'https://cloudflare-eth.com',
    ],
}


class RpcError(RuntimeError):
    pass


class RpcPool:
    def __init__(self, urls: Iterable[str], *, timeout: float = 30.0, retries: int = 8):
        self.urls = [u for u in urls if u]
        if not self.urls:
            raise ValueError('at least one RPC URL is required')
        self.timeout = timeout
        self.retries = retries
        self._id = 0
        self._next = 0

    @classmethod
    def for_chain(cls, chain: str) -> 'RpcPool':
        if chain not in DEFAULT_CHAINS:
            raise ValueError(f'unknown chain {chain!r}; known: {", ".join(DEFAULT_CHAINS)}')
        return cls(DEFAULT_CHAINS[chain])

    def call(self, method: str, params: list[Any]) -> Any:
        last: Exception | None = None
        for attempt in range(self.retries):
            url = self.urls[(self._next + attempt) % len(self.urls)]
            self._id += 1
            body = json.dumps({'jsonrpc': '2.0', 'id': self._id,
                               'method': method, 'params': params}).encode()
            request = urllib.request.Request(
                url, data=body,
                headers={'content-type': 'application/json', 'user-agent': 'ledgerkit/0.1'})
            try:
                with urllib.request.urlopen(request, timeout=self.timeout) as response:
                    payload = json.loads(response.read())
                if 'error' in payload:
                    raise RpcError(f'{method}: {payload["error"]}')
                self._next = (self._next + attempt) % len(self.urls)
                return payload.get('result')
            except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, RpcError) as exc:
                last = exc
                time.sleep(min(2 ** attempt, 12) * 0.25)
        raise RpcError(f'{method} failed after {self.retries} attempts: {last}')

    def block_number(self) -> int:
        return int(self.call('eth_blockNumber', []), 16)

    def get_logs(self, address: str, from_block: int, to_block: int, *,
                 topics: list[Any] | None = None, page: int = 2_000_000) -> list[dict[str, Any]]:
        """Fetch every log for ``address`` in ``[from_block, to_block]``.

        The range is walked in ascending windows and each page is retried with a
        halved span on failure, so a busier-than-expected range degrades in
        speed rather than in completeness.
        """
        out: list[dict[str, Any]] = []
        start = from_block
        while start <= to_block:
            end = min(start + page - 1, to_block)
            try:
                batch = self.call('eth_getLogs', [{
                    'address': address,
                    'fromBlock': hex(start),
                    'toBlock': hex(end),
                    **({'topics': topics} if topics else {}),
                }]) or []
            except RpcError:
                if page <= 100_000:
                    raise
                page //= 4
                continue
            out.extend(batch)
            start = end + 1
        return out
