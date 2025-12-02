import os
import subprocess
import sys
import time
from concurrent import futures
from pathlib import Path
import grpc
import csv
from xml.dom import minidom
import xml.etree.ElementTree as ET
from lxml import etree
import firebase_admin
from firebase_admin import credentials, firestore


HERE = os.path.dirname(os.path.abspath(__file__))
PROTO = os.path.join(HERE, "grpc.proto")
PB2 = os.path.join(HERE, "grpc_pb2.py")
PB2_GRPC = os.path.join(HERE, "grpc_pb2_grpc.py")


def _maybe_generate_protos():
    """Generate Python gRPC code from grpc.proto if generated files are missing."""
    if os.path.exists(PB2) and os.path.exists(PB2_GRPC):
        return

    print("Generating Python gRPC code from grpc.proto...")
    # Use grpc_tools.protoc to generate
    cmd = [
        sys.executable,
        "-m",
        "grpc_tools.protoc",
        f"-I{HERE}",
        f"--python_out={HERE}",
        f"--grpc_python_out={HERE}",
        PROTO,
    ]
    print("Running:", " ".join(cmd))
    subprocess.check_call(cmd)
    print("Generated grpc_pb2.py and grpc_pb2_grpc.py")


_maybe_generate_protos()

import grpc_pb2
import grpc_pb2_grpc

DATAFOLDER = Path("/data/shared").resolve()

# Initialize Firebase if credentials exist
db_firestore = None
cred_path = Path(HERE) / "chave-privada.json"
if cred_path.exists():
    try:
        cred = credentials.Certificate(str(cred_path))
        firebase_admin.initialize_app(cred)
        db_firestore = firestore.client()
    except Exception as e:
        print(f"Warning: failed to init Firebase: {e}")


class XmlServiceServicer(grpc_pb2_grpc.XmlServiceServicer):
    """Implements XML operations analogous to the XML-RPC server."""

    def CsvToXml(self, request, context):
        csv_filename = request.csv_name or ""
        try:
            if Path(csv_filename).name != csv_filename:
                return grpc_pb2.OperationReply(success=False, message="Erro: nome de arquivo inválido")
            csv_file = DATAFOLDER / csv_filename
            if not csv_file.exists():
                return grpc_pb2.OperationReply(success=False, message="Erro: arquivo CSV não encontrado")

            with csv_file.open('r', encoding='utf-8', newline='') as f:
                reader = csv.DictReader(f)
                headers = [h.strip().replace(" ", "_") for h in (reader.fieldnames or [])]
                root_name = csv_file.stem
                row_name = root_name + "_record"
                root = ET.Element(root_name)
                for row in reader:
                    record_el = ET.SubElement(root, row_name)
                    for key, value in row.items():
                        tag = key.strip().replace(" ", "_")
                        ET.SubElement(record_el, tag).text = (value or "").strip()

            tree = ET.ElementTree(root)
            try:
                ET.indent(tree, space="  ")
                xml_bytes = ET.tostring(root, encoding='utf-8')
            except AttributeError:
                rough = ET.tostring(root, encoding='utf-8')
                reparsed = minidom.parseString(rough)
                xml_bytes = reparsed.toprettyxml(indent="  ", encoding="utf-8")

            xml_file = DATAFOLDER / (csv_file.stem + ".xml")
            with xml_file.open('wb') as out:
                out.write(xml_bytes)

            # Also generate XSD from CSV headers to preserve semantics
            msg = self._xsd_from_headers(root_name, row_name, headers, xml_file.stem)
            success = not msg.startswith("Erro")
            return grpc_pb2.OperationReply(success=success, message=msg)
        except Exception as e:
            return grpc_pb2.OperationReply(success=False, message=f"Erro ao converter CSV: {e}")

    def XmlToXsd(self, request, context):
        msg = self._xml_to_xsd_internal(request.xml_name or "")
        return grpc_pb2.OperationReply(success=not msg.startswith("Erro"), message=msg)

    def _xml_to_xsd_internal(self, xml_filename: str) -> str:
        try:
            xml_file = DATAFOLDER / xml_filename
            if not xml_file.exists():
                return "Erro: arquivo XML não encontrado"

            ordered_tags = []
            seen = set()
            for event, elem in etree.iterparse(str(xml_file), events=("end",)):
                if elem.tag == "record":
                    for child in elem:
                        t = child.tag
                        if t not in seen:
                            seen.add(t)
                            ordered_tags.append(t)
                    elem.clear()

            if os.environ.get("XSD_SORT", "").lower() == "alpha":
                ordered_tags = sorted(ordered_tags)

            xsd_root = ET.Element("xs:schema", attrib={"xmlns:xs": "http://www.w3.org/2001/XMLSchema"})
            record_el = ET.SubElement(xsd_root, "xs:element", attrib={"name": "data"})
            complex_type = ET.SubElement(record_el, "xs:complexType")
            sequence = ET.SubElement(complex_type, "xs:sequence")
            record_type = ET.SubElement(sequence, "xs:element", attrib={"name": "record", "minOccurs": "0", "maxOccurs": "unbounded"})
            rec_complex = ET.SubElement(record_type, "xs:complexType")
            rec_seq = ET.SubElement(rec_complex, "xs:sequence")
            for tag in ordered_tags:
                ET.SubElement(rec_seq, "xs:element", attrib={"name": tag, "type": "xs:string", "minOccurs": "0"})

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

    def _xsd_from_headers(self, root_name: str, row_name: str, headers: list[str], stem: str) -> str:
        try:
            if not headers:
                return "Erro: cabeçalhos CSV não encontrados"
            xsd_root = ET.Element("xs:schema", attrib={"xmlns:xs": "http://www.w3.org/2001/XMLSchema"})
            root_el = ET.SubElement(xsd_root, "xs:element", attrib={"name": root_name})
            complex_type = ET.SubElement(root_el, "xs:complexType")
            sequence = ET.SubElement(complex_type, "xs:sequence")
            row_el = ET.SubElement(sequence, "xs:element", attrib={"name": row_name, "minOccurs": "0", "maxOccurs": "unbounded"})
            row_ct = ET.SubElement(row_el, "xs:complexType")
            row_seq = ET.SubElement(row_ct, "xs:sequence")
            for h in headers:
                ET.SubElement(row_seq, "xs:element", attrib={"name": h, "type": "xs:string", "minOccurs": "0"})
            xsd_file = DATAFOLDER / (stem + ".xsd")
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
            return f"Erro ao gerar XSD a partir do CSV: {e}"

    def ValidateXml(self, request, context):
        try:
            xml_file = DATAFOLDER / (request.xml_name or "")
            xsd_file = DATAFOLDER / (request.xsd_name or "")
            if not xml_file.exists():
                return grpc_pb2.OperationReply(success=False, message="Erro: arquivo XML não encontrado")
            if not xsd_file.exists():
                return grpc_pb2.OperationReply(success=False, message="Erro: arquivo XSD não encontrado")

            schemas = etree.XMLSchema(etree.parse(str(xsd_file)))
            for _, elem in etree.iterparse(str(xml_file), events=("end",), schema=schemas, huge_tree=True):
                elem.clear()
            return grpc_pb2.OperationReply(success=True, message="XML é válido contra o XSD")
        except Exception as e:
            return grpc_pb2.OperationReply(success=False, message=f"Erro ao validar XML contra XSD: {e}")

    def ProcessXml(self, request, context):
        xml_filename = request.xml_name or ""
        if Path(xml_filename).name != xml_filename:
            return grpc_pb2.OperationReply(success=False, message="Erro: nome de arquivo inválido")
        xml_file = DATAFOLDER / xml_filename
        if not xml_file.exists():
            return grpc_pb2.OperationReply(success=False, message="Erro: arquivo XML não encontrado")
        if db_firestore is None:
            return grpc_pb2.OperationReply(success=False, message="Erro: Firestore não inicializado")
        try:
            with xml_file.open('r', encoding='utf-8') as f:
                preview = f.read(2048)
                if not preview.strip():
                    return grpc_pb2.OperationReply(success=False, message="Erro: XML vazio")
            collection_name = xml_filename.replace(".xml", "")
            documentos = 0
            for event, elem in etree.iterparse(str(xml_file), events=("end",)):
                if elem.tag == "record":
                    data = {}
                    for child in elem:
                        data[child.tag] = (child.text or "").strip()
                    db_firestore.collection(collection_name).add(data)
                    documentos += 1
                    elem.clear()
                    parent = elem.getparent()
                    if parent is not None:
                        for ancestor in parent.iterancestors():
                            ancestor.clear()
            if documentos == 0:
                return grpc_pb2.OperationReply(success=False, message="Aviso: nenhum elemento <record> encontrado")
            return grpc_pb2.OperationReply(success=True, message=f"Dados gravados com sucesso no Firestore ({documentos} registros)")
        except (etree.XMLSyntaxError, ET.ParseError):
            return grpc_pb2.OperationReply(success=False, message="Erro: XML mal formado")
        except Exception as e:
            return grpc_pb2.OperationReply(success=False, message=f"Erro ao processar o XML: {str(e)}")

    def GetCollections(self, request, context):
        if db_firestore is None:
            return grpc_pb2.GetCollectionsReply(collections=[])
        try:
            collections = db_firestore.collections()
            names = [c.id for c in collections]
            return grpc_pb2.GetCollectionsReply(collections=names)
        except Exception as e:
            print(f"Erro ao obter coleções do Firestore: {e}")
            return grpc_pb2.GetCollectionsReply(collections=[])


def serve(host="0.0.0.0", port=50051):
    server = grpc.server(futures.ThreadPoolExecutor(max_workers=10))
    grpc_pb2_grpc.add_XmlServiceServicer_to_server(XmlServiceServicer(), server)
    address = f"{host}:{port}"
    server.add_insecure_port(address)
    server.start()
    print(f"gRPC XmlService server started on {address}")
    try:
        while True:
            time.sleep(60)
    except KeyboardInterrupt:
        print("Shutting down server...")
        server.stop(0)


if __name__ == "__main__":
    serve()
