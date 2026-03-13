from __future__ import annotations

import asyncio
from typing import List

from .binance_client import BinanceClient
from .models import Trade
from .storage import append_trades, get_last_trade_id_for_symbol


async def sync_trades_once() -> List[Trade]:
    """
    Fetch new trades from Binance for all configured symbols and append them to storage.
    """
    client = BinanceClient()
    new_trades: List[Trade] = []
    try:
        symbols = await client.get_futures_symbols()
        for symbol in symbols:
            last_id = get_last_trade_id_for_symbol(symbol)
            trades = await client.get_user_trades(symbol=symbol, from_id=last_id)
            if trades:
                new_trades.extend(trades)
        if new_trades:
            # sort by close_time to keep file ordered
            new_trades.sort(key=lambda t: t.close_time)
            append_trades(new_trades)
    finally:
        await client.close()

    return new_trades


def sync_trades_blocking() -> List[Trade]:
    return asyncio.run(sync_trades_once())

