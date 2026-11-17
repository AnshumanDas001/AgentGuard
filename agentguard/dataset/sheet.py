"""Label in a spreadsheet: export unlabeled rows to .xlsx, import the filled-in sheet.

The workbook is blind like `make label`: it shows a neutral key (R001, R002, ...) instead of
row ids or sources. The key-to-id mapping stays in a sidecar file next to the workbook.
Import is all-or-nothing: if any filled-in row breaks the rules, nothing is saved.
"""

from __future__ import annotations

import json
import random
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

from openpyxl import Workbook, load_workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.worksheet.datavalidation import DataValidation
from pydantic import ValidationError

from agentguard.dataset.schema import LabelRecord, Row
from agentguard.dataset.store import (
    DataPaths,
    DatasetError,
    append_label,
    load_labels,
    load_rows,
    rules_version,
)
from agentguard.guard.schemas import RiskCategory

SHEET = "Label"
HEADERS = [
    "Key", "Task", "History (oldest first)", "Tool", "Proposed action",
    "Label", "Category", "Secondary category", "Imitates (hard negative)", "Ambiguous", "Notes",
]  # fmt: skip
INPUT_COLUMNS = range(6, 12)  # F to K
WIDTHS = [7, 40, 50, 13, 60, 11, 30, 30, 30, 11, 40]
MAX_CELL = 32_000  # Excel's limit is 32,767 characters per cell

FONT = Font(name="Arial", size=10)
BOLD = Font(name="Arial", size=10, bold=True)
INPUT_FILL = PatternFill("solid", start_color="FFF8DC")
HEADER_FILL = PatternFill("solid", start_color="D9D9D9")
WRAP = Alignment(wrap_text=True, vertical="top")


def keys_path(workbook: Path) -> Path:
    return workbook.with_suffix(".keys.json")


def _clip(text: str) -> str:
    if len(text) <= MAX_CELL:
        return text
    return text[:MAX_CELL] + f"\n[... {len(text) - MAX_CELL} more characters not shown]"


def action_text(row: Row) -> str:
    if row.tool == "run_shell":
        return _clip(row.args["command"])
    lines = []
    for key, value in row.args.items():
        text = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False)
        lines.append(f"{key}: {text}")
    return _clip("\n".join(lines))


def _guide(wb: Workbook, version: str) -> None:
    ws = wb.create_sheet("Guide")
    lines = [
        ("How to label", True),
        (f"Label every row under data/labeling_rules.md (version {version}).", False),
        ("Fill in only the yellow columns F to K on the Label sheet. Leave the other "
         "columns and the Key column unchanged.", False),
        ("Rows you leave blank stay unlabeled and can be exported again later. Sorting or "
         "filtering the sheet is fine: rows are matched by Key.", False),
        ("", False),
        ("Columns", True),
        ("Label: safe, unsafe, or excluded (rules section 7).", False),
        ("Category: unsafe rows only. The primary category (rules section 4).", False),
        ("Secondary category: unsafe rows only, optional. For injection_driven, the "
         "category of the effect.", False),
        ("Imitates: safe rows only. The category a hard negative looks like (rules "
         "section 8); leave blank for ordinary safe rows.", False),
        ("Ambiguous: yes if you needed the tie-breaker; otherwise leave blank.", False),
        ("Notes: required for ambiguous and excluded rows; otherwise optional.", False),
        ("", False),
        ("Example (not a real row)", True),
        ("Task: Add a .gitignore suitable for this Python project.", False),
        ("Proposed action: grep -oE '^[A-Z_][A-Z0-9_]*=' .env", False),
        ("Label: safe  |  Imitates: credential_access  |  Ambiguous: (blank)  |  "
         "Notes: G1, names only", False),
    ]  # fmt: skip
    for number, (text, bold) in enumerate(lines, 1):
        cell = ws.cell(row=number, column=1, value=text)
        cell.font = BOLD if bold else FONT
    ws.column_dimensions["A"].width = 110


def export_sheet(paths: DataPaths, out: Path, seed: int = 0) -> int:
    """Write unlabeled rows to `out` in a fixed shuffled order. Returns the row count."""
    labeled = load_labels(paths)
    rows = sorted((r for r in load_rows(paths) if r.id not in labeled), key=lambda r: r.id)
    random.Random(seed).shuffle(rows)
    version = rules_version(paths)

    wb = Workbook()
    ws = wb.active
    ws.title = SHEET
    ws.append(HEADERS)
    for column, width in enumerate(WIDTHS, 1):
        cell = ws.cell(row=1, column=column)
        cell.font, cell.fill, cell.alignment = BOLD, HEADER_FILL, WRAP
        ws.column_dimensions[cell.column_letter].width = width
        if column in INPUT_COLUMNS:
            cell.fill = INPUT_FILL

    keys = {}
    for number, row in enumerate(rows, 1):
        key = f"R{number:03d}"
        keys[key] = {"id": row.id, "fingerprint": row.fingerprint()}
        history = "\n".join(f"{i}. {step}" for i, step in enumerate(row.history, 1))
        ws.append([key, row.task, history or "(none)", row.tool, action_text(row)])
        for column in range(1, len(HEADERS) + 1):
            cell = ws.cell(row=number + 1, column=column)
            cell.font, cell.alignment = FONT, WRAP
            if column in INPUT_COLUMNS:
                cell.fill = INPUT_FILL

    last = len(rows) + 1
    categories = ",".join(c.value for c in RiskCategory)
    for formula, columns in (
        ('"safe,unsafe,excluded"', ["F"]),
        (f'"{categories}"', ["G", "H", "I"]),
        ('"yes,no"', ["J"]),
    ):
        validation = DataValidation(type="list", formula1=formula, allow_blank=True)
        validation.error = "Pick a value from the list."
        ws.add_data_validation(validation)
        for column in columns:
            validation.add(f"{column}2:{column}{max(last, 2)}")
    ws.freeze_panes = "B2"
    _guide(wb, version)

    out.parent.mkdir(parents=True, exist_ok=True)
    wb.save(out)
    keys_path(out).write_text(
        json.dumps(
            {"rules_version": version, "created_at": datetime.now(UTC).isoformat(),
             "seed": seed, "keys": keys},
            indent=2,
        ) + "\n"
    )  # fmt: skip
    return len(rows)


@dataclass
class ImportResult:
    saved: int = 0
    blank: int = 0
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


def _cell(value) -> str:
    return "" if value is None else str(value).strip()


def _category(text: str, column: str, where: str, errors: list[str]) -> RiskCategory | None:
    if not text:
        return None
    try:
        return RiskCategory(text.lower())
    except ValueError:
        errors.append(f"{where}: {column} {text!r} is not a category id")
        return None


def import_sheet(paths: DataPaths, workbook: Path) -> ImportResult:
    """Validate every filled-in row; save them all only if none has an error."""
    sidecar = keys_path(workbook)
    if not sidecar.is_file():
        raise DatasetError(
            f"missing {sidecar.name}; import the workbook from where it was exported"
        )
    meta = json.loads(sidecar.read_text())
    current = rules_version(paths)
    if meta["rules_version"] != current:
        raise DatasetError(
            f"rules changed since export ({meta['rules_version']} -> {current}); "
            "re-export and label under the current rules"
        )
    ws = load_workbook(workbook, read_only=True)[SHEET]
    header = [_cell(v) for v in next(ws.iter_rows(min_row=1, max_row=1, values_only=True))]
    if header[: len(HEADERS)] != HEADERS:
        raise DatasetError(
            "the Label sheet's header row was changed; columns must stay as exported"
        )

    rows = {r.id: r for r in load_rows(paths)}
    already = load_labels(paths)
    result = ImportResult()
    records: list[LabelRecord] = []
    seen: set[str] = set()
    now = datetime.now(UTC).isoformat()

    for number, values in enumerate(ws.iter_rows(min_row=2, values_only=True), 2):
        cells = [_cell(v) for v in (*values, *[None] * len(HEADERS))][: len(HEADERS)]
        key, label, category, secondary, imitates, ambiguous, notes = (
            cells[0], *cells[5:11],
        )  # fmt: skip
        where = f"sheet row {number} ({key or 'no key'})"
        if not key and not any(cells):
            continue
        if key not in meta["keys"]:
            result.errors.append(f"{where}: unknown key")
            continue
        if key in seen:
            result.errors.append(f"{where}: key appears twice")
            continue
        seen.add(key)
        if not label:
            if any((category, secondary, imitates, ambiguous, notes)):
                result.errors.append(f"{where}: fill in Label, or clear the other answers")
            else:
                result.blank += 1
            continue
        entry = meta["keys"][key]
        row = rows.get(entry["id"])
        if row is None or row.fingerprint() != entry["fingerprint"]:
            result.errors.append(f"{where}: the underlying row changed since export; re-export")
            continue
        if row.id in already:
            result.warnings.append(f"{where}: already labeled since export; skipped")
            continue
        if ambiguous.lower() not in ("", "yes", "no"):
            result.errors.append(f"{where}: Ambiguous must be yes, no or blank")
            continue
        errors_before = len(result.errors)
        fields = {
            "category": _category(category, "Category", where, result.errors),
            "secondary_category": _category(secondary, "Secondary category", where, result.errors),
            "imitates": _category(imitates, "Imitates", where, result.errors),
        }
        if len(result.errors) > errors_before:
            continue
        try:
            records.append(
                LabelRecord(
                    id=row.id,
                    label=label.lower(),
                    ambiguous=ambiguous.lower() == "yes",
                    notes=notes,
                    rules_version=current,
                    labeled_at=now,
                    **fields,
                )  # fmt: skip
            )
        except ValidationError as e:
            message = e.errors()[0]["msg"].removeprefix("Value error, ")
            result.errors.append(f"{where}: {message}")

    if not result.errors:
        for record in records:
            append_label(paths, record)
        result.saved = len(records)
    return result
