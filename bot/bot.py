"""
Telegram-бот для калькулятора XAUUSD (Mini App).

  * /start — приветствие + кнопки: «Открыть калькулятор», «Открыть счёт», «Наш канал».
  * Кнопка меню «Калькулятор» слева от поля ввода.
  * База пользователей в SQLite (файл users.db рядом с ботом):
    кто пришёл, когда, откуда (ссылка t.me/БОТ?start=метка), кто заблокировал бота.
  * Для админов (ADMIN_IDS в .env):
      /stats      — статистика пользователей
      /broadcast  — ответьте этой командой на любое сообщение (текст, фото, видео…),
                    бот спросит подтверждение и разошлёт его всем пользователям.
  * /myid — показать свой Telegram ID (работает для всех).

Запуск:
  pip install -r requirements.txt
  заполнить .env (см. .env.example)
  python bot.py
"""
import asyncio
import logging
import os
import re
import sqlite3
from contextlib import closing
from datetime import datetime, timedelta, timezone
from pathlib import Path

from aiogram import Bot, Dispatcher, F
from aiogram.client.default import DefaultBotProperties
from aiogram.exceptions import TelegramBadRequest, TelegramForbiddenError, TelegramRetryAfter
from aiogram.filters import Command, CommandObject, CommandStart
from aiogram.types import (
    BotCommand,
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    MenuButtonWebApp,
    Message,
    TelegramObject,
    WebAppInfo,
)

try:
    from dotenv import load_dotenv
    load_dotenv(Path(__file__).with_name(".env"))
except ImportError:
    pass

BOT_TOKEN = os.getenv("BOT_TOKEN", "").strip()
WEBAPP_URL = os.getenv("WEBAPP_URL", "").strip()
ADMIN_IDS = {int(x) for x in re.findall(r"\d+", os.getenv("ADMIN_IDS", ""))}
DB_PATH = Path(os.getenv("DB_PATH") or Path(__file__).with_name("users.db"))

REF_LINK = "https://direct.group-fxpro.global/ru/partner/uyrLYKbo"
CHANNEL_LINK = "https://t.me/+sdNSmdt8qmphYzgy"

WELCOME = (
    "👋 Привет! Это <b>калькулятор XAUUSD (золото)</b>.\n\n"
    "Внутри четыре инструмента:\n"
    "• <b>Лот</b> — размер лота по балансу, % риска и стопу\n"
    "• <b>Позиция</b> — лот по сумме риска, цене входа, стопа и тейка (+ риск/прибыль)\n"
    "• <b>Маржа</b> — сколько денег нужно на сделку при вашем плече\n"
    "• <b>Пипс</b> — сколько стоит движение цены для любого лота\n\n"
    "Текущая цена золота подставляется автоматически.\n"
    "Нажмите «🧮 Открыть калькулятор» 👇"
)

log = logging.getLogger("goldcalc")


# ======================= База данных =======================
def db() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def db_init() -> None:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    with closing(db()) as c, c:
        c.execute("""
            CREATE TABLE IF NOT EXISTS users (
                user_id     INTEGER PRIMARY KEY,
                username    TEXT,
                first_name  TEXT,
                lang        TEXT,
                source      TEXT,
                joined_at   TEXT NOT NULL,
                last_seen   TEXT NOT NULL,
                blocked     INTEGER NOT NULL DEFAULT 0
            )""")


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def upsert_user(u) -> None:
    with closing(db()) as c, c:
        c.execute("""
            INSERT INTO users (user_id, username, first_name, lang, source, joined_at, last_seen, blocked)
            VALUES (?, ?, ?, ?, NULL, ?, ?, 0)
            ON CONFLICT(user_id) DO UPDATE SET
                username = excluded.username,
                first_name = excluded.first_name,
                lang = excluded.lang,
                last_seen = excluded.last_seen,
                blocked = 0
        """, (u.id, u.username, u.first_name, u.language_code, now(), now()))


def set_source_if_new(user_id: int, source: str) -> None:
    with closing(db()) as c, c:
        c.execute("UPDATE users SET source = ? WHERE user_id = ? AND source IS NULL", (source, user_id))


def set_blocked(user_id: int) -> None:
    with closing(db()) as c, c:
        c.execute("UPDATE users SET blocked = 1 WHERE user_id = ?", (user_id,))


def active_user_ids() -> list[int]:
    with closing(db()) as c:
        return [r[0] for r in c.execute("SELECT user_id FROM users WHERE blocked = 0")]


def stats_text() -> str:
    day = (datetime.now(timezone.utc) - timedelta(days=1)).isoformat(timespec="seconds")
    week = (datetime.now(timezone.utc) - timedelta(days=7)).isoformat(timespec="seconds")
    with closing(db()) as c:
        def one(q, *a):
            return c.execute(q, a).fetchone()[0]
        total = one("SELECT COUNT(*) FROM users")
        active = one("SELECT COUNT(*) FROM users WHERE blocked = 0")
        new_day = one("SELECT COUNT(*) FROM users WHERE joined_at >= ?", day)
        new_week = one("SELECT COUNT(*) FROM users WHERE joined_at >= ?", week)
        seen_week = one("SELECT COUNT(*) FROM users WHERE last_seen >= ?", week)
        sources = c.execute("""
            SELECT COALESCE(source, 'без метки') AS s, COUNT(*) AS n FROM users
            GROUP BY s ORDER BY n DESC LIMIT 10""").fetchall()
    lines = [
        "📊 <b>Статистика бота</b>",
        f"Всего пользователей: <b>{total}</b>",
        f"Не заблокировали бота: <b>{active}</b>",
        f"Новых за 24 часа: <b>{new_day}</b>",
        f"Новых за 7 дней: <b>{new_week}</b>",
        f"Заходили за 7 дней: <b>{seen_week}</b>",
    ]
    if sources:
        lines.append("\n<b>Откуда пришли</b> (метка из ссылки t.me/бот?start=метка):")
        lines += [f"• {r['s']}: {r['n']}" for r in sources]
    return "\n".join(lines)


# ======================= Клавиатуры =======================
def main_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🧮 Открыть калькулятор", web_app=WebAppInfo(url=WEBAPP_URL))],
        [InlineKeyboardButton(text="💼 Открыть счёт", url=REF_LINK)],
        [InlineKeyboardButton(text="📢 Наш Telegram-канал", url=CHANNEL_LINK)],
    ])


# ======================= Обработчики =======================
dp = Dispatcher()


@dp.update.outer_middleware()
async def remember_user(handler, event: TelegramObject, data: dict):
    """Каждого, кто пишет боту или жмёт кнопки, записываем/обновляем в базе."""
    user = data.get("event_from_user")
    if user and not user.is_bot:
        try:
            upsert_user(user)
        except Exception:
            log.exception("db error")
    return await handler(event, data)


@dp.message(CommandStart())
async def on_start(message: Message, command: CommandObject) -> None:
    # Метка источника: t.me/БОТ?start=channel → source = "channel" (записывается один раз)
    src = re.sub(r"[^\w-]", "", (command.args or ""))[:64]
    if src:
        set_source_if_new(message.from_user.id, src)
    await message.answer(WELCOME, reply_markup=main_keyboard())


@dp.message(Command("account"))
async def on_account(message: Message) -> None:
    await message.answer(
        "💼 Откройте счёт по ссылке — это займёт несколько минут:",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="Открыть счёт", url=REF_LINK)]]),
    )


@dp.message(Command("channel"))
async def on_channel(message: Message) -> None:
    await message.answer(
        "📢 Подписывайтесь на наш канал:",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="Перейти в канал", url=CHANNEL_LINK)]]),
    )


@dp.message(Command("myid"))
async def on_myid(message: Message) -> None:
    await message.answer(f"Ваш Telegram ID: <code>{message.from_user.id}</code>")


# ---------- Админские команды ----------
def is_admin(obj) -> bool:
    return bool(obj.from_user) and obj.from_user.id in ADMIN_IDS


@dp.message(Command("stats"), F.func(is_admin))
async def on_stats(message: Message) -> None:
    await message.answer(stats_text())


# Ожидающие подтверждения рассылки: admin_id -> (chat_id, message_id)
pending_broadcasts: dict[int, tuple[int, int]] = {}
broadcast_running = False


@dp.message(Command("broadcast"), F.func(is_admin))
async def on_broadcast(message: Message) -> None:
    src = message.reply_to_message
    if not src:
        await message.answer(
            "Как сделать рассылку:\n"
            "1. Отправьте боту сообщение, которое хотите разослать (текст, фото, видео — что угодно).\n"
            "2. Ответьте на него (Reply) командой /broadcast.\n"
            "3. Подтвердите отправку кнопкой."
        )
        return
    n = len(active_user_ids())
    pending_broadcasts[message.from_user.id] = (src.chat.id, src.message_id)
    await message.answer(
        f"Разослать это сообщение <b>{n}</b> пользователям?",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[[
            InlineKeyboardButton(text=f"✅ Отправить ({n})", callback_data="bc:go"),
            InlineKeyboardButton(text="✖️ Отмена", callback_data="bc:cancel"),
        ]]),
    )


@dp.callback_query(F.data.startswith("bc:"), F.func(is_admin))
async def on_broadcast_confirm(cb: CallbackQuery, bot: Bot) -> None:
    global broadcast_running
    job = pending_broadcasts.pop(cb.from_user.id, None)
    if cb.data == "bc:cancel":
        await cb.message.edit_text("Рассылка отменена.")
        await cb.answer()
        return
    if not job:
        await cb.message.edit_text("Нечего отправлять — повторите /broadcast.")
        await cb.answer()
        return
    if broadcast_running:
        await cb.answer("Уже идёт другая рассылка, подождите.", show_alert=True)
        return
    await cb.answer()
    broadcast_running = True
    await cb.message.edit_text("⏳ Рассылка началась…")
    sent = failed = blocked = 0
    try:
        for uid in active_user_ids():
            for _ in range(3):
                try:
                    await bot.copy_message(chat_id=uid, from_chat_id=job[0], message_id=job[1])
                    sent += 1
                    break
                except TelegramRetryAfter as e:
                    await asyncio.sleep(e.retry_after + 1)
                except TelegramForbiddenError:
                    set_blocked(uid)
                    blocked += 1
                    break
                except TelegramBadRequest:
                    failed += 1
                    break
            await asyncio.sleep(0.05)  # ~20 сообщений в секунду — в рамках лимитов Telegram
    finally:
        broadcast_running = False
    await cb.message.answer(
        f"✅ Рассылка завершена.\nДоставлено: <b>{sent}</b>\n"
        f"Заблокировали бота: <b>{blocked}</b>\nОшибок: <b>{failed}</b>"
    )


@dp.message()
async def fallback(message: Message) -> None:
    await message.answer("Откройте калькулятор кнопкой ниже 👇", reply_markup=main_keyboard())


# ======================= Запуск =======================
async def main() -> None:
    if not BOT_TOKEN or not WEBAPP_URL.startswith("https://"):
        raise SystemExit("Укажите BOT_TOKEN и WEBAPP_URL (должен начинаться с https://) в файле .env")

    logging.basicConfig(level=logging.INFO)
    db_init()
    if not ADMIN_IDS:
        log.warning("ADMIN_IDS не задан — /stats и /broadcast недоступны. Узнайте свой ID командой /myid.")

    bot = Bot(BOT_TOKEN, default=DefaultBotProperties(parse_mode="HTML"))
    await bot.set_chat_menu_button(
        menu_button=MenuButtonWebApp(text="Калькулятор", web_app=WebAppInfo(url=WEBAPP_URL))
    )
    await bot.set_my_commands([
        BotCommand(command="start", description="Открыть калькулятор"),
        BotCommand(command="account", description="Открыть счёт"),
        BotCommand(command="channel", description="Наш Telegram-канал"),
    ])
    # handle_as_tasks: рассылка идёт фоном, бот продолжает отвечать
    await dp.start_polling(bot, handle_as_tasks=True)


if __name__ == "__main__":
    asyncio.run(main())
