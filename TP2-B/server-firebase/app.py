import firebase_admin
from firebase_admin import credentials, firestore
from xmlrpc.server import SimpleXMLRPCServer
from xmlrpc.server import SimpleXMLRPCRequestHandler
import xml.etree.ElementTree as ET

cred = credentials.Certificate("tp2-b-782a3-firebase-adminsdk-fbsvc-1737b34933.json")
firebase_admin.initialize_app(cred)

# Inicializa o Firestore
db_firestore = firestore.client()

# Configuração do servidor XML-RPC
class RequestHandler(SimpleXMLRPCRequestHandler):
    rpc_paths = ('/RPC2',)

server = SimpleXMLRPCServer(('0.0.0.0', 8000), requestHandler=RequestHandler)
server.register_introspection_functions()

# Função para processar o XML e salvar no Firestore
def process_xml_and_save_to_firebase(xml_data, xml_filename):
    try:
        # Verifica se o XML está vazio
        if not xml_data.strip():
            return "Erro: XML vazio"

        # Parse do XML recebido
        root = ET.fromstring(xml_data)

        # Itera sobre os dados XML e armazena no Firestore
        for child in root:
            data = {}

            # Itera sobre os filhos de cada 'record' no XML e armazena como chave-valor
            for elem in child:
                data[elem.tag] = elem.text  # Cria um campo para cada tag XML

            # Salva os dados no Firestore como um novo documento na coleção 'TP2-B'
            collection_name = xml_filename.replace(".xml", "")
            db_firestore.collection(collection_name).add(data)


        return "Dados gravados com sucesso no Firestore"
    except ET.ParseError:
        return "Erro: XML mal formado"
    except Exception as e:
        return f"Erro ao processar o XML: {str(e)}"

# Registra a função XML-RPC no servidor
server.register_function(process_xml_and_save_to_firebase, 'process_xml')

# Inicia o servidor XML-RPC
if __name__ == "__main__":
    print("Servidor XML-RPC rodando em http://0.0.0.0:8000")
    server.serve_forever()
