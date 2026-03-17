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
    Fetch new trades from Binance.
    Символы: известные из storage + новые из Income API (POLYX, ZEC, ARIA и т.д.).
    При первом запуске (пустой storage) — все символы.
    """
    client = BinanceClient()
    new_trades: List[Trade] = []
    try:
        known = get_known_symbols()
        if known:
            # Добавляем символы с недавней активностью (POLYX, ZEC, ARIA и т.д.)
            recent = await client.get_recent_income_symbols(days=7)
            new_symbols = recent - known
            if new_symbols:
                log.info("Обнаружены новые символы: %s", sorted(new_symbols))
            symbols = sorted(known | recent)
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

