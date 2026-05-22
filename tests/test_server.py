import unittest
from unittest.mock import patch
from io import BytesIO
from wsgiref.util import setup_testing_defaults
from Server import app  # Предположим, что server.py создаёт WSGI-приложение app

class TestServer(unittest.TestCase):

    @patch("DataSource.SQLite.get_layers_with_geometry", return_value=["test_layer"])
    def test_services_endpoint(self, mock_get_layers):
        """
        Тестирует эндпоинт /services без реальной БД.
        """
        environ = {}
        setup_testing_defaults(environ)
        environ["PATH_INFO"] = "/services"
        environ["REQUEST_METHOD"] = "GET"

        def start_response(status, headers):
            self.assertEqual(status, "200 OK")

        result = app(environ, start_response)
        response_body = b"".join(result).decode("utf-8")

        self.assertIn("test_layer", response_body)

if __name__ == "__main__":
    unittest.main()

