from flask import Flask, request, Response, render_template, send_file, redirect, session
import io
import os
import csv
import re
import xml.etree.ElementTree as ET
from xml.sax.saxutils import escape, quoteattr
import xmlschema
import xmlrpc.client

app = Flask(__name__)
# Basic secret key for session storage; set FLASK_SECRET_KEY in production
app.secret_key = os.environ.get("FLASK_SECRET_KEY", "dev-secret-key")

def sanitize_xml_tag(tag):
    tag = re.sub(r'\s+', '_', tag)
    tag = re.sub(r'[^\w\-\.]', '', tag)
    if tag and tag[0].isdigit():
        tag = '_' + tag
    return tag or "column"

def generate_xml_stream(file_bytes, collection_name="collection", max_lines=None):
    text_stream = io.TextIOWrapper(file_bytes, encoding="utf-8", newline="")
    reader = csv.reader(text_stream, delimiter=',')
    try:
        headers = next(reader)
    except StopIteration:
        yield f'<{collection_name}></{collection_name}>'
        return

    sanitized_headers = [sanitize_xml_tag(h or "column") for h in headers]
    yield f'<{collection_name}>\n'

    line_count = 0
    for row in reader:
        if max_lines is not None and line_count >= max_lines:
            break
        # Emit a consistent record element for each row
        rec_index = line_count + 1
        yield f'<record index="{rec_index}">\n'
        # Align row length to headers; pad missing values with empty string
        values = list(row) + [""] * max(0, len(sanitized_headers) - len(row))
        for h, value in zip(sanitized_headers, values):
            safe_text = escape(value if value is not None else "")
            yield f'<{h}>{safe_text}</{h}>\n'
        yield f'</record>\n'
        line_count += 1

    yield f'</{collection_name}>'

def generate_xsd_from_xml(xml_bytes):
    """Generate a basic XSD from an XML document.
    Optimizations:
    - Strips namespaces from element/attribute names (valid XSD names)
    - Supports mixed content (text + children)
    - Uses maxOccurs="unbounded" for repeated siblings
    - Provides clearer error messages
    """
    try:
        tree = ET.parse(io.BytesIO(xml_bytes))
        root = tree.getroot()
    except ET.ParseError as e:
        return None, f"Invalid XML file: {e}"

    def local_name(tag: str) -> str:
        if not tag:
            return "element"
        if '}' in tag:
            return tag.split('}', 1)[1]
        if ':' in tag:
            return tag.split(':', 1)[1]
        return tag

    xsd_lines = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        '<xs:schema xmlns:xs="http://www.w3.org/2001/XMLSchema">'
    ]

    from collections import Counter

    def has_significant_text(el: ET.Element) -> bool:
        if (el.text or '').strip():
            return True
        for ch in list(el):
            if (ch.tail or '').strip():
                return True
        return False

    def process_element(element: ET.Element):
        lines = []
        name = local_name(element.tag)
        children = list(element)
        has_children = len(children) > 0
        text_present = has_significant_text(element)

        lines.append(f'  <xs:element name="{name}">')

        if has_children:
            mixed_attr = ' mixed="true"' if text_present else ''
            lines.append(f'    <xs:complexType{mixed_attr}>')
            lines.append('      <xs:sequence>')

            counts = Counter([local_name(c.tag) for c in children])
            seen = set()
            for child in children:
                cname = local_name(child.tag)
                if cname in seen:
                    continue
                seen.add(cname)
                cnt = counts[cname]
                occ = ' maxOccurs="unbounded"' if cnt > 1 else ''

                child_lines = process_element(child)
                first = child_lines[0].rstrip('>') + occ + '>'
                lines.append('        ' + first.strip())
                for sub in child_lines[1:]:
                    lines.append('        ' + sub.strip())

            lines.append('      </xs:sequence>')

            if element.attrib:
                for an in element.attrib.keys():
                    lines.append(f'      <xs:attribute name="{local_name(an)}" type="xs:string" use="optional"/>')

            lines.append('    </xs:complexType>')
        else:
            if element.attrib:
                lines.append('    <xs:complexType>')
                lines.append('      <xs:simpleContent>')
                lines.append('        <xs:extension base="xs:string">')
                for an in element.attrib.keys():
                    lines.append(f'          <xs:attribute name="{local_name(an)}" type="xs:string" use="optional"/>')
                lines.append('        </xs:extension>')
                lines.append('      </xs:simpleContent>')
                lines.append('    </xs:complexType>')
            else:
                lines.append('    <xs:simpleType>')
                lines.append('      <xs:restriction base="xs:string"/>')
                lines.append('    </xs:simpleType>')

        lines.append('  </xs:element>')
        return lines

    xsd_lines.extend(process_element(root))
    xsd_lines.append('</xs:schema>')

    xsd_content = "\n".join(xsd_lines)
    return xsd_content, None

def validate_xml_against_xsd(xml_bytes, xsd_bytes):
    try:
        schema = xmlschema.XMLSchema(xsd_bytes)
        xml_resource = xmlschema.XMLResource(xml_bytes)
        is_valid = schema.is_valid(xml_resource)
        message = "XML is valid according to the XSD." if is_valid else "XML is NOT valid according to the XSD."
        return is_valid, message
    except xmlschema.XMLSchemaException as e:
        return False, f"Error processing XSD/XML: {e}"

@app.route("/", methods=["GET", "POST"])
def index():
    """Root now serves unified XML Tool (CSV->XML & XML->Schema). Mirrors previous /xmltool logic."""
    result_xml = None
    result_xsd = None
    download_filename = None
    error = None
    # Initialize preview-related variables so GET requests don't error
    xml_preview = None
    large_xml = False
    total_xml_lines = None
    xml_size_bytes = None

    if request.method == "POST":
        op = request.form.get("op")
        # Early download using persisted hidden fields (no re-upload required)
        if request.form.get("download") == "xml" and request.form.get("xml_data"):
            persisted_xml = request.form.get("xml_data")
            persisted_name = request.form.get("xml_filename") or "output.xml"
            return Response(persisted_xml, mimetype="application/xml", headers={"Content-Disposition": f"attachment; filename={persisted_name}"})
        if request.form.get("download") == "xsd" and request.form.get("xsd_data"):
            persisted_xsd = request.form.get("xsd_data")
            persisted_name = request.form.get("xsd_filename") or "schema.xsd"
            return Response(persisted_xsd, mimetype="application/xml", headers={"Content-Disposition": f"attachment; filename={persisted_name}"})
        if op == "csv":
            csv_file = request.files.get("csvfile")
            if not csv_file:
                error = "No CSV file uploaded."
            else:
                try:
                    max_lines_raw = request.form.get("max_lines")
                    max_lines = int(max_lines_raw) if max_lines_raw else None
                except ValueError:
                    error = "Invalid max lines value."
                if error is None:
                    file_bytes = io.BytesIO(csv_file.read())
                    base_name = os.path.splitext(csv_file.filename)[0] or "collection"
                    collection_name = sanitize_xml_tag(base_name)
                    xml_parts = []
                    for chunk in generate_xml_stream(file_bytes, collection_name=collection_name, max_lines=max_lines):
                        xml_parts.append(chunk)
                    result_xml = "".join(xml_parts)
                    download_filename = f"{collection_name}.xml"
                    # Persist to session for reliable download
                    session["xml_data"] = result_xml
                    session["xml_filename"] = download_filename
        elif op == "schema":
            xml_file = request.files.get("xmlfile")
            if not xml_file:
                error = "No XML file uploaded."
            else:
                xml_bytes = xml_file.read()
                # Quick sanity check to give clearer message for non-XML content (e.g., 'None')
                if not xml_bytes or not xml_bytes.lstrip().startswith(b"<"):
                    error = "Uploaded file doesn't look like XML (must start with '<')."
                else:
                    xsd_content, gen_err = generate_xsd_from_xml(xml_bytes)
                    if gen_err:
                        error = gen_err
                    else:
                        result_xsd = xsd_content
                        base_name = os.path.splitext(xml_file.filename)[0] or "schema"
                        download_filename = f"{base_name}.xsd"
                        # Persist to session for reliable download
                        session["xsd_data"] = result_xsd
                        session["xsd_filename"] = download_filename
        else:
            error = "Unknown operation."
        # Prepare preview metadata (lazy loading / truncated preview for large XML)
        MAX_PREVIEW_LINES = 200
        MAX_COPY_SIZE_BYTES = 100_000  # ~100KB threshold for disabling copy button
        if result_xml:
            xml_size_bytes = len(result_xml.encode('utf-8'))
            lines = result_xml.splitlines()
            total_xml_lines = len(lines)
            if total_xml_lines > MAX_PREVIEW_LINES or xml_size_bytes > MAX_COPY_SIZE_BYTES:
                large_xml = True
                xml_preview = "\n".join(lines[:MAX_PREVIEW_LINES]) + "\n...\n<!-- Preview truncated: total lines {} size {} bytes. Download full file. -->".format(total_xml_lines, xml_size_bytes)
            else:
                xml_preview = result_xml

        # Serve download if requested (fallback to session if needed)
        if request.form.get("download") == "xml":
            data = request.form.get("xml_data") or session.get("xml_data")
            name = request.form.get("xml_filename") or session.get("xml_filename") or "output.xml"
            if data:
                return Response(data, mimetype="application/xml", headers={"Content-Disposition": f"attachment; filename={name}"})
        if request.form.get("download") == "xsd":
            data = request.form.get("xsd_data") or session.get("xsd_data")
            name = request.form.get("xsd_filename") or session.get("xsd_filename") or "schema.xsd"
            if data:
                return Response(data, mimetype="application/xml", headers={"Content-Disposition": f"attachment; filename={name}"})

    return render_template(
        "xml_tool.html",
        page="xml_tool",
        xml_output=result_xml,
        xml_preview=xml_preview,
        large_xml=large_xml,
        total_xml_lines=total_xml_lines,
        xml_size_bytes=xml_size_bytes,
        xsd_output=result_xsd,
        error=error,
        download_filename=download_filename,
    )

@app.route("/convert", methods=["POST"])
def convert():
    uploaded_file = request.files.get("csvfile")
    if not uploaded_file:
        return "No file uploaded", 400

    try:
        max_lines = int(request.args.get("lines")) if request.args.get("lines") else None
    except ValueError:
        return "Invalid 'lines' parameter", 400

    file_bytes = io.BytesIO(uploaded_file.read())
    base_name = os.path.splitext(uploaded_file.filename)[0]
    xml_filename = f"{base_name}.xml"
    collection_name = sanitize_xml_tag(base_name)

    return Response(
        generate_xml_stream(file_bytes, collection_name=collection_name, max_lines=max_lines),
        mimetype="application/xml",
        headers={"Content-Disposition": f"attachment; filename={xml_filename}"}
    )

@app.route("/schema")
def schema_page():
    return render_template("schema.html", page="xml_to_schema")

@app.route("/generate_schema", methods=["POST"])
def generate_schema():
    uploaded_file = request.files.get("xmlfile")
    if not uploaded_file:
        return "No file uploaded", 400

    xml_bytes = uploaded_file.read()
    xsd_content, error = generate_xsd_from_xml(xml_bytes)
    if error:
        return error, 400

    base_name = os.path.splitext(uploaded_file.filename)[0]
    xsd_filename = f"{base_name}.xsd"
    return Response(
        xsd_content,
        mimetype="application/xml",
        headers={"Content-Disposition": f"attachment; filename={xsd_filename}"}
    )

@app.route("/validator")
def validator_page():
    return render_template("validator.html", page="xml_validator")

@app.route("/validate_xml", methods=["POST"])
def validate_xml():
    xml_file = request.files.get("xmlfile")
    xsd_file = request.files.get("xsdfile")

    if not xml_file or not xsd_file:
        return "Both XML and XSD files are required.", 400

    xml_bytes = xml_file.read()
    xsd_bytes = xsd_file.read()
    is_valid, message = validate_xml_against_xsd(xml_bytes, xsd_bytes)

    return render_template("validator.html", page="xml_validator", valid=is_valid, message=message)

# ---------------- Import & Send to DB (via XML-RPC) ---------------- #

@app.route("/import", methods=["GET"])
def import_page():
    """Render a page to upload an XML and send it to an XML-RPC server."""
    # Defaults can be adjusted as needed
    default_server_url = os.environ.get("XMLRPC_SERVER_URL", "http://localhost:8000")
    default_method = os.environ.get("XMLRPC_METHOD", "save_xml")
    return render_template(
        "import.html",
        page="xml_import",
        default_server_url=default_server_url,
        default_method=default_method,
    )


@app.route("/send_to_db", methods=["POST"])
def send_to_db():
    """Receive uploaded XML and forward it to an XML-RPC server. Does not implement any DB logic here."""
    xml_file = request.files.get("xmlfile")
    server_url = request.form.get("server_url") or os.environ.get("XMLRPC_SERVER_URL", "http://localhost:8000")
    method_name = request.form.get("method_name") or os.environ.get("XMLRPC_METHOD", "save_xml")

    if not xml_file:
        return render_template(
            "import.html",
            page="xml_import",
            message="No XML file uploaded.",
            success=False,
            default_server_url=server_url,
            default_method=method_name,
        ), 400

    def _decode_xml_bytes(data: bytes) -> str:
        """Decode XML bytes to text using encoding from XML prolog if present, else UTF-8.
        Falls back to UTF-8 with replacement to avoid crashing on bad bytes.
        """
        # Detect encoding from XML declaration: <?xml version="1.0" encoding="..."?>
        m = re.match(br"\s*<\?xml[^>]*encoding=['\"]([^'\"]+)['\"]", data)
        enc = m.group(1).decode("ascii", "ignore") if m else "utf-8"
        try:
            return data.decode(enc)
        except Exception:
            try:
                return data.decode("utf-8")
            except Exception:
                return data.decode("utf-8", errors="replace")

    xml_bytes = xml_file.read()
    xml_text = _decode_xml_bytes(xml_bytes)

    try:
        proxy = xmlrpc.client.ServerProxy(server_url, allow_none=True)
        if hasattr(proxy, method_name):
            # Send the actual XML content as a string (preferred by XML-RPC)
            result = getattr(proxy, method_name)(xml_text)
        else:
            return render_template(
                "import.html",
                page="xml_import",
                message=f"Method '{method_name}' not found on server.",
                success=False,
                default_server_url=server_url,
                default_method=method_name,
            ), 400

        return render_template(
            "import.html",
            page="xml_import",
            message=f"XML sent successfully. Server response: {result}",
            success=True,
            default_server_url=server_url,
            default_method=method_name,
        )
    except Exception as e:
        return render_template(
            "import.html",
            page="xml_import",
            message=f"Failed to send XML to XML-RPC server: {e}",
            success=False,
            default_server_url=server_url,
            default_method=method_name,
        ), 500

# ---------------- Unified XML Tool (CSV → XML & XML → Schema) ---------------- #

@app.route("/xmltool")
def xml_tool_redirect():
    """Legacy route kept for compatibility; redirect to root."""
    return redirect("/")

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)
