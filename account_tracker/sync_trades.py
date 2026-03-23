from __future__ import annotations

import asyncio
import logging
from typing import List

from .binance_client import BinanceClient
from .models import Trade
from .storage import append_trades, get_last_trade_id_for_symbol, get_known_symbols

log = logging.getLogger(__name__)


async def _fetch_symbol_trades(
    client: BinanceClient,
    symbol: str,
) -> List[Trade]:
    """Запрос сделок по одному символу."""
    try:
        last_id = get_last_trade_id_for_symbol(symbol)
        from_id = (last_id + 1) if last_id is not None else None
        return await client.get_user_trades(symbol=symbol, from_id=from_id)
    except Exception as e:
        log.warning("sync %s: %s", symbol, e)
        return []


async def sync_trades_once() -> List[Trade]:
    """
    Fetch new trades from Binance.
    Известные + из Income API (новые пары) — быстро. Пустой storage = все символы.
    """
    client = BinanceClient()
    new_trades: List[Trade] = []
    try:
        known = get_known_symbols()
        if known:
            recent = await client.get_recent_income_symbols(days=7)
            symbols = sorted(known | recent)
            log.info("Sync: %d символов (known+income)", len(symbols))
        else:
            symbols = await client.get_futures_symbols()
            log.info("Sync: %d символов (все, первый запуск)", len(symbols))
        sem = asyncio.Semaphore(5)  # макс 5 одновременно — меньше нагрузка на сервер

        async def fetch_with_sem(s: str) -> List[Trade]:
            async with sem:
                return await _fetch_symbol_trades(client, s)

        results = await asyncio.gather(
            *[fetch_with_sem(s) for s in symbols],
            return_exceptions=True,
        )
        for r in results:
            if isinstance(r, list):
                new_trades.extend(r)
            elif isinstance(r, Exception):
                log.warning("sync error: %s", r)
        if new_trades:
            # sort by close_time to keep file ordered
            new_trades.sort(key=lambda t: t.close_time)
            append_trades(new_trades)
    except asyncio.CancelledError:
        # При Ctrl+C джоба отменяется — не логируем как ошибку
        return []
    finally:
        await client.close()

    return new_trades


def sync_trades_blocking() -> List[Trade]:
    return asyncio.run(sync_trades_once())

