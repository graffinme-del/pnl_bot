from __future__ import annotations

import hashlib
import hmac
import json
import logging
import time
from typing import Any, Dict, List, Optional

import aiohttp

log = logging.getLogger(__name__)

from .config import SETTINGS
from .models import Trade


BASE_URL = "https://fapi.binance.com"


class BinanceClient:
    def __init__(self) -> None:
        self._api_key = SETTINGS.binance_api_key
        self._secret = SETTINGS.binance_api_secret.encode("utf-8")
        self._session: Optional[aiohttp.ClientSession] = None
        self._time_offset_ms: Optional[int] = None

    async def _get_session(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession(
                headers={"X-MBX-APIKEY": self._api_key}
            )
        return self._session

    async def close(self) -> None:
        if self._session and not self._session.closed:
            await self._session.close()

    def _sign(self, params: Dict[str, Any]) -> Dict[str, Any]:
        # ВАЖНО: Binance считает подпись по строке запроса в том же порядке,
        # в котором параметры идут в URL. В Python 3.7+ dict сохраняет порядок
        # добавления ключей, поэтому просто итерируемся по items().
        query = "&".join(f"{k}={v}" for k, v in params.items())
        signature = hmac.new(self._secret, query.encode("utf-8"), hashlib.sha256).hexdigest()
        params["signature"] = signature
        return params

    async def _get_server_time(self) -> int:
        """
        Получить время сервера Binance (ms) и закешировать смещение.
        """
        session = await self._get_session()
        async with session.get(BASE_URL + "/fapi/v1/time", timeout=10) as resp:
            resp.raise_for_status()
            data: Dict[str, Any] = await resp.json()
        server_time = int(data["serverTime"])
        local_time = int(time.time() * 1000)
        self._time_offset_ms = server_time - local_time
        return server_time

    async def _timestamp_ms(self) -> int:
        """
        Вернуть timestamp, скорректированный по времени сервера.
        """
        if self._time_offset_ms is None:
            return await self._get_server_time()
        return int(time.time() * 1000 + self._time_offset_ms)

    async def get_recent_income_symbols(self, days: int = 7) -> set[str]:
        """Символы с активностью за N дней — для быстрого sync (новые пары).
        Пагинация при >1000 записей."""
        await self._get_server_time()
        path = "/fapi/v1/income"
        session = await self._get_session()
        symbols: set[str] = set()
        start = int((time.time() - days * 86400) * 1000)
        limit = 1000

        try:
            while True:
                ts = await self._timestamp_ms()
                params: Dict[str, Any] = {
                    "timestamp": ts,
                    "recvWindow": 60000,
                    "limit": limit,
                    "startTime": start,
                }
                signed = self._sign(params)
                async with session.get(BASE_URL + path, params=signed, timeout=30) as resp:
                    if resp.status >= 400:
                        break
                    data = json.loads(await resp.text())
                if not isinstance(data, list) or not data:
                    break
                for item in data:
                    if isinstance(item, dict):
                        s = item.get("symbol") or ""
                        if s and isinstance(s, str) and s.isascii() and s.endswith("USDT"):
                            symbols.add(s)
                if len(data) < limit:
                    break
                # Следующая страница: startTime = последняя запись + 1
                last_time = data[-1].get("time") if isinstance(data[-1], dict) else None
                if last_time is None:
                    break
                start = int(last_time) + 1
        except Exception:
            pass
        return symbols

    async def get_futures_symbols(self) -> List[str]:
        """
        Получить список всех доступных USDT-перпетуалов.
        """
        session = await self._get_session()
        async with session.get(BASE_URL + "/fapi/v1/exchangeInfo", timeout=30) as resp:
            resp.raise_for_status()
            data: Dict[str, Any] = await resp.json()

        symbols: List[str] = []
        for s in data.get("symbols", []):
            symbol = s.get("symbol", "")
            # Берём только стандартные USDT-перпетуалы с латинскими тикерами,
            # чтобы избежать проблем с юникодными символами в подписи
            if (
                s.get("contractType") == "PERPETUAL"
                and s.get("quoteAsset") == "USDT"
                and symbol.isascii()
                and symbol.isupper()
            ):
                symbols.append(symbol)
        return symbols

    async def _fetch_user_trades_raw(
        self,
        symbol: str,
        from_id: Optional[int],
        limit: int,
    ) -> List[Dict[str, Any]]:
        """Один запрос к API. При -1021 бросает ClientResponseError."""
        await self._get_server_time()
        path = "/fapi/v1/userTrades"
        ts = await self._timestamp_ms()
        params: Dict[str, Any] = {
            "symbol": symbol,
            "timestamp": ts,
            "recvWindow": 60000,
            "limit": limit,
        }
        if from_id is not None:
            params["fromId"] = from_id

        signed = self._sign(params)
        session = await self._get_session()
        async with session.get(BASE_URL + path, params=signed, timeout=30) as resp:
            text = await resp.text()
            if resp.status >= 400:
                raise aiohttp.ClientResponseError(
                    request_info=resp.request_info,
                    history=resp.history,
                    status=resp.status,
                    message=text,
                    headers=resp.headers,
                )
            return json.loads(text)

    async def get_user_trades(
        self,
        symbol: str,
        from_id: Optional[int] = None,
        limit: int = 1000,
    ) -> List[Trade]:
        """
        Fetch user's futures trades for a symbol using /fapi/v1/userTrades.
        Пагинация: при 1000+ сделок — подтягивает все (fromId по последнему id).
        При -1021 (timestamp) — одна повторная попытка с обновлением времени.
        """
        all_items: List[Dict[str, Any]] = []
        current_from_id = from_id

        while True:
            try:
                data = await self._fetch_user_trades_raw(
                    symbol, current_from_id, limit
                )
            except aiohttp.ClientResponseError as e:
                if "-1021" in str(e):
                    log.warning("Binance -1021 для %s, retry с обновлением времени", symbol)
                    self._time_offset_ms = None
                    data = await self._fetch_user_trades_raw(
                        symbol, current_from_id, limit
                    )
                else:
                    raise

            if not data:
                break
            all_items.extend(data)
            if len(data) < limit:
                break
            # API возвращает от старых к новым; fromId = id следующего за последним
            last_id = int(data[-1]["id"])
            current_from_id = last_id + 1

        trades: List[Trade] = []
        now_ms = int(time.time() * 1000)
        for item in all_items:
            realized_pnl = float(item.get("realizedPnl", 0.0))
            commission = float(item.get("commission", 0.0))
            trade = Trade(
                exchange="binance",
                market="USDT_PERPETUAL",
                symbol=item["symbol"],
                side=item["side"],
                position_side=item.get("positionSide"),
                order_id=int(item["orderId"]),
                trade_id=int(item["id"]),
                qty=float(item["qty"]),
                price=float(item["price"]),
                quote_qty=float(item["quoteQty"]),
                realized_pnl=realized_pnl,
                commission=-abs(commission),
                commission_asset=item.get("commissionAsset", "USDT"),
                open_time=None,
                close_time=int(item["time"]),
                is_maker=bool(item.get("maker", False)),
                updated_at=now_ms,
            )
            trades.append(trade)

        return trades

