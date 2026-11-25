"""
Фоновый запуск бота без окна консоли (Windows: pythonw.exe service.pyw).

  * пишет журнал в bot.log рядом с этим файлом (до 3 файлов по 1 МБ);
  * если бот упал — перезапускает его через 15 секунд;
  * не даёт запустить вторую копию (две копии мешают друг другу в Telegram).
"""
import asyncio
import logging
import sys
import time
from logging.handlers import RotatingFileHandler
from pathlib import Path

HERE = Path(__file__).resolve().parent
LOG_FILE = HERE / "bot.log"
LOCK_NAME = "GoldCalcBot_single_instance"


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


def single_instance():
    """Защита от второй копии. Windows: именованный мьютекс; Linux/Mac: блокировка файла.
    Возвращает объект-замок (держать до выхода) или None, если копия уже работает."""
    if sys.platform == "win32":
        import ctypes
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel32.CreateMutexW.restype = ctypes.c_void_p
        handle = kernel32.CreateMutexW(None, False, "Local\\" + LOCK_NAME)
        if not handle:
            logging.getLogger("service").warning("Не удалось создать мьютекс (%s) — запускаемся без проверки.", ctypes.get_last_error())
            return True
        if ctypes.get_last_error() == 183:  # ERROR_ALREADY_EXISTS
            kernel32.CloseHandle(ctypes.c_void_p(handle))
            return None
        return handle
    import fcntl
    f = open(HERE / ".service.lock", "w")
    try:
        fcntl.flock(f, fcntl.LOCK_EX | fcntl.LOCK_NB)
        return f
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
