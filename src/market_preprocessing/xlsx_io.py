"""Small OOXML reader for the GME XLSX input workbook."""

from __future__ import annotations

import re
import zipfile
from pathlib import Path
from xml.etree import ElementTree as ET


NS = {
    "m": "http://schemas.openxmlformats.org/spreadsheetml/2006/main",
    "r": "http://schemas.openxmlformats.org/officeDocument/2006/relationships",
    "pr": "http://schemas.openxmlformats.org/package/2006/relationships",
}


def read_sheet_rows(
    xlsx_path: Path,
    sheet_name_contains: str | None = None,
) -> list[list[str | None]]:
    """Read one worksheet from an XLSX file as rows of string values."""

    with zipfile.ZipFile(xlsx_path) as workbook_zip:
        shared_strings = _shared_strings(workbook_zip)
        _, sheet_path = _select_sheet(workbook_zip, sheet_name_contains)
        root = ET.fromstring(workbook_zip.read(sheet_path))
        rows: list[list[str | None]] = []
        for row_node in root.findall("m:sheetData/m:row", NS):
            rows.append(_read_row(row_node, shared_strings))
        return rows


def _select_sheet(
    workbook_zip: zipfile.ZipFile,
    sheet_name_contains: str | None,
) -> tuple[str, str]:
    sheets = _worksheet_paths(workbook_zip)
    if sheet_name_contains is None:
        return sheets[0]
    needle = sheet_name_contains.lower()
    for name, path in sheets:
        if needle in name.lower():
            return name, path
    available = ", ".join(name for name, _ in sheets)
    raise ValueError(f"Sheet containing {sheet_name_contains!r} not found. Available: {available}")


def _worksheet_paths(workbook_zip: zipfile.ZipFile) -> list[tuple[str, str]]:
    workbook = ET.fromstring(workbook_zip.read("xl/workbook.xml"))
    rels = ET.fromstring(workbook_zip.read("xl/_rels/workbook.xml.rels"))
    rel_map = {
        rel.get("Id"): rel.get("Target")
        for rel in rels.findall("pr:Relationship", NS)
    }

    sheets: list[tuple[str, str]] = []
    for sheet in workbook.findall("m:sheets/m:sheet", NS):
        relation_id = sheet.get(f"{{{NS['r']}}}id")
        target = rel_map.get(relation_id, "")
        if target.startswith("/"):
            path = target.lstrip("/")
        elif target.startswith("xl/"):
            path = target
        else:
            path = f"xl/{target.lstrip('/')}"
        sheets.append((sheet.get("name", ""), path))
    return sheets


def _shared_strings(workbook_zip: zipfile.ZipFile) -> list[str]:
    if "xl/sharedStrings.xml" not in workbook_zip.namelist():
        return []
    root = ET.fromstring(workbook_zip.read("xl/sharedStrings.xml"))
    return [
        "".join(text.text or "" for text in item.findall(".//m:t", NS))
        for item in root.findall("m:si", NS)
    ]


def _read_row(row_node: ET.Element, shared_strings: list[str]) -> list[str | None]:
    positioned: dict[int, str | None] = {}
    sequential_index = 1
    for cell in row_node.findall("m:c", NS):
        ref = cell.get("r")
        index = _column_index(ref) if ref else sequential_index
        positioned[index] = _cell_value(cell, shared_strings)
        sequential_index = index + 1
    if not positioned:
        return []
    return [positioned.get(index) for index in range(1, max(positioned) + 1)]


def _column_index(cell_ref: str) -> int:
    match = re.match(r"([A-Z]+)", cell_ref)
    if not match:
        return 1
    value = 0
    for char in match.group(1):
        value = value * 26 + ord(char) - ord("A") + 1
    return value


def _cell_value(cell: ET.Element, shared_strings: list[str]) -> str | None:
    if cell.get("t") == "inlineStr":
        text = "".join(node.text or "" for node in cell.findall(".//m:t", NS))
        return text if text else None
    value_node = cell.find("m:v", NS)
    if value_node is None:
        return None
    value_text = value_node.text or ""
    if cell.get("t") == "s":
        return shared_strings[int(value_text or "0")]
    return value_text if value_text else None

