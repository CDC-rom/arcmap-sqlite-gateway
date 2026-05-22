__author__    = "MetaCarta"
__copyright__ = "Copyright (c) 2006-2008 MetaCarta"
__license__   = "Clear BSD"
__version__   = "$Id: SQLite.py 449 2008-03-29 01:34:04Z brentp $"

import re
import logging
import sqlite3
import json
import traceback
from typing import List, Dict, Any, Optional
from DataSource import DataSource
from Feature import Feature
from .connection_pool import get_pool, PoolConfig

# Настройка логирования
logger = logging.getLogger(__name__)

class SQLite(DataSource):
    wkt_linestring_match = re.compile(r'\(([^()]+)\)')

    def __init__(self, name: str, srid: int = 4326, order: Optional[str] = None, 
                 writable: bool = True, **args: Any):
        logger.debug(f"SQLite: переданные аргументы: {args}")
        DataSource.__init__(self, name, **args)
        logger.debug(f"SQLite: name = {name}, args = {args}")
        self.table = args.get("layer", name)  # Используем значение из layer, если оно есть
        logger.debug(f"SQLite: итоговое имя слоя = {self.table}")
        self.name = self.table  # Добавляем это, чтобы имя слоя соответствовало имени таблицы
        self.fid_col  = args.get("fid_col", "feature_id")
        self.geom_col = args.get("geom_col", "wkt_geometry")
        self.order    = order
        self.srid     = srid
        self.dsn      = args.get("dsn") or args.get("file")
        self.writable = writable
        self.mode     = None

        logger.debug(f"SQLite: dsn = {self.dsn}")
        if not self.dsn:
            raise ValueError("Не указан путь к SQLite базе данных (dsn). Проверьте конфигурацию.")

        # Инициализируем пул соединений
        pool_config = PoolConfig(
            max_connections=int(args.get("max_connections", 10)),
            timeout=int(args.get("timeout", 30)),
            check_interval=int(args.get("check_interval", 300)),
            max_lifetime=int(args.get("max_lifetime", 3600))
        )
        self.pool = get_pool(self.dsn, pool_config)

        # Инициализируем схему базы данных
        self._initialize_schema()

    def _initialize_schema(self):
        """Инициализирует схему базы данных при первом запуске"""
        with self.pool.get_connection() as conn:
            c = conn.cursor()

            # Вывод версии SpatiaLite для отладки
            try:
                c.execute("SELECT spatialite_version();")
                version = c.fetchone()
                logger.debug(f"SpatiaLite версия: {version}")
            except sqlite3.OperationalError as e:
                logger.error(f"Не удалось получить версию SpatiaLite: {e}")

            # Проверяем, какие таблицы есть в БД
            c.execute("SELECT name FROM sqlite_master WHERE type='table'")
            tables = [row[0].lower() for row in c.fetchall()]
            logger.debug(f"Найденные таблицы в базе: {tables}")
        
            if self.table.lower() not in tables:
                logger.debug(f"Таблица {self.table} не найдена, создаём схему...")
                c.executescript(self.schema())
                self.mode = "two_tables"
            else:
                if (self.table + "_attrs").lower() in tables:
                    self.mode = "two_tables"
                    logger.debug(f"Используется режим с двумя таблицами (найдена таблица {(self.table + '_attrs').lower()}).")
                else:
                    self.mode = "one_table"
                    logger.debug("Используется режим с одной таблицей.")

    def _sqlite_to_esri_type(self, sqlite_type: str) -> str:
        """
        Конвертирует SQLite тип данных в ESRI ArcGIS тип.
        
        Args:
            sqlite_type: Тип данных из SQLite (например, INTEGER, TEXT, REAL)
            
        Returns:
            ESRI тип данных (esriFieldTypeInteger, esriFieldTypeString, и т.д.)
        """
        if not sqlite_type:
            return "esriFieldTypeString"
            
        sqlite_type_upper = sqlite_type.upper().strip()
        
        # Интегральные типы
        if 'INT' in sqlite_type_upper:
            return "esriFieldTypeInteger"
        
        # Типы с плавающей точкой
        elif 'REAL' in sqlite_type_upper or 'FLOAT' in sqlite_type_upper or 'DOUBLE' in sqlite_type_upper:
            return "esriFieldTypeDouble"
        
        # Текстовые типы
        elif 'CHAR' in sqlite_type_upper or 'TEXT' in sqlite_type_upper or 'STRING' in sqlite_type_upper or 'VARCHAR' in sqlite_type_upper:
            return "esriFieldTypeString"
        
        # Бинарные данные
        elif 'BLOB' in sqlite_type_upper or 'BINARY' in sqlite_type_upper:
            return "esriFieldTypeBlob"
        
        # Дата/время
        elif 'DATE' in sqlite_type_upper or 'TIME' in sqlite_type_upper:
            return "esriFieldTypeDate"
        
        # По умолчанию - строка
        else:
            return "esriFieldTypeString"

    def get_fields(self) -> List[Dict[str, Any]]:
        """
        Получает информацию о полях таблицы из SpatiaLite.
        
        Returns:
            Список словарей с информацией о полях для SOAP сервера.
            Например: {
                'name': 'OBJECTID',
                'type': 'esriFieldTypeInteger',
                'alias': 'Object ID',
                'length': 10,
                'nullable': False,
                'editable': True,
                'is_geometry': False
            }
        """
        fields = []
        
        try:
            with self.pool.get_connection() as conn:
                cursor = conn.cursor()
                
                # Получаем информацию о столбцах таблицы
                cursor.execute(f"PRAGMA table_info(\"{self.table}\")")
                columns = cursor.fetchall()
                
                logger.debug(f"Столбцы таблицы {self.table}: {columns}")
                
                for col in columns:
                    # PRAGMA table_info возвращает: (cid, name, type, notnull, dflt_value, pk)
                    col_id, col_name, col_type, not_null, dflt_value, is_pk = col
                    
                    # Пропускаем служебные столбцы служебных таблиц
                    if col_name.lower() in ('xmin', 'ymin', 'xmax', 'ymax', 'date_created', 'date_modified'):
                        continue
                    
                    # Проверяем, является ли это геометрией
                    is_geometry = col_name.lower() == self.geom_col.lower()
                    
                    # Пропускаем геометрию - она будет обработана отдельно
                    if is_geometry:
                        continue
                    
                    # Пропускаем feature_id если это внутренний ID
                    if col_name.lower() == 'feature_id' and self.fid_col.lower() != 'feature_id':
                        continue
                    
                    # Определяем длину поля для текстовых типов
                    length = 255  # По умолчанию для строк
                    if 'VARCHAR' in col_type.upper():
                        # Пытаемся извлечь длину из типа (например VARCHAR(50))
                        import re
                        match = re.search(r'VARCHAR\s*\(\s*(\d+)\s*\)', col_type.upper())
                        if match:
                            length = int(match.group(1))
                    elif 'CHAR' in col_type.upper():
                        import re
                        match = re.search(r'CHAR\s*\(\s*(\d+)\s*\)', col_type.upper())
                        if match:
                            length = int(match.group(1))
                    
                    # Создаем инфо о поле
                    field_info = {
                        'name': col_name,
                        'type': self._sqlite_to_esri_type(col_type),
                        'alias': col_name,  # Используем имя как псевдоним
                        'length': length,
                        'nullable': not not_null,
                        'editable': True,  # По умолчанию все поля редактируемы
                        'is_geometry': False,
                        'required': is_pk  # PK поля требуются
                    }
                    
                    fields.append(field_info)
                
                # Добавляем информацию о геометрии, если есть
                # Для SpatiaLite проверяем geometry_columns
                try:
                    cursor.execute("""
                        SELECT geometry_type FROM geometry_columns 
                        WHERE f_table_name = ? AND f_geometry_column = ?
                    """, (self.table, self.geom_col))
                    geom_info = cursor.fetchone()
                    
                    if geom_info:
                        geom_type_code = geom_info[0]
                        geom_type_name = self._get_geometry_type_name(geom_type_code)
                        
                        # Добавляем поле SHAPE
                        shape_field = {
                            'name': 'SHAPE',
                            'type': 'esriFieldTypeGeometry',
                            'alias': 'Geometry',
                            'length': 0,
                            'nullable': True,
                            'editable': True,
                            'is_geometry': True,
                            'required': False,
                            'geometry_type': geom_type_name
                        }
                        fields.append(shape_field)
                except Exception as e:
                    logger.debug(f"Не удалось получить информацию о геометрии из geometry_columns: {e}")
                    # Добавляем SHAPE поле даже если нет информации в geometry_columns
                    shape_field = {
                        'name': 'SHAPE',
                        'type': 'esriFieldTypeGeometry',
                        'alias': 'Geometry',
                        'length': 0,
                        'nullable': True,
                        'editable': True,
                        'is_geometry': True,
                        'required': False,
                        'geometry_type': 'esriGeometryPolygon'  # По умолчанию
                    }
                    fields.append(shape_field)
                
                logger.debug(f"Получено полей: {len(fields)}")
                
        except sqlite3.Error as e:
            logger.error(f"Ошибка при получении полей таблицы {self.table}: {e}")
            traceback.print_exc()
        
        return fields

    def _get_geometry_type_name(self, geom_type_code: int) -> str:
        """
        Преобразует код типа геометрии SpatiaLite в название ESRI ArcGIS типа.
        
        Коды SpatiaLite:
        0: Geometry (неизвестный тип)
        1: Point
        2: LineString
        3: Polygon
        4: MultiPoint
        5: MultiLineString
        6: MultiPolygon
        7: GeometryCollection
        """
        geom_mapping = {
            1: "esriGeometryPoint",
            2: "esriGeometryPolyline",
            3: "esriGeometryPolygon",
            4: "esriGeometryMultipoint",
            5: "esriGeometryPolyline",
            6: "esriGeometryPolygon",
            7: "esriGeometryPolygon",  # По умолчанию
            0: "esriGeometryPolygon"   # По умолчанию
        }
        return geom_mapping.get(geom_type_code, "esriGeometryPolygon")

    def get_layers(self) -> List[str]:
        """Возвращает список таблиц с пространственными данными, указанных в конфигурации."""
        try:
            with self.pool.get_connection() as conn:
                cur = conn.cursor()

                # Если в конфигурации указан конкретный слой, сразу возвращаем его
                if hasattr(self, 'table') and self.table:
                    return [self.table]

                # Определяем, есть ли таблица geometry_columns (SpatiaLite) или gpkg_geometry_columns (GeoPackage)
                cur.execute("SELECT name FROM sqlite_master WHERE type='table' AND name IN ('geometry_columns', 'gpkg_geometry_columns')")
                spatial_tables = [row[0] for row in cur.fetchall()]

                if not spatial_tables:
                    logger.error("В базе данных нет таблицы geometry_columns или gpkg_geometry_columns.")
                    return []

                # Определяем правильный запрос для SpatiaLite или GeoPackage
                if 'geometry_columns' in spatial_tables:
                    query = "SELECT f_table_name FROM geometry_columns"
                else:
                    query = "SELECT table_name FROM gpkg_geometry_columns"

                cur.execute(query)
                layers = [row[0] for row in cur.fetchall()]

                return layers

        except sqlite3.Error as e:
            logger.error(f"Ошибка при получении списка пространственных таблиц: {e}")
            return []

    def close(self) -> None:
        """Закрывает соединение с базой (устаревший метод, оставлен для совместимости)."""
        logger.warning("SQLite.close() is deprecated. Use connection pool instead.")
        # Пул соединений управляется автоматически

    def commit(self) -> None:
        """Выполняет коммит транзакции (устаревший метод, оставлен для совместимости)."""
        if self.writable:
            logger.warning("SQLite.commit() is deprecated. Transactions are managed automatically by the connection pool.")

    def rollback(self) -> None:
        """Выполняет откат транзакции (устаревший метод, оставлен для совместимости)."""
        if self.writable:
            logger.warning("SQLite.rollback() is deprecated. Transactions are managed automatically by the connection pool.")

    def tables(self) -> List[str]:
        """Возвращает список всех таблиц в базе данных."""
        with self.pool.get_connection() as conn:
            c = conn.cursor()
            res = c.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
            return [r[0] for r in res]

    def from_wkt(self, geom_str: str) -> Any:
        """
        Преобразует строку GeoJSON (возвращаемую функцией AsGeoJSON) в объект Python.
        Если требуется работать с WKT, измените реализацию.
        """
        try:
            return json.loads(geom_str)
        except json.JSONDecodeError as e:
            logger.error(f"Ошибка при парсинге GeoJSON: {e}")
            return geom_str

    @staticmethod
    def get_layers_with_geometry(dsn: str) -> List[str]:
        """
        Функция для получения слоёв с геометрией из SQLite/SpatiaLite базы данных.
        """
        layers = []
        
        try:
            # Используем пул соединений для статического метода
            pool = get_pool(dsn)
            with pool.get_connection() as conn:
                cursor = conn.cursor()

                # Запрашиваем таблицы, которые имеют геометрические данные
                cursor.execute("""
                    SELECT table_name FROM geometry_columns
                    WHERE f_table_name IS NOT NULL
                """)
                rows = cursor.fetchall()

                # Добавляем каждый слой в список
                for row in rows:
                    layer_name = row[0]
                    layers.append(layer_name)
            
        except sqlite3.Error as e:
            logger.error(f"Ошибка при получении слоев с геометрией: {e}")
        
        return layers

    def select(self, action: Any) -> List[Feature]:
        """Выполняет SELECT запрос к базе данных."""
        features = []

        try:
            with self.pool.get_connection() as conn:
                cursor = conn.cursor()

                if self.mode == "two_tables":
                    sql = ("SELECT DISTINCT t.feature_id as fid, t.%s as geom FROM \"%s\" t, \"%s_attrs\" a "
                        "WHERE a.feature_id = t.feature_id") % (self.geom_col, self.table, self.table)
                    logger.debug(f"SQL Query (two_tables): {sql}")
                    cursor.execute(sql)
                    results = cursor.fetchall()
                    logger.debug(f"Результаты запроса (two_tables): {results}")
                
                    sql_attrs = "SELECT key, value FROM \"%s_attrs\" WHERE feature_id = ?" % self.table
                    for row in results:
                        try:
                            geom = self.from_wkt(row["geom"])
                        except Exception as e:
                            logger.warning(f"Ошибка при обработке геометрии: {e}")
                            continue
                        fid = row["fid"]
                        attrs = cursor.execute(sql_attrs, (fid,)).fetchall()
                        d = {attr[0]: attr[1] for attr in attrs}
                        features.append(Feature(fid, geom, d))
                else:
                    # Изменяем запрос, чтобы возвращались поля с именами, соответствующими конфигурации
                    sql = f'SELECT {self.fid_col} as {self.fid_col}, AsGeoJSON({self.geom_col}) as {self.geom_col} FROM "{self.table}"'
                    logger.debug(f"SQL Query (one_table): {sql}")
                    cursor.execute(sql)
                    results = cursor.fetchall()
                    logger.debug(f"Результаты запроса (one_table): {results}")
                    mandatory = {self.fid_col, "xmin", "ymin", "xmax", "ymax", "date_created", "date_modified", self.geom_col}
                    for row in results:
                        try:
                            geom = self.from_wkt(row[self.geom_col])
                        except Exception as e:
                            logger.error(f"Ошибка при преобразовании геометрии: {e}")
                            continue
                        fid = row[self.fid_col]
                        d = {key: row[key] for key in row.keys() if key not in mandatory}
                        features.append(Feature(fid, geom, d))
        
        except sqlite3.Error as e:
            logger.error(f"Ошибка при выполнении запроса: {e}")
            raise
    
        return features

    def create(self, action: Any) -> List[Feature]:
        """Создает новый объект в базе данных."""
        feature = action.feature
        bbox = feature.get_bbox()

        try:
            with self.pool.get_connection() as conn:
                cursor = conn.cursor()

                if self.mode == "two_tables":
                    sql = "INSERT INTO \"%s\" (%s, xmin, ymin, xmax, ymax) VALUES (?,?,?,?,?)" % (self.table, self.geom_col)
                    values = [self.to_wkt(feature.geometry)] + list(bbox)
                    cursor.execute(sql, values)
                    action.id = cursor.lastrowid

                    sql = "INSERT INTO \"%s_attrs\" (feature_id, key, value) VALUES (?, ?, ?)" % self.table
                    attrs = [(action.id, k, v) for k, v in feature.properties.items()]
                    cursor.executemany(sql, attrs)
                else:
                    columns = "wkt_geometry, xmin, ymin, xmax, ymax"
                    values = [self.to_wkt(feature.geometry)] + list(bbox)
                    sql = "INSERT INTO \"%s\" (%s) VALUES (?,?,?,?,?)" % (self.table, columns)
                    cursor.execute(sql, values)
                action.id = cursor.lastrowid

            return self.select(action)
        except sqlite3.Error as e:
            logger.error(f"Ошибка при создании объекта: {e}")
            raise

    def delete(self, action: Any) -> List[Feature]:
        """Удаляет объект из базы данных."""
        try:
            with self.pool.get_connection() as conn:
                cursor = conn.cursor()

                if self.mode == "two_tables":
                    cursor.execute("DELETE FROM \"%s\" WHERE %s = ?" % (self.table, self.fid_col), (action.id,))
                    cursor.execute("DELETE FROM \"%s_attrs\" WHERE feature_id = ?" % self.table, (action.id,))
                else:
                    cursor.execute("DELETE FROM \"%s\" WHERE %s = ?" % (self.table, self.fid_col), (action.id,))

            return []
        except sqlite3.Error as e:
            logger.error(f"Ошибка при удалении объекта: {e}")
            raise

    def update(self, action: Any) -> List[Feature]:
        """Обновляет объект в базе данных."""
        feature = action.feature
        bbox = feature.get_bbox()

        try:
            with self.pool.get_connection() as conn:
                cursor = conn.cursor()

                if self.mode == "two_tables":
                    sql = "UPDATE \"%s\" SET %s = ?, xmin = ?, ymin = ?, xmax = ?, ymax = ? WHERE %s = ?" % (self.table, self.geom_col, self.fid_col)
                    cursor.execute(sql, [self.to_wkt(feature.geometry)] + list(bbox) + [action.id])

                    sql = "UPDATE \"%s_attrs\" SET value = ? WHERE feature_id = ? AND key = ?" % self.table
                    for key, value in feature.properties.items():
                        cursor.execute(sql, (value, action.id, key))
                else:
                    update_fields = ["%s = ?" % self.geom_col] + ["xmin = ?", "ymin = ?", "xmax = ?", "ymax = ?"]
                    values = [self.to_wkt(feature.geometry)] + list(bbox)
                    sql = "UPDATE \"%s\" SET %s WHERE %s = ?" % (self.table, ", ".join(update_fields), self.fid_col)
                    cursor.execute(sql, values + [action.id])

            return self.select(action)
        except sqlite3.Error as e:
            logger.error(f"Ошибка при обновлении объекта: {e}")
            raise

    def schema(self) -> str:
        """Возвращает SQL схему для создания таблиц."""
        return f"""
        CREATE TABLE IF NOT EXISTS "{self.table}" (
            feature_id INTEGER PRIMARY KEY AUTOINCREMENT,
            {self.geom_col} TEXT,
            xmin REAL,
            ymin REAL,
            xmax REAL,
            ymax REAL
        );
        
        CREATE TABLE IF NOT EXISTS "{self.table}_attrs" (
            feature_id INTEGER,
            key TEXT,
            value TEXT,
            FOREIGN KEY (feature_id) REFERENCES "{self.table}" (feature_id)
        );
        
        CREATE INDEX IF NOT EXISTS idx_{self.table}_geom ON "{self.table}" ({self.geom_col});
        CREATE INDEX IF NOT EXISTS idx_{self.table}_bbox ON "{self.table}" (xmin, ymin, xmax, ymax);
        CREATE INDEX IF NOT EXISTS idx_{self.table}_attrs ON "{self.table}_attrs" (feature_id, key);
        """

    def to_wkt(self, geometry: Any) -> str:
        """Преобразует геометрию в WKT формат."""
        if isinstance(geometry, dict):
            # GeoJSON формат
            geom_type = geometry.get('type', '').upper()
            coordinates = geometry.get('coordinates', [])
            
            if geom_type == 'POINT':
                return f"POINT({coordinates[0]} {coordinates[1]})"
            elif geom_type == 'LINESTRING':
                coords_str = ', '.join([f"{coord[0]} {coord[1]}" for coord in coordinates])
                return f"LINESTRING({coords_str})"
            elif geom_type == 'POLYGON':
                # Обрабатываем только внешнее кольцо для простоты
                ring = coordinates[0] if coordinates else []
                coords_str = ', '.join([f"{coord[0]} {coord[1]}" for coord in ring])
                return f"POLYGON(({coords_str}))"
            else:
                return "POINT(0 0)"  # Fallback
        elif isinstance(geometry, str):
            # Уже в WKT формате
            return geometry
        else:
            return "POINT(0 0)"  # Fallback
