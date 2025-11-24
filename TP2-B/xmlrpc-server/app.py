import firebase_admin
import os
from pathlib import Path
from firebase_admin import credentials, firestore
from xmlrpc.server import SimpleXMLRPCServer
from xmlrpc.server import SimpleXMLRPCRequestHandler
import csv
from xml.dom import minidom
import xml.etree.ElementTree as ET
from lxml import etree

cred = credentials.Certificate("chave-privada.json")
firebase_admin.initialize_app(cred)

DATAFOLDER = Path("/data/shared").resolve()

# Inicializa o Firestore
db_firestore = firestore.client()

# Configuração do servidor XML-RPC
class RequestHandler(SimpleXMLRPCRequestHandler):
    rpc_paths = ('/RPC2',)

server = SimpleXMLRPCServer(('0.0.0.0', 8000), requestHandler=RequestHandler)
server.register_introspection_functions()

def csv_to_xml(csv_filename):
    try:
        # valida nome simples (evita path traversal)
        if Path(csv_filename).name != csv_filename:
            return "Erro: nome de arquivo inválido"
        csv_file = DATAFOLDER / csv_filename
        if not csv_file.exists():
            return "Erro: arquivo CSV não encontrado"

        with csv_file.open('r', encoding='utf-8', newline='') as f:
            reader = csv.DictReader(f)
            root = ET.Element("data")
            for row in reader:
                record_el = ET.SubElement(root, "record")
                for key, value in row.items():
                    tag = key.strip().replace(" ", "_")
                    ET.SubElement(record_el, tag).text = (value or "").strip()

        tree = ET.ElementTree(root)
        # Tenta identação nativa (Python 3.9+)
        try:
            ET.indent(tree, space="  ")
            xml_bytes = ET.tostring(root, encoding='utf-8')
        except AttributeError:
            # Fallback para pretty print usando minidom
            rough = ET.tostring(root, encoding='utf-8')
            reparsed = minidom.parseString(rough)
            xml_bytes = reparsed.toprettyxml(indent="  ", encoding="utf-8")

        xml_file = DATAFOLDER / (csv_file.stem + ".xml")
        with xml_file.open('wb') as out:
            out.write(xml_bytes)

        xml_str = xml_bytes.decode('utf-8')
        
        return xml_to_xsd(xml_file.name)
    except Exception as e:
        return f"Erro ao converter CSV: {e}"
    
def xml_to_xsd(xml_filename):
    try:
        xml_file = DATAFOLDER / xml_filename
        if not xml_file.exists():
            return "Erro: arquivo XML não encontrado"

        ordered_tags = []  # preserves first appearance
        seen = set()
        for event, elem in etree.iterparse(str(xml_file), events=("end",)):
            if elem.tag == "record":
                for child in elem:
                    t = child.tag
                    if t not in seen:
                        seen.add(t)
                        ordered_tags.append(t)
                # free memory for large files
                elem.clear()

        if os.environ.get("XSD_SORT", "").lower() == "alpha":
            ordered_tags = sorted(ordered_tags)

        xsd_root = ET.Element("xs:schema", attrib={
            "xmlns:xs": "http://www.w3.org/2001/XMLSchema"
        })

        record_el = ET.SubElement(xsd_root, "xs:element", attrib={"name": "data"})
        complex_type = ET.SubElement(record_el, "xs:complexType")
        sequence = ET.SubElement(complex_type, "xs:sequence")

        record_type = ET.SubElement(sequence, "xs:element", attrib={
            "name": "record",
            "minOccurs": "0",
            "maxOccurs": "unbounded"
        })
        rec_complex = ET.SubElement(record_type, "xs:complexType")
        rec_seq = ET.SubElement(rec_complex, "xs:sequence")

        for tag in ordered_tags:
            ET.SubElement(rec_seq, "xs:element", attrib={
                "name": tag,
                "type": "xs:string",
                "minOccurs": "0"
            })

        xsd_file = DATAFOLDER / (xml_file.stem + ".xsd")
        tree = ET.ElementTree(xsd_root)
        try:
            ET.indent(tree, space="  ")
            tree.write(xsd_file, encoding='utf-8', xml_declaration=True)
            xsd_str = ET.tostring(xsd_root, encoding='utf-8').decode('utf-8')
        except AttributeError:
            rough = ET.tostring(xsd_root, encoding='utf-8')
            reparsed = minidom.parseString(rough)
            xsd_str = reparsed.toprettyxml(indent="  ")
            with xsd_file.open('w', encoding='utf-8') as f:
                f.write(xsd_str)

        return xsd_str
    except Exception as e:
        return f"Erro ao converter XML para XSD: {e}"

def validate_xml_against_xsd(xml_filename, xsd_filename):
    try:
        xml_file = DATAFOLDER / xml_filename
        xsd_file = DATAFOLDER / xsd_filename

        if not xml_file.exists():
            return "Erro: arquivo XML não encontrado"
        if not xsd_file.exists():
            return "Erro: arquivo XSD não encontrado"


        schemas = etree.XMLSchema(etree.parse(str(xsd_file)))
        # Coleta tags presentes no XML
        for _, elem in etree.iterparse(str(xml_file), events=("end",), schema=schemas, huge_tree=True):
            elem.clear()
            parent = elem.getparent()
            # if parent is not None:
            #     while parent.getprevious() is not None:
            #         del parent.getprevious()[0]
        return "XML é válido contra o XSD"
    except ImportError:
        return "Erro: biblioteca 'xmlschema' não instalada"
    except Exception as e:
        return f"Erro ao validar XML contra XSD: {e}"

# Função para processar o XML e salvar no Firestore
def process_xml_and_save_to_firebase(xml_filename):
    # valida nome simples (evita path traversal)
    if Path(xml_filename).name != xml_filename:
        return "Erro: nome de arquivo inválido"

    xml_file = DATAFOLDER / xml_filename
    if not xml_file.exists():
        return "Erro: arquivo XML não encontrado"

    try:
        # Verifica se o XML está vazio rapidamente sem carregar tudo no parser
        with xml_file.open('r', encoding='utf-8') as f:
            preview = f.read(2048)
            if not preview.strip():
                return "Erro: XML vazio"

        collection_name = xml_filename.replace(".xml", "")
        documentos = 0

        # Usa iterparse para processamento em streaming (menor uso de memória)
        for event, elem in etree.iterparse(str(xml_file), events=("end",)):
            if elem.tag == "record":
                data = {}
                for child in elem:
                    data[child.tag] = (child.text or "").strip()
                db_firestore.collection(collection_name).add(data)
                documentos += 1
                # Libera memória do elemento já processado
                elem.clear()
                parent = elem.getparent()
                if parent is not None:
                    for ancestor in parent.iterancestors():
                        ancestor.clear()

        if documentos == 0:
            return "Aviso: nenhum elemento <record> encontrado"
        return f"Dados gravados com sucesso no Firestore ({documentos} registros)"
    except (etree.XMLSyntaxError, ET.ParseError):
        return "Erro: XML mal formado"
    except Exception as e:
        return f"Erro ao processar o XML: {str(e)}"

def getFirebaseCollections():
    try:
        collections = db_firestore.collections()
        collection_names = [collection.id for collection in collections]
        return collection_names
    except Exception as e:
        return f"Erro ao obter coleções do Firestore: {str(e)}"

# Inicia o servidor XML-RPC
if __name__ == "__main__":
    # Registra a função XML-RPC no servidor
    server.register_function(process_xml_and_save_to_firebase, 'process_xml')
    server.register_function(csv_to_xml, 'csv_to_xml')
    server.register_function(xml_to_xsd, 'xml_to_xsd')
    server.register_function(validate_xml_against_xsd, 'validate_xml')
    server.register_function(getFirebaseCollections, 'get_collections')
    print("Servidor XML-RPC rodando em http://0.0.0.0:8000")
    server.serve_forever()
