"""Обезличивание выгрузок перед тем, как они куда-либо поедут.

Единственное, что опознает клиента в выгрузке, — номер договора. Он заменяется на
псевдоним HMAC-SHA256 с ключом, который лежит только на машине пользователя.
Заодно отбрасываются колонки, которых нет в расчете: из 32 колонок транзакций
формулам нужны 9, а колонка «Регион» с 74 значениями не используется вовсе —
география берется из «Отделения ТО», где значений 11.

Сырые выгрузки остаются в data/raw, результат ложится в data/anon. Наружу —
в репозиторий, в CI, в сервис — уезжает только data/anon.
"""

from __future__ import annotations

import csv
import datetime as dt
import hashlib
import hmac
import json
import os
import re
import secrets
from dataclasses import dataclass, field
from pathlib import Path

import openpyxl

from mkforge.home import MAPPING_FILE

TRANSACTIONS_SHEET = "Транзакции участников"
CONTRACTS_SHEET = "База участников"

# Заголовок в выгрузке -> имя поля в обезличенном файле.
# Все остальные колонки отбрасываются: это либо промежуточные вычисления Excel
# (ключи, счетчики уникальности, справочные маржи), либо лишняя география.
TRANSACTION_COLUMNS = {
    "№ договора": "договор",
    "Сегмент": "сегмент",
    "Месяц": "месяц",
    "Вид продукта": "вид_продукта",
    "Класс продукта": "класс_продукта",
    "Количество": "количество_л",
    "Объем т": "объем_т",
    "Выручка со скидкой": "выручка_со_скидкой",
    "Сервисный сбор": "сервисный_сбор",
    "Отделение ТО": "отделение",
}

CONTRACT_COLUMNS = {
    "№ договора": "договор",
    "Сегмент": "сегмент",
    "Дата подключения": "дата_подключения",
}

CONTRACT_FIELD = "договор"
PSEUDONYM_LENGTH = 10  # шестнадцатеричных знаков, 40 бит
KEY_ENV_VAR = "MK_FORGE_HMAC_KEY"


class ExportError(Exception):
    """Выгрузка не той формы: нет листа или нет обязательной колонки."""


class MissingKeyError(Exception):
    """Таблица соответствия есть, а ключа, которым она построена, нет."""


@dataclass
class Result:
    """Что получилось, чтобы было видно: ничего не потеряно и ничего не утекло."""

    contracts: int = 0
    transactions: int = 0
    dropped_columns: int = 0
    totals: dict[str, float] = field(default_factory=dict)
    files: list[Path] = field(default_factory=list)

    def report(self) -> str:
        lines = [
            f"договоров:   {self.contracts}",
            f"транзакций:  {self.transactions}",
            f"отброшено колонок: {self.dropped_columns}",
        ]
        lines += [f"сумма {name}: {value:,.3f}".replace(",", " ") for name, value in self.totals.items()]
        lines += [f"записан {path}" for path in self.files]
        return "\n".join(lines)


def normalize_header(header: object) -> str:
    """Заголовки в выгрузке бывают с переносами строк и двойными пробелами."""
    return re.sub(r"\s+", " ", str(header or "")).strip()


def _key_text(root: Path) -> tuple[str, str] | None:
    """Ключ как текст и откуда он взят: из переменной или из .env в корне данных."""
    if value := os.environ.get(KEY_ENV_VAR):
        return value, f"из переменной {KEY_ENV_VAR}"
    env = root / ".env"
    if env.exists():
        for line in env.read_text(encoding="utf-8").splitlines():
            name, _, value = line.partition("=")
            if name.strip() == KEY_ENV_VAR and value.strip():
                return value.strip(), f"в {env.name} корня данных"
    return None


def existing_mappings(root: Path, mapping_path: Path) -> list[Path]:
    """Таблицы соответствия, которые уже есть: указанная и та, что в корне данных.

    Смотрим обе: prepare в новую таблицу при потерянном ключе иначе молча
    создал бы новый, и старая таблица в корне разошлась бы с ним.
    """
    return [path for path in dict.fromkeys((mapping_path, root / MAPPING_FILE)) if path.exists()]


def key_origin(root: Path) -> str | None:
    """Откуда возьмется ключ. Сам ключ не возвращается — его нельзя печатать."""
    found = _key_text(root)
    return found[1] if found else None


def hmac_key(root: Path, mapping_path: Path) -> bytes:
    """Ключ HMAC из окружения или из .env в корне данных. Если его нет — создать.

    Ключ никогда не покидает машину: .env в gitignore. Потеря ключа означает,
    что старые псевдонимы больше не совпадут с новыми, поэтому .env стоит
    забэкапить туда, где хранятся пароли.

    Новый ключ не создается, если таблица соответствия уже есть: значит, ключ
    был, и новый молча развел бы псевдонимы свежих данных со старыми книгами.
    """
    if found := _key_text(root):
        return bytes.fromhex(found[0])

    env = root / ".env"
    if existing := existing_mappings(root, mapping_path):
        raise MissingKeyError(
            f"таблица соответствия {existing[0]} есть, а ключа нет ни в переменной "
            f"{KEY_ENV_VAR}, ни в {env}. С новым ключом псевдонимы не совпали бы "
            f"со старыми, поэтому новый не создаю: верни прежний ключ в {env}"
        )

    new_key = secrets.token_hex(32)
    with env.open("a", encoding="utf-8") as f:
        f.write("\n# Ключ обезличивания. Не коммитить, но забэкапить.\n")
        f.write(f"{KEY_ENV_VAR}={new_key}\n")
    print(f"создан новый ключ обезличивания в {env} — сохрани его, иначе псевдонимы разъедутся")
    return bytes.fromhex(new_key)


def pseudonym(contract: str, key: bytes) -> str:
    """Устойчивый псевдоним: один и тот же договор всегда дает один и тот же код.

    Префикс номера (МС, СЗ, ЕК, ...) не сохраняется — он дублирует отделение,
    которое и так есть отдельной колонкой.
    """
    mac = hmac.new(key, str(contract).strip().encode("utf-8"), hashlib.sha256)
    return "Д-" + mac.hexdigest()[:PSEUDONYM_LENGTH].upper()


def _read_sheet(ws, columns: dict[str, str], sheet: str) -> tuple[list[dict], int]:
    """Вытащить только нужные колонки, находя их по заголовку, а не по букве.

    Позиции колонок между выгрузками уезжают, заголовки — нет.
    """
    rows = ws.iter_rows(values_only=True)
    headers = [normalize_header(h) for h in next(rows)]

    indexes: dict[str, int] = {}
    for header, field_name in columns.items():
        if header not in headers:
            raise ExportError(f"на листе «{sheet}» нет колонки «{header}»")
        indexes[field_name] = headers.index(header)

    data = []
    for row in rows:
        if not row or row[indexes[CONTRACT_FIELD]] in (None, ""):
            continue  # пустые строки и хвост форматирования
        data.append({name: row[i] for name, i in indexes.items()})

    dropped = sum(1 for h in headers if h) - len(indexes)
    return data, dropped


def _write_csv(path: Path, rows: list[dict], fields: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        for row in rows:
            writer.writerow(
                {
                    name: (value.date().isoformat() if isinstance(value, dt.datetime) else value)
                    for name, value in row.items()
                }
            )


def anonymize(
    source: Path,
    out_dir: Path,
    mapping_path: Path,
    root: Path,
) -> Result:
    """Прочитать сырую выгрузку, заменить номера договоров, записать data/anon.

    `root` — корень данных: в нем лежит .env с ключом. Текущая папка не подставляется.
    """
    key = hmac_key(root, mapping_path)

    wb = openpyxl.load_workbook(source, read_only=True, data_only=True)
    try:
        for sheet in (TRANSACTIONS_SHEET, CONTRACTS_SHEET):
            if sheet not in wb.sheetnames:
                raise ExportError(f"в книге нет листа «{sheet}»")
        transactions, dropped_tx = _read_sheet(
            wb[TRANSACTIONS_SHEET], TRANSACTION_COLUMNS, TRANSACTIONS_SHEET
        )
        contracts, dropped_contracts = _read_sheet(
            wb[CONTRACTS_SHEET], CONTRACT_COLUMNS, CONTRACTS_SHEET
        )
    finally:
        wb.close()

    # Псевдонимы на весь пул сразу, чтобы поймать коллизию до записи файлов.
    real = {str(row[CONTRACT_FIELD]).strip() for row in contracts}
    real |= {str(row[CONTRACT_FIELD]).strip() for row in transactions}
    mapping: dict[str, str] = {}
    for number in sorted(real):
        code = pseudonym(number, key)
        if code in mapping and mapping[code] != number:
            raise ExportError(
                f"коллизия псевдонимов на {number} и {mapping[code]}, "
                f"увеличь PSEUDONYM_LENGTH"
            )
        mapping[code] = number
    reverse = {number: code for code, number in mapping.items()}

    for row in (*transactions, *contracts):
        row[CONTRACT_FIELD] = reverse[str(row[CONTRACT_FIELD]).strip()]

    tx_path = out_dir / "transactions.csv"
    contracts_path = out_dir / "contracts.csv"
    _write_csv(tx_path, transactions, list(TRANSACTION_COLUMNS.values()))
    _write_csv(contracts_path, contracts, list(CONTRACT_COLUMNS.values()))

    mapping_path.parent.mkdir(parents=True, exist_ok=True)
    mapping_path.write_text(
        json.dumps(mapping, ensure_ascii=False, indent=2, sort_keys=True),
        encoding="utf-8",
    )

    def total(field_name: str) -> float:
        return sum(float(row[field_name] or 0) for row in transactions)

    return Result(
        contracts=len(contracts),
        transactions=len(transactions),
        dropped_columns=dropped_tx + dropped_contracts,
        totals={
            "объем_т": total("объем_т"),
            "количество_л": total("количество_л"),
            "выручка_со_скидкой": total("выручка_со_скидкой"),
            "сервисный_сбор": total("сервисный_сбор"),
        },
        files=[tx_path, contracts_path, mapping_path],
    )
