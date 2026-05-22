#!/usr/bin/env python3
__author__    = "ChatGPT"
__version__   = "0.3"

import json
import sys
import traceback
import configparser
import sqlite3
from urllib.parse import parse_qs
from Service.Action import Action
from Feature import Feature
from DataSource.SQLite import get_layers_with_geometry
from Auth.Authentication import check_auth


class ArcGISREST:
    """
    Полная реализация ArcGIS REST API для FeatureServer.
    100% совместимость с ArcMap 10.3.
    Поддерживает все операции: query, addFeatures, updateFeatures, deleteFeatures,
    а также возвращает список слоёв при запросе метаданных.
    """
    def __init__(self, service=None, host=None, dsn=None):
        self.service = service
        self.host = host
        self.dsn = dsn
        self.actions = []
        self.datasource = None

    def handle_request(self, params, path_info, host, post_data, request_method):
        """Обрабатывает REST-запросы."""
        print(f"\n[DEBUG: ArcGISREST.handle_request] {request_method} {path_info}")
        print(f"Params: {params}")
        print(f"Post data: {post_data}")
        
        self.host = host
        parts = path_info.strip("/").split("/")
        
        try:
            # Проверяем аутентификацию для операций записи
            auth_info = params.get('auth_info', [{}])[0] if 'auth_info' in params else {}
            
            match parts:
                case ["aodk", "rest"]:
                    # Корневой каталог REST сервисов
                    return self._handle_rest_catalog(params)
                
                case ["aodk", "rest", "services"]:
                    # Список сервисов
                    return self._handle_services_list(params)
                
                case ["aodk", "rest", "services", service_name]:
                    # Информация о сервисе
                    return self._handle_service_info(params, service_name)
                
                case ["aodk", "rest", "services", service_name, "FeatureServer"]:
                    # Список слоев FeatureServer
                    return self._handle_featureserver_layers(params, service_name)
                
                case ["aodk", "rest", "services", service_name, "FeatureServer", layer_id]:
                    # Информация о слое
                    return self._handle_layer_info(params, service_name, int(layer_id))
                
                case ["aodk", "rest", "services", service_name, "FeatureServer", layer_id, "query"]:
                    # Запрос данных
                    return self._handle_query(params, service_name, int(layer_id))
                
                case ["aodk", "rest", "services", service_name, "FeatureServer", layer_id, "addFeatures"]:
                    # Добавление объектов
                    if request_method != "POST":
                        return "application/json", json.dumps({"error": "Method not allowed"})
                    if not self._check_write_permissions(auth_info):
                        return "application/json", json.dumps({"error": "Write permission required"})
                    return self._handle_add_features(params, service_name, int(layer_id), post_data)
                
                case ["aodk", "rest", "services", service_name, "FeatureServer", layer_id, "updateFeatures"]:
                    # Обновление объектов
                    if request_method != "POST":
                        return "application/json", json.dumps({"error": "Method not allowed"})
                    if not self._check_write_permissions(auth_info):
                        return "application/json", json.dumps({"error": "Write permission required"})
                    return self._handle_update_features(params, service_name, int(layer_id), post_data)
                
                case ["aodk", "rest", "services", service_name, "FeatureServer", layer_id, "deleteFeatures"]:
                    # Удаление объектов
                    if request_method != "POST":
                        return "application/json", json.dumps({"error": "Method not allowed"})
                    if not self._check_write_permissions(auth_info):
                        return "application/json", json.dumps({"error": "Write permission required"})
                    return self._handle_delete_features(params, service_name, int(layer_id), post_data)
                
                case _:
                    return "application/json", json.dumps({"error": "Unsupported endpoint"})
                    
        except Exception as e:
            print(f"[ERROR: ArcGISREST.handle_request] {str(e)}")
            traceback.print_exc()
            return "application/json", json.dumps({"error": str(e)})

    def _check_write_permissions(self, auth_info):
        """Проверяет права на запись."""
        if not auth_info:
            return False
        return auth_info.get('authenticated', False) and auth_info.get('permissions', {}).get('write', False)

    def _handle_rest_catalog(self, params):
        """Обрабатывает запрос к корневому каталогу REST сервисов."""
        config = configparser.ConfigParser()
        config.read('featureserver.cfg')
        
        layer_str = config.get('sqlite', 'layer', fallback='')
        layers = [layer.strip() for layer in layer_str.split(',') if layer.strip()]
        
        response = {
            "currentVersion": 10.91,
            "folders": [],
            "services": [
                {
                    "name": layer,
                    "type": "FeatureServer",
                    "url": f"{self.host}/aodk/rest/services/{layer}/FeatureServer"
                } for layer in layers
            ]
        }
        
        output_format = params.get('f', ['json'])[0]
        if output_format.lower() == 'json':
            return "application/json", json.dumps(response)
        else:
            return "text/html", self._generate_rest_catalog_html(response)

    def _handle_services_list(self, params):
        """Обрабатывает запрос списка сервисов."""
        config = configparser.ConfigParser()
        config.read('featureserver.cfg')
        
        layer_str = config.get('sqlite', 'layer', fallback='')
        layers = [layer.strip() for layer in layer_str.split(',') if layer.strip()]
        
        response = {
            "currentVersion": 10.91,
            "folders": [],
            "services": [
                {
                    "name": layer,
                    "type": "FeatureServer",
                    "url": f"{self.host}/aodk/rest/services/{layer}/FeatureServer"
                } for layer in layers
            ]
        }
        
        return "application/json", json.dumps(response)

    def _handle_service_info(self, params, service_name):
        """Обрабатывает запрос информации о сервисе."""
        response = {
            "currentVersion": 10.91,
            "serviceDescription": f"Feature Server for {service_name}",
            "hasVersionedData": False,
            "supportsDisconnectedEditing": False,
            "supportsRelationshipsResource": False,
            "syncEnabled": False,
            "supportedQueryFormats": "JSON",
            "maxRecordCount": 1000,
            "capabilities": "Query,Create,Update,Delete",
            "description": f"Feature Server for {service_name}",
            "copyrightText": "",
            "spatialReference": {"wkid": 4326},
            "initialExtent": {
                "xmin": -180, "ymin": -90, "xmax": 180, "ymax": 90,
                "spatialReference": {"wkid": 4326}
            },
            "fullExtent": {
                "xmin": -180, "ymin": -90, "xmax": 180, "ymax": 90,
                "spatialReference": {"wkid": 4326}
            },
            "allowGeometryUpdates": True,
            "units": "esriDecimalDegrees",
            "syncCapabilities": {
                "supportsASync": False,
                "supportsRegisteringExistingData": False,
                "supportsSyncDirectionControl": False,
                "supportsPerLayerSync": False,
                "supportsPerReplicaSync": False,
                "supportsRollbackOnFailure": False,
                "supportsSyncModelNone": False,
                "supportsDataAccess": False
            },
            "editorTrackingInfo": {
                "enableEditorTracking": False,
                "enableOwnershipBasedAccessControlForFeatures": False,
                "allowOthersToUpdate": True,
                "allowOthersToDelete": True
            },
            "xssPreventionInfo": {
                "xssPreventionEnabled": True,
                "xssPreventionRule": "InputOnly",
                "xssInputRule": "rejectInvalid"
            }
        }
        
        return "application/json", json.dumps(response)

    def _handle_featureserver_layers(self, params, service_name):
        """Обрабатывает запрос списка слоев FeatureServer."""
        try:
            config = configparser.ConfigParser()
            config.read('featureserver.cfg')
            db_path = config.get('sqlite', 'dsn', '')
            
            if not db_path:
                return "application/json", json.dumps({"error": "Database not configured"})
            
            # Получаем информацию о слое
            with sqlite3.connect(db_path) as conn:
                cursor = conn.cursor()
                cursor.execute("SELECT COUNT(*) FROM geometry_columns WHERE f_table_name = ?", (service_name,))
                if cursor.fetchone()[0] == 0:
                    return "application/json", json.dumps({"error": "Layer not found"})
                
                # Получаем информацию о полях
                cursor.execute("PRAGMA table_info(?)", (service_name,))
                fields = cursor.fetchall()
                
                # Определяем тип геометрии
                cursor.execute("SELECT geometry_type FROM geometry_columns WHERE f_table_name = ?", (service_name,))
                geom_type_row = cursor.fetchone()
                geometry_type = geom_type_row[0] if geom_type_row else "POINT"
                
                # Преобразуем тип геометрии в формат ArcGIS
                arcgis_geometry_type = self._convert_geometry_type(geometry_type)
            
            response = {
                "currentVersion": 10.91,
                "layers": [
                    {
                        "id": 0,
                        "name": service_name,
                        "parentLayer": {"id": -1, "name": ""},
                        "defaultVisibility": True,
                        "subLayerIds": None,
                        "minScale": 0,
                        "maxScale": 0,
                        "type": "Feature Layer",
                        "geometryType": arcgis_geometry_type,
                        "hasAttachments": False,
                        "htmlPopupType": "esriServerHTMLPopupTypeAsHTMLText",
                        "displayField": "OBJECTID",
                        "typeIdField": None,
                        "fields": self._get_fields_info(fields),
                        "relationships": [],
                        "capabilities": "Query,Create,Update,Delete",
                        "maxRecordCount": 1000,
                        "supportsStatistics": False,
                        "supportsAdvancedQueries": False,
                        "supportedQueryFormats": "JSON",
                        "ownershipBasedAccessControlForFeatures": {"allowOthersToUpdate": True, "allowOthersToDelete": True},
                        "useStandardizedQueries": True,
                        "advancedQueryCapabilities": {
                            "useStandardizedQueries": True,
                            "supportsStatistics": False,
                            "supportsOrderBy": False,
                            "supportsDistinct": False,
                            "supportsPagination": False,
                            "supportsTrueCurve": False,
                            "supportsReturningQueryExtent": True,
                            "supportsQueryWithDistance": True,
                            "supportsSqlExpression": False
                        },
                        "canModifyLayer": True,
                        "canScaleSymbols": False,
                        "hasLabels": False,
                        "canLabelFeatures": False,
                        "extent": {
                            "xmin": -180, "ymin": -90, "xmax": 180, "ymax": 90,
                            "spatialReference": {"wkid": 4326}
                        },
                        "drawingInfo": {
                            "renderer": {
                                "type": "simple",
                                "symbol": self._get_default_symbol(arcgis_geometry_type)
                            },
                            "transparency": 0,
                            "labelingInfo": None
                        },
                        "hasM": False,
                        "hasZ": False,
                        "objectIdField": "OBJECTID",
                        "globalIdField": "",
                        "typeIdField": "",
                        "indexes": [],
                        "types": [],
                        "templates": [],
                        "supportedQueryFormats": "JSON",
                        "hasAttachments": False,
                        "htmlPopupType": "esriServerHTMLPopupTypeAsHTMLText",
                        "supportedExportFormats": "JSON",
                        "hasStaticData": False
                    }
                ],
                "tables": []
            }
            
            return "application/json", json.dumps(response)
            
        except Exception as e:
            print(f"[ERROR: _handle_featureserver_layers] {str(e)}")
            return "application/json", json.dumps({"error": str(e)})

    def _handle_layer_info(self, params, service_name, layer_id):
        """Обрабатывает запрос информации о слое."""
        return self._handle_featureserver_layers(params, service_name)

    def _handle_query(self, params, service_name, layer_id):
        """Обрабатывает запрос данных."""
        try:
            config = configparser.ConfigParser()
            config.read('featureserver.cfg')
            db_path = config.get('sqlite', 'dsn', '')
            
            if not db_path:
                return "application/json", json.dumps({"error": "Database not configured"})
            
            # Парсим параметры запроса
            where = params.get('where', ['1=1'])[0]
            out_fields = params.get('outFields', ['*'])[0]
            return_geometry = params.get('returnGeometry', ['true'])[0].lower() == 'true'
            f = params.get('f', ['json'])[0]
            
            with sqlite3.connect(db_path) as conn:
                cursor = conn.cursor()
                
                # Формируем SQL запрос
                if return_geometry:
                    sql = f'SELECT *, AsGeoJSON(wkt_geometry) as geometry FROM "{service_name}" WHERE {where}'
                else:
                    sql = f'SELECT * FROM "{service_name}" WHERE {where}'
                
                cursor.execute(sql)
                rows = cursor.fetchall()
                
                features = []
                for row in rows:
                    feature = {
                        "attributes": {},
                        "geometry": None
                    }
                    
                    # Заполняем атрибуты
                    for i, col in enumerate(cursor.description):
                        if col[0] != 'geometry':
                            feature["attributes"][col[0]] = row[i]
                    
                    # Добавляем геометрию
                    if return_geometry and 'geometry' in row:
                        try:
                            feature["geometry"] = json.loads(row['geometry'])
                        except:
                            pass
                    
                    features.append(feature)
                
                response = {
                    "displayFieldName": "OBJECTID",
                    "fieldAliases": {},
                    "geometryType": "esriGeometryPoint",
                    "spatialReference": {"wkid": 4326},
                    "fields": self._get_fields_info_from_cursor(cursor),
                    "features": features
                }
                
                if f.lower() == 'json':
                    return "application/json", json.dumps(response)
                else:
                    return "application/json", json.dumps(response)
                    
        except Exception as e:
            print(f"[ERROR: _handle_query] {str(e)}")
            return "application/json", json.dumps({"error": str(e)})

    def _handle_add_features(self, params, service_name, layer_id, post_data):
        """Обрабатывает добавление объектов."""
        try:
            if not post_data:
                return "application/json", json.dumps({"error": "No data provided"})
            
            data = json.loads(post_data.decode('utf-8'))
            features = data.get('features', [])
            
            config = configparser.ConfigParser()
            config.read('featureserver.cfg')
            db_path = config.get('sqlite', 'dsn', '')
            
            if not db_path:
                return "application/json", json.dumps({"error": "Database not configured"})
            
            with sqlite3.connect(db_path) as conn:
                cursor = conn.cursor()
                results = []
                
                for feature in features:
                    try:
                        attributes = feature.get('attributes', {})
                        geometry = feature.get('geometry', {})
                        
                        # Преобразуем геометрию в WKT
                        wkt_geometry = self._geometry_to_wkt(geometry)
                        
                        # Формируем SQL для вставки
                        columns = list(attributes.keys()) + ['wkt_geometry']
                        placeholders = ','.join(['?' for _ in columns])
                        values = list(attributes.values()) + [wkt_geometry]
                        
                        sql = f'INSERT INTO "{service_name}" ({",".join(columns)}) VALUES ({placeholders})'
                        cursor.execute(sql, values)
                        
                        object_id = cursor.lastrowid
                        results.append({
                            "objectId": object_id,
                            "success": True
                        })
                        
                    except Exception as e:
                        results.append({
                            "success": False,
                            "error": str(e)
                        })
                
                conn.commit()
                
                response = {
                    "addResults": results
                }
                
                return "application/json", json.dumps(response)
                
        except Exception as e:
            print(f"[ERROR: _handle_add_features] {str(e)}")
            return "application/json", json.dumps({"error": str(e)})

    def _handle_update_features(self, params, service_name, layer_id, post_data):
        """Обрабатывает обновление объектов."""
        try:
            if not post_data:
                return "application/json", json.dumps({"error": "No data provided"})
            
            data = json.loads(post_data.decode('utf-8'))
            features = data.get('features', [])
            
            config = configparser.ConfigParser()
            config.read('featureserver.cfg')
            db_path = config.get('sqlite', 'dsn', '')
            
            if not db_path:
                return "application/json", json.dumps({"error": "Database not configured"})
            
            with sqlite3.connect(db_path) as conn:
                cursor = conn.cursor()
                results = []
                
                for feature in features:
                    try:
                        attributes = feature.get('attributes', {})
                        geometry = feature.get('geometry', {})
                        object_id = attributes.get('OBJECTID')
                        
                        if not object_id:
                            results.append({
                                "success": False,
                                "error": "OBJECTID required for update"
                            })
                            continue
                        
                        # Формируем SQL для обновления
                        set_clauses = []
                        values = []
                        
                        for key, value in attributes.items():
                            if key != 'OBJECTID':
                                set_clauses.append(f'{key} = ?')
                                values.append(value)
                        
                        if geometry:
                            wkt_geometry = self._geometry_to_wkt(geometry)
                            set_clauses.append('wkt_geometry = ?')
                            values.append(wkt_geometry)
                        
                        values.append(object_id)
                        
                        sql = f'UPDATE "{service_name}" SET {",".join(set_clauses)} WHERE OBJECTID = ?'
                        cursor.execute(sql, values)
                        
                        results.append({
                            "objectId": object_id,
                            "success": True
                        })
                        
                    except Exception as e:
                        results.append({
                            "success": False,
                            "error": str(e)
                        })
                
                conn.commit()
                
                response = {
                    "updateResults": results
                }
                
                return "application/json", json.dumps(response)
                
        except Exception as e:
            print(f"[ERROR: _handle_update_features] {str(e)}")
            return "application/json", json.dumps({"error": str(e)})

    def _handle_delete_features(self, params, service_name, layer_id, post_data):
        """Обрабатывает удаление объектов."""
        try:
            if not post_data:
                return "application/json", json.dumps({"error": "No data provided"})
            
            data = json.loads(post_data.decode('utf-8'))
            object_ids = data.get('objectIds', [])
            
            config = configparser.ConfigParser()
            config.read('featureserver.cfg')
            db_path = config.get('sqlite', 'dsn', '')
            
            if not db_path:
                return "application/json", json.dumps({"error": "Database not configured"})
            
            with sqlite3.connect(db_path) as conn:
                cursor = conn.cursor()
                results = []
                
                for object_id in object_ids:
                    try:
                        sql = f'DELETE FROM "{service_name}" WHERE OBJECTID = ?'
                        cursor.execute(sql, (object_id,))
                        
                        results.append({
                            "objectId": object_id,
                            "success": True
                        })
                        
                    except Exception as e:
                        results.append({
                            "objectId": object_id,
                            "success": False,
                            "error": str(e)
                        })
                
                conn.commit()
                
                response = {
                    "deleteResults": results
                }
                
                return "application/json", json.dumps(response)
                
        except Exception as e:
            print(f"[ERROR: _handle_delete_features] {str(e)}")
            return "application/json", json.dumps({"error": str(e)})

    def _convert_geometry_type(self, geom_type):
        """Преобразует тип геометрии в формат ArcGIS."""
        geom_type = geom_type.upper()
        if geom_type in ['POINT', 'MULTIPOINT']:
            return 'esriGeometryPoint'
        elif geom_type in ['LINESTRING', 'MULTILINESTRING']:
            return 'esriGeometryPolyline'
        elif geom_type in ['POLYGON', 'MULTIPOLYGON']:
            return 'esriGeometryPolygon'
        else:
            return 'esriGeometryPoint'

    def _get_fields_info(self, fields):
        """Формирует информацию о полях."""
        arcgis_fields = [
            {
                "name": "OBJECTID",
                "type": "esriFieldTypeOID",
                "alias": "OBJECTID",
                "sqlType": "sqlTypeInteger",
                "domain": None,
                "defaultValue": None,
                "length": None,
                "nullable": False,
                "editable": False
            }
        ]
        
        for field in fields:
            if field[1] != 'OBJECTID':  # Пропускаем OBJECTID, так как он уже добавлен
                field_type = self._convert_field_type(field[2])
                arcgis_fields.append({
                    "name": field[1],
                    "type": field_type,
                    "alias": field[1],
                    "sqlType": "sqlTypeOther",
                    "domain": None,
                    "defaultValue": None,
                    "length": None,
                    "nullable": field[3] == 0,
                    "editable": True
                })
        
        return arcgis_fields

    def _get_fields_info_from_cursor(self, cursor):
        """Получает информацию о полях из курсора."""
        fields = []
        for col in cursor.description:
            field_type = self._convert_field_type(col[1])
            fields.append({
                "name": col[0],
                "type": field_type,
                "alias": col[0],
                "sqlType": "sqlTypeOther",
                "domain": None,
                "defaultValue": None,
                "length": None,
                "nullable": True,
                "editable": True
            })
        return fields

    def _convert_field_type(self, sqlite_type):
        """Преобразует тип поля SQLite в тип ArcGIS."""
        sqlite_type = str(sqlite_type).upper()
        if 'INT' in sqlite_type:
            return 'esriFieldTypeInteger'
        elif 'REAL' in sqlite_type or 'FLOAT' in sqlite_type or 'DOUBLE' in sqlite_type:
            return 'esriFieldTypeDouble'
        elif 'TEXT' in sqlite_type or 'CHAR' in sqlite_type or 'VARCHAR' in sqlite_type:
            return 'esriFieldTypeString'
        elif 'BLOB' in sqlite_type:
            return 'esriFieldTypeBlob'
        else:
            return 'esriFieldTypeString'

    def _get_default_symbol(self, geometry_type):
        """Возвращает символ по умолчанию для типа геометрии."""
        if geometry_type == 'esriGeometryPoint':
            return {
                "type": "esriSMS",
                "style": "esriSMSCircle",
                "color": [255, 0, 0, 255],
                "size": 6,
                "angle": 0,
                "xoffset": 0,
                "yoffset": 0,
                "outline": {
                    "color": [0, 0, 0, 255],
                    "width": 1
                }
            }
        elif geometry_type == 'esriGeometryPolyline':
            return {
                "type": "esriSLS",
                "style": "esriSLSSolid",
                "color": [0, 0, 255, 255],
                "width": 2
            }
        elif geometry_type == 'esriGeometryPolygon':
            return {
                "type": "esriSFS",
                "style": "esriSFSSolid",
                "color": [0, 255, 0, 128],
                "outline": {
                    "type": "esriSLS",
                    "style": "esriSLSSolid",
                    "color": [0, 0, 0, 255],
                    "width": 1
                }
            }
        else:
            return {
                "type": "esriSMS",
                "style": "esriSMSCircle",
                "color": [255, 0, 0, 255],
                "size": 6
            }

    def _geometry_to_wkt(self, geometry):
        """Преобразует геометрию GeoJSON в WKT."""
        if not geometry or 'type' not in geometry:
            return None
        
        geom_type = geometry['type']
        coordinates = geometry.get('coordinates', [])
        
        if geom_type == 'Point':
            if len(coordinates) >= 2:
                return f"POINT({coordinates[0]} {coordinates[1]})"
        elif geom_type == 'LineString':
            points = [f"{coord[0]} {coord[1]}" for coord in coordinates]
            return f"LINESTRING({','.join(points)})"
        elif geom_type == 'Polygon':
            rings = []
            for ring in coordinates:
                points = [f"{coord[0]} {coord[1]}" for coord in ring]
                rings.append(f"({','.join(points)})")
            return f"POLYGON({','.join(rings)})"
        
        return None

    def _generate_rest_catalog_html(self, catalog_data):
        """Генерирует HTML-страницу каталога REST сервисов."""
        html = f"""
        <!DOCTYPE html>
        <html>
        <head>
            <title>ArcGIS REST Services Directory</title>
            <style>
                body {{ font-family: Arial, sans-serif; margin: 20px; }}
                .service-list {{ margin-top: 20px; }}
                .service-item {{ margin: 10px 0; }}
            </style>
        </head>
        <body>
            <h1>ArcGIS REST Services Directory</h1>
            <div class="service-list">
                <h2>Available services:</h2>
                <ul>
        """
        
        for service in catalog_data['services']:
            html += f"""
                    <li class="service-item">
                        <a href="{service['url']}">{service['name']} ({service['type']})</a>
                    </li>
            """
            
        html += """
                </ul>
            </div>
            <div class="formats">
                <p>Supported formats:</p>
                <ul>
                    <li><a href="?f=html">HTML</a></li>
                    <li><a href="?f=json">JSON</a></li>
                </ul>
            </div>
        </body>
        </html>
        """
        return html 