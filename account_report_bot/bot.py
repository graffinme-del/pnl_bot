from __future__ import annotations

import asyncio
import logging
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
    report = build_pnl_report(period=period, now=now)

    # Графики только для недели и месяца (по агрегированным позициям)
    images: list[Path] = []
    if period in ("week", "month") and report.positions:
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

    # При ручном вызове — удалить текст и картинки через 2 минуты (в фоне)
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

