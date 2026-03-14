from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import List

import matplotlib.pyplot as plt
import pandas as pd

from .config import SETTINGS
from .reports import AggregatedPosition


def _ensure_dir(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)


def plot_equity_curve(positions: List[AggregatedPosition], output_path: Path) -> None:
    if not positions:
        return
    tz = SETTINGS.timezone
    sorted_pos = sorted(positions, key=lambda p: p.close_time)
    times = [datetime.fromtimestamp(p.close_time / 1000, tz=tz) for p in sorted_pos]
    pnls = [p.pnl_gross for p in sorted_pos]
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


def plot_long_short_pie(positions: List[AggregatedPosition], output_path: Path) -> None:
    if not positions:
        return
    long_pnl = sum(p.pnl_gross for p in positions if p.position_side == "LONG")
    short_pnl = sum(p.pnl_gross for p in positions if p.position_side == "SHORT")
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


def plot_pnl_histogram(positions: List[AggregatedPosition], output_path: Path) -> None:
    if not positions:
        return
    pnls = [p.pnl_gross for p in positions]

    _ensure_dir(output_path)
    plt.figure(figsize=(6, 4))
    bins = min(15, max(5, len(positions) // 2))  # меньше столбцов при малом числе позиций
    plt.hist(pnls, bins=bins, edgecolor="black", alpha=0.7)
    plt.title("Сколько позиций с каким PnL")
    plt.xlabel("PnL позиции, USDT")
    plt.ylabel("Количество позиций")
    plt.grid(True, alpha=0.3)
    plt.tight_layout()
    plt.savefig(output_path)
    plt.close()

