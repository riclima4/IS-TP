from typing import Optional, Dict, List
from pathlib import Path
from collections import defaultdict

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from lxml import etree

DATAFOLDER = Path("/data/shared").resolve()

app = FastAPI(title="Rest_api", version="0.1")

@app.get("/", tags=["root"])
def read_root():
    return {"message": "Hello from FastAPI REST API"}

class AggSpec(BaseModel):
    field: Optional[str] = None
    op: str

class GroupRequest(BaseModel):
    xml_name: str
    group_tag: str
    agg: Optional[List[AggSpec]] = None
    output_name: Optional[str] = None

def _coerce_number(val: Optional[str]) -> Optional[float]:
    if val is None:
        return None
    try:
        return float(val)
    except Exception:
        return None

@app.post("/group", tags=["group"])
def group_xml(req: GroupRequest):
    xml_path = DATAFOLDER / req.xml_name
    xml_name = req.xml_name.rsplit(".", 1)[0]
    if not xml_path.exists():
        raise HTTPException(status_code=404, detail="XML not found")
    group_tag = req.group_tag.strip()
    if not group_tag:
        raise HTTPException(status_code=400, detail="group_tag is required")
    # Parse and group rows by group_tag
    groups: Dict[str, List[Dict[str, str]]] = defaultdict(list)
    root_name: Optional[str] = None
    headers: List[str] = []
    for event, elem in etree.iterparse(str(xml_path), events=("end",)):
        if root_name is None and elem.getparent() is None:
            root_name = elem.tag
        if elem.tag == xml_name+"_record":
            row_dict = {child.tag: (child.text or "") for child in elem}
            if not headers:
                headers = list(row_dict.keys())
            key = row_dict.get(group_tag, "")
            groups[key].append(row_dict)
            elem.clear()

    if not groups:
        raise HTTPException(status_code=400, detail="No rows found to group")

    # Build grouped XML
    out_root = etree.Element(f"{xml_name}_groupedby")
    for key, rows in groups.items():
        g_el = etree.SubElement(out_root, f"{xml_name}_group")
        g_el.set("key", key)
        if req.agg:
            # Aggregates
            for spec in req.agg:
                op = (spec.op or "count").lower()
                fname = (spec.field or "").strip()
                tag_name = f"{fname}_{op}" if fname else op
                if op == "count":
                    etree.SubElement(g_el, tag_name).text = str(len(rows))
                elif op in ("sum", "avg", "min", "max"):
                    nums = [n for n in ( _coerce_number(r.get(fname)) for r in rows ) if n is not None]
                    if not nums:
                        etree.SubElement(g_el, tag_name).text = "0"
                    else:
                        if op == "sum":
                            etree.SubElement(g_el, tag_name).text = str(sum(nums))
                        elif op == "avg":
                            etree.SubElement(g_el, tag_name).text = str(sum(nums) / len(nums))
                        elif op == "min":
                            etree.SubElement(g_el, tag_name).text = str(min(nums))
                        elif op == "max":
                            etree.SubElement(g_el, tag_name).text = str(max(nums))
                else:
                    etree.SubElement(g_el, tag_name).text = "unsupported"
        else:
            # Default: embed rows
            for r in rows:
                row_el = etree.SubElement(g_el, "row")
                for h in headers:
                    etree.SubElement(row_el, h).text = r.get(h, "")

    # Write output XML
    output_stem = (req.output_name or f"{xml_path.stem}_grouped").strip()
    out_xml = DATAFOLDER / f"{output_stem}.xml"
    with open(out_xml, "wb") as f:
        f.write(etree.tostring(out_root, encoding="utf-8", xml_declaration=True, pretty_print=True))

    return {
        "success": True,
        "message": "Grouped XML generated",
        "output_xml": out_xml.name,
    }