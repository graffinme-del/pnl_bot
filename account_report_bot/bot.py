from __future__ import annotations

import asyncio
import logging
import re
from datetime import datetime, time as dtime

log = logging.getLogger(__name__)
from pathlib import Path

from aiogram import Bot, Dispatcher
from aiogram.filters import Command
from aiogram.client.default import DefaultBotProperties
from aiogram.types import BotCommand, BotCommandScopeAllPrivateChats, FSInputFile, Message
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

from account_tracker.config import SETTINGS
from account_tracker.reports import build_pnl_report
from account_tracker.charts import (
    plot_equity_curve,
    plot_long_short_pie,
    plot_pnl_histogram,
)
from account_tracker.sync_trades import sync_trades_once


bot = Bot(
    token=SETTINGS.telegram_bot_token,
    default=DefaultBotProperties(parse_mode="HTML"),
)
dp = Dispatcher()


async def _send_report(
    period: str,
    auto: bool,
    source_message: Message | None = None,
    start: datetime | None = None,
    end: datetime | None = None,
) -> None:
    # Сразу удаляем командное сообщение пользователя (при ручном вызове)
    if not auto and source_message is not None:
        try:
            await source_message.delete()
        except Exception:
            pass

    # Sync перед ручным отчётом — свежие данные
    if not auto and source_message:
        try:
            status_msg = await bot.send_message(
                source_message.chat.id, "Синхронизирую сделки..."
            )
            await sync_trades_once()
            try:
                await status_msg.delete()
            except Exception:
                pass
        except Exception:
            pass

    now = datetime.now(tz=SETTINGS.timezone)
    report = build_pnl_report(period=period, now=now, start=start, end=end)

    # Графики для недели, месяца и произвольного периода (если > 3 дней)
    images: list[Path] = []
    show_charts = period in ("week", "month") or (
        period == "range"
        and start is not None
        and end is not None
        and (end - start).days >= 3
        and report.positions
    )
    if show_charts and report.positions:
        charts_dir = Path("charts") / period
        equity_path = charts_dir / "equity.png"
        pie_path = charts_dir / "long_short.png"
        hist_path = charts_dir / "hist.png"
        plot_equity_curve(report.positions, equity_path)
        plot_long_short_pie(report.positions, pie_path)
        plot_pnl_histogram(report.positions, hist_path)
        images = [equity_path, pie_path, hist_path]

    chat_id = SETTINGS.report_chat_id
    # Telegram лимит ~4096 символов — разбиваем по строкам при необходимости
    text = report.text
    max_len = 4000
    sent_ids: list[int] = []
    if len(text) <= max_len:
        m = await bot.send_message(chat_id, text)
        sent_ids.append(m.message_id)
    else:
        lines = text.split("\n")
        parts: list[str] = []
        buf = ""
        for line in lines:
            if len(buf) + len(line) + 1 <= max_len:
                buf += line + "\n"
            else:
                if buf:
                    parts.append(buf.rstrip())
                buf = line + "\n"
        if buf:
            parts.append(buf.rstrip())
        for part in parts:
            m = await bot.send_message(chat_id, part)
            sent_ids.append(m.message_id)

    # Отправка картинок
    for img_path in images:
        if img_path.exists():
            m = await bot.send_photo(chat_id, FSInputFile(str(img_path)))
            if not auto:
                sent_ids.append(m.message_id)

    # Только при ручном вызове — удалить через 2 минуты
    if not auto and sent_ids:

        async def _delete_after_delay() -> None:
            await asyncio.sleep(120)
            for mid in sent_ids:
                try:
                    await bot.delete_message(chat_id, mid)
                except Exception as e:
                    log.warning("Не удалось удалить сообщение %s: %s", mid, e)

        asyncio.create_task(_delete_after_delay())


@dp.message(Command("pnl_today"))
async def cmd_pnl_today(message: Message) -> None:
    await _send_report("day", auto=False, source_message=message)


@dp.message(Command("pnl_week"))
async def cmd_pnl_week(message: Message) -> None:
    await _send_report("week", auto=False, source_message=message)


@dp.message(Command("pnl_month"))
async def cmd_pnl_month(message: Message) -> None:
    await _send_report("month", auto=False, source_message=message)


def _parse_dates(text: str, tz) -> tuple[datetime, datetime] | None:
    """
    Парсит даты из текста. Форматы: DD.MM.YYYY, DD.MM, D.M
    Возвращает (start, end) или None при ошибке.
    """
    # Убираем команду, оставляем аргументы
    parts = text.split(maxsplit=1)
    args = (parts[1] if len(parts) > 1 else "").strip()
    if not args:
        return None
    tokens = args.split()
    if not tokens:
        return None

    def parse_one(s: str) -> datetime | None:
        m = re.match(r"^(\d{1,2})\.(\d{1,2})(?:\.(\d{4}))?$", s.strip())
        if not m:
            return None
        d, mon = int(m.group(1)), int(m.group(2))
        y = int(m.group(3)) if m.group(3) else datetime.now(tz).year
        try:
            return datetime(y, mon, d, tzinfo=tz)
        except ValueError:
            return None

    dt1 = parse_one(tokens[0])
    if not dt1:
        return None
    dt2 = parse_one(tokens[1]) if len(tokens) >= 2 else dt1
    if not dt2:
        return None
    if dt1 > dt2:
        dt1, dt2 = dt2, dt1
    return dt1, dt2


@dp.message(Command("pnl_range"))
async def cmd_pnl_range(message: Message) -> None:
    """Отчёт за выбранный период. Примеры:
    /pnl_range 22.03.2026
    /pnl_range 10.03.2026 22.03.2026
    """
    tz = SETTINGS.timezone
    parsed = _parse_dates(message.text or "", tz)
    if not parsed:
        await message.reply(
            "Формат: /pnl_range DD.MM.YYYY или /pnl_range DD.MM.YYYY DD.MM.YYYY\n"
            "Пример: /pnl_range 22.03.2026\n"
            "Пример: /pnl_range 10.03 22.03.2026"
        )
        return
    start, end = parsed
    await _send_report("range", auto=False, source_message=message, start=start, end=end)


def _setup_scheduler(scheduler: AsyncIOScheduler) -> None:
    tz = SETTINGS.timezone

    # Ежедневно в 21:00
    scheduler.add_job(
        _send_report,
        CronTrigger(hour=21, minute=0, timezone=tz),
        args=("day", True, None),
        name="daily_pnl",
    )

    # Еженедельно в воскресенье в 21:00
    scheduler.add_job(
        _send_report,
        CronTrigger(day_of_week="sun", hour=21, minute=0, timezone=tz),
        args=("week", True, None),
        name="weekly_pnl",
    )

    # Ежемесячно в последний день месяца в 21:00
    scheduler.add_job(
        _send_report,
        CronTrigger(day="last", hour=21, minute=0, timezone=tz),
        args=("month", True, None),
        name="monthly_pnl",
    )

    # Sync всех символов — каждые 15 минут (200+ запросов, ~2–3 мин)
    scheduler.add_job(
        sync_trades_once,
        CronTrigger(minute="*/15", timezone=tz),
        name="sync_trades",
    )


async def main() -> None:
    # Меню команд: для всех личных чатов и для русского языка
    commands = [
        BotCommand(command="pnl_today", description="Отчёт за сегодня"),
        BotCommand(command="pnl_week", description="Отчёт за неделю"),
        BotCommand(command="pnl_month", description="Отчёт за месяц"),
        BotCommand(command="pnl_range", description="Отчёт за период (DD.MM DD.MM)"),
    ]
    await bot.set_my_commands(commands, scope=BotCommandScopeAllPrivateChats())
    await bot.set_my_commands(commands, scope=BotCommandScopeAllPrivateChats(), language_code="ru")

    scheduler = AsyncIOScheduler()
    _setup_scheduler(scheduler)
    scheduler.start()

    # polling_timeout=30 — меньше Request timeout от Telegram
    await dp.start_polling(bot, polling_timeout=30)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s %(message)s")
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass  # Ctrl+C — нормальное завершение, без traceback

