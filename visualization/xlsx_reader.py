"""使用 Python 标准库只读解析简单的 Excel 工作表。"""

from __future__ import annotations

import re
import zipfile
from pathlib import Path, PurePosixPath
from xml.etree import ElementTree


MAIN_NS = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
REL_NS = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
PACKAGE_REL_NS = "http://schemas.openxmlformats.org/package/2006/relationships"


def _read_shared_strings(workbook: zipfile.ZipFile) -> list[str]:
    if "xl/sharedStrings.xml" not in workbook.namelist():
        return []

    root = ElementTree.fromstring(workbook.read("xl/sharedStrings.xml"))
    return [
        "".join(text.text or "" for text in item.findall(f".//{{{MAIN_NS}}}t"))
        for item in root.findall(f"{{{MAIN_NS}}}si")
    ]


def _find_sheet_path(workbook: zipfile.ZipFile, sheet_name: str) -> str:
    workbook_root = ElementTree.fromstring(workbook.read("xl/workbook.xml"))
    relationship_id = None
    for sheet in workbook_root.findall(f".//{{{MAIN_NS}}}sheet"):
        if sheet.get("name") == sheet_name:
            relationship_id = sheet.get(f"{{{REL_NS}}}id")
            break
    if not relationship_id:
        raise ValueError(f"Excel 中不存在工作表：{sheet_name}")

    relationships = ElementTree.fromstring(
        workbook.read("xl/_rels/workbook.xml.rels")
    )
    for relationship in relationships.findall(f"{{{PACKAGE_REL_NS}}}Relationship"):
        if relationship.get("Id") == relationship_id:
            target = relationship.get("Target", "")
            return str(PurePosixPath("xl") / target).replace("xl/xl/", "xl/")
    raise ValueError(f"无法定位工作表文件：{sheet_name}")


def _column_name(cell_reference: str) -> str:
    match = re.match(r"[A-Z]+", cell_reference)
    return match.group(0) if match else ""


def _read_cell(cell: ElementTree.Element, shared_strings: list[str]) -> str:
    cell_type = cell.get("t")
    if cell_type == "inlineStr":
        return "".join(
            text.text or "" for text in cell.findall(f".//{{{MAIN_NS}}}t")
        )

    value_node = cell.find(f"{{{MAIN_NS}}}v")
    if value_node is None or value_node.text is None:
        return ""
    value = value_node.text
    if cell_type == "s":
        return shared_strings[int(value)]
    return value


# 2026/09/02 历史趋势可视化，新增功能：只读提取指定工作表，不改写真实数据源。
def read_sheet_rows(workbook_path: Path, sheet_name: str) -> list[dict[str, str]]:
    """按行返回“列字母 -> 单元格文本”，仅支持展示所需的常见单元格类型。"""

    with zipfile.ZipFile(workbook_path) as workbook:
        shared_strings = _read_shared_strings(workbook)
        sheet_path = _find_sheet_path(workbook, sheet_name)
        sheet_root = ElementTree.fromstring(workbook.read(sheet_path))

    rows: list[dict[str, str]] = []
    for row in sheet_root.findall(f".//{{{MAIN_NS}}}row"):
        values: dict[str, str] = {}
        for cell in row.findall(f"{{{MAIN_NS}}}c"):
            column = _column_name(cell.get("r", ""))
            if column:
                values[column] = _read_cell(cell, shared_strings).strip()
        rows.append(values)
    return rows

