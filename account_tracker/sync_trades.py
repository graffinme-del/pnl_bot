from __future__ import annotations

import asyncio
import logging
from typing import List

from .binance_client import BinanceClient
from .models import Trade
from .storage import append_trades, get_last_trade_id_for_symbol, get_known_symbols

log = logging.getLogger(__name__)


async def sync_trades_once() -> List[Trade]:
    """
    Fetch new trades from Binance. Синхронизируем только символы, по которым уже есть сделки
    (иначе 200+ запросов — долго и ошибки timestamp). При первом запуске — все символы.
    """
    client = BinanceClient()
    new_trades: List[Trade] = []
    try:
        known = get_known_symbols()
        if known:
            symbols = sorted(known)
        else:
            symbols = await client.get_futures_symbols()
        for symbol in symbols:
            try:
                last_id = get_last_trade_id_for_symbol(symbol)
                # fromId в Binance — включительно, поэтому берём last_id+1,
                # иначе каждый раз подтягиваем уже сохранённую сделку.
                from_id = (last_id + 1) if last_id is not None else None
                trades = await client.get_user_trades(symbol=symbol, from_id=from_id)
                if trades:
                    new_trades.extend(trades)
            except Exception as e:
                # Ошибка по одному символу — логируем и продолжаем, бот не падает
                log.warning("sync %s: %s", symbol, e)
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

