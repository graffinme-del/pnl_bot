from __future__ import annotations

import json
from pathlib import Path
from typing import Iterable, List

from .models import Trade, TradeRow


STORAGE_DIR = Path(__file__).resolve().parents[1] / "storage"
TRADES_PATH = STORAGE_DIR / "account_trades.jsonl"


def ensure_storage_dir() -> None:
    STORAGE_DIR.mkdir(parents=True, exist_ok=True)
    if not TRADES_PATH.exists():
        TRADES_PATH.touch()


def append_trades(trades: Iterable[Trade]) -> None:
    ensure_storage_dir()
    with TRADES_PATH.open("a", encoding="utf-8") as f:
        for trade in trades:
            row: TradeRow = trade.to_row()
            f.write(json.dumps(row, separators=(",", ":")) + "\n")


def read_all_trades() -> List[Trade]:
    ensure_storage_dir()
    result: List[Trade] = []
    seen: set[tuple[str, int]] = set()  # (symbol, trade_id) — дедупликация
    with TRADES_PATH.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            data: TradeRow = json.loads(line)
            key = (data.get("symbol", ""), int(data.get("trade_id", 0)))
            if key in seen:
                continue
            seen.add(key)
            result.append(Trade.from_row(data))
    return result


def get_known_symbols() -> set[str]:
    """Символы, по которым уже есть сделки в хранилище."""
    ensure_storage_dir()
    symbols: set[str] = set()
    with TRADES_PATH.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            data: dict = json.loads(line)
            s = data.get("symbol")
            if s:
                symbols.add(s)
    return symbols


def get_last_trade_id_for_symbol(symbol: str) -> int | None:
    ensure_storage_dir()
    last_id: int | None = None
    with TRADES_PATH.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            data: TradeRow = json.loads(line)
            if data.get("symbol") != symbol:
                continue
            trade_id = int(data["trade_id"])
            if last_id is None or trade_id > last_id:
                last_id = trade_id
    return last_id

