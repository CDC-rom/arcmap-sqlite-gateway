#!/usr/bin/env python3
"""
Тесты для Connection Pool
"""

import pytest
import tempfile
import os
import sqlite3
import threading
import time
from DataSource.connection_pool import SQLiteConnectionPool, PoolConfig, get_pool, close_all_pools


class TestConnectionPool:
    """Тесты для пула соединений SQLite"""
    
    @pytest.fixture
    def temp_db(self):
        """Создает временную базу данных для тестов"""
        fd, path = tempfile.mkstemp(suffix='.db')
        os.close(fd)
        
        # Инициализируем базу данных
        conn = sqlite3.connect(path)
        conn.execute("""
            CREATE TABLE test_table (
                id INTEGER PRIMARY KEY,
                name TEXT,
                value REAL
            )
        """)
        conn.execute("INSERT INTO test_table (name, value) VALUES (?, ?)", ("test1", 1.0))
        conn.execute("INSERT INTO test_table (name, value) VALUES (?, ?)", ("test2", 2.0))
        conn.commit()
        conn.close()
        
        yield path
        
        # Очистка
        try:
            os.unlink(path)
        except OSError:
            pass
    
    @pytest.fixture
    def pool_config(self):
        """Конфигурация пула для тестов"""
        return PoolConfig(
            max_connections=5,
            timeout=5,
            check_interval=60,
            max_lifetime=300
        )
    
    def test_pool_initialization(self, temp_db, pool_config):
        """Тест инициализации пула"""
        pool = SQLiteConnectionPool(temp_db, pool_config)
        
        assert pool.dsn == temp_db
        assert pool.config.max_connections == 5
        assert pool.pool.qsize() > 0  # Пул должен содержать соединения
    
    def test_get_connection(self, temp_db, pool_config):
        """Тест получения соединения из пула"""
        pool = SQLiteConnectionPool(temp_db, pool_config)
        
        with pool.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT COUNT(*) FROM test_table")
            count = cursor.fetchone()[0]
            assert count == 2
    
    def test_connection_reuse(self, temp_db, pool_config):
        """Тест переиспользования соединений"""
        pool = SQLiteConnectionPool(temp_db, pool_config)
        
        # Получаем статистику до использования
        stats_before = pool.get_stats()
        
        # Используем несколько соединений
        for _ in range(10):
            with pool.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("SELECT 1")
                cursor.fetchone()
        
        # Получаем статистику после использования
        stats_after = pool.get_stats()
        
        # Должно быть переиспользование соединений
        assert stats_after['total_reused'] > 0
        assert stats_after['reuse_ratio'] > 0
    
    def test_concurrent_access(self, temp_db, pool_config):
        """Тест конкурентного доступа к пулу"""
        pool = SQLiteConnectionPool(temp_db, pool_config)
        results = []
        errors = []
        
        def worker(worker_id):
            try:
                with pool.get_connection() as conn:
                    cursor = conn.cursor()
                    cursor.execute("SELECT name FROM test_table WHERE id = ?", (worker_id % 2 + 1,))
                    result = cursor.fetchone()
                    results.append((worker_id, result[0] if result else None))
                    time.sleep(0.01)  # Небольшая задержка для имитации работы
            except Exception as e:
                errors.append((worker_id, str(e)))
        
        # Запускаем несколько потоков
        threads = []
        for i in range(10):
            thread = threading.Thread(target=worker, args=(i,))
            threads.append(thread)
            thread.start()
        
        # Ждем завершения всех потоков
        for thread in threads:
            thread.join()
        
        # Проверяем результаты
        assert len(errors) == 0, f"Errors occurred: {errors}"
        assert len(results) == 10
        
        # Проверяем статистику
        stats = pool.get_stats()
        assert stats['total_created'] <= pool_config.max_connections
    
    def test_pool_exhaustion(self, temp_db):
        """Тест исчерпания пула соединений"""
        # Создаем пул с очень маленьким размером
        small_config = PoolConfig(max_connections=1, timeout=1)
        pool = SQLiteConnectionPool(temp_db, small_config)
        
        # Блокируем единственное соединение
        conn1 = pool.pool.get()
        
        # Пытаемся получить еще одно соединение (должно создать новое)
        with pool.get_connection() as conn2:
            assert conn2 is not None
        
        # Возвращаем первое соединение
        pool.pool.put(conn1)
        
        # Проверяем статистику
        stats = pool.get_stats()
        assert stats['total_created'] >= 2
    
    def test_connection_health_check(self, temp_db, pool_config):
        """Тест проверки здоровья соединений"""
        pool = SQLiteConnectionPool(temp_db, pool_config)
        
        # Получаем соединение и закрываем его вручную
        with pool.get_connection() as conn:
            conn.close()  # Закрываем соединение
        
        # Следующее получение соединения должно создать новое
        with pool.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT 1")
            result = cursor.fetchone()
            assert result[0] == 1
    
    def test_pool_registry(self, temp_db, pool_config):
        """Тест глобального реестра пулов"""
        # Закрываем все пулы перед тестом
        close_all_pools()
        
        # Получаем пул через реестр
        pool1 = get_pool(temp_db, pool_config)
        pool2 = get_pool(temp_db, pool_config)
        
        # Должен быть один и тот же пул
        assert pool1 is pool2
        
        # Проверяем работу пула
        with pool1.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT COUNT(*) FROM test_table")
            count = cursor.fetchone()[0]
            assert count == 2
    
    def test_pool_cleanup(self, temp_db, pool_config):
        """Тест очистки пула"""
        pool = SQLiteConnectionPool(temp_db, pool_config)
        
        # Получаем статистику
        stats_before = pool.get_stats()
        
        # Закрываем все соединения
        pool.close_all()
        
        # Проверяем, что пул пуст
        assert pool.pool.empty()
        assert pool._active_connections == 0


class TestConnectionPoolIntegration:
    """Интеграционные тесты с реальной базой данных"""
    
    @pytest.fixture
    def spatialite_db(self):
        """Создает временную SpatiaLite базу данных"""
        fd, path = tempfile.mkstemp(suffix='.db')
        os.close(fd)
        
        # Инициализируем SpatiaLite
        conn = sqlite3.connect(path)
        conn.enable_load_extension(True)
        
        try:
            conn.execute("SELECT load_extension('mod_spatialite')")
            conn.execute("SELECT InitSpatialMetaData(1)")
            
            # Создаем таблицу с геометрией
            conn.execute("""
                CREATE TABLE spatial_test (
                    id INTEGER PRIMARY KEY,
                    name TEXT,
                    geometry BLOB
                )
            """)
            
            # Добавляем геометрическую колонку
            conn.execute("SELECT AddGeometryColumn('spatial_test', 'geometry', 4326, 'POINT', 'XY')")
            
            conn.commit()
            conn.close()
            
        except sqlite3.OperationalError:
            # SpatiaLite недоступен, создаем обычную таблицу
            conn = sqlite3.connect(path)
            conn.execute("""
                CREATE TABLE spatial_test (
                    id INTEGER PRIMARY KEY,
                    name TEXT,
                    geometry TEXT
                )
            """)
            conn.commit()
            conn.close()
        
        yield path
        
        # Очистка
        try:
            os.unlink(path)
        except OSError:
            pass
    
    def test_spatialite_connection(self, spatialite_db):
        """Тест работы с SpatiaLite через пул"""
        pool = SQLiteConnectionPool(spatialite_db)
        
        with pool.get_connection() as conn:
            cursor = conn.cursor()
            
            # Проверяем, что можем выполнять запросы
            cursor.execute("SELECT name FROM sqlite_master WHERE type='table'")
            tables = [row[0] for row in cursor.fetchall()]
            assert 'spatial_test' in tables
    
    def test_connection_pool_with_sqlite_class(self, spatialite_db):
        """Тест интеграции пула с классом SQLite"""
        from DataSource.SQLite import SQLite
        
        # Создаем экземпляр SQLite с пулом соединений
        sqlite_ds = SQLite(
            name="test_layer",
            dsn=spatialite_db,
            layer="spatial_test",
            max_connections=3
        )
        
        # Проверяем, что пул работает
        assert sqlite_ds.pool is not None
        
        # Проверяем статистику пула
        stats = sqlite_ds.pool.get_stats()
        assert stats['max_connections'] == 3


if __name__ == "__main__":
    pytest.main([__file__]) 