"""Возврат настоящих номеров договоров в собранную книгу.

Книга собирается на псевдонимах, потому что расчет идет по обезличенным данным.
Экономистам нужны настоящие номера, поэтому последним шагом псевдонимы меняются
обратно по локальной таблице соответствия.

Шаг делается после проверки, а не до: проверка сверяет книгу с обезличенными
данными и опирается на псевдонимы.

Формулы при этом не страдают. Они сравнивают ячейки по ссылкам, а не по значениям:
SUMIFS сопоставляет колонку договоров транзакций с колонкой договоров пула, и обе
меняются согласованно.

Книга на выходе остается живой моделью: формулы на месте. Числа в ней тоже есть —
после подмены номеров книга пересчитывается, иначе openpyxl оставил бы файл без
значений, и любой предпросмотр показал бы его пустым, хотя Excel открыл бы верно.
"""

from __future__ import annotations

import json
import os
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

import openpyxl

from mkforge.core.models import ModelError
from mkforge.renderers import participants as pool_sheet
from mkforge.renderers import transactions as tx

# Лист -> колонка с номером договора.
CONTRACT_CELLS = {
    tx.SHEET: tx.CONTRACT,
    pool_sheet.SHEET: pool_sheet.CONTRACT,
}


@dataclass
class RestoreResult:
    """Сколько номеров вернулось и куда легла книга."""

    path: Path
    replaced: dict[str, int] = field(default_factory=dict)
    contracts: int = 0
    recalculated: bool = False
    note: str = ""

    def report(self) -> str:
        lines = [f"книга с настоящими номерами: {self.path}"]
        lines += [f"  {sheet}: {count} ячеек" for sheet, count in sorted(self.replaced.items())]
        lines.append(f"  уникальных договоров: {self.contracts}")
        if self.recalculated:
            lines.append("  числа посчитаны, формулы живые: книга готова к отправке")
        else:
            lines.append(
                "  числа не посчитаны — Excel посчитает при открытии, "
                "но предпросмотр покажет пустые ячейки"
            )
        if self.note:
            lines.append(f"  {self.note}")
        return "\n".join(lines)


def deliverable_path(book: Path, out_dir: Path) -> Path:
    """Куда положить готовую книгу.

    Рабочие копии на псевдонимах собираются в отдельной папке, готовые лежат
    рядом с ней уровнем выше. Имя не меняется: папка и так их различает,
    а суффиксы в названии книги мешают ее отправлять.

    Если книга уже лежит в папке готовых, имя все же придется дополнить —
    иначе мы затрем то, из чего считаем.
    """
    target = out_dir / book.name
    if target.resolve() == book.resolve():
        return book.with_name(f"{book.stem} с номерами{book.suffix}")
    return target


def load_mapping(path: Path) -> dict[str, str]:
    """Таблица соответствия: псевдоним -> настоящий номер."""
    if not path.exists():
        raise ModelError(
            f"нет таблицы соответствия {path}; "
            f"собери входные данные командой mk-forge prepare"
        )
    mapping = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(mapping, dict) or not mapping:
        raise ModelError(f"{path.name}: таблица соответствия пустая или не разобралась")
    return mapping


def restore_numbers(
    book: Path, mapping_path: Path, out: Path, recalculate: bool = True
) -> RestoreResult:
    """Заменить псевдонимы на настоящие номера и положить готовую книгу в `out`.

    По умолчанию книга после подмены пересчитывается: openpyxl при записи теряет
    посчитанные значения, и без пересчета получится файл, который Excel откроет
    правильно, а любой предпросмотр покажет пустым. Если LibreOffice не найден,
    шаг пропускается, и об этом говорится в отчете.

    Подмена и пересчет идут во временной папке рядом с целью, а на место книга
    ложится одним переименованием. Иначе прерванная сборка оставила бы в готовых
    недосчитанную книгу, и страница предложила бы ее скачать. Папка рядом, а не
    системная временная: переименование атомарно только в пределах одного диска,
    а в контейнере том и /tmp — разные.
    """
    mapping = load_mapping(mapping_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=out.parent, prefix=".mk-forge-") as temporary:
        draft = Path(temporary) / out.name
        result = _replace_pseudonyms(book, mapping, draft)
        result.path = out
        if recalculate:
            draft = _recalculate(draft, result)
        os.replace(draft, out)
    return result


def _replace_pseudonyms(book: Path, mapping: dict[str, str], out: Path) -> RestoreResult:
    workbook = openpyxl.load_workbook(book)
    try:
        result = RestoreResult(path=out)
        seen: set[str] = set()
        for sheet, column in CONTRACT_CELLS.items():
            if sheet not in workbook.sheetnames:
                raise ModelError(f"в книге нет листа «{sheet}»")
            ws = workbook[sheet]
            replaced = 0
            for row in range(2, ws.max_row + 1):
                cell = ws[f"{column}{row}"]
                pseudonym = cell.value
                if pseudonym in (None, ""):
                    continue
                real = mapping.get(str(pseudonym))
                if real is None:
                    raise ModelError(
                        f"{sheet}!{column}{row}: псевдоним {pseudonym} отсутствует "
                        f"в таблице соответствия — книга собрана на других данных"
                    )
                cell.value = real
                seen.add(real)
                replaced += 1
            result.replaced[sheet] = replaced
        result.contracts = len(seen)
        workbook.save(out)
    finally:
        workbook.close()
    return result


def _recalculate(book: Path, result: RestoreResult) -> Path:
    """Посчитать числа в книге, оставив формулы живыми. Возвращает, какой файл класть.

    LibreOffice пишет и формулы, и значения, поэтому книга остается моделью,
    а не превращается в набор констант. Пересчет не удался — кладется книга
    без значений, и отчет об этом говорит.
    """
    from mkforge.core.validate import RecalculationError, recalculate

    try:
        computed = recalculate(book, book.parent / "пересчет")
    except RecalculationError as error:
        result.note = f"пересчет пропущен: {error}"
        return book
    result.recalculated = True
    return computed
