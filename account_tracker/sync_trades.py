from __future__ import annotations

import asyncio
import logging
from typing import List

from .binance_client import BinanceClient
from .models import Trade
from .storage import append_trades, get_last_trade_id_for_symbol

log = logging.getLogger(__name__)


async def sync_trades_once() -> List[Trade]:
    """
    Fetch new trades from Binance. Синхронизируем ВСЕ символы — как на странице
    https://www.binance.com/ru/my/orders/futures/positionhistory
    """
    client = BinanceClient()
    new_trades: List[Trade] = []
    try:
        symbols = await client.get_futures_symbols()
        log.info("Sync: %d символов", len(symbols))
        for i, symbol in enumerate(symbols):
            try:
                last_id = get_last_trade_id_for_symbol(symbol)
                from_id = (last_id + 1) if last_id is not None else None
                trades = await client.get_user_trades(symbol=symbol, from_id=from_id)
                if trades:
                    new_trades.extend(trades)
                # Пауза каждые 20 символов — меньше нагрузка на API
                if (i + 1) % 20 == 0:
                    await asyncio.sleep(1)
            except Exception as e:
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

