"""
DataSource module для работы с пространственными данными.

Поддерживает:
- SQLite с SpatiaLite расширением
- Connection pooling
- Автоматическая загрузка mod_spatialite.dll/so/dylib из папки mod_spatialite/
"""

from .spatialite_loader import (
    configure_dll_search_path,
    load_spatialite,
    verify_spatialite,
    get_spatialite_dir,
    get_extension_load_path,
)

__all__ = [
    "configure_dll_search_path",
    "load_spatialite",
    "verify_spatialite",
    "get_spatialite_dir",
    "get_extension_load_path",
]
