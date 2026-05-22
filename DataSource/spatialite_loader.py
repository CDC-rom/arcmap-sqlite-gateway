"""
Загрузка SpatiaLite из каталога mod_spatialite в корне проекта.
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
    if sys.platform == "win32":
        return ("mod_spatialite.dll",)
    if sys.platform == "darwin":
        return ("mod_spatialite.dylib", "mod_spatialite.so")
    return ("mod_spatialite.so",)


def _directory_has_extension(directory: Path) -> bool:
    return any((directory / name).is_file() for name in _extension_names())


def get_spatialite_dir() -> Optional[Path]:
    """Каталог с mod_spatialite и зависимыми библиотеками."""
    global _spatialite_dir
    if _spatialite_dir is not None:
        return _spatialite_dir

    candidates = []  # type: list[Path]
    env_dir = os.environ.get("SPATIALITE_DIR")
    if env_dir:
        candidates.append(Path(env_dir))
    candidates.extend((_PROJECT_ROOT / "mod_spatialite", Path.cwd() / "mod_spatialite"))

    for path in candidates:
        if path.is_dir() and _directory_has_extension(path):
            _spatialite_dir = path.resolve()
            return _spatialite_dir

    return None


def get_extension_load_path() -> Optional[Path]:
    """Путь для load_extension (без расширения .dll/.so)."""
    global _extension_path
    if _extension_path is not None:
        return _extension_path

    directory = get_spatialite_dir()
    if directory is None:
        return None

    for name in _extension_names():
        if (directory / name).is_file():
            _extension_path = directory / Path(name).stem
            return _extension_path

    return None


def configure_dll_search_path() -> bool:
    """Регистрирует mod_spatialite в путях поиска нативных библиотек."""
    global _dll_configured
    if _dll_configured:
        return get_spatialite_dir() is not None

    _dll_configured = True
    directory = get_spatialite_dir()
    if directory is None:
        logger.warning(
            "Каталог mod_spatialite не найден (ожидается %s или переменная SPATIALITE_DIR)",
            _PROJECT_ROOT / "mod_spatialite",
        )
        return False

    dir_str = str(directory)
    if sys.platform == "win32" and hasattr(os, "add_dll_directory"):
        try:
            os.add_dll_directory(dir_str)
        except OSError as exc:
            logger.warning("add_dll_directory(%s): %s", dir_str, exc)

    path_var = "PATH" if sys.platform == "win32" else "LD_LIBRARY_PATH"
    current = os.environ.get(path_var, "")
    if dir_str not in current.split(os.pathsep):
        os.environ[path_var] = dir_str + (os.pathsep + current if current else "")

    if sys.platform != "win32":
        current_path = os.environ.get("PATH", "")
        if dir_str not in current_path.split(os.pathsep):
            os.environ["PATH"] = dir_str + (os.pathsep + current_path if current_path else "")

    logger.debug("SpatiaLite: каталог библиотек %s", directory)
    return True


def load_spatialite(conn: sqlite3.Connection) -> bool:
    """Загружает расширение SpatiaLite в соединение SQLite."""
    if not configure_dll_search_path():
        return False

    ext_path = get_extension_load_path()
    if ext_path is None:
        return False

    ext_str = str(ext_path)
    try:
        conn.enable_load_extension(True)
    except AttributeError:
        logger.error("Сборка SQLite без поддержки load_extension")
        return False

    try:
        conn.load_extension(ext_str)
        logger.debug("SpatiaLite загружен из %s", ext_str)
        return True
    except sqlite3.OperationalError:
        pass

    try:
        conn.execute(f"SELECT load_extension('{ext_path.as_posix()}')")
        logger.debug("SpatiaLite загружен через SQL из %s", ext_str)
        return True
    except sqlite3.Error as exc:
        logger.warning("Не удалось загрузить SpatiaLite из %s: %s", ext_str, exc)
        return False
