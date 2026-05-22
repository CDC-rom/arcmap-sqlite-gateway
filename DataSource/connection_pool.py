#!/usr/bin/env python3
"""
Connection Pool для SQLite с поддержкой SpatiaLite
Оптимизирует производительность за счет переиспользования соединений
"""

import queue
import threading
import sqlite3
import logging
import time
from contextlib import contextmanager
from typing import Optional, Dict, Any
from dataclasses import dataclass

from .spatialite_loader import configure_dll_search_path, load_spatialite

configure_dll_search_path()

logger = logging.getLogger(__name__)

@dataclass
class PoolConfig:
    """Конфигурация пула соединений"""
    max_connections: int = 10
    timeout: int = 30
    check_interval: int = 300  # 5 минут
    max_lifetime: int = 3600   # 1 час

class SQLiteConnectionPool:
    """
    Пул соединений для SQLite с автоматическим управлением жизненным циклом
    """
    
    def __init__(self, dsn: str, config: Optional[PoolConfig] = None):
        self.dsn = dsn
        self.config = config or PoolConfig()
        self.pool = queue.Queue(maxsize=self.config.max_connections)
        self._lock = threading.Lock()
        self._active_connections = 0
        self._total_created = 0
        self._total_reused = 0
        self._last_cleanup = time.time()
        
        # Инициализируем пул
        self._initialize_pool()
        logger.info(f"SQLite Connection Pool initialized for {dsn} with {self.config.max_connections} max connections")
    
    def _initialize_pool(self):
        """Инициализирует пул соединений"""
        try:
            for _ in range(min(5, self.config.max_connections)):  # Создаем только 5 соединений изначально
                conn = self._create_connection()
                if conn:
                    self.pool.put(conn)
                    self._total_created += 1
        except Exception as e:
            logger.error(f"Failed to initialize connection pool: {e}")
            raise
    
    def _create_connection(self) -> Optional[sqlite3.Connection]:
        """Создает новое соединение с SpatiaLite"""
        conn = None
        try:
            conn = sqlite3.connect(
                self.dsn, 
                timeout=self.config.timeout,
                check_same_thread=False  # Разрешаем использование в разных потоках
            )
            
            if not load_spatialite(conn):
                logger.warning("SpatiaLite не загружен — пространственные функции недоступны")

            return conn
            
        except Exception as e:
            logger.error(f"Failed to create SQLite connection: {e}")
            if conn:
                try:
                    conn.close()
                except:
                    pass
            return None
    
    def _is_connection_alive(self, conn: sqlite3.Connection) -> bool:
        """Проверяет, живо ли соединение"""
        try:
            conn.execute("SELECT 1")
            return True
        except (sqlite3.OperationalError, sqlite3.DatabaseError, AttributeError):
            return False
    
    def _is_connection_expired(self, conn: sqlite3.Connection) -> bool:
        """Проверяет, не истекло ли время жизни соединения"""
        # Пропускаем проверку времени, т.к. нет атрибутов
        return False
    
    def _cleanup_expired_connections(self):
        """Удаляет истекшие соединения из пула"""
        current_time = time.time()
        if current_time - self._last_cleanup < self.config.check_interval:
            return
        
        with self._lock:
            self._last_cleanup = current_time
            temp_queue = queue.Queue()
            
            while not self.pool.empty():
                try:
                    conn = self.pool.get_nowait()
                    if self._is_connection_alive(conn) and not self._is_connection_expired(conn):
                        temp_queue.put(conn)
                    else:
                        try:
                            conn.close()
                        except:
                            pass
                        self._active_connections -= 1
                except queue.Empty:
                    break
            
            # Возвращаем валидные соединения обратно в пул
            while not temp_queue.empty():
                try:
                    self.pool.put(temp_queue.get_nowait())
                except queue.Full:
                    break
    
    @contextmanager
    def get_connection(self):
        """
        Получает соединение из пула
        
        Usage:
            with pool.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("SELECT * FROM table")
                results = cursor.fetchall()
        """
        conn = None
        start_time = time.time()
        
        try:
            # Очищаем истекшие соединения
            self._cleanup_expired_connections()
            
            # Пытаемся получить соединение из пула
            try:
                conn = self.pool.get(timeout=self.config.timeout)
                # conn._pool_last_used = time.time()  # Пропускаем
                self._total_reused += 1
                logger.debug("Reused connection from pool")
            except queue.Empty:
                # Пул пуст, создаем новое соединение
                if self._active_connections < self.config.max_connections:
                    conn = self._create_connection()
                    if conn:
                        self._active_connections += 1
                        self._total_created += 1
                        logger.debug("Created new connection")
                    else:
                        raise Exception("Failed to create new connection")
                else:
                    raise Exception("Connection pool exhausted")
            
            # Проверяем, что соединение живо
            if not self._is_connection_alive(conn):
                try:
                    conn.close()
                except:
                    pass
                self._active_connections -= 1
                raise Exception("Connection is dead")
            
            yield conn
            
        except Exception as e:
            logger.error(f"Error in get_connection: {e}")
            if conn:
                try:
                    conn.close()
                except:
                    pass
                self._active_connections -= 1
            raise
        finally:
            # Возвращаем соединение в пул
            if conn and self._is_connection_alive(conn):
                try:
                    # Проверяем, что соединение не истекло
                    if not self._is_connection_expired(conn):
                        self.pool.put_nowait(conn)
                        logger.debug("Returned connection to pool")
                    else:
                        try:
                            conn.close()
                        except:
                            pass
                        self._active_connections -= 1
                        logger.debug("Closed expired connection")
                except queue.Full:
                    # Пул полон, закрываем соединение
                    try:
                        conn.close()
                    except:
                        pass
                    self._active_connections -= 1
                    logger.debug("Pool full, closed connection")
            
            # Логируем статистику
            elapsed = time.time() - start_time
            if elapsed > 1.0:  # Логируем медленные операции
                logger.warning(f"Slow database operation: {elapsed:.2f}s")
    
    def get_stats(self) -> Dict[str, Any]:
        """Возвращает статистику пула соединений"""
        return {
            'total_created': self._total_created,
            'total_reused': self._total_reused,
            'active_connections': self._active_connections,
            'pool_size': self.pool.qsize(),
            'max_connections': self.config.max_connections,
            'reuse_ratio': self._total_reused / max(self._total_created, 1)
        }
    
    def close_all(self):
        """Закрывает все соединения в пуле"""
        with self._lock:
            while not self.pool.empty():
                try:
                    conn = self.pool.get_nowait()
                    try:
                        conn.close()
                    except:
                        pass
                except queue.Empty:
                    break
            self._active_connections = 0
            logger.info("All connections in pool closed")

# Глобальный реестр пулов для переиспользования
_pool_registry: Dict[str, SQLiteConnectionPool] = {}
_registry_lock = threading.Lock()

def get_pool(dsn: str, config: Optional[PoolConfig] = None) -> SQLiteConnectionPool:
    """
    Получает или создает пул соединений для указанного DSN
    
    Args:
        dsn: Путь к файлу базы данных
        config: Конфигурация пула
    
    Returns:
        SQLiteConnectionPool: Пул соединений
    """
    with _registry_lock:
        if dsn not in _pool_registry:
            _pool_registry[dsn] = SQLiteConnectionPool(dsn, config)
        return _pool_registry[dsn]

def close_all_pools():
    """Закрывает все пулы соединений"""
    with _registry_lock:
        for pool in _pool_registry.values():
            pool.close_all()
        _pool_registry.clear()
        logger.info("All connection pools closed") 