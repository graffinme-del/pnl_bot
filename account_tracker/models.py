from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Literal, TypedDict


Side = Literal["BUY", "SELL"]
PositionSide = Literal["LONG", "SHORT"]


class TradeRow(TypedDict, total=False):
    exchange: str
    market: str
    symbol: str
    side: Side
    position_side: PositionSide | None
    order_id: int
    trade_id: int
    qty: float
    price: float
    quote_qty: float
    realized_pnl: float
    commission: float
    commission_asset: str
    open_time: int | None
    close_time: int  # timestamp ms
    is_maker: bool
    updated_at: int  # timestamp ms


@dataclass
class Trade:
    exchange: str
    market: str
    symbol: str
    side: Side
    position_side: PositionSide | None
    order_id: int
    trade_id: int
    qty: float
    price: float
    quote_qty: float
    realized_pnl: float
    commission: float
    commission_asset: str
    open_time: int | None
    close_time: int
    is_maker: bool
    updated_at: int

    @property
    def pnl_gross(self) -> float:
        return self.realized_pnl

    @property
    def pnl_net(self) -> float:
        return self.realized_pnl + self.commission

    @property
    def closed_at_dt(self) -> datetime:
        return datetime.fromtimestamp(self.close_time / 1000, tz=timezone.utc)

    def to_row(self) -> TradeRow:
        return TradeRow(
            exchange=self.exchange,
            market=self.market,
            symbol=self.symbol,
            side=self.side,
            position_side=self.position_side,
            order_id=self.order_id,
            trade_id=self.trade_id,
            qty=self.qty,
            price=self.price,
            quote_qty=self.quote_qty,
            realized_pnl=self.realized_pnl,
            commission=self.commission,
            commission_asset=self.commission_asset,
            open_time=self.open_time,
            close_time=self.close_time,
            is_maker=self.is_maker,
            updated_at=self.updated_at,
        )

    @classmethod
    def from_row(cls, row: TradeRow) -> "Trade":
        return cls(
            exchange=row.get("exchange", "binance"),
            market=row.get("market", "USDT_PERPETUAL"),
            symbol=row["symbol"],
            side=row["side"],
            position_side=row.get("position_side"),
            order_id=int(row.get("order_id", 0)),
            trade_id=int(row["trade_id"]),
            qty=float(row["qty"]),
            price=float(row["price"]),
            quote_qty=float(row["quote_qty"]),
            realized_pnl=float(row.get("realized_pnl", 0.0)),
            commission=float(row.get("commission", 0.0)),
            commission_asset=row.get("commission_asset", "USDT"),
            open_time=int(row["open_time"]) if row.get("open_time") is not None else None,
            close_time=int(row["close_time"]),
            is_maker=bool(row.get("is_maker", False)),
            updated_at=int(row.get("updated_at", row["close_time"])),
        )

