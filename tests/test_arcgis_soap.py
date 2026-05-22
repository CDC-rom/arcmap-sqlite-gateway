import unittest
from xml.etree.ElementTree import fromstring, Element, SubElement
import re

from Service.ArcGISSOAP import ArcGISSOAP


class DummyDataSource:
    def __init__(self, name="layer1", geometry_type="esriGeometryPoint", fields=None):
        self.name = name
        self.geometry_type = geometry_type
        self._fields = fields or []

    def get_fields(self):
        return self._fields


class DummyServer:
    def __init__(self, datasources=None):
        self.datasources = datasources or {}
        self.metadata = {"url": "http://localhost:8888"}


def strip_namespace(elem):
    """Remove namespace from ElementTree elements for easier testing."""
    if elem.tag.startswith('{'):
        elem.tag = elem.tag.split('}', 1)[1]
    for child in elem:
        strip_namespace(child)


class ArcGISSOAPTests(unittest.TestCase):
    def setUp(self):
        # Create datasource with test fields
        test_fields = [
            {
                "name": "OBJECTID",
                "type": "esriFieldTypeInteger",
                "alias": "Object ID",
                "length": None,
                "nullable": False,
                "editable": False,
                "required": True,
                "is_geometry": False
            },
            {
                "name": "NAME",
                "type": "esriFieldTypeString",
                "alias": "Feature Name",
                "length": 255,
                "nullable": True,
                "editable": True,
                "required": False,
                "is_geometry": False
            }
        ]
        ds = DummyDataSource(fields=test_fields)
        self.server = DummyServer(datasources={"layer1": ds})
        self.soap = ArcGISSOAP(self.server)
        
        # Create empty datasource for default value tests
        empty_ds = DummyDataSource()
        self.empty_server = DummyServer(datasources={"layer1": empty_ds})
        self.empty_soap = ArcGISSOAP(self.empty_server)

    def _make_body(self, operation, elements=None):
        body = Element("Body")
        op = Element(operation)
        if elements:
            for name, text in elements.items():
                e = SubElement(op, name)
                e.text = str(text)
        body.append(op)
        return body
    
    def _strip_namespace(self, elem):
        """Remove namespace from element and all children for easier XPath queries."""
        if elem.tag.startswith('{'):
            elem.tag = elem.tag.split('}', 1)[1]
        for child in elem:
            self._strip_namespace(child)

    def test_get_service_info_layer_info_structure(self):
        """Test that GetServiceInfo returns LayerInfo with basic elements (no Fields)."""
        body = self._make_body("GetServiceInfo", {"serviceName": "whatever"})
        xml = self.soap._handle_get_service_info(body)
        root = fromstring(xml)
        self._strip_namespace(root)
        
        # Ensure Layers element exists
        layers = root.findall(".//LayerInfo")
        self.assertTrue(len(layers) >= 1, "LayerInfo element missing")
        
        # Each LayerInfo should have ID, Name, Type, GeometryType but NO Fields
        for li in layers:
            id_elem = li.find("ID")
            name_elem = li.find("Name")
            type_elem = li.find("Type")
            geom_elem = li.find("GeometryType")
            fields = li.find("Fields")
            
            self.assertIsNotNone(id_elem, "ID element missing")
            self.assertIsNotNone(name_elem, "Name element missing")
            self.assertIsNotNone(type_elem, "Type element missing")
            self.assertIsNotNone(geom_elem, "GeometryType element missing")
            self.assertIsNone(fields, "Fields element should NOT be in GetServiceInfo LayerInfo")
    
    def test_get_layer_info_field_metadata_extended_properties(self):
        """Test that GetLayerInfo FieldInfo includes all metadata: Length, Nullable, Editable, Required."""
        body = self._make_body("GetLayerInfo", {"layerID": "0"})
        xml = self.soap._handle_get_layer_info(body)
        root = fromstring(xml)
        self._strip_namespace(root)
        
        # Get the second FieldInfo (NAME field with length)
        field_infos = root.findall(".//FieldInfo")
        self.assertTrue(len(field_infos) >= 2, "Expected at least 2 fields")
        
        field_info = field_infos[1]  # NAME field
        
        # Check all required elements exist
        name_elem = field_info.find("Name")
        type_elem = field_info.find("Type")
        alias_elem = field_info.find("Alias")
        
        self.assertIsNotNone(name_elem, "Name element missing")
        self.assertIsNotNone(type_elem, "Type element missing")
        self.assertIsNotNone(alias_elem, "Alias element missing")
        self.assertEqual(name_elem.text, "NAME", "Should be NAME field")
        
        # Check extended metadata elements exist
        length_elem = field_info.find("Length")
        nullable_elem = field_info.find("Nullable")
        editable_elem = field_info.find("Editable")
        required_elem = field_info.find("Required")
        
        # Field with length should have Length element (NAME field has length 255)
        self.assertIsNotNone(length_elem, "Length element missing for string field")
        self.assertEqual(length_elem.text, "255", "Length should be 255 for NAME field")
        
        # Should have boolean metadata
        self.assertIsNotNone(nullable_elem, "Nullable element missing")
        self.assertIsNotNone(editable_elem, "Editable element missing")
        self.assertIsNotNone(required_elem, "Required element missing")
        
        # Check boolean format (should be "true" or "false")
        self.assertIn(nullable_elem.text, ("true", "false"), "Nullable should be boolean")
        self.assertIn(editable_elem.text, ("true", "false"), "Editable should be boolean")
        self.assertIn(required_elem.text, ("true", "false"), "Required should be boolean")

    def test_get_layer_info_defaults_to_empty_strings(self):
        """Test that GetLayerInfo returns proper elements with default values."""
        # Use empty datasource (no fields, default geometry type)
        body = self._make_body("GetLayerInfo", {"layerID": "0"})
        xml = self.empty_soap._handle_get_layer_info(body)
        root = fromstring(xml)
        self._strip_namespace(root)
        
        name_elem = root.find(".//Name")
        geom_type_elem = root.find(".//GeometryType")
        
        self.assertIsNotNone(name_elem, "Name element not found")
        self.assertIsNotNone(geom_type_elem, "GeometryType element not found")
        
        # Name should have some value (layer name from datasource = "layer1")
        self.assertIsNotNone(name_elem.text, "Name should not be None")
        self.assertEqual(name_elem.text, "layer1", "Name should be layer1")
        
        # GeometryType defaults to Point
        geom_type = geom_type_elem.text if geom_type_elem.text else ""
        self.assertEqual(geom_type, "Point", "GeometryType defaults to Point")

    def test_query_feature_outputs_geometry_tag_even_without_data(self):
        """Test that Query returns geometry element even when no geometry data."""
        # monkeypatch _query_database to return feature with no geometry
        def fake_query(layer, where, out, retgeom):
            return [{"attributes": {"foo": "bar"}, "geometry": None}]

        self.soap._query_database = fake_query
        body = self._make_body("Query", {"layerID": "0", "returnGeometry": "true"})
        xml = self.soap._handle_query(body)
        root = fromstring(xml)
        self._strip_namespace(root)
        
        geom = root.find(".//geometry")
        self.assertIsNotNone(geom, "geometry element should be present")
        # should not have point or extent children
        self.assertIsNone(geom.find("point"))
        self.assertIsNone(geom.find("extent"))

    def test_query_feature_attributes_flat_structure(self):
        """Test that Query returns flat attribute elements instead of Attribute wrappers."""
        def fake_query(layer, where, out, retgeom):
            return [{"attributes": {"OBJECTID": 1, "NAME": "Test"}, "geometry": None}]

        self.soap._query_database = fake_query
        body = self._make_body("Query", {"layerID": "0", "returnGeometry": "false"})
        xml = self.soap._handle_query(body)
        root = fromstring(xml)
        self._strip_namespace(root)

        attrs = root.find(".//attributes")
        self.assertIsNotNone(attrs, "attributes element should exist")
        self.assertIsNotNone(attrs.find("OBJECTID"), "OBJECTID field should be returned directly")
        self.assertIsNotNone(attrs.find("NAME"), "NAME field should be returned directly")
        self.assertIsNone(attrs.find("Attribute"), "Attribute wrapper should not be present")

    def test_process_soap_request_recognizes_namespaced_operation(self):
        """Test that SOAP request parsing works with namespaced operation tags."""
        xml = '''<?xml version="1.0" encoding="UTF-8"?>
<soap:Envelope xmlns:soap="http://schemas.xmlsoap.org/soap/envelope/">
    <soap:Body>
        <tns:GetServiceInfo xmlns:tns="http://www.esri.com/schemas/ArcGIS/10.3">
            <tns:serviceName>MapServer</tns:serviceName>
        </tns:GetServiceInfo>
    </soap:Body>
</soap:Envelope>'''
        response = self.soap.process_soap_request(xml)
        root = fromstring(response)
        self.assertEqual(root.tag, '{http://schemas.xmlsoap.org/soap/envelope/}Envelope')
        body = root.find('.//{http://schemas.xmlsoap.org/soap/envelope/}Body')
        self.assertIsNotNone(body, 'SOAP Body should exist in response')
        self.assertIsNotNone(body.find('.//{http://www.esri.com/schemas/ArcGIS/10.3}GetServiceInfoResponse'),
                             'Response should contain GetServiceInfoResponse')

    def test_query_with_no_layers_still_returns_layers_element(self):
        """Test that Query returns Layers element even when no layers exist."""
        # create soap with no datasources
        empty_server = DummyServer(datasources={})
        soap2 = ArcGISSOAP(empty_server)
        body = self._make_body("GetServiceInfo", {"serviceName": "whatever"})
        xml = soap2._handle_get_service_info(body)
        root = fromstring(xml)
        self._strip_namespace(root)
        
        layers = root.find(".//Layers")
        self.assertIsNotNone(layers, "Layers element must exist even if empty")
        # should be empty
        self.assertEqual(len(list(layers)), 0)
    
    def test_layer_info_includes_field_metadata(self):
        """Test that GetLayerInfo also returns complete field metadata."""
        body = self._make_body("GetLayerInfo", {"layerID": "0"})
        xml = self.soap._handle_get_layer_info(body)
        root = fromstring(xml)
        self._strip_namespace(root)
        
        # Find Fields element
        fields_elem = root.find(".//Fields")
        self.assertIsNotNone(fields_elem, "Fields element missing")
        
        # Should have 2 FieldInfo elements
        field_infos = fields_elem.findall("FieldInfo")
        self.assertEqual(len(field_infos), 2, "Expected 2 FieldInfo elements")
        
        # Check first field (OBJECTID)
        first_field = field_infos[0]
        name = first_field.find("Name")
        self.assertEqual(name.text, "OBJECTID", "First field should be OBJECTID")
        
        type_elem = first_field.find("Type")
        self.assertEqual(type_elem.text, "esriFieldTypeInteger", "OBJECTID should be integer")
        
        # OBJECTID should not be editable
        editable = first_field.find("Editable")
        self.assertEqual(editable.text, "false", "OBJECTID should not be editable")
        
        # OBJECTID should be required
        required = first_field.find("Required")
        self.assertEqual(required.text, "true", "OBJECTID should be required")
    
    def test_get_layer_info_string_field_has_length_metadata(self):
        """Test that GetLayerInfo string fields include Length metadata."""
        body = self._make_body("GetLayerInfo", {"layerID": "0"})
        xml = self.soap._handle_get_layer_info(body)
        root = fromstring(xml)
        self._strip_namespace(root)
        
        # Find the NAME field (second field, string type with length 255)
        field_infos = root.findall(".//FieldInfo")
        self.assertTrue(len(field_infos) >= 2, "Expected at least 2 fields")
        name_field = field_infos[1]  # Second field is NAME
        
        name_elem = name_field.find("Name")
        self.assertEqual(name_elem.text, "NAME", "Second field should be NAME")
        
        # String field should have Length element
        length_elem = name_field.find("Length")
        self.assertIsNotNone(length_elem, "String field should have Length element")
        self.assertEqual(length_elem.text, "255", "NAME field length should be 255")
        
        # String field should be nullable and editable in our test data
        nullable_elem = name_field.find("Nullable")
        editable_elem = name_field.find("Editable")
        
        self.assertEqual(nullable_elem.text, "true", "NAME field should be nullable")
        self.assertEqual(editable_elem.text, "true", "NAME field should be editable")
    
    def test_get_layer_info_integer_field_no_length_metadata(self):
        """Test that GetLayerInfo integer fields without length don't output Length element with None value."""
        body = self._make_body("GetLayerInfo", {"layerID": "0"})
        xml = self.soap._handle_get_layer_info(body)
        root = fromstring(xml)
        self._strip_namespace(root)
        
        # Find the OBJECTID field (first field, integer type with length=None)
        field_infos = root.findall(".//FieldInfo")
        self.assertTrue(len(field_infos) >= 1, "Expected at least 1 field")
        objectid_field = field_infos[0]
        
        # Integer field without explicit length should not have Length element
        length_elem = objectid_field.find("Length")
        # If Length element exists, it must not be None (which would be converted to "None" string)
        if length_elem is not None:
            # For numeric fields with no length, we shouldn't output "None" as text
            self.assertNotEqual(length_elem.text, "None", 
                              "Length element should not contain string 'None'")
    
    def test_get_service_info_returns_correct_layer_list(self):
        """Test that GetServiceInfo returns correct layer list from server.datasources."""
        # Create server with multiple datasources
        ds1 = DummyDataSource(name="layer1", geometry_type="esriGeometryPoint")
        ds2 = DummyDataSource(name="layer2", geometry_type="esriGeometryPolyline")
        server = DummyServer(datasources={"layer1": ds1, "layer2": ds2})
        soap = ArcGISSOAP(server)
        
        body = self._make_body("GetServiceInfo", {"serviceName": "test"})
        xml = soap._handle_get_service_info(body)
        root = fromstring(xml)
        self._strip_namespace(root)
        
        layers = root.findall(".//LayerInfo")
        self.assertEqual(len(layers), 2, "Should have 2 LayerInfo elements")
        
        # Check first layer
        layer1 = layers[0]
        id_elem = layer1.find("ID")
        self.assertEqual(id_elem.text, "0", "First layer ID should be 0")
        name_elem = layer1.find("Name")
        self.assertEqual(name_elem.text, "layer1", "First layer name should be layer1")
        geom_elem = layer1.find("GeometryType")
        self.assertEqual(geom_elem.text, "Point", "First layer geometry type should be Point")
        
        # Check second layer
        layer2 = layers[1]
        id_elem2 = layer2.find("ID")
        self.assertEqual(id_elem2.text, "1", "Second layer ID should be 1")
        name_elem2 = layer2.find("Name")
        self.assertEqual(name_elem2.text, "layer2", "Second layer name should be layer2")
        geom_elem2 = layer2.find("GeometryType")
        self.assertEqual(geom_elem2.text, "Polyline", "Second layer geometry type should be Polyline")

    def test_create_feature_returns_soap_response(self):
        """Test that CreateFeature returns proper SOAP response with new OID."""
        # Mock the database insert
        inserted_oid = 99
        def fake_insert(layer, attributes, geometry):
            return inserted_oid
        
        self.soap._insert_feature_to_database = fake_insert
        
        # Create request with feature data
        body = Element("Body")
        op = Element("CreateFeature")
        layer_id_elem = SubElement(op, "layerID")
        layer_id_elem.text = "0"
        
        # Add attributes
        attrs_elem = SubElement(op, "attributes")
        name_elem = SubElement(attrs_elem, "NAME")
        name_elem.text = "New Feature"
        
        # Add geometry (point)
        geom_elem = SubElement(op, "geometry")
        point_elem = SubElement(geom_elem, "point")
        x_elem = SubElement(point_elem, "x")
        x_elem.text = "37.5"
        y_elem = SubElement(point_elem, "y")
        y_elem.text = "55.5"
        
        body.append(op)
        
        xml = self.soap._handle_create_feature(body)
        root = fromstring(xml)
        self._strip_namespace(root)
        
        # Check response structure
        result_elem = root.find(".//return")
        self.assertIsNotNone(result_elem, "return element not found")
        
        oid_elem = result_elem.find("OID")
        self.assertIsNotNone(oid_elem, "OID element not found in response")
        self.assertEqual(oid_elem.text, str(inserted_oid), f"OID should be {inserted_oid}")
        
        # Check success flag
        success_elem = result_elem.find("success")
        self.assertIsNotNone(success_elem, "success element not found")
        self.assertEqual(success_elem.text, "true", "Operation should return success=true")

    def test_create_feature_with_required_attributes(self):
        """Test that CreateFeature includes all required response elements."""
        def fake_insert(layer, attributes, geometry):
            return 42
        
        self.soap._insert_feature_to_database = fake_insert
        
        body = self._make_body("CreateFeature", {"layerID": "0"})
        attrs_elem = SubElement(body.find("CreateFeature"), "attributes")
        name_elem = SubElement(attrs_elem, "NAME")
        name_elem.text = "Test"
        
        xml = self.soap._handle_create_feature(body)
        root = fromstring(xml)
        self._strip_namespace(root)
        
        return_elem = root.find(".//return")
        
        # Verify all required elements
        self.assertIsNotNone(return_elem.find("OID"), "Missing OID element")
        self.assertIsNotNone(return_elem.find("success"), "Missing success element")
        self.assertIsNotNone(return_elem.find("globalID"), "Missing globalID element")

    def test_update_feature_returns_soap_response(self):
        """Test that UpdateFeature returns proper SOAP response."""
        # Mock the database update
        def fake_update(layer, oid, attributes, geometry):
            return True
        
        self.soap._update_feature_in_database = fake_update
        
        # Create request with feature data
        body = Element("Body")
        op = Element("UpdateFeature")
        layer_id_elem = SubElement(op, "layerID")
        layer_id_elem.text = "0"
        oid_elem = SubElement(op, "OID")
        oid_elem.text = "42"
        
        # Add attributes to update
        attrs_elem = SubElement(op, "attributes")
        name_elem = SubElement(attrs_elem, "NAME")
        name_elem.text = "Updated Name"
        
        body.append(op)
        
        xml = self.soap._handle_update_feature(body)
        root = fromstring(xml)
        self._strip_namespace(root)
        
        # Check response structure
        result_elem = root.find(".//return")
        self.assertIsNotNone(result_elem, "return element not found")
        
        success_elem = result_elem.find("success")
        self.assertIsNotNone(success_elem, "success element not found")
        self.assertEqual(success_elem.text, "true", "Operation should return success=true")
        
        # Check OID in response
        resp_oid_elem = result_elem.find("OID")
        self.assertIsNotNone(resp_oid_elem, "OID element not found in response")
        self.assertEqual(resp_oid_elem.text, "42", "Response should echo back the OID")

    def test_update_feature_with_geometry_change(self):
        """Test that UpdateFeature handles geometry updates."""
        def fake_update(layer, oid, attributes, geometry):
            return True
        
        self.soap._update_feature_in_database = fake_update
        
        body = Element("Body")
        op = Element("UpdateFeature")
        layer_id_elem = SubElement(op, "layerID")
        layer_id_elem.text = "0"
        oid_elem = SubElement(op, "OID")
        oid_elem.text = "10"
        
        # Add geometry change
        geom_elem = SubElement(op, "geometry")
        point_elem = SubElement(geom_elem, "point")
        x_elem = SubElement(point_elem, "x")
        x_elem.text = "38.0"
        y_elem = SubElement(point_elem, "y")
        y_elem.text = "56.0"
        
        body.append(op)
        
        xml = self.soap._handle_update_feature(body)
        root = fromstring(xml)
        self._strip_namespace(root)
        
        result_elem = root.find(".//return")
        success_elem = result_elem.find("success")
        self.assertEqual(success_elem.text, "true", "Geometry update should succeed")

    def test_delete_feature_returns_soap_response(self):
        """Test that DeleteFeature returns proper SOAP response."""
        # Mock the database delete
        def fake_delete(layer, oid):
            return True
        
        self.soap._delete_feature_from_database = fake_delete
        
        # Create request
        body = Element("Body")
        op = Element("DeleteFeature")
        layer_id_elem = SubElement(op, "layerID")
        layer_id_elem.text = "0"
        oid_elem = SubElement(op, "OID")
        oid_elem.text = "42"
        
        body.append(op)
        
        xml = self.soap._handle_delete_feature(body)
        root = fromstring(xml)
        self._strip_namespace(root)
        
        # Check response structure
        result_elem = root.find(".//return")
        self.assertIsNotNone(result_elem, "return element not found")
        
        success_elem = result_elem.find("success")
        self.assertIsNotNone(success_elem, "success element not found")
        self.assertEqual(success_elem.text, "true", "Operation should return success=true")
        
        # Check OID in response
        resp_oid_elem = result_elem.find("OID")
        self.assertIsNotNone(resp_oid_elem, "OID element not found in response")
        self.assertEqual(resp_oid_elem.text, "42", "Response should echo back the OID")

    def test_delete_feature_requires_oid(self):
        """Test that DeleteFeature requires OID parameter."""
        def fake_delete(layer, oid):
            return True
        
        self.soap._delete_feature_from_database = fake_delete
        
        # Create request without OID (should fail)
        body = Element("Body")
        op = Element("DeleteFeature")
        layer_id_elem = SubElement(op, "layerID")
        layer_id_elem.text = "0"
        # Missing OID!
        
        body.append(op)
        
        xml = self.soap._handle_delete_feature(body)
        root = fromstring(xml)
        self._strip_namespace(root)
        
        # Should return error in SOAP Fault
        fault = root.find(".//Fault")
        if fault is not None:
            fault_string = fault.find("faultstring")
            self.assertIsNotNone(fault_string, "Fault should have faultstring")
        else:
            # Or it might return error in result
            result_elem = root.find(".//return")
            error_elem = result_elem.find("error")
            self.assertIsNotNone(error_elem, "Should indicate error when OID missing")

    def test_create_feature_error_handling(self):
        """Test that CreateFeature handles database errors properly."""
        # Mock a database error
        def fake_insert_error(layer, attributes, geometry):
            raise Exception("Database connection failed")
        
        self.soap._insert_feature_to_database = fake_insert_error
        
        body = self._make_body("CreateFeature", {"layerID": "0"})
        xml = self.soap._handle_create_feature(body)
        root = fromstring(xml)
        self._strip_namespace(root)
        
        # Should return SOAP Fault
        fault = root.find(".//Fault")
        self.assertIsNotNone(fault, "Should return SOAP Fault on error")
        
        fault_code = fault.find("faultcode")
        self.assertIsNotNone(fault_code, "Fault should have faultcode")
        self.assertEqual(fault_code.text, "soap:Server", "Error should be Server fault")

    def test_update_feature_error_handling(self):
        """Test that UpdateFeature handles errors when OID not found."""
        # Mock no-rows-affected scenario
        def fake_update_no_affect(layer, oid, attributes, geometry):
            return False  # No rows were updated
        
        self.soap._update_feature_in_database = fake_update_no_affect
        
        body = Element("Body")
        op = Element("UpdateFeature")
        layer_id_elem = SubElement(op, "layerID")
        layer_id_elem.text = "0"
        oid_elem = SubElement(op, "OID")
        oid_elem.text = "9999"  # Non-existent OID
        
        body.append(op)
        
        xml = self.soap._handle_update_feature(body)
        root = fromstring(xml)
        self._strip_namespace(root)
        
        result_elem = root.find(".//return")
        success_elem = result_elem.find("success")
        self.assertEqual(success_elem.text, "false", "Should return success=false when OID not found")

    def test_operations_return_correct_soap_envelope(self):
        """Test that all edit operations return proper SOAP envelope structure."""
        def fake_insert(layer, attributes, geometry):
            return 1
        
        self.soap._insert_feature_to_database = fake_insert
        
        body = self._make_body("CreateFeature", {"layerID": "0"})
        xml = self.soap._handle_create_feature(body)
        
        # Parse and check envelope structure
        self.assertTrue(xml.startswith('<?xml version'), "Should have XML declaration")
        self.assertIn('soap:Envelope', xml, "Should have SOAP Envelope")
        self.assertIn('soap:Body', xml, "Should have SOAP Body")
        self.assertIn('xmlns:soap="http://schemas.xmlsoap.org/soap/envelope/"', xml, 
                      "Should have correct SOAP namespace")
        self.assertIn('xmlns:tns="http://www.esri.com/schemas/ArcGIS/10.3"', xml,
                      "Should have correct ArcGIS namespace")


if __name__ == "__main__":
    unittest.main()
