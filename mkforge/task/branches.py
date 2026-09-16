"""Таблица отделений на странице: к какому региону прогноза маржи относится отделение.

Транзакции размечены отделениями, прогноз маржи — регионами, и связи между ними
в выгрузке нет. У пользователя в томе таблицы нет, а без нее расчет не идет,
поэтому страница заполняет ее формой: отделения берутся из транзакций, регионы —
из прогноза маржи той же выгрузки. Выбрать регион, которого в прогнозе нет, нельзя.

По названию пары не подбираются: часть их сведена по названию, часть вручную,
и догадка, которая выглядит верной, опаснее пустой строки, которая останавливает расчет.

Строки для отделений, которых в выгрузке нет, при записи сохраняются: на расчет
они не влияют, а следующая выгрузка может их вернуть.
"""

from __future__ import annotations

import csv
import os
import uuid
from pathlib import Path
from typing import Any, Mapping

from mkforge.core.loaders import BRANCHES_FILE, MARGIN_FILE, TRANSACTIONS_FILE

FIELDS = ("отделение", "регион")
NO_EXPORT = "таблицу отделений заполняют после загрузки выгрузки"


def _column(path: Path, name: str) -> list[str]:
    with path.open(encoding="utf-8", newline="") as file:
        return sorted({(row.get(name) or "").strip() for row in csv.DictReader(file)} - {""})


def _table(path: Path) -> dict[str, str]:
    """Таблица как есть, без строгости загрузчика: форма открывается и на сломанной."""
    if not path.exists():
        return {}
    table: dict[str, str] = {}
    with path.open(encoding="utf-8", newline="") as file:
        for row in csv.DictReader(file):
            branch = (row.get("отделение") or "").strip()
            region = (row.get("регион") or "").strip()
            if branch and region:
                table[branch] = region
    return table


def describe(inputs_dir: Path) -> dict:
    """Отделения выгрузки, регионы прогноза и то, что уже записано."""
    transactions, margin = inputs_dir / TRANSACTIONS_FILE, inputs_dir / MARGIN_FILE
    if not transactions.exists() or not margin.exists():
        return {"ok": False, "message": NO_EXPORT}
    regions = _column(margin, "регион")
    table = _table(inputs_dir / BRANCHES_FILE)
    rows = [
        {"branch": branch, "region": table.get(branch), "known": table.get(branch) in regions}
        for branch in _column(transactions, "отделение")
    ]
    return {
        "ok": True,
        "branches": rows,
        "regions": regions,
        "missing": [row["branch"] for row in rows if not row["known"]],
    }


def save(inputs_dir: Path, pairs: Mapping[str, Any]) -> dict:
    """Записать пары «отделение — регион». Неверная пара — ответ со списком, а не запись."""
    described = describe(inputs_dir)
    if not described["ok"]:
        return {"ok": False, "errors": [{"branch": "", "message": described["message"]}]}
    branches = {row["branch"] for row in described["branches"]}
    regions = set(described["regions"])

    errors = []
    chosen: dict[str, str] = {}
    for branch, region in pairs.items():
        region = region.strip() if isinstance(region, str) else ""
        if branch not in branches:
            errors.append({"branch": branch, "message": "такого отделения в выгрузке нет"})
        elif not region:
            continue  # не выбрано — строка останется пустой, расчет скажет об этом сам
        elif region not in regions:
            errors.append({"branch": branch, "message": "такого региона в прогнозе маржи нет"})
        else:
            chosen[branch] = region
    if errors:
        return {"ok": False, "errors": errors}

    path = inputs_dir / BRANCHES_FILE
    table = {**_table(path), **chosen}
    temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex[:8]}")
    try:
        with temporary.open("w", encoding="utf-8", newline="") as file:
            writer = csv.writer(file)
            writer.writerow(FIELDS)
            writer.writerows(sorted(table.items()))
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)
    return {"ok": True, "errors": [], "saved": len(chosen)}
