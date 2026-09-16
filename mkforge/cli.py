"""Точка входа: mk-forge <команда>."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from mkforge.core.anonymize import ExportError, anonymize
from mkforge.core.extract import ParametersError, extract
from mkforge.config_edit import EditError
from mkforge.core.loaders import check, load_inputs
from mkforge.core.models import ModelError
from mkforge.core.notice import NoticeError
from mkforge.config import ConfigError, load_config
from mkforge.core.validate import RecalculationError, validate_path
from mkforge.core.verify import verify_all
from mkforge.doctor import diagnose
from mkforge.renderers.xlsx import build
from mkforge.restore import deliverable_path, restore_numbers


# Готовые книги лежат в out/, рабочие копии на псевдонимах — уровнем ниже.
# Так в out/ остается только то, что отдают, и убирать за собой не нужно.
OUT_DIR = Path("out")
WORK_DIR = OUT_DIR / "рабочие"


def _cmd_prepare(args: argparse.Namespace) -> int:
    """Превратить сырую книгу в безопасный набор входных данных в data/anon."""
    anonymized = anonymize(
        source=args.source,
        out_dir=args.out,
        mapping_path=args.mapping,
    )
    print(anonymized.report())
    extracted = extract(source=args.source, out_dir=args.out, notice=args.notice)
    print(extracted.report())
    print()
    print(check(load_inputs(args.out)).report())
    return 0


def _cmd_verify(args: argparse.Namespace) -> int:
    """Сверить ядро с эталонной книгой по каждому договору."""
    report = verify_all(
        book=args.book,
        inputs_dir=args.inputs,
        mapping_path=args.mapping,
        config=load_config(args.config),
    )
    print(report.report())
    return 0 if report.ok else 1


def _cmd_build(args: argparse.Namespace) -> int:
    """Собрать книгу по конфигу акции."""
    config = load_config(args.config)
    inputs = load_inputs(args.inputs)
    report = check(inputs)
    if not report.ok:
        print(report.report(), file=sys.stderr)
        return 1
    print(build(inputs=inputs, config=config, path=args.out).report())
    return 0


def _cmd_validate(args: argparse.Namespace) -> int:
    """Пересчитать книгу и сверить ее с расчетным ядром."""
    report = validate_path(
        book=args.book,
        inputs_dir=args.inputs,
        config_path=args.config,
        work_dir=args.work,
    )
    print(report.report())
    return 0 if report.ok else 1


def _cmd_restore(args: argparse.Namespace) -> int:
    """Вернуть настоящие номера договоров в собранную книгу."""
    out = args.out or deliverable_path(args.book, OUT_DIR)
    print(
        restore_numbers(
            book=args.book,
            mapping_path=args.mapping,
            out=out,
            recalculate=not args.no_recalc,
        ).report()
    )
    return 0


def _cmd_page(args: argparse.Namespace) -> int:
    """Поднять локальную страницу акции."""
    from mkforge.page.server import serve
    from mkforge.task.calculate import open_workspace

    inputs = load_inputs(args.inputs)
    report = check(inputs)
    if not report.ok:
        print(report.report(), file=sys.stderr)
        return 1
    state = open_workspace(
        inputs_dir=args.inputs,
        config_path=args.config,
        mapping_path=args.mapping,
        work_dir=args.work,
        out_dir=OUT_DIR,
    )
    return serve(state, port=args.port, open_browser=not args.no_open)


def _cmd_doctor(args: argparse.Namespace) -> int:
    """Показать, что найдено в окружении и чего не хватает."""
    print(
        diagnose(
            inputs_dir=args.inputs, config_path=args.config, mapping_path=args.mapping
        ).report()
    )
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="mk-forge",
        description="Генератор расчетных моделей маркетинговых кампаний",
    )
    commands = parser.add_subparsers(dest="command", required=True)

    prepare = commands.add_parser(
        "prepare",
        help=(
            "подготовить входные данные: обезличить номера договоров, "
            "отбросить лишние колонки, вынуть шкалу СТП, экономику и прогноз маржи"
        ),
    )
    prepare.add_argument("source", type=Path, help="путь к xlsx из data/raw")
    prepare.add_argument(
        "--out", type=Path, default=Path("data/anon"), help="куда положить результат"
    )
    prepare.add_argument(
        "--notice", type=Path, default=None,
        help="уведомление о СТП (docx): первоисточник шкалы, только в нем трассовые ставки",
    )
    prepare.add_argument(
        "--mapping",
        type=Path,
        default=Path("data/contracts.mapping.json"),
        help="куда положить таблицу соответствия (остается локально)",
    )
    prepare.set_defaults(func=_cmd_prepare)

    verify = commands.add_parser(
        "verify",
        help="сверить расчетное ядро с эталонной книгой по каждому договору",
    )
    verify.add_argument("book", type=Path, help="эталонная книга из reference/")
    verify.add_argument(
        "--inputs", type=Path, default=Path("data/anon"), help="каталог обезличенных данных"
    )
    verify.add_argument(
        "--mapping", type=Path, default=Path("data/contracts.mapping.json"),
        help="таблица соответствия псевдонимов",
    )
    verify.add_argument(
        "--config", type=Path, required=True, help="конфиг акции, по которому считать"
    )
    verify.set_defaults(func=_cmd_verify)

    assemble = commands.add_parser("build", help="собрать книгу Excel по конфигу акции")
    assemble.add_argument("config", type=Path, help="конфиг акции из configs/")
    assemble.add_argument(
        "--inputs", type=Path, default=Path("data/anon"), help="каталог обезличенных данных"
    )
    assemble.add_argument(
        "--out", type=Path, default=WORK_DIR / "книга.xlsx",
        help="куда сохранить книгу (по умолчанию рабочая папка)"
    )
    assemble.set_defaults(func=_cmd_build)

    check_book = commands.add_parser(
        "validate",
        help="пересчитать собранную книгу в LibreOffice и сверить ее числа с ядром",
    )
    check_book.add_argument("book", type=Path, help="собранная книга из out/")
    check_book.add_argument(
        "--config", type=Path, required=True,
        help="конфиг акции, по которому собиралась книга",
    )
    check_book.add_argument(
        "--inputs", type=Path, default=Path("data/anon"), help="каталог обезличенных данных"
    )
    check_book.add_argument(
        "--work", type=Path, default=WORK_DIR / "пересчет",
        help="куда положить пересчитанную копию",
    )
    check_book.set_defaults(func=_cmd_validate)

    real = commands.add_parser(
        "restore",
        help="вернуть в собранную книгу настоящие номера договоров вместо псевдонимов",
    )
    real.add_argument("book", type=Path, help="собранная книга из out/")
    real.add_argument(
        "--mapping", type=Path, default=Path("data/contracts.mapping.json"),
        help="таблица соответствия псевдонимов (остается локально)",
    )
    real.add_argument(
        "--out", type=Path, default=None,
        help="куда сохранить готовую книгу (по умолчанию в out/, под тем же именем)",
    )
    real.add_argument(
        "--no-recalc", action="store_true",
        help="не пересчитывать книгу после подмены номеров",
    )
    real.set_defaults(func=_cmd_restore)

    page = commands.add_parser(
        "page", help="открыть локальную страницу акции в браузере"
    )
    # Конфиг по умолчанию не подставляется: страница пишет в него поля формы,
    # и молча открытый пример из репозитория правился бы вместо своей акции.
    page.add_argument(
        "config", type=Path, help="конфиг акции с распределением глубины скидки"
    )
    page.add_argument(
        "--inputs", type=Path, default=Path("data/anon"), help="каталог обезличенных данных"
    )
    page.add_argument("--port", type=int, default=8765, help="порт на 127.0.0.1")
    page.add_argument(
        "--work", type=Path, default=WORK_DIR, help="куда собирать книги"
    )
    page.add_argument(
        "--mapping", type=Path, default=Path("data/contracts.mapping.json"),
        help="таблица соответствия псевдонимов (остается локально)",
    )
    page.add_argument(
        "--no-open", action="store_true", help="не открывать браузер самому"
    )
    page.set_defaults(func=_cmd_page)

    doctor = commands.add_parser(
        "doctor", help="проверить окружение: LibreOffice, данные, ключ, конфиг"
    )
    doctor.add_argument(
        "--inputs", type=Path, default=Path("data/anon"), help="каталог обезличенных данных"
    )
    doctor.add_argument(
        "--config", type=Path, default=Path("configs/example_levels.yaml"),
        help="конфиг акции (по умолчанию пример из репозитория)",
    )
    doctor.add_argument(
        "--mapping", type=Path, default=Path("data/contracts.mapping.json"),
        help="таблица соответствия псевдонимов",
    )
    doctor.set_defaults(func=_cmd_doctor)

    args = parser.parse_args(argv)
    try:
        return args.func(args)
    except (
        ExportError, ParametersError, ModelError, ConfigError,
        RecalculationError, NoticeError, EditError,
    ) as error:
        print(f"выгрузка не подходит: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
