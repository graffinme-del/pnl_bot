from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Iterable, List, Literal, Tuple

from .config import SETTINGS
from .models import Trade
from .storage import read_all_trades


Period = Literal["day", "week", "month", "range"]


@dataclass
class AggregatedPosition:
    """Одна закрытая позиция (ордер) — сумма всех исполнений (fills)."""
    order_id: int
    symbol: str
    position_side: str
    pnl_gross: float
    commission: float
    close_time: int  # ms, время последнего исполнения

    @property
    def pnl_net(self) -> float:
        """Чистый PnL после комиссии (как в интерфейсе Binance)."""
        return self.pnl_gross + self.commission


def _aggregate_by_order(trades: List[Trade]) -> List[AggregatedPosition]:
    """Группируем fills по order_id — одна строка = одна закрытая позиция."""
    by_order: dict[int, List[Trade]] = defaultdict(list)
    for t in trades:
        by_order[t.order_id].append(t)

    result: List[AggregatedPosition] = []
    for order_id, group in by_order.items():
        first = group[0]
        result.append(AggregatedPosition(
            order_id=order_id,
            symbol=first.symbol,
            position_side=first.position_side or first.side,
            pnl_gross=sum(x.pnl_gross for x in group),
            commission=sum(x.commission for x in group),
            close_time=max(x.close_time for x in group),
        ))
    return result


@dataclass
class ReportResult:
    text: str
    period: Period
    start: datetime
    end: datetime
    trades: List[Trade]
    positions: List[AggregatedPosition]  # агрегированные позиции для графиков


# Минимальный |PnL| для учёта сделки (отсекаем «нулевые» / отменённые)
MIN_PNL_THRESHOLD = 0.01


def _filter_trades(trades: Iterable[Trade], start: datetime, end: datetime) -> List[Trade]:
    """Фильтр только по времени. Не отсекаем fills с pnl=0 — у них есть комиссия."""
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

    # Агрегируем по ордерам: одна закрытая позиция = одна строка
    positions = _aggregate_by_order(trades)
    positions = [p for p in positions if abs(p.pnl_gross) >= MIN_PNL_THRESHOLD]

    total_profit = sum(p.pnl_gross for p in positions if p.pnl_gross > 0)
    total_loss = sum(p.pnl_gross for p in positions if p.pnl_gross < 0)
    total_fees = sum(p.commission for p in positions)
    total_pnl = total_profit + total_loss
    net_pnl = total_pnl + total_fees

    wins = sum(1 for p in positions if p.pnl_gross > 0)
    losses = sum(1 for p in positions if p.pnl_gross < 0)
    trades_count = len(positions)
    winrate = (wins / trades_count * 100) if trades_count else 0.0

    header_date = end_local.strftime("%d.%m.%Y")
    if period == "day":
        header = f"📊 Отчёт по фьючерсам Binance — за СЕГОДНЯ ({header_date})"
    elif period == "week":
        header = "📊 Отчёт по фьючерсам Binance — за НЕДЕЛЮ"
    elif period == "range":
        header = (
            f"📊 Отчёт по фьючерсам Binance — "
            f"{start_local.strftime('%d.%m.%Y')} – {end_local.strftime('%d.%m.%Y')}"
        )
    else:
        header = "📊 Отчёт по фьючерсам Binance — за МЕСЯЦ"

    lines: List[str] = [header, "", "<b>Итог за период:</b>"]
    lines.append(f"• Profit (до комиссий): <b>{total_profit:.2f} USDT</b>")
    lines.append(f"• Loss (до комиссий): <b>{total_loss:.2f} USDT</b>")
    lines.append(f"• Общий PnL: <b>{total_pnl:.2f} USDT</b>")
    lines.append(f"• Комиссии: {total_fees:.2f} USDT")
    lines.append(f"• <b>Чистый результат: {net_pnl:.2f} USDT</b>")
    lines.append(f"• <b><i>Сделок: {trades_count}</i></b>")
    lines.append(f"• <b><i>Winrate: {winrate:.1f}% ({wins} / {trades_count})</i></b>")

    if period in ("week", "month", "range"):
        if abs(total_loss) > 1e-9:
            profit_factor = total_profit / abs(total_loss)
        else:
            profit_factor = 0.0
        lines.append(f"• Profit factor: {profit_factor:.2f}")

    # Detailed sections
    if period in ("day", "week", "range"):
        lines.append("")
        lines.append("<b>По сделкам</b> (Realized PnL, как на Binance — до комиссий):")
        sorted_positions = sorted(positions, key=lambda p: p.close_time)

        max_positions_to_show = 60
        for idx, p in enumerate(sorted_positions[:max_positions_to_show], start=1):
            dt = datetime.fromtimestamp(p.close_time / 1000, tz=tz)
            if period == "day":
                time_str = dt.strftime("%H:%M")
            else:
                time_str = dt.strftime("%d.%m %H:%M")
            # pnl_gross — как Realized PnL на странице Binance Position History
            lines.append(
                f"{idx}) {time_str}  {p.symbol}  {p.position_side}   {p.pnl_gross:.2f} USDT"
            )
        hidden = max(0, len(sorted_positions) - max_positions_to_show)
        if hidden > 0:
            lines.append(f"... ещё {hidden} позиций скрыто.")
    else:
        # month: aggregate by symbol (позиции уже агрегированы по ордерам)
        per_symbol: dict[str, List[AggregatedPosition]] = defaultdict(list)
        for p in positions:
            per_symbol[p.symbol].append(p)
        lines.append("")
        lines.append("По монетам (агрегировано за месяц):")
        for symbol, ps in sorted(per_symbol.items()):
            symbol_profit = sum(x.pnl_gross for x in ps if x.pnl_gross > 0)
            symbol_loss = sum(x.pnl_gross for x in ps if x.pnl_gross < 0)
            symbol_pnl = symbol_profit + symbol_loss
            lines.append(
                f"{symbol}: Profit {symbol_profit:.2f} USDT, Loss {symbol_loss:.2f} USDT, "
                f"Общий PnL {symbol_pnl:.2f} USDT, позиций {len(ps)}"
            )

    # Directions
    long_positions = [p for p in positions if p.position_side == "LONG"]
    short_positions = [p for p in positions if p.position_side == "SHORT"]

    def _dir_stats(ps: List[AggregatedPosition]) -> tuple[float, float, float, int, float]:
        """По gross — как в блоке «По сделкам» и на Binance."""
        d_profit = sum(p.pnl_gross for p in ps if p.pnl_gross > 0)
        d_loss = sum(p.pnl_gross for p in ps if p.pnl_gross < 0)
        d_pnl = d_profit + d_loss
        d_count = len(ps)
        d_wins = sum(1 for p in ps if p.pnl_gross > 0)
        d_winrate = (d_wins / d_count * 100) if d_count else 0.0
        return d_profit, d_loss, d_pnl, d_count, d_winrate

    long_profit, long_loss, long_pnl, long_count, long_wr = _dir_stats(long_positions)
    short_profit, short_loss, short_pnl, short_count, short_wr = _dir_stats(short_positions)

    lines.append("")
    lines.append("<b><i>По направлениям</i></b> (до комиссий, как Binance):")
    lines.append("")
    lines.append("<b>Лонги</b>")
    lines.append(f"  Profit: {long_profit:.2f}  |  Loss: {long_loss:.2f}  |  PnL: <b>{long_pnl:.2f} USDT</b>")
    lines.append(f"  Сделок: {long_count}  |  Winrate: {long_wr:.1f}%")
    lines.append("")
    lines.append("<b>Шорты</b>")
    lines.append(f"  Profit: {short_profit:.2f}  |  Loss: {short_loss:.2f}  |  PnL: <b>{short_pnl:.2f} USDT</b>")
    lines.append(f"  Сделок: {short_count}  |  Winrate: {short_wr:.1f}%")

    # Period footer
    if period == "day":
        period_line = (
            f"⏱ Период отчёта: сегодня, 00:00–{end_local.strftime('%H:%M')} (локальное время)"
        )
    elif period == "range":
        period_line = (
            f"⏱ Период отчёта: {start_local.strftime('%d.%m.%Y')} 00:00 – "
            f"{end_local.strftime('%d.%m.%Y')} {end_local.strftime('%H:%M')} (локальное время)"
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


def build_pnl_report(
    period: Period,
    now: datetime | None = None,
    start: datetime | None = None,
    end: datetime | None = None,
) -> ReportResult:
    tz = SETTINGS.timezone
    now = now or datetime.now(tz=tz)
    if start is not None and end is not None:
        start = start.astimezone(tz).replace(hour=0, minute=0, second=0, microsecond=0)
        end = end.astimezone(tz)
        period = "range"
    else:
        start, end = _calc_period_bounds(period, now)
    all_trades = read_all_trades()
    period_trades = _filter_trades(all_trades, start, end)
    positions = _aggregate_by_order(period_trades)
    positions = [p for p in positions if abs(p.pnl_gross) >= MIN_PNL_THRESHOLD]
    text = _format_report(period, start, end, period_trades)
    return ReportResult(
        text=text, period=period, start=start, end=end,
        trades=period_trades, positions=positions,
    )

