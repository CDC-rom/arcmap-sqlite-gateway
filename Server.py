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
import argparse
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
    required = ["featureserver.cfg"]
    optional = ["config.ini"]

    missing_required = [file_name for file_name in required if not os.path.exists(file_name)]
    if missing_required:
        for file_name in missing_required:
            logger.error(f"Отсутствует обязательный конфигурационный файл {file_name}")
        sys.exit(1)

    return required + [file_name for file_name in optional if os.path.exists(file_name)]


def parse_bool(value: Optional[str], default: bool = False) -> bool:
    """Преобразует строковое значение в bool."""
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    normalized = str(value).strip().lower()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off"}:
        return False
    raise ValueError(f"Неверное булево значение: {value}")


def parse_cli_args() -> argparse.Namespace:
    """Парсинг аргументов командной строки."""
    parser = argparse.ArgumentParser(
        description="ArcGIS SOAP/REST Server",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter
    )

    # Явный алиас, как просили: -help
    parser.add_argument("-help", action="help", help="Показать это сообщение и выйти")

    parser.add_argument("--port", type=int, default=None, help="Порт HTTP сервера")
    parser.add_argument("--pool-monitor-interval", type=int, default=None, help="Интервал мониторинга пулов (сек)")

    parser.add_argument("--auth-enabled", default=None, help="Включить аутентификацию (true/false)")
    parser.add_argument("--auth-type", default=None, help="Тип аутентификации (basic/token/ldap)")
    parser.add_argument("--auth-username", default=None, help="Логин для Basic auth")
    parser.add_argument("--auth-password", default=None, help="Пароль для Basic auth")
    parser.add_argument("--auth-token-secret", default=None, help="Секрет для токенов")
    parser.add_argument("--auth-token-expiry", type=int, default=None, help="Время жизни токена, сек")
    parser.add_argument("--auth-ldap-server", default=None, help="LDAP сервер")
    parser.add_argument("--auth-ldap-base-dn", default=None, help="LDAP base DN")
    parser.add_argument("--auth-ldap-bind-dn", default=None, help="LDAP bind DN")
    parser.add_argument("--auth-ldap-bind-password", default=None, help="LDAP bind пароль")

    return parser.parse_args()


def merge_cli_overrides(server: 'Server', args: argparse.Namespace) -> None:
    """Применяет переопределения из CLI поверх загруженной конфигурации."""
    if args.port is not None:
        server.metadata["port"] = str(args.port)
    elif "port" not in server.metadata:
        server.metadata["port"] = "8888"

    if args.pool_monitor_interval is not None:
        server.metadata["pool_monitor_interval"] = str(args.pool_monitor_interval)

    cli_auth = {
        "enabled": args.auth_enabled,
        "type": args.auth_type,
        "username": args.auth_username,
        "password": args.auth_password,
        "token_secret": args.auth_token_secret,
        "token_expiry": args.auth_token_expiry,
        "ldap_server": args.auth_ldap_server,
        "ldap_base_dn": args.auth_ldap_base_dn,
        "ldap_bind_dn": args.auth_ldap_bind_dn,
        "ldap_bind_password": args.auth_ldap_bind_password,
    }
    for key, value in cli_auth.items():
        if value is not None:
            server.auth_config[key] = value

    if "enabled" not in server.auth_config:
        server.auth_config["enabled"] = False
    else:
        server.auth_config["enabled"] = parse_bool(server.auth_config["enabled"], default=False)

    if "token_expiry" in server.auth_config:
        server.auth_config["token_expiry"] = int(server.auth_config["token_expiry"])
    else:
        server.auth_config["token_expiry"] = 3600

    from Auth import AuthenticationManager
    if server.auth_config.get("enabled", False):
        server.auth_manager = AuthenticationManager(server.auth_config)
    else:
        server.auth_manager = None

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
        args = parse_cli_args()
        server = create_app()
        merge_cli_overrides(server, args)
        port = int(server.metadata.get('port', 8888))
        host = server.metadata.get('host', 'localhost')
        base_url = server.metadata.get('url', f'http://{host}:{port}')
        logger.info(f"Starting server on port {port}...")
        logger.info(f"Authentication enabled: {server.auth_manager is not None}")
        logger.info(f"ArcMap REST endpoint: {base_url}/aodk/rest")
        logger.info(f"ArcMap SOAP WSDL: {base_url}/aodk/soap?wsdl")
        
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
