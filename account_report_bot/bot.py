from __future__ import annotations

import asyncio
from datetime import datetime, time as dtime
from pathlib import Path

from aiogram import Bot, Dispatcher, F
from aiogram.client.default import DefaultBotProperties
from aiogram.types import BotCommand, BotCommandScopeAllPrivateChats, Message
from aiogram.utils.keyboard import ReplyKeyboardMarkup, KeyboardButton
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


def _main_keyboard() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="/pnl_today")],
            [KeyboardButton(text="/pnl_week"), KeyboardButton(text="/pnl_month")],
        ],
        resize_keyboard=True,
    )


async def _send_report(
    period: str,
    auto: bool,
) -> None:
    now = datetime.now(tz=SETTINGS.timezone)
    report = build_pnl_report(period=period, now=now)

    # Графики только для недели и месяца
    images: list[Path] = []
    if period in ("week", "month") and report.trades:
        charts_dir = Path("charts") / period
        equity_path = charts_dir / "equity.png"
        pie_path = charts_dir / "long_short.png"
        hist_path = charts_dir / "hist.png"
        plot_equity_curve(report.trades, equity_path)
        plot_long_short_pie(report.trades, pie_path)
        plot_pnl_histogram(report.trades, hist_path)
        images = [equity_path, pie_path, hist_path]

    chat_id = SETTINGS.report_chat_id
    msg = await bot.send_message(chat_id, report.text, reply_markup=_main_keyboard())

    # Принудительно вызванные команды — автоудаление через 30 секунд
    if not auto:
        await asyncio.sleep(30)
        try:
            await bot.delete_message(chat_id, msg.message_id)
        except Exception:
            pass

    # Отправка картинок (они не удаляются даже для auto=False)
    for img_path in images:
        if img_path.exists():
            with img_path.open("rb") as f:
                await bot.send_photo(chat_id, f)


@dp.message(F.text == "/pnl_today")
async def cmd_pnl_today(message: Message) -> None:
    await _send_report("day", auto=False)


@dp.message(F.text == "/pnl_week")
async def cmd_pnl_week(message: Message) -> None:
    await _send_report("week", auto=False)


@dp.message(F.text == "/pnl_month")
async def cmd_pnl_month(message: Message) -> None:
    await _send_report("month", auto=False)


def _setup_scheduler(scheduler: AsyncIOScheduler) -> None:
    tz = SETTINGS.timezone

    # Ежедневно в 21:00
    scheduler.add_job(
        lambda: _send_report("day", auto=True),
        CronTrigger(hour=21, minute=0, timezone=tz),
        name="daily_pnl",
    )

    # Еженедельно в воскресенье в 21:00
    scheduler.add_job(
        lambda: _send_report("week", auto=True),
        CronTrigger(day_of_week="sun", hour=21, minute=0, timezone=tz),
        name="weekly_pnl",
    )

    # Ежемесячно в последний день месяца в 21:00
    scheduler.add_job(
        lambda: _send_report("month", auto=True),
        CronTrigger(day="last", hour=21, minute=0, timezone=tz),
        name="monthly_pnl",
    )

    # Периодический sync сделок, например каждые 5 минут
    scheduler.add_job(
        sync_trades_once,
        CronTrigger(minute="*/5", timezone=tz),
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

    await dp.start_polling(bot)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass  # Ctrl+C — нормальное завершение, без traceback

