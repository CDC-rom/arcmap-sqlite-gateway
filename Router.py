class Router:
    """
    Маршрутизатор запросов ArcGIS Server.
    
    Порядок проверки маршрутов:
    1. SOAP запросы (?wsdl) - для интеграции с legacy системами
    2. REST каталог сервисов - базовый endpoint для обнаружения сервисов
    3. REST API запросы - все остальные операции с данными
    """

    def __init__(self, server):
        self.server = server

    def route(self, path_info, params, host, post_data, request_method):
        """
        Маршрутизация запросов по приоритетам:
        1. SOAP - для интеграции с legacy системами
        2. REST каталог - для обнаружения сервисов
        3. REST API - для работы с данными
        """
        try:
            # 1. SOAP запросы
            if self._is_soap_request(path_info, params):
                return self._handle_soap(params, path_info, host, post_data, request_method)

            # 2. REST каталог
            if self._is_rest_catalog_request(path_info):
                return self._handle_rest_catalog(params)

            # 3. REST API запросы
            if self._is_rest_api_request(path_info):
                return self._handle_rest_api(params, path_info, host, post_data, request_method)

            # Если запрос не соответствует ни одному из маршрутов
            raise ValueError(f"Неподдерживаемый путь запроса: {path_info}")
        except Exception as e:
            print(f"Ошибка маршрутизации: {str(e)}")
            raise

    def _is_soap_request(self, path_info, params):
        """Проверяет, является ли запрос SOAP запросом."""
        return path_info.startswith("/aodk/soap") and "wsdl" in params

    def _is_rest_catalog_request(self, path_info):
        """Проверяет, является ли запрос запросом к REST каталогу."""
        return path_info == "/aodk/rest"

    def _is_rest_api_request(self, path_info):
        """Проверяет, является ли запрос REST API запросом."""
        return path_info.startswith("/aodk/rest")

    def _handle_soap(self, params, path_info, host, post_data, request_method):
        """Обработка SOAP запросов"""
        from Service.ArcGISSOAP import ArcGISSOAP
        soap_handler = ArcGISSOAP(self.server)
        return soap_handler.handle_request(params, path_info, host, post_data, request_method)

    def _handle_rest_catalog(self, params):
        """Обработка запросов к REST каталогу"""
        from Service.ArcGISREST import ArcGISREST
        rest_handler = ArcGISREST(self.server)
        return rest_handler.handle_catalog_request(params)

    def _handle_rest_api(self, params, path_info, host, post_data, request_method):
        """Обработка REST API запросов"""
        from Service.ArcGISREST import ArcGISREST
        rest_handler = ArcGISREST(self.server)
        return rest_handler.handle_request(params, path_info, host, post_data, request_method)
