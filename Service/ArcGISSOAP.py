import traceback
from xml.etree.ElementTree import Element, SubElement, tostring

class ArcGISSOAP:
    """Класс для реализации основных функций ArcGIS Server SOAP."""

    def __init__(self, server):
        self.server = server

    def handle_request(self, params, path_info, host, post_data, request_method):
        """Обрабатывает SOAP-запросы."""
        # Проверяем аутентификацию (опционально)
        auth_result = self._check_authentication(params, path_info, host, post_data, request_method)
        if auth_result is not None:
            return auth_result
            
        if "wsdl" in params:
            return "text/xml", self.generate_wsdl()
        else:
            return "text/xml", self.process_soap_request(post_data)

    def _check_authentication(self, params, path_info, host, post_data, request_method):
        """Проверяет аутентификацию (опциональная функция)."""
        # Аутентификация уже проверена в wsgiApp, получаем информацию из environ
        # Эта функция оставлена для совместимости
        return None

    def _check_permissions(self, operation, auth_info):
        """Проверяет права доступа для операции."""
        if not auth_info.get('authenticated', False):
            return False
        
        permissions = auth_info.get('permissions', [])
        
        # Операции чтения
        if operation in ['GetServiceInfo', 'GetLayerInfo', 'Query']:
            return 'read' in permissions
        
        # Операции записи
        elif operation in ['CreateFeature', 'UpdateFeature', 'DeleteFeature']:
            return 'write' in permissions
        
        # По умолчанию разрешаем
        return True

    def _find_element(self, parent, tag_name):
        """Находит первый элемент по локальному имени, игнорируя namespace."""
        for elem in parent.iter():
            if not isinstance(elem.tag, str):
                continue
            if elem.tag == tag_name or elem.tag.endswith('}' + tag_name):
                return elem
        return None

    def _create_unauthorized_fault(self, operation):
        """Создает SOAP Fault для ошибки авторизации."""
        return f"""<?xml version="1.0" encoding="UTF-8"?>
<soap:Envelope xmlns:soap="http://schemas.xmlsoap.org/soap/envelope/"
               xmlns:tns="http://www.esri.com/schemas/ArcGIS/10.3">
    <soap:Body>
        <soap:Fault>
            <faultcode>soap:Client</faultcode>
            <faultstring>Insufficient permissions</faultstring>
            <detail>
                <tns:ArcGISError>
                    <tns:errorCode>403</tns:errorCode>
                    <tns:errorMessage>User does not have permission to perform operation: {operation}</tns:errorMessage>
                </tns:ArcGISError>
            </detail>
        </soap:Fault>
    </soap:Body>
</soap:Envelope>"""

    def _convert_esri_geometry_type_to_soap(self, esri_type):
        """Преобразует ESRI тип геометрии в формат SOAP для ArcGIS.
        
        Examples:
            esriGeometryPoint -> Point
            esriGeometryPolyline -> Polyline
            esriGeometryPolygon -> Polygon
        """
        mapping = {
            'esriGeometryPoint': 'Point',
            'esriGeometryPolyline': 'Polyline',
            'esriGeometryPolygon': 'Polygon',
            'esriGeometryMultipoint': 'Multipoint',
            'esriGeometryEnvelope': 'Envelope'
        }
        return mapping.get(esri_type, esri_type)

    def _get_layer_types(self):
        """Получает типы слоев из базы данных."""
        layers = []
        try:
            # Получаем слои из базы через метаданные сервера
            if hasattr(self.server, 'datasources'):
                for source_name, source in self.server.datasources.items():
                    layer_info = {
                        "name": source.name if hasattr(source, 'name') else source_name,
                        "geometryType": source.geometry_type if hasattr(source, 'geometry_type') else "esriGeometryPoint",
                        "fields": source.get_fields() if hasattr(source, 'get_fields') else []
                    }
                    layers.append(layer_info)
        except Exception as e:
            print(f"Ошибка при получении типов слоев: {e}")
            traceback.print_exc()
        return layers

    def generate_wsdl(self):
        """Генерирует WSDL-документ на основе конфигурации и данных."""
        base_url = self.server.metadata.get('url', 'http://localhost:8888')
        layers = self._get_layer_types()
        
        wsdl_content = f"""<?xml version="1.0" encoding="UTF-8"?>
<definitions name="ArcGISServer"
             targetNamespace="http://www.esri.com/schemas/ArcGIS/10.3"
             xmlns="http://schemas.xmlsoap.org/wsdl/"
             xmlns:soap="http://schemas.xmlsoap.org/wsdl/soap/"
             xmlns:tns="http://www.esri.com/schemas/ArcGIS/10.3"
             xmlns:xsd="http://www.w3.org/2001/XMLSchema">

    <types>
        <xsd:schema targetNamespace="http://www.esri.com/schemas/ArcGIS/10.3">
            <xsd:complexType name="MapServerInfo">
                <xsd:sequence>
                    <xsd:element name="Name" type="xsd:string"/>
                    <xsd:element name="Description" type="xsd:string"/>
                    <xsd:element name="Layers" type="tns:ArrayOfLayerInfo"/>
                    <xsd:element name="SpatialReference" type="tns:SpatialReference"/>
                    <xsd:element name="Units" type="xsd:string"/>
                </xsd:sequence>
            </xsd:complexType>
            
            <xsd:complexType name="LayerInfo">
                <xsd:sequence>
                    <xsd:element name="ID" type="xsd:int"/>
                    <xsd:element name="Name" type="xsd:string"/>
                    <xsd:element name="Type" type="xsd:string"/>
                    <xsd:element name="GeometryType" type="xsd:string"/>
                    <xsd:element name="Fields" type="tns:ArrayOfFieldInfo"/>
                </xsd:sequence>
            </xsd:complexType>
            
            <xsd:complexType name="ArrayOfLayerInfo">
                <xsd:sequence>
                    <xsd:element name="LayerInfo" type="tns:LayerInfo" minOccurs="0" maxOccurs="unbounded"/>
                </xsd:sequence>
            </xsd:complexType>
            
            <xsd:complexType name="FieldInfo">
                <xsd:sequence>
                    <xsd:element name="Name" type="xsd:string"/>
                    <xsd:element name="Type" type="xsd:string"/>
                    <xsd:element name="Alias" type="xsd:string"/>
                    <xsd:element name="Length" type="xsd:int" minOccurs="0"/>
                    <xsd:element name="Nullable" type="xsd:boolean" minOccurs="0"/>
                    <xsd:element name="Editable" type="xsd:boolean" minOccurs="0"/>
                    <xsd:element name="Required" type="xsd:boolean" minOccurs="0"/>
                </xsd:sequence>
            </xsd:complexType>
            
            <xsd:complexType name="ArrayOfFieldInfo">
                <xsd:sequence>
                    <xsd:element name="FieldInfo" type="tns:FieldInfo" minOccurs="0" maxOccurs="unbounded"/>
                </xsd:sequence>
            </xsd:complexType>
            
            <xsd:complexType name="SpatialReference">
                <xsd:sequence>
                    <xsd:element name="WKID" type="xsd:int"/>
                    <xsd:element name="WKT" type="xsd:string"/>
                </xsd:sequence>
            </xsd:complexType>

            <xsd:element name="GetServiceInfo">
                <xsd:complexType>
                    <xsd:sequence>
                        <xsd:element name="serviceName" type="xsd:string"/>
                    </xsd:sequence>
                </xsd:complexType>
            </xsd:element>

            <xsd:element name="GetServiceInfoResponse">
                <xsd:complexType>
                    <xsd:sequence>
                        <xsd:element name="return" type="tns:MapServerInfo"/>
                    </xsd:sequence>
                </xsd:complexType>
            </xsd:element>

            <xsd:element name="GetLayerInfo">
                <xsd:complexType>
                    <xsd:sequence>
                        <xsd:element name="layerID" type="xsd:int"/>
                    </xsd:sequence>
                </xsd:complexType>
            </xsd:element>

            <xsd:element name="GetLayerInfoResponse">
                <xsd:complexType>
                    <xsd:sequence>
                        <xsd:element name="return" type="tns:LayerInfo"/>
                    </xsd:sequence>
                </xsd:complexType>
            </xsd:element>

            <xsd:element name="Query">
                <xsd:complexType>
                    <xsd:sequence>
                        <xsd:element name="layerID" type="xsd:int"/>
                        <xsd:element name="whereClause" type="xsd:string" minOccurs="0"/>
                        <xsd:element name="outFields" type="xsd:string" minOccurs="0"/>
                        <xsd:element name="returnGeometry" type="xsd:boolean" minOccurs="0"/>
                        <xsd:element name="spatialRel" type="xsd:string" minOccurs="0"/>
                        <xsd:element name="geometry" type="tns:Geometry" minOccurs="0"/>
                    </xsd:sequence>
                </xsd:complexType>
            </xsd:element>

            <xsd:complexType name="Geometry">
                <xsd:choice>
                    <xsd:element name="extent" type="tns:Extent"/>
                    <xsd:element name="point" type="tns:Point"/>
                </xsd:choice>
            </xsd:complexType>

            <xsd:complexType name="Extent">
                <xsd:sequence>
                    <xsd:element name="xmin" type="xsd:double"/>
                    <xsd:element name="ymin" type="xsd:double"/>
                    <xsd:element name="xmax" type="xsd:double"/>
                    <xsd:element name="ymax" type="xsd:double"/>
                </xsd:sequence>
            </xsd:complexType>

            <xsd:complexType name="Point">
                <xsd:sequence>
                    <xsd:element name="x" type="xsd:double"/>
                    <xsd:element name="y" type="xsd:double"/>
                </xsd:sequence>
            </xsd:complexType>

            <xsd:element name="QueryResponse">
                <xsd:complexType>
                    <xsd:sequence>
                        <xsd:element name="return" type="tns:QueryResult"/>
                    </xsd:sequence>
                </xsd:complexType>
            </xsd:element>

            <xsd:complexType name="QueryResult">
                <xsd:sequence>
                    <xsd:element name="features" type="tns:ArrayOfFeature"/>
                    <xsd:element name="count" type="xsd:int"/>
                </xsd:sequence>
            </xsd:complexType>

            <xsd:complexType name="ArrayOfFeature">
                <xsd:sequence>
                    <xsd:element name="Feature" type="tns:Feature" minOccurs="0" maxOccurs="unbounded"/>
                </xsd:sequence>
            </xsd:complexType>

            <xsd:complexType name="Feature">
                <xsd:sequence>
                    <xsd:element name="attributes" type="tns:ArrayOfAttribute"/>
                    <xsd:element name="geometry" type="tns:Geometry" minOccurs="0"/>
                </xsd:sequence>
            </xsd:complexType>

            <xsd:complexType name="ArrayOfAttribute">
                <xsd:sequence>
                    <xsd:element name="Attribute" type="tns:Attribute" minOccurs="0" maxOccurs="unbounded"/>
                </xsd:sequence>
            </xsd:complexType>

            <xsd:complexType name="Attribute">
                <xsd:sequence>
                    <xsd:element name="name" type="xsd:string"/>
                    <xsd:element name="value" type="xsd:anyType"/>
                </xsd:sequence>
            </xsd:complexType>

            <xsd:element name="CreateFeature">
                <xsd:complexType>
                    <xsd:sequence>
                        <xsd:element name="layerID" type="xsd:int"/>
                        <xsd:element name="geometry" type="tns:Geometry"/>
                        <xsd:element name="attributes" type="tns:ArrayOfAttribute"/>
                    </xsd:sequence>
                </xsd:complexType>
            </xsd:element>

            <xsd:element name="CreateFeatureResponse">
                <xsd:complexType>
                    <xsd:sequence>
                        <xsd:element name="return" type="tns:CreateFeatureResult"/>
                    </xsd:sequence>
                </xsd:complexType>
            </xsd:element>

            <xsd:complexType name="CreateFeatureResult">
                <xsd:sequence>
                    <xsd:element name="success" type="xsd:boolean"/>
                    <xsd:element name="featureID" type="xsd:int"/>
                    <xsd:element name="message" type="xsd:string"/>
                </xsd:sequence>
            </xsd:complexType>

            <xsd:element name="UpdateFeature">
                <xsd:complexType>
                    <xsd:sequence>
                        <xsd:element name="layerID" type="xsd:int"/>
                        <xsd:element name="featureID" type="xsd:int"/>
                        <xsd:element name="geometry" type="tns:Geometry" minOccurs="0"/>
                        <xsd:element name="attributes" type="tns:ArrayOfAttribute" minOccurs="0"/>
                    </xsd:sequence>
                </xsd:complexType>
            </xsd:element>

            <xsd:element name="UpdateFeatureResponse">
                <xsd:complexType>
                    <xsd:sequence>
                        <xsd:element name="return" type="tns:UpdateFeatureResult"/>
                    </xsd:sequence>
                </xsd:complexType>
            </xsd:element>

            <xsd:complexType name="UpdateFeatureResult">
                <xsd:sequence>
                    <xsd:element name="success" type="xsd:boolean"/>
                    <xsd:element name="message" type="xsd:string"/>
                </xsd:sequence>
            </xsd:complexType>

            <xsd:element name="DeleteFeature">
                <xsd:complexType>
                    <xsd:sequence>
                        <xsd:element name="layerID" type="xsd:int"/>
                        <xsd:element name="featureID" type="xsd:int"/>
                    </xsd:sequence>
                </xsd:complexType>
            </xsd:element>

            <xsd:element name="DeleteFeatureResponse">
                <xsd:complexType>
                    <xsd:sequence>
                        <xsd:element name="return" type="tns:DeleteFeatureResult"/>
                    </xsd:sequence>
                </xsd:complexType>
            </xsd:element>

            <xsd:complexType name="DeleteFeatureResult">
                <xsd:sequence>
                    <xsd:element name="success" type="xsd:boolean"/>
                    <xsd:element name="message" type="xsd:string"/>
                </xsd:sequence>
            </xsd:complexType>
        </xsd:schema>
    </types>

    <message name="GetServiceInfoRequest">
        <part name="parameters" element="tns:GetServiceInfo"/>
    </message>
    
    <message name="GetServiceInfoResponse">
        <part name="parameters" element="tns:GetServiceInfoResponse"/>
    </message>
    
    <message name="GetLayerInfoRequest">
        <part name="parameters" element="tns:GetLayerInfo"/>
    </message>
    
    <message name="GetLayerInfoResponse">
        <part name="parameters" element="tns:GetLayerInfoResponse"/>
    </message>
    
    <message name="QueryRequest">
        <part name="parameters" element="tns:Query"/>
    </message>
    
    <message name="QueryResponse">
        <part name="parameters" element="tns:QueryResponse"/>
    </message>

    <message name="CreateFeatureRequest">
        <part name="parameters" element="tns:CreateFeature"/>
    </message>
    
    <message name="CreateFeatureResponse">
        <part name="parameters" element="tns:CreateFeatureResponse"/>
    </message>

    <message name="UpdateFeatureRequest">
        <part name="parameters" element="tns:UpdateFeature"/>
    </message>
    
    <message name="UpdateFeatureResponse">
        <part name="parameters" element="tns:UpdateFeatureResponse"/>
    </message>

    <message name="DeleteFeatureRequest">
        <part name="parameters" element="tns:DeleteFeature"/>
    </message>
    
    <message name="DeleteFeatureResponse">
        <part name="parameters" element="tns:DeleteFeatureResponse"/>
    </message>

    <portType name="ArcGISServerPortType">
        <operation name="GetServiceInfo">
            <input message="tns:GetServiceInfoRequest"/>
            <output message="tns:GetServiceInfoResponse"/>
        </operation>
        
        <operation name="GetLayerInfo">
            <input message="tns:GetLayerInfoRequest"/>
            <output message="tns:GetLayerInfoResponse"/>
        </operation>
        
        <operation name="Query">
            <input message="tns:QueryRequest"/>
            <output message="tns:QueryResponse"/>
        </operation>

        <operation name="CreateFeature">
            <input message="tns:CreateFeatureRequest"/>
            <output message="tns:CreateFeatureResponse"/>
        </operation>

        <operation name="UpdateFeature">
            <input message="tns:UpdateFeatureRequest"/>
            <output message="tns:UpdateFeatureResponse"/>
        </operation>

        <operation name="DeleteFeature">
            <input message="tns:DeleteFeatureRequest"/>
            <output message="tns:DeleteFeatureResponse"/>
        </operation>
    </portType>

    <binding name="ArcGISServerBinding" type="tns:ArcGISServerPortType">
        <soap:binding style="rpc" transport="http://schemas.xmlsoap.org/soap/http"/>
        <operation name="GetServiceInfo">
            <soap:operation soapAction="http://www.esri.com/schemas/ArcGIS/10.3/GetServiceInfo"/>
            <input>
                <soap:body use="encoded" namespace="http://www.esri.com/schemas/ArcGIS/10.3" encodingStyle="http://schemas.xmlsoap.org/soap/encoding/"/>
            </input>
            <output>
                <soap:body use="encoded" namespace="http://www.esri.com/schemas/ArcGIS/10.3" encodingStyle="http://schemas.xmlsoap.org/soap/encoding/"/>
            </output>
        </operation>
        
        <operation name="GetLayerInfo">
            <soap:operation soapAction="http://www.esri.com/schemas/ArcGIS/10.3/GetLayerInfo"/>
            <input>
                <soap:body use="encoded" namespace="http://www.esri.com/schemas/ArcGIS/10.3" encodingStyle="http://schemas.xmlsoap.org/soap/encoding/"/>
            </input>
            <output>
                <soap:body use="encoded" namespace="http://www.esri.com/schemas/ArcGIS/10.3" encodingStyle="http://schemas.xmlsoap.org/soap/encoding/"/>
            </output>
        </operation>
        
        <operation name="Query">
            <soap:operation soapAction="http://www.esri.com/schemas/ArcGIS/10.3/Query"/>
            <input>
                <soap:body use="encoded" namespace="http://www.esri.com/schemas/ArcGIS/10.3" encodingStyle="http://schemas.xmlsoap.org/soap/encoding/"/>
            </input>
            <output>
                <soap:body use="encoded" namespace="http://www.esri.com/schemas/ArcGIS/10.3" encodingStyle="http://schemas.xmlsoap.org/soap/encoding/"/>
            </output>
        </operation>

        <operation name="CreateFeature">
            <soap:operation soapAction="http://www.esri.com/schemas/ArcGIS/10.3/CreateFeature"/>
            <input>
                <soap:body use="encoded" namespace="http://www.esri.com/schemas/ArcGIS/10.3" encodingStyle="http://schemas.xmlsoap.org/soap/encoding/"/>
            </input>
            <output>
                <soap:body use="encoded" namespace="http://www.esri.com/schemas/ArcGIS/10.3" encodingStyle="http://schemas.xmlsoap.org/soap/encoding/"/>
            </output>
        </operation>

        <operation name="UpdateFeature">
            <soap:operation soapAction="http://www.esri.com/schemas/ArcGIS/10.3/UpdateFeature"/>
            <input>
                <soap:body use="encoded" namespace="http://www.esri.com/schemas/ArcGIS/10.3" encodingStyle="http://schemas.xmlsoap.org/soap/encoding/"/>
            </input>
            <output>
                <soap:body use="encoded" namespace="http://www.esri.com/schemas/ArcGIS/10.3" encodingStyle="http://schemas.xmlsoap.org/soap/encoding/"/>
            </output>
        </operation>

        <operation name="DeleteFeature">
            <soap:operation soapAction="http://www.esri.com/schemas/ArcGIS/10.3/DeleteFeature"/>
            <input>
                <soap:body use="encoded" namespace="http://www.esri.com/schemas/ArcGIS/10.3" encodingStyle="http://schemas.xmlsoap.org/soap/encoding/"/>
            </input>
            <output>
                <soap:body use="encoded" namespace="http://www.esri.com/schemas/ArcGIS/10.3" encodingStyle="http://schemas.xmlsoap.org/soap/encoding/"/>
            </output>
        </operation>
    </binding>

    <service name="ArcGISServerService">
        <port name="ArcGISServerPort" binding="tns:ArcGISServerBinding">
            <soap:address location="{base_url}/aodk/soap"/>
        </port>
    </service>
</definitions>"""
        return wsdl_content

    def process_soap_request(self, post_data):
        """Обрабатывает SOAP-запрос."""
        try:
            if not post_data:
                return self._create_error_response("No POST data received")
            
            # Парсим SOAP запрос
            from xml.etree.ElementTree import fromstring
            root = fromstring(post_data)
            
            # Определяем операцию
            body = root.find('.//{http://schemas.xmlsoap.org/soap/envelope/}Body')
            if body is None:
                return self._create_error_response("SOAP Body not found")
            
            # Проверяем тип операции
            if self._find_element(body, 'GetServiceInfo') is not None:
                return self._handle_get_service_info(body)
            elif self._find_element(body, 'GetLayerInfo') is not None:
                return self._handle_get_layer_info(body)
            elif self._find_element(body, 'Query') is not None:
                return self._handle_query(body)
            elif self._find_element(body, 'CreateFeature') is not None:
                return self._handle_create_feature(body)
            elif self._find_element(body, 'UpdateFeature') is not None:
                return self._handle_update_feature(body)
            elif self._find_element(body, 'DeleteFeature') is not None:
                return self._handle_delete_feature(body)
            else:
                return self._create_error_response("Unknown operation")
                
        except Exception as e:
            print(f"Error processing SOAP request: {e}")
            traceback.print_exc()
            return self._create_error_response(f"Internal Server Error: {str(e)}")

    def _handle_get_service_info(self, body):
        """Обрабатывает запрос GetServiceInfo."""
        try:
            # Проверяем права доступа (если аутентификация включена)
            if hasattr(self.server, 'auth_manager') and self.server.auth_manager:
                # Получаем информацию об аутентификации из environ
                # В реальной реализации нужно передавать auth_info из wsgiApp
                auth_info = getattr(self, '_auth_info', {'authenticated': True, 'permissions': ['read']})
                if not self._check_permissions('GetServiceInfo', auth_info):
                    return self._create_unauthorized_fault('GetServiceInfo')
            
            # Получаем информацию о сервисе
            layers = self._get_layer_types()
            
            # Создаем ответ
            response = Element("GetServiceInfoResponse", {
                "xmlns": "http://www.esri.com/schemas/ArcGIS/10.3"
            })
            
            return_elem = SubElement(response, "return")
            
            # Добавляем основную информацию
            name_elem = SubElement(return_elem, "Name")
            name_elem.text = "MapServer"
            
            desc_elem = SubElement(return_elem, "Description")
            desc_elem.text = "Пространственные данные"
            
            # Добавляем слои
            layers_elem = SubElement(return_elem, "Layers")
            for i, layer in enumerate(layers):
                layer_info = SubElement(layers_elem, "LayerInfo")
                
                id_elem = SubElement(layer_info, "ID")
                id_elem.text = str(i)
                
                name_elem = SubElement(layer_info, "Name")
                # if name missing, use empty string to match spec
                name_elem.text = layer.get('name', '') or ""
                
                type_elem = SubElement(layer_info, "Type")
                type_elem.text = "Feature Layer"
                
                geom_type_elem = SubElement(layer_info, "GeometryType")
                geom_type_elem.text = self._convert_esri_geometry_type_to_soap(layer.get('geometryType', '')) or ""
            
            # Добавляем пространственную привязку
            sr_elem = SubElement(return_elem, "SpatialReference")
            wkid_elem = SubElement(sr_elem, "WKID")
            wkid_elem.text = "4326"
            
            wkt_elem = SubElement(sr_elem, "WKT")
            wkt_elem.text = 'GEOGCS["WGS 84",DATUM["WGS_1984",SPHEROID["WGS 84",6378137,298.257223563,AUTHORITY["EPSG","7030"]],AUTHORITY["EPSG","6326"]],PRIMEM["Greenwich",0,AUTHORITY["EPSG","8901"]],UNIT["degree",0.0174532925199433,AUTHORITY["EPSG","9122"]],AUTHORITY["EPSG","4326"]]'
            
            units_elem = SubElement(return_elem, "Units")
            units_elem.text = "Decimal Degrees"
            
            return self._create_soap_response(response)
            
        except Exception as e:
            print(f"Error in GetServiceInfo: {e}")
            traceback.print_exc()
            return self._create_error_response(f"GetServiceInfo error: {str(e)}")

    def _handle_get_layer_info(self, body):
        """Обрабатывает запрос GetLayerInfo."""
        try:
            # Проверяем права доступа
            if hasattr(self.server, 'auth_manager') and self.server.auth_manager:
                auth_info = getattr(self, '_auth_info', {'authenticated': True, 'permissions': ['read']})
                if not self._check_permissions('GetLayerInfo', auth_info):
                    return self._create_unauthorized_fault('GetLayerInfo')
            
            # Получаем ID слоя
            layer_id_elem = self._find_element(body, 'layerID')
            if layer_id_elem is None:
                return self._create_error_response("layerID parameter not found")
            
            layer_id = int(layer_id_elem.text)
            layers = self._get_layer_types()
            
            if layer_id >= len(layers):
                return self._create_error_response(f"Layer with ID {layer_id} not found")
            
            layer = layers[layer_id]
            
            # Создаем ответ
            response = Element("GetLayerInfoResponse", {
                "xmlns": "http://www.esri.com/schemas/ArcGIS/10.3"
            })
            
            return_elem = SubElement(response, "return")
            
            # Добавляем информацию о слое
            id_elem = SubElement(return_elem, "ID")
            id_elem.text = str(layer_id)
            
            name_elem = SubElement(return_elem, "Name")
            name_elem.text = layer.get('name', '') or ""
            
            type_elem = SubElement(return_elem, "Type")
            type_elem.text = "Feature Layer"
            
            geom_type_elem = SubElement(return_elem, "GeometryType")
            geom_type_elem.text = self._convert_esri_geometry_type_to_soap(layer.get('geometryType', '')) or ""
            
            # Добавляем поля (тег обязательный)
            fields_elem = SubElement(return_elem, "Fields")
            for field in layer.get('fields', []):
                field_info = SubElement(fields_elem, "FieldInfo")
                
                field_name = SubElement(field_info, "Name")
                field_name.text = field.get('name', '') or ""
                
                field_type = SubElement(field_info, "Type")
                field_type.text = field.get('type', '') or ""
                
                field_alias = SubElement(field_info, "Alias")
                field_alias.text = field.get('alias', '') or field.get('name', '') or ""
                
                # Add optional field attributes
                # Only add Length if it's not None
                if 'length' in field and field.get('length') is not None:
                    field_length = SubElement(field_info, "Length")
                    field_length.text = str(field.get('length'))
                if 'nullable' in field:
                    field_nullable = SubElement(field_info, "Nullable")
                    field_nullable.text = "true" if field.get('nullable', False) else "false"
                if 'editable' in field:
                    field_editable = SubElement(field_info, "Editable")
                    field_editable.text = "true" if field.get('editable', False) else "false"
                if 'required' in field:
                    field_required = SubElement(field_info, "Required")
                    field_required.text = "true" if field.get('required', False) else "false"
            
            return self._create_soap_response(response)
            
        except Exception as e:
            print(f"Error in GetLayerInfo: {e}")
            traceback.print_exc()
            return self._create_error_response(f"GetLayerInfo error: {str(e)}")

    def _handle_query(self, body):
        """Обрабатывает запрос Query."""
        try:
            # Проверяем права доступа
            if hasattr(self.server, 'auth_manager') and self.server.auth_manager:
                auth_info = getattr(self, '_auth_info', {'authenticated': True, 'permissions': ['read']})
                if not self._check_permissions('Query', auth_info):
                    return self._create_unauthorized_fault('Query')
            
            # Получаем параметры запроса
            layer_id_elem = self._find_element(body, 'layerID')
            where_clause_elem = self._find_element(body, 'whereClause')
            out_fields_elem = self._find_element(body, 'outFields')
            return_geometry_elem = self._find_element(body, 'returnGeometry')
            
            if layer_id_elem is None:
                return self._create_error_response("layerID parameter not found")
            
            layer_id = int(layer_id_elem.text)
            where_clause = where_clause_elem.text if where_clause_elem is not None else ""
            out_fields = out_fields_elem.text if out_fields_elem is not None else "*"
            return_geometry = return_geometry_elem.text.lower() == "true" if return_geometry_elem is not None else True
            
            # Получаем данные из источника
            layers = self._get_layer_types()
            if layer_id >= len(layers):
                return self._create_error_response(f"Layer with ID {layer_id} not found")
            
            layer_name = layers[layer_id]['name']
            
            # Выполняем запрос к базе данных
            features = self._query_database(layer_name, where_clause, out_fields, return_geometry)
            
            # Создаем ответ
            response = Element("QueryResponse", {
                "xmlns": "http://www.esri.com/schemas/ArcGIS/10.3"
            })
            
            return_elem = SubElement(response, "return")
            
            # Добавляем объекты
            features_elem = SubElement(return_elem, "features")
            for feature in features:
                feature_elem = SubElement(features_elem, "Feature")
                
                # Добавляем атрибуты
                attrs_elem = SubElement(feature_elem, "attributes")
                for key, value in feature.get('attributes', {}).items():
                    attr_field = SubElement(attrs_elem, str(key))
                    attr_field.text = "" if value is None else str(value)
                
                # Объявляем элемент geometry всегда
                geom_elem = SubElement(feature_elem, "geometry")
                if return_geometry and 'geometry' in feature and feature['geometry']:
                    # Определяем тип геометрии и создаем соответствующий элемент
                    geom_data = feature['geometry']
                    if isinstance(geom_data, dict):
                        geom_type = geom_data.get('type', 'Point')
                        
                        if geom_type == 'Point':
                            point_elem = SubElement(geom_elem, "point")
                            coords = geom_data.get('coordinates', [0, 0])
                            if isinstance(coords, list) and len(coords) >= 2:
                                x_elem = SubElement(point_elem, "x")
                                x_elem.text = str(coords[0])
                                y_elem = SubElement(point_elem, "y")
                                y_elem.text = str(coords[1])
                        
                        elif geom_type == 'LineString':
                            # Для линий создаем extent
                            coords = geom_data.get('coordinates', [])
                            if coords:
                                x_coords = [coord[0] for coord in coords]
                                y_coords = [coord[1] for coord in coords]
                                extent_elem = SubElement(geom_elem, "extent")
                                xmin_elem = SubElement(extent_elem, "xmin")
                                xmin_elem.text = str(min(x_coords))
                                ymin_elem = SubElement(extent_elem, "ymin")
                                ymin_elem.text = str(min(y_coords))
                                xmax_elem = SubElement(extent_elem, "xmax")
                                xmax_elem.text = str(max(x_coords))
                                ymax_elem = SubElement(extent_elem, "ymax")
                                ymax_elem.text = str(max(y_coords))
                        
                        elif geom_type == 'Polygon':
                            # Для полигонов создаем extent
                            coords = geom_data.get('coordinates', [[]])
                            if coords and coords[0]:
                                x_coords = [coord[0] for coord in coords[0]]
                                y_coords = [coord[1] for coord in coords[0]]
                                extent_elem = SubElement(geom_elem, "extent")
                                xmin_elem = SubElement(extent_elem, "xmin")
                                xmin_elem.text = str(min(x_coords))
                                ymin_elem = SubElement(extent_elem, "ymin")
                                ymin_elem.text = str(min(y_coords))
                                xmax_elem = SubElement(extent_elem, "xmax")
                                xmax_elem.text = str(max(x_coords))
                                ymax_elem = SubElement(extent_elem, "ymax")
                                ymax_elem.text = str(max(y_coords))
            
            # Добавляем количество
            count_elem = SubElement(return_elem, "count")
            count_elem.text = str(len(features))
            
            return self._create_soap_response(response)
            
        except Exception as e:
            print(f"Error in Query: {e}")
            traceback.print_exc()
            return self._create_error_response(f"Query error: {str(e)}")

    def _query_database(self, layer_name, where_clause, out_fields, return_geometry):
        """Выполняет запрос к базе данных."""
        try:
            # Получаем источник данных
            if layer_name in self.server.datasources:
                datasource = self.server.datasources[layer_name]
                
                # Создаем действие для запроса
                from Service.Action import Action
                action = Action("select")
                action.where = where_clause
                
                # Выполняем запрос
                features = datasource.select(action)
                
                # Преобразуем в нужный формат
                result = []
                for feature in features:
                    feature_data = {
                        'attributes': feature.properties,
                        'geometry': feature.geometry if return_geometry else None
                    }
                    result.append(feature_data)
                
                return result
            else:
                return []
                
        except Exception as e:
            print(f"Error querying database: {e}")
            return []

    def _handle_create_feature(self, body):
        """Обрабатывает запрос CreateFeature."""
        try:
            # Проверяем права доступа
            if hasattr(self.server, 'auth_manager') and self.server.auth_manager:
                auth_info = getattr(self, '_auth_info', {'authenticated': True, 'permissions': ['read']})
                if not self._check_permissions('CreateFeature', auth_info):
                    return self._create_unauthorized_fault('CreateFeature')
            
            # Получаем параметры запроса
            layer_id_elem = self._find_element(body, 'layerID')
            geometry_elem = self._find_element(body, 'geometry')
            attributes_elem = self._find_element(body, 'attributes')
            
            if layer_id_elem is None:
                return self._create_error_response("layerID parameter not found")
            
            layer_id = int(layer_id_elem.text)
            layers = self._get_layer_types()
            
            if layer_id >= len(layers):
                return self._create_error_response(f"Layer with ID {layer_id} not found")
            
            layer_name = layers[layer_id]['name']
            
            # Создаем объект Feature
            from Feature.Feature import Feature
            from Service.Action import Action
            
            # Парсим геометрию
            geometry = self._parse_geometry(geometry_elem)
            
            # Парсим атрибуты
            attributes = self._parse_attributes(attributes_elem)
            
            # Создаем объект Feature
            feature = Feature(None, geometry, attributes)
            
            # Создаем действие
            action = Action("create")
            action.feature = feature
            
            # Выполняем создание
            if layer_name in self.server.datasources:
                datasource = self.server.datasources[layer_name]
                if hasattr(datasource, 'create'):
                    result = datasource.create(action)
                    
                    # Создаем ответ
                    response = Element("CreateFeatureResponse", {
                        "xmlns": "http://www.esri.com/schemas/ArcGIS/10.3"
                    })
                    
                    return_elem = SubElement(response, "return")
                    
                    success_elem = SubElement(return_elem, "success")
                    success_elem.text = "true"
                    
                    feature_id_elem = SubElement(return_elem, "featureID")
                    feature_id_elem.text = str(action.id)
                    
                    message_elem = SubElement(return_elem, "message")
                    message_elem.text = "Feature created successfully"
                    
                    return self._create_soap_response(response)
                else:
                    return self._create_error_response("Layer is not writable")
            else:
                return self._create_error_response(f"Layer {layer_name} not found")
                
        except Exception as e:
            print(f"Error in CreateFeature: {e}")
            traceback.print_exc()
            return self._create_error_response(f"CreateFeature error: {str(e)}")

    def _handle_update_feature(self, body):
        """Обрабатывает запрос UpdateFeature."""
        try:
            # Проверяем права доступа
            if hasattr(self.server, 'auth_manager') and self.server.auth_manager:
                auth_info = getattr(self, '_auth_info', {'authenticated': True, 'permissions': ['read']})
                if not self._check_permissions('UpdateFeature', auth_info):
                    return self._create_unauthorized_fault('UpdateFeature')
            
            # Получаем параметры запроса
            layer_id_elem = self._find_element(body, 'layerID')
            feature_id_elem = self._find_element(body, 'featureID')
            geometry_elem = self._find_element(body, 'geometry')
            attributes_elem = self._find_element(body, 'attributes')
            
            if layer_id_elem is None or feature_id_elem is None:
                return self._create_error_response("layerID or featureID parameter not found")
            
            layer_id = int(layer_id_elem.text)
            feature_id = int(feature_id_elem.text)
            layers = self._get_layer_types()
            
            if layer_id >= len(layers):
                return self._create_error_response(f"Layer with ID {layer_id} not found")
            
            layer_name = layers[layer_id]['name']
            
            # Создаем объект Feature
            from Feature.Feature import Feature
            from Service.Action import Action
            
            # Парсим геометрию (если есть)
            geometry = None
            if geometry_elem is not None:
                geometry = self._parse_geometry(geometry_elem)
            
            # Парсим атрибуты (если есть)
            attributes = {}
            if attributes_elem is not None:
                attributes = self._parse_attributes(attributes_elem)
            
            # Создаем объект Feature
            feature = Feature(feature_id, geometry, attributes)
            
            # Создаем действие
            action = Action("update")
            action.feature = feature
            action.id = feature_id
            
            # Выполняем обновление
            if layer_name in self.server.datasources:
                datasource = self.server.datasources[layer_name]
                if hasattr(datasource, 'update'):
                    result = datasource.update(action)
                    
                    # Создаем ответ
                    response = Element("UpdateFeatureResponse", {
                        "xmlns": "http://www.esri.com/schemas/ArcGIS/10.3"
                    })
                    
                    return_elem = SubElement(response, "return")
                    
                    success_elem = SubElement(return_elem, "success")
                    success_elem.text = "true"
                    
                    message_elem = SubElement(return_elem, "message")
                    message_elem.text = "Feature updated successfully"
                    
                    return self._create_soap_response(response)
                else:
                    return self._create_error_response("Layer is not writable")
            else:
                return self._create_error_response(f"Layer {layer_name} not found")
                
        except Exception as e:
            print(f"Error in UpdateFeature: {e}")
            traceback.print_exc()
            return self._create_error_response(f"UpdateFeature error: {str(e)}")

    def _handle_delete_feature(self, body):
        """Обрабатывает запрос DeleteFeature."""
        try:
            # Проверяем права доступа
            if hasattr(self.server, 'auth_manager') and self.server.auth_manager:
                auth_info = getattr(self, '_auth_info', {'authenticated': True, 'permissions': ['read']})
                if not self._check_permissions('DeleteFeature', auth_info):
                    return self._create_unauthorized_fault('DeleteFeature')
            
            # Получаем параметры запроса
            layer_id_elem = self._find_element(body, 'layerID')
            feature_id_elem = self._find_element(body, 'featureID')
            
            if layer_id_elem is None or feature_id_elem is None:
                return self._create_error_response("layerID or featureID parameter not found")
            
            layer_id = int(layer_id_elem.text)
            feature_id = int(feature_id_elem.text)
            layers = self._get_layer_types()
            
            if layer_id >= len(layers):
                return self._create_error_response(f"Layer with ID {layer_id} not found")
            
            layer_name = layers[layer_id]['name']
            
            # Создаем действие
            from Service.Action import Action
            action = Action("delete")
            action.id = feature_id
            
            # Выполняем удаление
            if layer_name in self.server.datasources:
                datasource = self.server.datasources[layer_name]
                if hasattr(datasource, 'delete'):
                    result = datasource.delete(action)
                    
                    # Создаем ответ
                    response = Element("DeleteFeatureResponse", {
                        "xmlns": "http://www.esri.com/schemas/ArcGIS/10.3"
                    })
                    
                    return_elem = SubElement(response, "return")
                    
                    success_elem = SubElement(return_elem, "success")
                    success_elem.text = "true"
                    
                    message_elem = SubElement(return_elem, "message")
                    message_elem.text = "Feature deleted successfully"
                    
                    return self._create_soap_response(response)
                else:
                    return self._create_error_response("Layer is not writable")
            else:
                return self._create_error_response(f"Layer {layer_name} not found")
                
        except Exception as e:
            print(f"Error in DeleteFeature: {e}")
            traceback.print_exc()
            return self._create_error_response(f"DeleteFeature error: {str(e)}")

    def _parse_geometry(self, geometry_elem):
        """Парсит геометрию из XML элемента."""
        try:
            # Проверяем тип геометрии
            point_elem = geometry_elem.find('.//point')
            if point_elem is not None:
                x_elem = point_elem.find('.//x')
                y_elem = point_elem.find('.//y')
                if x_elem is not None and y_elem is not None:
                    return {
                        'type': 'Point',
                        'coordinates': [float(x_elem.text), float(y_elem.text)]
                    }
            
            # Можно добавить поддержку других типов геометрии
            return None
            
        except Exception as e:
            print(f"Error parsing geometry: {e}")
            return None

    def _parse_attributes(self, attributes_elem):
        """Парсит атрибуты из XML элемента."""
        try:
            attributes = {}
            attr_elems = attributes_elem.findall('.//Attribute')
            
            for attr_elem in attr_elems:
                name_elem = attr_elem.find('.//name')
                value_elem = attr_elem.find('.//value')
                
                if name_elem is not None and value_elem is not None:
                    attributes[name_elem.text] = value_elem.text
            
            return attributes
            
        except Exception as e:
            print(f"Error parsing attributes: {e}")
            return {}

    def _create_soap_response(self, body_content):
        """Создает SOAP-ответ в формате XML."""
        try:
            envelope = Element("soap:Envelope", {
                "xmlns:soap": "http://schemas.xmlsoap.org/soap/envelope/",
                "xmlns:xsi": "http://www.w3.org/2001/XMLSchema-instance",
                "xmlns:xsd": "http://www.w3.org/2001/XMLSchema",
                "xmlns:esri": "http://www.esri.com/schemas/ArcGIS/10.3",
                "xmlns:tns": "http://www.esri.com/schemas/ArcGIS/10.3"
            })
            body = SubElement(envelope, "soap:Body")
            body.append(body_content)
            return tostring(envelope, encoding="utf-8", xml_declaration=True, method="xml").decode("utf-8")
        except Exception as e:
            print(f"Error creating SOAP response: {e}")
            return self._create_error_response("Internal Server Error")

    def _handle_create_feature(self, body):
        """Обрабатывает запрос CreateFeature."""
        try:
            # Получаем параметры запроса
            layer_id_elem = self._find_element(body, 'layerID')
            if layer_id_elem is None:
                return self._create_error_response("layerID parameter not found")
            
            layer_id = int(layer_id_elem.text)
            
            # Получаем слой
            layers = self._get_layer_types()
            if layer_id >= len(layers):
                return self._create_error_response(f"Layer with ID {layer_id} not found")
            
            layer_name = layers[layer_id]['name']
            
            # Парсим атрибуты
            attributes = {}
            attrs_elem = self._find_element(body, 'attributes')
            if attrs_elem is not None:
                for child in attrs_elem:
                    if child.tag.endswith('}') or ':' in child.tag:
                        tag_name = child.tag.split('}')[-1]
                    else:
                        tag_name = child.tag
                    attributes[tag_name] = child.text if child.text else ""
            
            # Парсим геометрию
            geometry = {}
            geom_elem = self._find_element(body, 'geometry')
            if geom_elem is not None:
                point_elem = self._find_element(geom_elem, 'point')
                if point_elem is not None:
                    x_elem = self._find_element(point_elem, 'x')
                    y_elem = self._find_element(point_elem, 'y')
                    if x_elem is not None and y_elem is not None:
                        geometry['type'] = 'Point'
                        geometry['x'] = float(x_elem.text) if x_elem.text else 0.0
                        geometry['y'] = float(y_elem.text) if y_elem.text else 0.0
            
            # Вставляем в БД
            new_oid = self._insert_feature_to_database(layer_name, attributes, geometry)
            
            # Создаем ответ
            response = Element("CreateFeatureResponse", {
                "xmlns": "http://www.esri.com/schemas/ArcGIS/10.3"
            })
            
            return_elem = SubElement(response, "return")
            
            oid_elem = SubElement(return_elem, "OID")
            oid_elem.text = str(new_oid)
            
            success_elem = SubElement(return_elem, "success")
            success_elem.text = "true"
            
            global_id_elem = SubElement(return_elem, "globalID")
            global_id_elem.text = ""
            
            return self._create_soap_response(response)
            
        except Exception as e:
            print(f"Error in CreateFeature: {e}")
            traceback.print_exc()
            return self._create_error_response(str(e))

    def _handle_update_feature(self, body):
        """Обрабатывает запрос UpdateFeature."""
        try:
            # Получаем параметры запроса
            layer_id_elem = self._find_element(body, 'layerID')
            oid_elem = self._find_element(body, 'OID')
            
            if layer_id_elem is None:
                return self._create_error_response("layerID parameter not found")
            if oid_elem is None:
                return self._create_error_response("OID parameter not found")
            
            layer_id = int(layer_id_elem.text)
            oid = int(oid_elem.text)
            
            # Получаем слой
            layers = self._get_layer_types()
            if layer_id >= len(layers):
                return self._create_error_response(f"Layer with ID {layer_id} not found")
            
            layer_name = layers[layer_id]['name']
            
            # Парсим атрибуты
            attributes = {}
            attrs_elem = self._find_element(body, 'attributes')
            if attrs_elem is not None:
                for child in attrs_elem:
                    if child.tag.endswith('}') or ':' in child.tag:
                        tag_name = child.tag.split('}')[-1]
                    else:
                        tag_name = child.tag
                    attributes[tag_name] = child.text if child.text else ""
            
            # Парсим геометрию
            geometry = {}
            geom_elem = self._find_element(body, 'geometry')
            if geom_elem is not None:
                point_elem = self._find_element(geom_elem, 'point')
                if point_elem is not None:
                    x_elem = self._find_element(point_elem, 'x')
                    y_elem = self._find_element(point_elem, 'y')
                    if x_elem is not None and y_elem is not None:
                        geometry['type'] = 'Point'
                        geometry['x'] = float(x_elem.text) if x_elem.text else 0.0
                        geometry['y'] = float(y_elem.text) if y_elem.text else 0.0
            
            # Обновляем в БД
            updated = self._update_feature_in_database(layer_name, oid, attributes, geometry)
            
            # Создаем ответ
            response = Element("UpdateFeatureResponse", {
                "xmlns": "http://www.esri.com/schemas/ArcGIS/10.3"
            })
            
            return_elem = SubElement(response, "return")
            
            oid_resp_elem = SubElement(return_elem, "OID")
            oid_resp_elem.text = str(oid)
            
            success_elem = SubElement(return_elem, "success")
            success_elem.text = "true" if updated else "false"
            
            global_id_elem = SubElement(return_elem, "globalID")
            global_id_elem.text = ""
            
            return self._create_soap_response(response)
            
        except Exception as e:
            print(f"Error in UpdateFeature: {e}")
            traceback.print_exc()
            return self._create_error_response(str(e))

    def _handle_delete_feature(self, body):
        """Обрабатывает запрос DeleteFeature."""
        try:
            # Получаем параметры запроса
            layer_id_elem = self._find_element(body, 'layerID')
            oid_elem = self._find_element(body, 'OID')
            
            if layer_id_elem is None:
                return self._create_error_response("layerID parameter not found")
            if oid_elem is None:
                return self._create_error_response("OID parameter not found")
            
            layer_id = int(layer_id_elem.text)
            oid = int(oid_elem.text)
            
            # Получаем слой
            layers = self._get_layer_types()
            if layer_id >= len(layers):
                return self._create_error_response(f"Layer with ID {layer_id} not found")
            
            layer_name = layers[layer_id]['name']
            
            # Удаляем из БД
            deleted = self._delete_feature_from_database(layer_name, oid)
            
            # Создаем ответ
            response = Element("DeleteFeatureResponse", {
                "xmlns": "http://www.esri.com/schemas/ArcGIS/10.3"
            })
            
            return_elem = SubElement(response, "return")
            
            oid_resp_elem = SubElement(return_elem, "OID")
            oid_resp_elem.text = str(oid)
            
            success_elem = SubElement(return_elem, "success")
            success_elem.text = "true" if deleted else "false"
            
            global_id_elem = SubElement(return_elem, "globalID")
            global_id_elem.text = ""
            
            return self._create_soap_response(response)
            
        except Exception as e:
            print(f"Error in DeleteFeature: {e}")
            traceback.print_exc()
            return self._create_error_response(str(e))

    def _insert_feature_to_database(self, layer_name, attributes, geometry):
        """Вставляет новый объект в БД. Переопределяется в подклассах."""
        # Эта функция должна быть переопределена в реальной реализации
        # Возвращает OID вставленного объекта
        raise NotImplementedError("_insert_feature_to_database must be implemented")

    def _update_feature_in_database(self, layer_name, oid, attributes, geometry):
        """Обновляет объект в БД. Переопределяется в подклассах."""
        # Эта функция должна быть переопределена в реальной реализации
        # Возвращает True если обновление успешно, False если объект не найден
        raise NotImplementedError("_update_feature_in_database must be implemented")

    def _delete_feature_from_database(self, layer_name, oid):
        """Удаляет объект из БД. Переопределяется в подклассах."""
        # Эта функция должна быть переопределена в реальной реализации
        # Возвращает True если удаление успешно, False если объект не найден
        raise NotImplementedError("_delete_feature_from_database must be implemented")

    def getCapabilities(self):
        """Возвращает описание возможностей сервера в формате SOAP."""
        try:
            capabilities = Element("GetCapabilitiesResponse", {
                "xmlns": "http://www.esri.com/arcgis/services"
            })
            capabilities.text = "GetMap, GetFeature, GetLegend"
            return self._create_soap_response(capabilities)
        except Exception as e:
            print("Ошибка в getCapabilities:")
            traceback.print_exc()
            return self._create_error_response(str(e))

    def getMap(self, parameters):
        """Возвращает карту на основе переданных параметров в формате SOAP."""
        try:
            map_response = Element("GetMapResponse", {
                "xmlns": "http://www.esri.com/arcgis/services"
            })
            map_response.text = f"Generated map with parameters: {parameters}"
            return self._create_soap_response(map_response)
        except Exception as e:
            print("Ошибка в getMap:")
            traceback.print_exc()
            return self._create_error_response(str(e))

    def getFeature(self, parameters):
        """Возвращает данные объекта на основе переданных параметров в формате SOAP."""
        try:
            feature_response = Element("GetFeatureResponse", {
                "xmlns": "http://www.esri.com/arcgis/services"
            })
            feature_response.text = f"Feature data with parameters: {parameters}"
            return self._create_soap_response(feature_response)
        except Exception as e:
            print("Ошибка в getFeature:")
            traceback.print_exc()
            return self._create_error_response(str(e))

    def getLegend(self):
        """Возвращает легенду карты в формате SOAP."""
        try:
            legend_response = Element("GetLegendResponse", {
                "xmlns": "http://www.esri.com/arcgis/services"
            })
            legend_response.text = "Map legend content"
            return self._create_soap_response(legend_response)
        except Exception as e:
            print("Ошибка в getLegend:")
            traceback.print_exc()
            return self._create_error_response(str(e))

    def _create_error_response(self, error_message):
        """Создает SOAP-ответ с ошибкой."""
        try:
            envelope = Element("soap:Envelope", {
                "xmlns:soap": "http://schemas.xmlsoap.org/soap/envelope/",
                "xmlns:xsi": "http://www.w3.org/2001/XMLSchema-instance",
                "xmlns:xsd": "http://www.w3.org/2001/XMLSchema",
                "xmlns:tns": "http://www.esri.com/schemas/ArcGIS/10.3"
            })
            body = SubElement(envelope, "soap:Body")
            fault = SubElement(body, "soap:Fault")
            fault_code = SubElement(fault, "faultcode")
            fault_code.text = "soap:Server"
            fault_string = SubElement(fault, "faultstring")
            fault_string.text = error_message
            detail = SubElement(fault, "detail")
            error_detail = SubElement(detail, "tns:Error")
            error_detail.text = error_message
            return tostring(envelope, encoding="utf-8", xml_declaration=True, method="xml").decode("utf-8")
        except Exception as e:
            print(f"Error creating error response: {e}")
            fallback = Element("soap:Fault")
            fault_code = SubElement(fallback, "faultcode")
            fault_code.text = "soap:Server"
            fault_string = SubElement(fallback, "faultstring")
            fault_string.text = error_message
            return tostring(fallback, encoding="utf-8", xml_declaration=True, method="xml").decode("utf-8")
