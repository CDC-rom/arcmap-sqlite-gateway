"""
Загрузка SpatiaLite из каталога mod_spatialite в корне проекта.
Поддерживает mod_spatialite.dll x64 для Windows и .so для Linux/macOS.
"""

import logging
import os
import sys
import sqlite3
from pathlib import Path
from typing import Optional, Tuple

logger = logging.getLogger(__name__)

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
_spatialite_dir: Optional[Path] = None
_extension_path: Optional[Path] = None
_dll_configured = False


def _extension_names() -> Tuple[str, ...]:
    """Возвращает возможные имена расширения SpatiaLite для текущей платформы."""
    if sys.platform == "win32":
        # Windows: поддержка x64 и x86
        return ("mod_spatialite.dll", "mod_spatialite_x64.dll", "mod_spatialite_x86.dll")
    if sys.platform == "darwin":
        # macOS: поддержка .dylib и .so
        return ("mod_spatialite.dylib", "mod_spatialite.so")
    # Linux и другие Unix-системы
    return ("mod_spatialite.so",)


def _get_platform_arch() -> str:
    """Возвращает текущую архитектуру платформы."""
    import struct
    bits = struct.calcsize("P") * 8
    return "x64" if bits == 64 else "x86"


def _directory_has_extension(directory: Path) -> bool:
    """Проверяет наличие расширения SpatiaLite в директории."""
    return any((directory / name).is_file() for name in _extension_names())


def get_spatialite_dir() -> Optional[Path]:
    """
    Возвращает путь к каталогу с mod_spatialite и зависимыми библиотеками.
    
    Порядок поиска:
    1. Переменная окружения SPATIALITE_DIR
    2. Папка {PROJECT_ROOT}/mod_spatialite (рекомендуется)
    3. Папка {CWD}/mod_spatialite
    """
    global _spatialite_dir
    if _spatialite_dir is not None:
        return _spatialite_dir

    candidates = []  # type: list[Path]
    
    # 1. Проверяем переменную окружения
    env_dir = os.environ.get("SPATIALITE_DIR")
    if env_dir:
        candidates.append(Path(env_dir))
    
    # 2. Проверяем папку в корне проекта
    candidates.append(_PROJECT_ROOT / "mod_spatialite")
    
    # 3. Проверяем текущую рабочую директорию
    candidates.append(Path.cwd() / "mod_spatialite")
    
    for path in candidates:
        if path.is_dir() and _directory_has_extension(path):
            _spatialite_dir = path.resolve()
            logger.info(
                "Найдена директория SpatiaLite: %s (архитектура: %s)",
                _spatialite_dir,
                _get_platform_arch()
            )
            return _spatialite_dir

    return None


def get_extension_load_path() -> Optional[Path]:
    """
    Возвращает путь для load_extension (без расширения .dll/.so).
    """
    global _extension_path
    if _extension_path is not None:
        return _extension_path

    directory = get_spatialite_dir()
    if directory is None:
        return None

    for name in _extension_names():
        file_path = directory / name
        if file_path.is_file():
            _extension_path = directory / Path(name).stem
            logger.debug("Путь расширения: %s", _extension_path)
            return _extension_path

    return None


def configure_dll_search_path() -> bool:
    """
    Регистрирует mod_spatialite в путях поиска нативных библиотек.
    
    Для Windows:
    - Использует os.add_dll_directory() (Python 3.8+)
    - Обновляет переменную PATH
    
    Для Linux/macOS:
    - Обновляет LD_LIBRARY_PATH и PATH
    """
    global _dll_configured
    if _dll_configured:
        return get_spatialite_dir() is not None

    _dll_configured = True
    directory = get_spatialite_dir()
    if directory is None:
        logger.warning(
            "⚠️  Каталог mod_spatialite не найден\n"
            "   Ожидается: %s\n"
            "   Или установите переменную: SPATIALITE_DIR=%s\n"
            "   Документация: %s/mod_spatialite/README.md",
            _PROJECT_ROOT / "mod_spatialite",
            _PROJECT_ROOT / "mod_spatialite",
            _PROJECT_ROOT
        )
        return False

    dir_str = str(directory)
    
    # Windows: используем os.add_dll_directory (Python 3.8+)
    if sys.platform == "win32":
        if hasattr(os, "add_dll_directory"):
            try:
                os.add_dll_directory(dir_str)
                logger.debug("✓ add_dll_directory: %s", dir_str)
            except OSError as exc:
                logger.warning("✗ add_dll_directory(%s): %s", dir_str, exc)
        
        # Всегда обновляем PATH как резервный вариант
        path_var = "PATH"
        current = os.environ.get(path_var, "")
        if dir_str not in current.split(os.pathsep):
            os.environ[path_var] = dir_str + (os.pathsep + current if current else "")
            logger.debug("✓ PATH: %s", dir_str)
    else:
        # Linux/macOS: обновляем LD_LIBRARY_PATH
        path_var = "LD_LIBRARY_PATH"
        current = os.environ.get(path_var, "")
        if dir_str not in current.split(os.pathsep):
            os.environ[path_var] = dir_str + (os.pathsep + current if current else "")
            logger.debug("✓ LD_LIBRARY_PATH: %s", dir_str)
        
        # Обновляем PATH
        current_path = os.environ.get("PATH", "")
        if dir_str not in current_path.split(os.pathsep):
            os.environ["PATH"] = dir_str + (os.pathsep + current_path if current_path else "")
            logger.debug("✓ PATH: %s", dir_str)

    logger.info("✓ SpatiaLite: библиотеки найдены в %s", directory)
    return True


def load_spatialite(conn: sqlite3.Connection) -> bool:
    """
    Загружает расширение SpatiaLite в соединение SQLite.
    
    Returns:
        True если успешно загружено, False в противном случае
    """
    if not configure_dll_search_path():
        logger.error("✗ SpatiaLite: не удалось настроить пути поиска")
        return False

    ext_path = get_extension_load_path()
    if ext_path is None:
        logger.error("✗ SpatiaLite: расширение не найдено")
        return False

    ext_str = str(ext_path)
    
    # Проверяем поддержку load_extension
    try:
        conn.enable_load_extension(True)
    except AttributeError:
        logger.error("✗ SQLite скомпилирован без поддержки load_extension")
        return False

    # Вариант 1: Использование conn.load_extension()
    try:
        conn.load_extension(ext_str)
        logger.info("✓ SpatiaLite загружен из %s (метод: load_extension)", ext_str)
        return True
    except sqlite3.OperationalError as e:
        logger.debug("✗ conn.load_extension() не сработал: %s", e)

    # Вариант 2: Использование SQL SELECT load_extension()
    try:
        conn.execute(f"SELECT load_extension('{ext_path.as_posix()}')")
        logger.info("✓ SpatiaLite загружен из %s (метод: SQL)", ext_str)
        return True
    except sqlite3.Error as exc:
        logger.error("✗ Не удалось загрузить SpatiaLite из %s: %s", ext_str, exc)
        return False


def verify_spatialite(conn: sqlite3.Connection) -> bool:
    """
    Проверяет, что SpatiaLite корректно загружен и функционирует.
    
    Returns:
        True если SpatiaLite готов к использованию
    """
    try:
        # Пытаемся выполнить базовый запрос SpatiaLite
        cursor = conn.execute("SELECT spatialite_version()")
        version = cursor.fetchone()[0]
        logger.info("✓ SpatiaLite версия: %s", version)
        return True
    except sqlite3.OperationalError as e:
        logger.error("✗ SpatiaLite не загружен или не функционирует: %s", e)
        return False
    except Exception as e:
        logger.error("✗ Ошибка при проверке SpatiaLite: %s", e)
        return False
