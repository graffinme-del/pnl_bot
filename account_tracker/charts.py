from __future__ import annotations

from pathlib import Path
from typing import List

import matplotlib.pyplot as plt
import pandas as pd

from .config import SETTINGS
from .models import Trade


def _ensure_dir(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)


def plot_equity_curve(trades: List[Trade], output_path: Path) -> None:
    if not trades:
        return
    tz = SETTINGS.timezone
    sorted_trades = sorted(trades, key=lambda t: t.close_time)
    times = [t.closed_at_dt.astimezone(tz) for t in sorted_trades]
    pnls = [t.pnl_gross for t in sorted_trades]
    equity = pd.Series(pnls).cumsum()

    _ensure_dir(output_path)
    plt.figure(figsize=(8, 4))
    plt.plot(times, equity, marker="o")
    plt.title("Кривая PnL за период")
    plt.xlabel("Время")
    plt.ylabel("Накопленный PnL, USDT")
    plt.grid(True, alpha=0.3)
    plt.tight_layout()
    plt.savefig(output_path)
    plt.close()


def plot_long_short_pie(trades: List[Trade], output_path: Path) -> None:
    if not trades:
        return
    long_pnl = sum(t.pnl_gross for t in trades if (t.position_side or t.side) == "LONG")
    short_pnl = sum(t.pnl_gross for t in trades if (t.position_side or t.side) == "SHORT")
    values = [max(long_pnl, 0.0), max(short_pnl, 0.0)]
    labels = ["Лонги", "Шорты"]
    if sum(values) <= 0:
        return

    _ensure_dir(output_path)
    plt.figure(figsize=(4, 4))
    plt.pie(values, labels=labels, autopct="%1.1f%%")
    plt.title("Доли PnL: лонги / шорты")
    plt.tight_layout()
    plt.savefig(output_path)
    plt.close()


def plot_pnl_histogram(trades: List[Trade], output_path: Path) -> None:
    if not trades:
        return
    pnls = [t.pnl_gross for t in trades]

    _ensure_dir(output_path)
    plt.figure(figsize=(6, 4))
    plt.hist(pnls, bins=15, edgecolor="black", alpha=0.7)
    plt.title("Распределение PnL по сделкам")
    plt.xlabel("Pnl сделки, USDT")
    plt.ylabel("Количество сделок")
    plt.grid(True, alpha=0.3)
    plt.tight_layout()
    plt.savefig(output_path)
    plt.close()

