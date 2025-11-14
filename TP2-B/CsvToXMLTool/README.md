# CsvToXML Tool (TP2-B)

Academic project: CSV ↔ XML utilities

This small Flask application provides utilities to convert CSV files to XML, generate a basic XSD from an XML document, and validate XML against an XSD. It was created as part of the TP2-B assignment.

## Features

- Convert CSV -> XML (streamed response for large files)
- Generate a best-effort XSD from a given XML file
- Validate an XML document against an XSD
- Simple web UI with forms for uploading files (templates in `templates/`)
- Dockerfile and compose.yaml for containerized runs

## Repository layout

```
TP2-B/
  CsvToXML/
    server.py            # Flask app
    requirements.txt     # Python deps
    Dockerfile
    compose.yaml
    templates/           # Jinja2 HTML templates
      base.html
      index.html
      schema.html
      validator.html
```

## Requirements

- Python 3.8+ (3.10 or 3.11 recommended)
- pip
- Optionally: Docker (to build/run container)

The Python dependencies are listed in `requirements.txt`. Install them in a virtual environment:

On Windows (bash):

```bash
python -m venv .venv
source .venv/Scripts/activate
pip install -r TP2-B/CsvToXML/requirements.txt
```

On Unix/macOS (bash):

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r TP2-B/CsvToXML/requirements.txt
```

## Run locally (development)

From project root (where `TP2-B` folder lives):

```bash
cd TP2-B/CsvToXML
# If you created a virtual env, activate it first
python server.py
# or
FLASK_APP=server.py flask run --host=0.0.0.0 --port=5000
```

Then visit http://127.0.0.1:5000 in your browser.

## Docker

Build and run the container:

```bash
docker build -t csvtoxml TP2-B/CsvToXML
docker run -p 5000:5000 csvtoxml
```

Or use `compose.yaml` (if present):

```bash
cd TP2-B/CsvToXML
docker compose up --build
```

## Web UI Endpoints

- `/` — CSV → XML page. Upload a CSV and download the generated XML.
- `/convert` — POST endpoint that returns the generated XML file. Form uses multipart/form-data.
- `/schema` — form page to upload XML and request an XSD.
- `/generate_schema` — POST that returns an XSD based on the uploaded XML.
- `/validator` — form page to upload XML + XSD and validate.
- `/validate_xml` — POST that runs validation and returns a result page.

## Example usage (curl)

Convert CSV to XML (download):

```bash
curl -F "csvfile=@data.csv" http://localhost:5000/convert -o data.xml
```

Generate XSD from XML:

```bash
curl -F "xmlfile=@sample.xml" http://localhost:5000/generate_schema -o sample.xsd
```

Validate XML against XSD (form/response HTML):

```bash
curl -F "xmlfile=@sample.xml" -F "xsdfile=@sample.xsd" http://localhost:5000/validate_xml
```

## Implementation notes & limitations

- `server.py` uses a best-effort generator (`generate_xsd_from_xml`) to produce a basic XSD describing structure: element names, sibling multiplicity, and attributes.
- The generated XSD uses `xs:string` for element and attribute types — the tool does not infer numeric/date types automatically.
- The schema generator aims to be simple and readable rather than exhaustive. For production-grade schemas you should refine types, cardinality, and constraints manually.
- The validator uses the `xmlschema` Python package to validate XML against a given XSD.

## Development suggestions / next steps

- Add unit tests for `generate_xsd_from_xml` (happy path + attributes + nested repeated elements).
- Improve type inference (integers, floats, dates using heuristics).
- Add drag-and-drop file upload to the UI and progress indicators for large files.
- Provide an option to download both the XML and generated XSD in a single archive.

## Academic information

- Author: Ricardo (student)
- Course: IS (TP2)
- Date: 2025

## License

This project is intended for academic use; include your institution's preferred license or keep it unlicensed for coursework.
