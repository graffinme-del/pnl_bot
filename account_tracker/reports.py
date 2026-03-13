from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Iterable, List, Literal, Tuple

from .config import SETTINGS
from .models import Trade
from .storage import read_all_trades


Period = Literal["day", "week", "month"]


@dataclass
class ReportResult:
    text: str
    period: Period
    start: datetime
    end: datetime
    trades: List[Trade]


def _filter_trades(trades: Iterable[Trade], start: datetime, end: datetime) -> List[Trade]:
    start_ts = int(start.timestamp() * 1000)
    end_ts = int(end.timestamp() * 1000)
    return [t for t in trades if start_ts <= t.close_time <= end_ts]


def _calc_period_bounds(period: Period, now: datetime) -> Tuple[datetime, datetime]:
    tz = SETTINGS.timezone
    now = now.astimezone(tz)
    if period == "day":
        start = now.replace(hour=0, minute=0, second=0, microsecond=0)
        end = now
    elif period == "week":
        weekday = now.weekday()  # 0 = Monday
        start = (now - timedelta(days=weekday)).replace(
            hour=0, minute=0, second=0, microsecond=0
        )
        end = now
    else:  # month
        start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        end = now
    return start, end


def _format_report(period: Period, start: datetime, end: datetime, trades: List[Trade]) -> str:
    tz = SETTINGS.timezone
    start_local = start.astimezone(tz)
    end_local = end.astimezone(tz)

    total_profit = sum(t.pnl_gross for t in trades if t.pnl_gross > 0)
    total_loss = sum(t.pnl_gross for t in trades if t.pnl_gross < 0)
    total_fees = sum(t.commission for t in trades)
    total_pnl = total_profit + total_loss
    net_pnl = total_pnl + total_fees

    wins = sum(1 for t in trades if t.pnl_gross > 0)
    losses = sum(1 for t in trades if t.pnl_gross < 0)
    trades_count = len(trades)
    winrate = (wins / trades_count * 100) if trades_count else 0.0

    header_date = end_local.strftime("%d.%m.%Y")
    if period == "day":
        header = f"📊 Отчёт по фьючерсам Binance — за СЕГОДНЯ ({header_date})"
    elif period == "week":
        header = "📊 Отчёт по фьючерсам Binance — за НЕДЕЛЮ"
    else:
        header = "📊 Отчёт по фьючерсам Binance — за МЕСЯЦ"

    lines: List[str] = [header, "", "Итог за период:"]
    lines.append(f"• Profit: {total_profit:.2f} USDT")
    lines.append(f"• Loss: {total_loss:.2f} USDT")
    lines.append(f"• Общий PnL (до комиссий): {total_pnl:.2f} USDT")
    lines.append(f"• Комиссии: {total_fees:.2f} USDT")
    lines.append(f"• Чистый результат (после комиссий): {net_pnl:.2f} USDT")
    lines.append(f"• Сделок: {trades_count}")
    lines.append(f"• Winrate: {winrate:.1f}% ({wins} / {trades_count})")

    if period in ("week", "month"):
        if abs(total_loss) > 1e-9:
            profit_factor = total_profit / abs(total_loss)
        else:
            profit_factor = 0.0
        lines.append(f"• Profit factor: {profit_factor:.2f}")

    # Detailed sections
    if period in ("day", "week"):
        lines.append("")
        lines.append("По сделкам (в хронологическом порядке, только закрытые сделки):")
        sorted_trades = sorted(trades, key=lambda t: t.close_time)
        for idx, t in enumerate(sorted_trades, start=1):
            dt = t.closed_at_dt.astimezone(tz)
            if period == "day":
                time_str = dt.strftime("%H:%M")
            else:
                time_str = dt.strftime("%d.%m %H:%M")
            lines.append(
                f"{idx}) {time_str}  {t.symbol}  {t.position_side or t.side}   {t.pnl_gross:.2f} USDT"
            )
    else:
        # month: aggregate by symbol
        per_symbol: dict[str, List[Trade]] = {}
        for t in trades:
            per_symbol.setdefault(t.symbol, []).append(t)
        lines.append("")
        lines.append("По монетам (агрегировано за месяц):")
        for symbol, ts in sorted(per_symbol.items()):
            symbol_profit = sum(x.pnl_gross for x in ts if x.pnl_gross > 0)
            symbol_loss = sum(x.pnl_gross for x in ts if x.pnl_gross < 0)
            symbol_pnl = symbol_profit + symbol_loss
            lines.append(
                f"{symbol}: Profit {symbol_profit:.2f} USDT, Loss {symbol_loss:.2f} USDT, "
                f"Общий PnL {symbol_pnl:.2f} USDT, сделок {len(ts)}"
            )

    # Directions
    long_trades = [t for t in trades if (t.position_side or t.side) == "LONG"]
    short_trades = [t for t in trades if (t.position_side or t.side) == "SHORT"]

    def _dir_stats(ts: List[Trade]) -> tuple[float, float, float, int, float]:
        d_profit = sum(t.pnl_gross for t in ts if t.pnl_gross > 0)
        d_loss = sum(t.pnl_gross for t in ts if t.pnl_gross < 0)
        d_pnl = d_profit + d_loss
        d_count = len(ts)
        d_wins = sum(1 for t in ts if t.pnl_gross > 0)
        d_winrate = (d_wins / d_count * 100) if d_count else 0.0
        return d_profit, d_loss, d_pnl, d_count, d_winrate

    long_profit, long_loss, long_pnl, long_count, long_wr = _dir_stats(long_trades)
    short_profit, short_loss, short_pnl, short_count, short_wr = _dir_stats(short_trades)

    lines.append("")
    lines.append("По направлениям:")
    lines.append(
        f"• Лонги: Profit {long_profit:.2f} USDT, Loss {long_loss:.2f} USDT, "
        f"Общий PnL {long_pnl:.2f} USDT"
    )
    lines.append(
        f"  Сделок: {long_count}, winrate {long_wr:.1f}%"
    )
    lines.append(
        f"• Шорты: Profit {short_profit:.2f} USDT, Loss {short_loss:.2f} USDT, "
        f"Общий PnL {short_pnl:.2f} USDT"
    )
    lines.append(
        f"  Сделок: {short_count}, winrate {short_wr:.1f}%"
    )

    # Period footer
    if period == "day":
        period_line = (
            f"⏱ Период отчёта: сегодня, 00:00–{end_local.strftime('%H:%M')} (локальное время)"
        )
    elif period == "week":
        period_line = (
            "⏱ Период отчёта: текущая неделя "
            f"(с {start_local.strftime('%d.%m.%Y')} по {end_local.strftime('%d.%m.%Y')}, "
            f"{end_local.strftime('%H:%M')}, локальное время)"
        )
    else:
        # month
        period_line = (
            "⏱ Период отчёта: текущий месяц "
            f"(с {start_local.strftime('%d.%m.%Y')} по {end_local.strftime('%d.%m.%Y')}, "
            f"{end_local.strftime('%H:%M')}, локальное время)"
        )

    lines.append("")
    lines.append(period_line)
    lines.append("Данные получены из истории сделок Binance Futures.")

    return "\n".join(lines)


def build_pnl_report(period: Period, now: datetime | None = None) -> ReportResult:
    if now is None:
        now = datetime.now(tz=SETTINGS.timezone)
    start, end = _calc_period_bounds(period, now)
    all_trades = read_all_trades()
    period_trades = _filter_trades(all_trades, start, end)
    text = _format_report(period, start, end, period_trades)
    return ReportResult(text=text, period=period, start=start, end=end, trades=period_trades)

