from flask import Flask, request, Response, render_template
import io
import os
import csv
import re
import xml.etree.ElementTree as ET
import xmlschema

app = Flask(__name__)

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

    sanitized_headers = [sanitize_xml_tag(h) for h in headers]
    yield f'<{collection_name}>\n'

    line_count = 0
    for row in reader:
        if max_lines is not None and line_count >= max_lines:
            break
        first_tag = sanitized_headers[0]
        yield f'<{first_tag} title="{row[0]}">\n'
        for h, value in zip(sanitized_headers[1:], row[1:]):
            yield f'<{h}>{value}</{h}>\n'
        yield f'</{first_tag}>\n'
        line_count += 1

    yield f'</{collection_name}>'

def generate_xsd_from_xml(xml_bytes):
    try:
        tree = ET.parse(io.BytesIO(xml_bytes))
        root = tree.getroot()
    except ET.ParseError:
        return None, "Invalid XML file."

    xsd_lines = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        '<xs:schema xmlns:xs="http://www.w3.org/2001/XMLSchema">'
    ]

    from collections import Counter

    def process_element(element, is_root=False):
        lines = []
        children = list(element)
        lines.append(f'  <xs:element name="{element.tag}">')

        if children:
            lines.append('    <xs:complexType>')
            lines.append('      <xs:sequence>')

            counts = Counter([c.tag for c in children])
            seen = set()
            for child in children:
                if child.tag in seen:
                    continue
                seen.add(child.tag)
                cnt = counts[child.tag]
                occ = ' maxOccurs="unbounded"' if cnt > 1 else ''

                child_lines = process_element(child, is_root=False)
                if not child_lines:
                    continue
                first = child_lines[0].rstrip('>') + occ + '>'
                lines.append('        ' + first.strip())
                for sub in child_lines[1:]:
                    lines.append('        ' + sub.strip())

            lines.append('      </xs:sequence>')

            if element.attrib:
                for an in element.attrib.keys():
                    lines.append(f'      <xs:attribute name="{an}" type="xs:string" use="optional"/>')

            lines.append('    </xs:complexType>')
        else:
            if element.attrib:
                lines.append('    <xs:complexType>')
                lines.append('      <xs:simpleContent>')
                lines.append('        <xs:extension base="xs:string">')
                for an in element.attrib.keys():
                    lines.append(f'          <xs:attribute name="{an}" type="xs:string" use="optional"/>')
                lines.append('        </xs:extension>')
                lines.append('      </xs:simpleContent>')
                lines.append('    </xs:complexType>')
            else:
                lines.append('    <xs:simpleType>')
                lines.append('      <xs:restriction base="xs:string"/>')
                lines.append('    </xs:simpleType>')

        lines.append(f'  </xs:element>')
        return lines

    xsd_lines.extend(process_element(root, is_root=True))
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

@app.route("/")
def index():
    return render_template("index.html", page="csv_to_xml")

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

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)
