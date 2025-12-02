from flask import Flask, request, render_template, redirect, jsonify
from pathlib import Path
from werkzeug.utils import secure_filename
import os
import sys
import subprocess
import grpc

app = Flask(__name__)

DATAFOLDER = Path("/data/shared").resolve()
DATAFOLDER.mkdir(parents=True, exist_ok=True)

HERE = Path(__file__).parent.resolve()
PROTO = HERE / "grpc.proto"
PB2 = HERE / "grpc_pb2.py"
PB2_GRPC = HERE / "grpc_pb2_grpc.py"

def _maybe_generate_protos():
	if PB2.exists() and PB2_GRPC.exists():
		return
	cmd = [
		sys.executable,
		"-m",
		"grpc_tools.protoc",
		f"-I{HERE}",
		f"--python_out={HERE}",
		f"--grpc_python_out={HERE}",
		str(PROTO),
	]
	subprocess.check_call(cmd)

_maybe_generate_protos()

import grpc_pb2
import grpc_pb2_grpc

def listcsvfiles():
	try:
		return sorted([p.name for p in DATAFOLDER.glob("*.csv") if p.is_file()])
	except Exception:
		return []

def list_xml_xsd_pairs():
	try:
		xml_files = [p for p in DATAFOLDER.glob("*.xml") if p.is_file()]
		pairs = []
		for xml in xml_files:
			xsd = DATAFOLDER / f"{xml.stem}.xsd"
			if xsd.exists():
				pairs.append((xml.name, xsd.name))
		return sorted(pairs)
	except Exception:
		return []
    
@app.route("/", methods=["GET", "POST"])
def index():
	return render_template(
		"xml_tool.html",
		page="xml_tool",
		csv_files=listcsvfiles(),
		xml_xsd_pairs=list_xml_xsd_pairs(),
		db_collections=get_db_collections()
	)

@app.route("/rpc_generate_xml", methods=["POST"])
def rpc_generate_xml():
	"""Generate XML for a CSV using remote XML-RPC service."""
	csv_name = request.form.get("csv_name")
	if not csv_name:
		return render_template(
			"xml_tool.html", page="xml_tool", error="No CSV filename provided.", csv_files=listcsvfiles(),xml_xsd_pairs=list_xml_xsd_pairs(),db_collections=get_db_collections(),
		), 400
	filename = secure_filename(csv_name)
	if not filename.lower().endswith('.csv'):
		return render_template(
			"xml_tool.html", page="xml_tool", error="Invalid CSV filename.", csv_files=listcsvfiles(),xml_xsd_pairs=list_xml_xsd_pairs(),db_collections=get_db_collections()
		), 400
	# Optional: quickly verify local existence (may not exist if volume not shared but keep soft check)
	local_file = DATAFOLDER / filename
	if not local_file.exists():
		# still attempt remote (remote may have it) but note warning
		missing_note = f"(local copy missing)"
	else:
		missing_note = ""
	target = os.environ.get("GRPC_SERVER", "grpc_server:50051")
	try:
		with grpc.insecure_channel(target) as channel:
			stub = grpc_pb2_grpc.XmlServiceStub(channel)
			resp = stub.CsvToXml(grpc_pb2.CsvToXmlRequest(csv_name=filename))
			if not resp.success:
				return render_template(
					"xml_tool.html", page="xml_tool", error=resp.message, csv_files=listcsvfiles(),xml_xsd_pairs=list_xml_xsd_pairs(),db_collections=get_db_collections()
				), 500
	except Exception as e:
		return render_template(
			"xml_tool.html", page="xml_tool", error=f"gRPC error: {e}", csv_files=listcsvfiles(),xml_xsd_pairs=list_xml_xsd_pairs(),db_collections=get_db_collections()
		), 500
	xml_filename = filename.rsplit('.', 1)[0] + '.xml'
	xsd_filename = filename.rsplit('.', 1)[0] + '.xsd'
	return render_template(
		"xml_tool.html",
		page="xml_tool",
		message=f"XML generation requested for '{filename}' {missing_note}. '{xml_filename}' and '{xsd_filename}' generated.",
		success=True,
		csv_files=listcsvfiles(),
		xml_xsd_pairs = list_xml_xsd_pairs(),
		db_collections=get_db_collections(),
	), 200

@app.route("/convert", methods=["POST"])
def convert():
	uploaded_file = request.files.get("csvfile")
	if not uploaded_file or uploaded_file.filename == "":
		return jsonify(error="No CSV file uploaded."), 400

	original_name = secure_filename(uploaded_file.filename) or "upload.csv"
	if not original_name.lower().endswith(".csv"):
		original_name += ".csv"

	target_path = DATAFOLDER / original_name
	if target_path.exists():
		stem = target_path.stem
		suffix = target_path.suffix  # .csv
		counter = 1
		while True:
			candidate = DATAFOLDER / f"{stem}_{counter}{suffix}"
			if not candidate.exists():
				target_path = candidate
				break
			counter += 1

	try:
		uploaded_file.save(target_path)
	except Exception as e:
		return render_template(
			"xml_tool.html",
			page="xml_tool",
			message=f"Failed to save file: {e}",
			success=False,
			csv_files=listcsvfiles(),
			xml_xsd_pairs = list_xml_xsd_pairs(),
			db_collections=get_db_collections(),
		), 400
            
	return render_template(
		"xml_tool.html",
		page="xml_tool",
		message="CSV uploaded successfully",
		success=True,
		csv_files=listcsvfiles(),
		xml_xsd_pairs=list_xml_xsd_pairs(),
		db_collections=get_db_collections(),
	), 200

@app.route("/rpc_validate", methods=["POST"])
def rpc_validate():
	"""Validate an XML against its XSD via XML-RPC service."""
	xml_name = request.form.get("xml_name")
	xsd_name = request.form.get("xsd_name")
	if not xml_name or not xsd_name:
		return render_template(
			"xml_tool.html",
			page="xml_tool",
			error="Missing XML or XSD filename.",
			csv_files=listcsvfiles(),
			xml_xsd_pairs=list_xml_xsd_pairs(),
			db_collections=get_db_collections(),
		), 400
	target = os.environ.get("GRPC_SERVER", "grpc_server:50051")
	try:
		with grpc.insecure_channel(target) as channel:
			stub = grpc_pb2_grpc.XmlServiceStub(channel)
			resp = stub.ValidateXml(grpc_pb2.ValidateXmlRequest(xml_name=xml_name, xsd_name=xsd_name))
	except Exception as e:
		return render_template(
			"xml_tool.html",
			page="xml_tool",
			error=f"gRPC error: {e}",
			csv_files=listcsvfiles(),
			xml_xsd_pairs=list_xml_xsd_pairs(),
			db_collections=get_db_collections(),
		), 500
	success = resp.success
	return render_template(
		"xml_tool.html",
		page="xml_tool",
		message=resp.message,
		success=success,
		csv_files=listcsvfiles(),
		xml_xsd_pairs=list_xml_xsd_pairs(),
		db_collections=get_db_collections(),
	), 200 if success else 400
    
@app.route("/rpc_process_xml", methods=["POST"])
def send_to_db():
	xml_name = request.form.get("xml_name")
	target = os.environ.get("GRPC_SERVER", "grpc_server:50051")
	try:
		with grpc.insecure_channel(target) as channel:
			stub = grpc_pb2_grpc.XmlServiceStub(channel)
			resp = stub.ProcessXml(grpc_pb2.ProcessXmlRequest(xml_name=xml_name))
			return render_template(
				"xml_tool.html",
				page="xml_tool",
				message=resp.message,
				success=resp.success,
				csv_files=listcsvfiles(),
				xml_xsd_pairs=list_xml_xsd_pairs(),
				db_collections=get_db_collections(),
			), 200 if resp.success else 400
	except Exception as e:
		return render_template(
			"xml_tool.html",
			page="xml_tool",
			error= f"gRPC error: {e}",
			csv_files=listcsvfiles(),
			xml_xsd_pairs=list_xml_xsd_pairs(),
			db_collections=get_db_collections(),
		), 500

def get_db_collections():
	target = os.environ.get("GRPC_SERVER", "grpc_server:50051")
	try:
		with grpc.insecure_channel(target) as channel:
			stub = grpc_pb2_grpc.XmlServiceStub(channel)
			resp = stub.GetCollections(grpc_pb2.GetCollectionsRequest())
			return list(resp.collections)
	except Exception:
		return []

@app.route("/remove_csv", methods=["POST"])
def remove_csv():
	csv_name = request.form.get("csv_name")
	target = DATAFOLDER / csv_name if csv_name else None
	if not target or not target.exists():
		return render_template(
			"xml_tool.html", page="xml_tool", error="CSV not found.",
			csv_files=listcsvfiles(), xml_xsd_pairs=list_xml_xsd_pairs(), db_collections=get_db_collections()
		), 404
	try:
		target.unlink()
	except Exception as e:
		return render_template(
			"xml_tool.html", page="xml_tool", error=f"Error removing CSV: {e}",
			csv_files=listcsvfiles(), xml_xsd_pairs=list_xml_xsd_pairs(), db_collections=get_db_collections()
		), 500
	return render_template(
		"xml_tool.html", page="xml_tool", message=f"Removed {csv_name}", success=True,
		csv_files=listcsvfiles(), xml_xsd_pairs=list_xml_xsd_pairs(), db_collections=get_db_collections()
	), 200

@app.route("/remove_xml_xsd", methods=["POST"])
def remove_xml_xsd():
	xml_name = request.form.get("xml_name")
	xsd_name = request.form.get("xsd_name")
	xml_path = DATAFOLDER / xml_name if xml_name else None
	xsd_path = DATAFOLDER / xsd_name if xsd_name else None
	if not xml_path or not xsd_path:
		return render_template(
			"xml_tool.html", page="xml_tool", error="Missing filenames.",
			csv_files=listcsvfiles(), xml_xsd_pairs=list_xml_xsd_pairs(), db_collections=get_db_collections()
		), 400
	removed_any = False
	try:
		if xml_path.exists():
			xml_path.unlink()
			removed_any = True
		if xsd_path.exists():
			xsd_path.unlink()
			removed_any = True
	except Exception as e:
		return render_template(
			"xml_tool.html", page="xml_tool", error=f"Error removing files: {e}",
			csv_files=listcsvfiles(), xml_xsd_pairs=list_xml_xsd_pairs(), db_collections=get_db_collections()
		), 500
	if not removed_any:
		return render_template(
			"xml_tool.html", page="xml_tool", error="Files not found.",
			csv_files=listcsvfiles(), xml_xsd_pairs=list_xml_xsd_pairs(), db_collections=get_db_collections()
		), 404
	return render_template(
		"xml_tool.html", page="xml_tool", message=f"Removed {xml_name} and {xsd_name}", success=True,
		csv_files=listcsvfiles(), xml_xsd_pairs=list_xml_xsd_pairs(), db_collections=get_db_collections()
	), 200

@app.route("/xmltool")
def xml_tool_redirect():
	return redirect("/")

if __name__ == "__main__":
	app.run(host="0.0.0.0", port=5000)

