"""Выгрузка через страницу, слой «задание»: прием файлов, обработка, замена данных.

Главные свойства: сырой файл после обработки не остается, чем бы она ни кончилась;
неудачная обработка не трогает прежние данные; загрузка не может затереть то,
что уже лежит в `data/raw`.
"""

from __future__ import annotations

import io
from pathlib import Path

import openpyxl
import pytest
from conftest import BRANCH_REGIONS, notice_document, write_branch_regions

from mkforge.core.anonymize import ExportError, MissingKeyError
from mkforge.core.loaders import BRANCHES_FILE
from mkforge.task import intake as intake_module
from mkforge.task.calculate import Places, Waiting, Workspace
from mkforge.task.intake import (
    PREPARED_FILES,
    BadName,
    Incomplete,
    IntakeError,
    TooLarge,
    Uploads,
    WrongKind,
    file_name,
    intake,
    sweep,
)


@pytest.fixture
def places(home_in_tmp: Path, distributed_config_path: Path) -> Places:
    root = home_in_tmp
    return Places(
        root=root,
        raw_dir=root / "data" / "raw",
        inputs_dir=root / "data" / "anon",
        config_path=distributed_config_path,
        mapping_path=root / "data" / "contracts.mapping.json",
        work_dir=root / "out" / "рабочие",
        out_dir=root / "out",
    )


def send(uploads: Uploads, path: Path, name: str | None = None, length: int | None = None):
    data = path.read_bytes()
    return uploads.receive(name or path.name, len(data) if length is None else length,
                           io.BytesIO(data).read)


def upload(places: Places, export: Path | None, notice: Path | None = None):
    uploads = Uploads(places.raw_dir)
    for path in (export, notice):
        if path is not None:
            send(uploads, path)
    return uploads.take()


def run(places: Places, batch, steps: list | None = None) -> dict:
    return intake(places, batch, places.open, (steps if steps is not None else []).append)


def snapshot(places: Places) -> dict[str, bytes]:
    files = [places.inputs_dir / name for name in (*PREPARED_FILES, BRANCHES_FILE)]
    return {str(path): path.read_bytes() for path in (*files, places.mapping_path) if path.exists()}


def leftovers(places: Places) -> list[Path]:
    """Временные папки загрузки и обработки, оставшиеся в корне."""
    found = []
    for parent, prefix in ((places.raw_dir, ".upload-"), (places.inputs_dir.parent, ".anon-")):
        if parent.is_dir():
            found += [path for path in parent.iterdir() if path.name.startswith(prefix)]
    return found


# --- имя и прием файла -----------------------------------------------------


@pytest.mark.parametrize("given,expected", [
    ("Выгрузка за август.xlsx", "Выгрузка за август.xlsx"),
    ("../../etc/выгрузка.xlsx", "выгрузка.xlsx"),
    ("C:\\Users\\кто-то\\Рабочий стол\\Уведомление.docx", "Уведомление.docx"),
    ("/абсолютный/путь/выгрузка.XLSX", "выгрузка.XLSX"),
])
def test_name_is_reduced_to_its_base(given, expected):
    assert file_name(given) == expected


@pytest.mark.parametrize("given", [None, "", "   ", "..", "../", ".xlsx", "папка/.скрытый.xlsx",
                                   "вы\x07грузка.xlsx"])
def test_names_with_nothing_left_are_refused(given):
    with pytest.raises(BadName):
        file_name(given)


def test_only_xlsx_and_docx_are_taken(places, tmp_path):
    other = tmp_path / "таблица.csv"
    other.write_text("отделение,регион\n", encoding="utf-8")
    uploads = Uploads(places.raw_dir)
    with pytest.raises(WrongKind, match="нужна выгрузка .xlsx"):
        send(uploads, other)
    assert uploads.take().folder is None


def test_renamed_file_is_refused_and_not_kept(places, tmp_path):
    fake = tmp_path / "выгрузка.xlsx"
    fake.write_text("это не книга", encoding="utf-8")
    uploads = Uploads(places.raw_dir)
    with pytest.raises(WrongKind, match="не похож"):
        send(uploads, fake)
    assert uploads.take().folder is None
    assert not any(places.raw_dir.iterdir())


def test_body_shorter_than_declared_leaves_nothing(places, export):
    uploads = Uploads(places.raw_dir)
    with pytest.raises(Incomplete):
        send(uploads, export, length=export.stat().st_size + 10)
    assert not any(places.raw_dir.iterdir())


def test_refusal_drops_what_was_already_taken(places, export, tmp_path):
    """После отказа страница до обработки не дойдет: принятое уведомление не остается лежать."""
    uploads = Uploads(places.raw_dir)
    send(uploads, notice_document(tmp_path / "уведомление.docx"))
    fake = tmp_path / "выгрузка.xlsx"
    fake.write_text("это не книга", encoding="utf-8")
    with pytest.raises(WrongKind):
        send(uploads, fake)
    assert uploads.take() == intake_module.Batch(None, None, None)
    assert not any(places.raw_dir.iterdir())


def test_too_large_is_refused_before_reading(places):
    def read(size):
        raise AssertionError("тело читать незачем")

    with pytest.raises(TooLarge):
        Uploads(places.raw_dir).receive("выгрузка.xlsx", intake_module.UPLOAD_LIMIT + 1, read)


def test_same_kind_replaces_the_previous_file(places, export, tmp_path):
    other = tmp_path / "другая.xlsx"
    other.write_bytes(export.read_bytes())
    uploads = Uploads(places.raw_dir)
    send(uploads, export)
    send(uploads, other)
    batch = uploads.take()
    assert batch.export.name == "другая.xlsx"
    assert [path.name for path in batch.folder.iterdir()] == ["другая.xlsx"]
    assert uploads.take().folder is None, "после передачи в обработку здесь пусто"


def test_upload_never_touches_what_already_lies_in_raw(places, export):
    """Из исходников корень — папка проекта: рядом лежат настоящие выгрузки."""
    places.raw_dir.mkdir(parents=True)
    original = places.raw_dir / export.name
    original.write_bytes(b"PK\x03\x04 real export")

    batch = upload(places, export)
    assert batch.export != original
    run(places, batch)
    assert original.read_bytes() == b"PK\x03\x04 real export"


# --- обработка ---------------------------------------------------------------


def test_intake_puts_data_in_place_and_removes_raw_files(places, export, tmp_path):
    notice = notice_document(tmp_path / "Уведомление о СТП.docx")
    steps = []
    result = run(places, upload(places, export, notice), steps)

    assert result["ok"] and result["contracts"] == 20 and result["transactions"] == 40
    assert result["branches"] == len(BRANCH_REGIONS)
    assert result["notice"] is True
    assert result["ready"] is False, "таблицы отделений еще нет"
    for name in PREPARED_FILES:
        assert (places.inputs_dir / name).exists()
    assert places.mapping_path.exists()
    assert not any(places.raw_dir.iterdir()), "сырые файлы после обработки не остаются"
    assert not leftovers(places)

    texts = [step.text for step in steps if step.state == "done"]
    assert any("из уведомления «Уведомление о СТП.docx»" in text for text in texts)

    write_branch_regions(places.inputs_dir)
    assert isinstance(places.open(), Workspace)


def test_intake_without_notice_says_there_are_no_highway_rates(places, export):
    steps = []
    result = run(places, upload(places, export), steps)
    assert result["notice"] is False
    assert any("трассовых ставок в книге не будет" in step.text for step in steps)


def test_notice_without_highway_rates_is_not_called_complete(places, export, tmp_path):
    rows = [("0 – 50", ("0,00", "0,00", "-3,50", "0,00")),
            ("более 50", ("0,00", "0,00", "-1,00", "0,00"))]
    notice = notice_document(tmp_path / "без трассы.docx", rows=rows)
    steps = []
    run(places, upload(places, export, notice), steps)
    texts = [step.text for step in steps]
    assert any("трассовых ставок в нем нет" in text for text in texts)
    assert not any("с трассовыми ставками" in text for text in texts)


def test_notice_without_highway_column_is_accepted(places, export, tmp_path):
    """Уведомление вовсе без трассовой колонки: данные встают на место и страница их читает."""
    rows = [("0 – 50", ("0,00", "0,00", "-3,50")), ("более 50", ("0,00", "0,00", "-1,00"))]
    notice = notice_document(tmp_path / "без трассы.docx", highway=False, rows=rows)
    steps = []
    result = run(places, upload(places, export, notice), steps)

    assert result["ok"] and result["notice"] is True
    assert not any(places.raw_dir.iterdir()) and not leftovers(places)
    texts = [step.text for step in steps]
    assert any("трассовых ставок в нем нет" in text for text in texts)

    write_branch_regions(places.inputs_dir)
    assert isinstance(places.open(), Workspace)


def test_intake_reopens_the_page(places, export):
    places.inputs_dir.mkdir(parents=True)
    write_branch_regions(places.inputs_dir)
    opened = []

    def reopen():
        opened.append(places.open())
        return opened[-1]

    result = intake(places, upload(places, export), reopen)
    assert result["ready"] is True
    assert len(opened) == 1 and isinstance(opened[0], Workspace)


def test_broken_export_keeps_the_old_data(places, export, tmp_path):
    run(places, upload(places, export))
    write_branch_regions(places.inputs_dir)
    before = snapshot(places)

    broken = tmp_path / "не та выгрузка.xlsx"
    openpyxl.Workbook().save(broken)
    steps = []
    with pytest.raises(ExportError):
        run(places, upload(places, broken), steps)

    assert snapshot(places) == before
    assert steps[-1].state == "failed"
    assert not any(places.raw_dir.iterdir()), "сырые файлы удаляются и после ошибки"
    assert not leftovers(places)
    assert isinstance(places.open(), Workspace), "по прежним данным считать можно"


def test_export_that_contradicts_itself_keeps_the_old_data(places, export, tmp_path):
    """Договор в транзакциях, которого нет в пуле, на странице не исправить."""
    run(places, upload(places, export))
    before = snapshot(places)

    wb = openpyxl.load_workbook(export)
    wb["База участников"].delete_rows(2)
    orphaned = tmp_path / "без договора.xlsx"
    wb.save(orphaned)

    with pytest.raises(IntakeError, match="нет в пуле акции"):
        run(places, upload(places, orphaned))
    assert snapshot(places) == before
    assert not leftovers(places)


def test_gaps_in_branch_table_are_not_a_failure(places, export):
    """Новое отделение закрывают формой на странице, а не отказом в загрузке."""
    places.inputs_dir.mkdir(parents=True)
    (places.inputs_dir / BRANCHES_FILE).write_text(
        "отделение,регион\nОтделение А,Регион маржи А\n", encoding="utf-8"
    )
    result = run(places, upload(places, export))
    assert result["ok"] and result["ready"] is False
    state = places.open()
    assert isinstance(state, Waiting)
    assert any("отделения без региона" in problem for problem in state.problems)
    assert (places.inputs_dir / BRANCHES_FILE).read_text(encoding="utf-8").count("\n") == 2, (
        "таблицу отделений обработка не трогает"
    )


def test_missing_key_with_existing_mapping_refuses_and_changes_nothing(
    places, export, monkeypatch
):
    monkeypatch.delenv("MK_FORGE_HMAC_KEY")
    places.mapping_path.parent.mkdir(parents=True)
    places.mapping_path.write_text('{"Д-0000000000": "АА000000000"}', encoding="utf-8")
    before = snapshot(places)

    with pytest.raises(MissingKeyError):
        run(places, upload(places, export))
    assert snapshot(places) == before
    assert not (places.root / ".env").exists(), "нового ключа не создано"
    assert not any(places.raw_dir.iterdir())


def test_no_export_among_uploads(places, tmp_path):
    batch = upload(places, None, notice_document(tmp_path / "уведомление.docx"))
    with pytest.raises(IntakeError, match="выгрузки .xlsx"):
        run(places, batch)
    assert not batch.folder.exists()


def test_sweep_removes_only_leftovers_of_the_page(places):
    raw, data = places.raw_dir, places.inputs_dir.parent
    (raw / ".upload-0123456789ab").mkdir(parents=True)
    (raw / ".upload-0123456789ab" / "выгрузка.xlsx").write_bytes(b"PK")
    (data / ".anon-0123456789ab").mkdir(parents=True)
    (raw / "настоящая выгрузка.xlsx").write_bytes(b"PK")
    (raw / "папка").mkdir()

    assert sweep(places) == 2
    assert sorted(path.name for path in raw.iterdir()) == ["настоящая выгрузка.xlsx", "папка"]
    assert not (data / ".anon-0123456789ab").exists()
