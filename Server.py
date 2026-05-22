#!/usr/bin/env python3
"""
ArcGIS Server SOAP/REST API Server
Поддерживает полную совместимость с ArcMap 10.3
"""

import sys
import os
import traceback
import configparser
import logging
from typing import Optional, Dict, Any
from urllib.parse import parse_qs
from wsgiref.simple_server import make_server
from Router import Router
from DataSource.spatialite_loader import configure_dll_search_path

configure_dll_search_path()

# Настройка логирования
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler('server.log')
    ]
)
logger = logging.getLogger(__name__)

def get_config_files() -> list:
    """Получает список конфигурационных файлов."""
    config_files = ["featureserver.cfg", "config.ini"]
    
    missing_files = [file_name for file_name in config_files if not os.path.exists(file_name)]
    if missing_files:
        for file_name in missing_files:
            logger.error(f"Отсутствует обязательный конфигурационный файл {file_name}")
        sys.exit(1)

    return config_files

class Server:
    """Сервер управляет конфигурацией и источниками данных."""
    
    def __init__(self, datasources: Dict[str, Any], metadata: Optional[Dict[str, Any]] = None, 
                 auth_config: Optional[Dict[str, Any]] = None):
        self.datasources = datasources
        self.metadata = metadata or {}
        self.auth_config = auth_config or {}
        
        # Инициализируем аутентификацию
        if auth_config:
            from Auth import AuthenticationManager
            self.auth_manager = AuthenticationManager(auth_config)
        else:
            self.auth_manager = None
        
        # Инициализируем мониторинг пулов соединений
        self._init_pool_monitoring()
        
        logger.info("Server initialized successfully")
    
    def _init_pool_monitoring(self):
        """Инициализирует мониторинг пулов соединений"""
        try:
            from utils.pool_monitor import start_pool_monitoring
            
            # Получаем интервал мониторинга из конфигурации
            monitor_interval = int(self.metadata.get('pool_monitor_interval', 60))
            
            # Запускаем мониторинг
            start_pool_monitoring(monitor_interval)
            logger.info(f"Pool monitoring started with {monitor_interval}s interval")
            
        except Exception as e:
            logger.warning(f"Failed to start pool monitoring: {e}")
    
    @classmethod
    def load(cls, *files: str) -> 'Server':
        """Загружает конфигурацию сервера и источники данных."""
        config = configparser.ConfigParser()
        config.read(files)
        
        metadata = {}
        datasources = {}
        auth_config = {}
        
        # Загрузка источников данных
        for section in config.sections():
            if section in {"metadata", "server", "auth"}:
                continue
            source = cls.loadFromSection(config, section, "DataSource")
            if source:
                datasources[section] = source
        
        # Загрузка метаданных сервера
        if config.has_section("server"):
            metadata.update(dict(config.items("server")))

        # Загрузка конфигурации аутентификации
        if config.has_section("auth"):
            auth_config.update(dict(config.items("auth")))
            # Преобразуем строковые значения в нужные типы
            auth_config['enabled'] = auth_config.get('enabled', 'false').lower() == 'true'
            auth_config['token_expiry'] = int(auth_config.get('token_expiry', '3600'))

        return cls(datasources, metadata, auth_config)

    @classmethod
    def loadFromSection(cls, config: configparser.ConfigParser, section: str, 
                       module_type: str, **objargs: Any) -> Optional[Any]:
        """Загружает модуль из конфигурационной секции."""
        try:
            type_ = config.get(section, "type")
            module = __import__("%s.%s" % (module_type, type_), globals(), locals(), [type_])
            objclass = getattr(module, type_)

            # Заполняем параметры из конфигурации
            for opt in config.options(section):
                if opt != "type":
                    objargs[opt] = config.get(section, opt)

            if module_type == 'DataSource':
                return objclass(section, **objargs)
            else:
                return objclass(**objargs)
        except ImportError as e:
            logger.error(f"Ошибка импорта модуля {module_type}.{section}: {e}")
            return None
        except AttributeError as e:
            logger.error(f"Ошибка атрибута в модуле {module_type}.{section}: {e}")
            return None
        except Exception as e:
            logger.error(f"Ошибка при загрузке модуля {module_type}.{section}: {e}")
            traceback.print_exc()
            return None

def create_app() -> 'Server':
    """Создает экземпляр сервера для WSGI."""
    cfgfiles = get_config_files()
    return Server.load(*cfgfiles)

def wsgiApp(environ: Dict[str, Any], start_response) -> list:
    """WSGI-приложение для обработки запросов."""
    # Создаем сервер для каждого запроса (можно оптимизировать)
    server = create_app()

    try:
        # Проверяем аутентификацию перед обработкой запроса
        if server.auth_manager:
            try:
                auth_result = server.auth_manager.authenticate_request(environ)
                environ['auth_info'] = auth_result
            except Exception as auth_error:
                logger.warning(f"Authentication failed: {auth_error}")
                # Возвращаем ошибку аутентификации
                fault_xml = server.auth_manager.create_soap_fault(str(auth_error))
                start_response('401 Unauthorized', [
                    ('Content-Type', 'text/xml'),
                    ('WWW-Authenticate', server.auth_manager.create_www_authenticate_header())
                ])
                return [fault_xml.encode('utf-8')]
        else:
            # Аутентификация отключена
            environ['auth_info'] = {'authenticated': True, 'user': 'anonymous', 'method': 'none'}

        # Получение параметров запроса
        params = parse_qs(environ.get('QUERY_STRING', ''))
        path_info = environ.get('PATH_INFO', '')
        host = environ.get('HTTP_HOST', '')
        request_method = environ.get('REQUEST_METHOD', 'GET')
        
        # Получение POST-данных
        post_data = None
        if request_method == "POST":
            try:
                content_length = int(environ.get('CONTENT_LENGTH', 0))
                post_data = environ['wsgi.input'].read(content_length) if content_length > 0 else None
            except (ValueError, KeyError) as e:
                logger.warning(f"Error reading POST data: {e}")
                post_data = None
        
        # Маршрутизация запроса
        router = Router(server)
        response_content_type, response_body = router.route(
            path_info, params, host, post_data, request_method
        )

        start_response('200 OK', [('Content-Type', response_content_type)])
        # Убеждаемся, что response_body - это строка
        if isinstance(response_body, str):
            return [response_body.encode('utf-8')]
        else:
            return [str(response_body).encode('utf-8')]

    except Exception as e:
        logger.error(f"Error in wsgiApp: {e}")
        logger.error(traceback.format_exc())
        start_response('500 Internal Server Error', [('Content-Type', 'text/plain')])
        return [f"Internal Server Error: {str(e)}".encode('utf-8')]

def cleanup_on_exit():
    """Очистка ресурсов при выходе"""
    try:
        from utils.pool_monitor import stop_pool_monitoring
        from DataSource.connection_pool import close_all_pools
        
        logger.info("Cleaning up resources...")
        stop_pool_monitoring()
        close_all_pools()
        logger.info("Cleanup completed")
    except Exception as e:
        logger.error(f"Error during cleanup: {e}")

# Запуск сервера
if __name__ == '__main__':
    try:
        server = create_app()
        port = int(server.metadata.get('port', 8888))
        logger.info(f"Starting server on port {port}...")
        logger.info(f"Authentication enabled: {server.auth_manager is not None}")
        
        httpd = make_server('', port, wsgiApp)
        logger.info(f"Server started successfully on port {port}")
        
        # Регистрируем обработчик для корректного завершения
        import atexit
        atexit.register(cleanup_on_exit)
        
        httpd.serve_forever()
    except KeyboardInterrupt:
        logger.info("Server stopped by user")
        cleanup_on_exit()
    except Exception as e:
        logger.error(f"Failed to start server: {e}")
        cleanup_on_exit()
        sys.exit(1)
