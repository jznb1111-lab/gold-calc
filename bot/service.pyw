"""
Фоновый запуск бота без окна консоли (Windows: pythonw.exe service.pyw).

  * пишет журнал в bot.log рядом с этим файлом (до 3 файлов по 1 МБ);
  * если бот упал — перезапускает его через 15 секунд;
  * не даёт запустить вторую копию (две копии мешают друг другу в Telegram).
"""
import asyncio
import logging
import socket
import sys
import time
from logging.handlers import RotatingFileHandler
from pathlib import Path

HERE = Path(__file__).resolve().parent
LOG_FILE = HERE / "bot.log"
LOCK_PORT = 47613  # локальный порт-«замок» для защиты от второй копии


def setup_logging() -> None:
    handler = RotatingFileHandler(LOG_FILE, maxBytes=1_000_000, backupCount=2, encoding="utf-8")
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
    root = logging.getLogger()
    root.handlers[:] = [handler]
    root.setLevel(logging.INFO)
    # pythonw не имеет консоли: всё, что попадёт в stdout/stderr, тоже пишем в журнал
    class _ToLog:
        def __init__(self, level): self.level = level
        def write(self, msg):
            msg = msg.strip()
            if msg:
                logging.getLogger("stdout").log(self.level, msg)
        def flush(self): pass
    sys.stdout = _ToLog(logging.INFO)
    sys.stderr = _ToLog(logging.ERROR)


def single_instance() -> socket.socket | None:
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        s.bind(("127.0.0.1", LOCK_PORT))
        s.listen(1)
        return s
    except OSError:
        return None


def main() -> None:
    setup_logging()
    log = logging.getLogger("service")
    lock = single_instance()
    if lock is None:
        log.warning("Бот уже запущен — вторая копия не нужна, выходим.")
        return

    sys.path.insert(0, str(HERE))
    import bot  # noqa: E402

    log.info("=== Сервис запущен ===")
    while True:
        try:
            asyncio.run(bot.main())
            log.warning("Бот остановился. Перезапуск через 15 секунд.")
        except SystemExit as e:
            # Ошибка настроек (.env) — перезапуск не поможет, пока её не исправят
            log.error("Бот не запущен: %s", e)
            log.error("Исправьте bot/.env и запустите бота заново (start_bot.bat).")
            return
        except Exception:
            log.exception("Бот упал. Перезапуск через 15 секунд.")
        time.sleep(15)


if __name__ == "__main__":
    main()
