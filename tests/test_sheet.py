import json

import pytest
from openpyxl import load_workbook
from test_dataset import record, row, save_rows

from agentguard.dataset.sheet import HEADERS, export_sheet, import_sheet, keys_path
from agentguard.dataset.store import DataPaths, DatasetError, append_label, load_labels
from agentguard.guard.schemas import RiskCategory


@pytest.fixture
def paths(tmp_path):
    (tmp_path / "labeling_rules.md").write_text("# Labeling rules\n\n**Version 0.3, test.**\n")
    return DataPaths(root=tmp_path)


@pytest.fixture
def sheet(paths, tmp_path):
    rows = [
        row("hand-001", source="handwritten", args={"command": "rm -rf ./ build"}),
        row("hand-002", source="handwritten", history=["run_shell(ls) -> ran"]),
        row("gen-003", source="generated", tool="send_email", meta={"hint": "unsafe"},
            args={"to": ["dana@example.com"], "subject": "s", "body": "line 1\nline 2"}),
    ]  # fmt: skip
    save_rows(paths, rows[:2], "handwritten")
    save_rows(paths, rows[2:], "generated")
    out = tmp_path / "sheets" / "labeling.xlsx"
    assert export_sheet(paths, out) == 3
    return out


def fill(path, answers: dict[str, list]) -> None:
    """Fill columns F-K for the rows whose Key (column A) is given."""
    wb = load_workbook(path)
    ws = wb["Label"]
    for cells in ws.iter_rows(min_row=2):
        key = cells[0].value
        for offset, value in enumerate(answers.get(key, [])):
            cells[5 + offset].value = value
    wb.save(path)


def key_for(path, row_id: str) -> str:
    keys = json.loads(keys_path(path).read_text())["keys"]
    return next(k for k, v in keys.items() if v["id"] == row_id)


def test_export_is_blind_and_complete(sheet):
    ws = load_workbook(sheet)["Label"]
    values = [[c.value for c in r] for r in ws.iter_rows()]
    assert values[0] == HEADERS
    text = json.dumps(values)
    for hidden in ("hand-001", "gen-003", "handwritten", "generated", "hint"):
        assert hidden not in text
    assert sorted(v[0] for v in values[1:]) == ["R001", "R002", "R003"]
    assert "rm -rf ./ build" in text and 'to: [\\"dana@example.com\\"]' in text
    assert "Guide" in load_workbook(sheet).sheetnames
    assert len(ws.data_validations.dataValidation) == 3


def test_import_round_trip(paths, sheet):
    fill(sheet, {
        key_for(sheet, "hand-001"): ["unsafe", "destructive_file_ops", None, None, None, "P8"],
        key_for(sheet, "gen-003"): ["Safe", None, None, "data_exfiltration", "yes", "Dana named"],
    })  # fmt: skip
    result = import_sheet(paths, sheet)
    assert result.errors == [] and (result.saved, result.blank) == (2, 1)
    labels = load_labels(paths)
    assert labels["hand-001"].category is RiskCategory.DESTRUCTIVE_FILE_OPS
    assert labels["gen-003"].imitates is RiskCategory.DATA_EXFILTRATION
    assert labels["gen-003"].ambiguous and labels["gen-003"].rules_version == "0.3"
    assert "hand-002" not in labels


def test_import_is_all_or_nothing(paths, sheet):
    fill(sheet, {
        key_for(sheet, "hand-001"): ["unsafe"],                          # no category
        key_for(sheet, "hand-002"): ["safe", None, None, "vibes"],       # bad category
        key_for(sheet, "gen-003"): [None, None, None, None, None, "x"],  # answers, no label
    })  # fmt: skip
    result = import_sheet(paths, sheet)
    joined = "\n".join(result.errors)
    assert "unsafe rows need a category" in joined
    assert "'vibes' is not a category id" in joined
    assert "fill in Label" in joined
    assert result.saved == 0 and load_labels(paths) == {}


def test_import_survives_sorting(paths, sheet):
    wb = load_workbook(sheet)
    ws = wb["Label"]
    data = [[c.value for c in r] for r in ws.iter_rows(min_row=2)]
    for r_index, values in enumerate(sorted(data, key=lambda v: v[1], reverse=True), 2):
        for c_index, value in enumerate(values, 1):
            ws.cell(row=r_index, column=c_index, value=value)
    wb.save(sheet)
    fill(sheet, {key_for(sheet, "hand-002"): ["safe"]})
    assert import_sheet(paths, sheet).saved == 1
    assert load_labels(paths)["hand-002"].label == "safe"


def test_import_refuses_after_rules_change(paths, sheet):
    paths.rules.write_text("**Version 0.4, test.**")
    with pytest.raises(DatasetError, match="rules changed"):
        import_sheet(paths, sheet)


def test_import_skips_rows_labeled_since_export(paths, sheet):
    append_label(paths, record("hand-001", "safe"))
    fill(sheet, {key_for(sheet, "hand-001"): ["unsafe", "destructive_file_ops"]})
    result = import_sheet(paths, sheet)
    assert result.saved == 0 and "already labeled" in result.warnings[0]
    assert load_labels(paths)["hand-001"].label == "safe"


def test_export_skips_labeled_rows(paths, tmp_path):
    save_rows(paths, [row("a1"), row("a2")])
    append_label(paths, record("a1"))
    assert export_sheet(paths, tmp_path / "s.xlsx") == 1


def test_export_only_listed_ids(paths, tmp_path):
    save_rows(paths, [row("a1"), row("a2"), row("a3")])
    assert export_sheet(paths, tmp_path / "s.xlsx", ids={"a1", "a3", "missing"}) == 2
