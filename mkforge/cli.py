"""Точка входа: mk-forge <команда>."""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

from mkforge.core.anonymize import ExportError, MissingKeyError, anonymize
from mkforge.core.extract import ParametersError, extract
from mkforge.config_edit import EditError
from mkforge.core.loaders import check, load_inputs
from mkforge.core.models import ModelError
from mkforge.core.notice import NoticeError
from mkforge.config import ConfigError, load_config
from mkforge.core.validate import RecalculationError, validate_path
from mkforge.core.verify import verify_all
from mkforge.doctor import diagnose
from mkforge.home import Home, HomeError, find_home, seed_configs
from mkforge.renderers.xlsx import build
from mkforge.restore import deliverable_path, restore_numbers


CONFIG_ENV_VAR = "MK_FORGE_CONFIG"

ROOT_NOTE = (
    "Относительные пути считаются от корня данных: переменная MK_FORGE_HOME, "
    "без нее — папка проекта. Текущая папка роли не играет."
)


def _path(home: Home, value: Path | None, default: Path | None = None) -> Path | None:
    """Путь из аргумента от корня данных; не задан — путь по умолчанию."""
    return home.resolve(value) if value is not None else default


def _cmd_prepare(args: argparse.Namespace, home: Home) -> int:
    """Превратить сырую книгу в безопасный набор входных данных в data/anon."""
    source = home.resolve(args.source)
    out = _path(home, args.out, home.inputs)
    anonymized = anonymize(
        source=source,
        out_dir=out,
        mapping_path=_path(home, args.mapping, home.mapping),
        root=home.root,
    )
    print(anonymized.report())
    extracted = extract(source=source, out_dir=out, notice=_path(home, args.notice))
    print(extracted.report())
    print()
    print(check(load_inputs(out)).report())
    return 0


def _cmd_verify(args: argparse.Namespace, home: Home) -> int:
    """Сверить ядро с эталонной книгой по каждому договору."""
    report = verify_all(
        book=home.resolve(args.book),
        inputs_dir=_path(home, args.inputs, home.inputs),
        mapping_path=_path(home, args.mapping, home.mapping),
        config=load_config(home.resolve(args.config)),
    )
    print(report.report())
    return 0 if report.ok else 1


def _cmd_build(args: argparse.Namespace, home: Home) -> int:
    """Собрать книгу по конфигу акции."""
    config = load_config(home.resolve(args.config))
    inputs = load_inputs(_path(home, args.inputs, home.inputs))
    report = check(inputs)
    if not report.ok:
        print(report.report(), file=sys.stderr)
        return 1
    out = _path(home, args.out, home.work / "книга.xlsx")
    print(build(inputs=inputs, config=config, path=out).report())
    return 0


def _cmd_validate(args: argparse.Namespace, home: Home) -> int:
    """Пересчитать книгу и сверить ее с расчетным ядром."""
    report = validate_path(
        book=home.resolve(args.book),
        inputs_dir=_path(home, args.inputs, home.inputs),
        config_path=home.resolve(args.config),
        work_dir=_path(home, args.work, home.work / "пересчет"),
    )
    print(report.report())
    return 0 if report.ok else 1


def _cmd_restore(args: argparse.Namespace, home: Home) -> int:
    """Вернуть настоящие номера договоров в собранную книгу."""
    # Готовые книги лежат в out/, рабочие копии на псевдонимах — уровнем ниже.
    # Так в out/ остается только то, что отдают, и убирать за собой не нужно.
    book = home.resolve(args.book)
    out = _path(home, args.out, deliverable_path(book, home.out))
    print(
        restore_numbers(
            book=book,
            mapping_path=_path(home, args.mapping, home.mapping),
            out=out,
            recalculate=not args.no_recalc,
        ).report()
    )
    return 0


def _cmd_page(args: argparse.Namespace, home: Home) -> int:
    """Поднять страницу акции. Без данных она открывается с приглашением загрузить выгрузку."""
    from mkforge.page.server import serve
    from mkforge.task.calculate import Places

    # В контейнере аргументов не передают, акцию задает переменная. Пустая
    # переменная — не задана: конфиг по умолчанию не подставляется и здесь.
    config = args.config or os.environ.get(CONFIG_ENV_VAR, "").strip()
    if not config:
        print(
            f"конфиг акции не задан: укажи его аргументом или в {CONFIG_ENV_VAR}",
            file=sys.stderr,
        )
        return 1
    for sample in seed_configs(home):
        print(f"в корне не было конфигов, положен образец {sample.name}")
    places = Places(
        root=home.root,
        raw_dir=home.raw,
        inputs_dir=_path(home, args.inputs, home.inputs),
        config_path=home.resolve(Path(config)),
        mapping_path=_path(home, args.mapping, home.mapping),
        work_dir=_path(home, args.work, home.work),
        out_dir=home.out,
    )
    return serve(
        places.open(), out_dir=home.out, host=args.host, port=args.port,
        open_browser=not args.no_open, places=places,
    )


def _cmd_doctor(args: argparse.Namespace, home: Home) -> int:
    """Показать, что найдено в окружении и чего не хватает.

    Ненулевой код — только когда книгу пересчитать нечем: на нем стоит смоук образа.
    """
    report = diagnose(
        home=home,
        inputs_dir=_path(home, args.inputs, home.inputs),
        config_path=_path(home, args.config, home.configs / "example_levels.yaml"),
        mapping_path=_path(home, args.mapping, home.mapping),
    )
    print(report.report())
    return 0 if report.can_validate else 1


def _cmd_guide(args: argparse.Namespace, home: Home) -> int:
    """Собрать гайд «Установка на Mac» из docs/install-mac.md одним html-файлом для пересылки."""
    from mkforge.guide import OUT_NAME, GuideError, build_guide

    try:
        out = build_guide(out=_path(home, args.out, home.out / OUT_NAME))
    except GuideError as error:
        print(f"гайд не собран: {error}", file=sys.stderr)
        return 1
    print(f"гайд собран: {out}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="mk-forge",
        description="Генератор расчетных моделей маркетинговых кампаний",
        epilog=ROOT_NOTE,
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
        "--out", type=Path, default=None, help="куда положить результат (по умолчанию data/anon)"
    )
    prepare.add_argument(
        "--notice", type=Path, default=None,
        help="уведомление о СТП (docx): первоисточник шкалы, только в нем трассовые ставки",
    )
    prepare.add_argument(
        "--mapping",
        type=Path,
        default=None,
        help="куда положить таблицу соответствия (по умолчанию data/contracts.mapping.json, "
        "остается локально)",
    )
    prepare.set_defaults(func=_cmd_prepare)

    verify = commands.add_parser(
        "verify",
        help="сверить расчетное ядро с эталонной книгой по каждому договору",
    )
    verify.add_argument("book", type=Path, help="эталонная книга из reference/")
    verify.add_argument(
        "--inputs", type=Path, default=None, help="каталог обезличенных данных (по умолчанию data/anon)"
    )
    verify.add_argument(
        "--mapping", type=Path, default=None,
        help="таблица соответствия псевдонимов (по умолчанию data/contracts.mapping.json)",
    )
    verify.add_argument(
        "--config", type=Path, required=True, help="конфиг акции, по которому считать"
    )
    verify.set_defaults(func=_cmd_verify)

    assemble = commands.add_parser("build", help="собрать книгу Excel по конфигу акции")
    assemble.add_argument("config", type=Path, help="конфиг акции из configs/")
    assemble.add_argument(
        "--inputs", type=Path, default=None, help="каталог обезличенных данных (по умолчанию data/anon)"
    )
    assemble.add_argument(
        "--out", type=Path, default=None,
        help="куда сохранить книгу (по умолчанию out/рабочие/книга.xlsx)"
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
        "--inputs", type=Path, default=None, help="каталог обезличенных данных (по умолчанию data/anon)"
    )
    check_book.add_argument(
        "--work", type=Path, default=None,
        help="куда положить пересчитанную копию (по умолчанию out/рабочие/пересчет)",
    )
    check_book.set_defaults(func=_cmd_validate)

    real = commands.add_parser(
        "restore",
        help="вернуть в собранную книгу настоящие номера договоров вместо псевдонимов",
    )
    real.add_argument("book", type=Path, help="собранная книга из out/")
    real.add_argument(
        "--mapping", type=Path, default=None,
        help="таблица соответствия псевдонимов (по умолчанию data/contracts.mapping.json, "
        "остается локально)",
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
        "config", type=Path, nargs="?", default=None,
        help=f"конфиг акции с распределением глубины скидки; без аргумента — из {CONFIG_ENV_VAR}",
    )
    page.add_argument(
        "--inputs", type=Path, default=None, help="каталог обезличенных данных (по умолчанию data/anon)"
    )
    page.add_argument(
        "--host", default="127.0.0.1",
        help="адрес, который слушать; в контейнере 0.0.0.0, из исходников — только петля",
    )
    page.add_argument("--port", type=int, default=8765, help="порт, один и тот же всегда")
    page.add_argument(
        "--work", type=Path, default=None,
        help="куда собирать книги (по умолчанию out/рабочие)"
    )
    page.add_argument(
        "--mapping", type=Path, default=None,
        help="таблица соответствия псевдонимов (по умолчанию data/contracts.mapping.json, "
        "остается локально)",
    )
    page.add_argument(
        "--no-open", action="store_true", help="не открывать браузер самому"
    )
    page.set_defaults(func=_cmd_page)

    doctor = commands.add_parser(
        "doctor", help="проверить окружение: LibreOffice, данные, ключ, конфиг"
    )
    doctor.add_argument(
        "--inputs", type=Path, default=None, help="каталог обезличенных данных (по умолчанию data/anon)"
    )
    doctor.add_argument(
        "--config", type=Path, default=None,
        help="конфиг акции (по умолчанию пример configs/example_levels.yaml)",
    )
    doctor.add_argument(
        "--mapping", type=Path, default=None,
        help="таблица соответствия псевдонимов (по умолчанию data/contracts.mapping.json)",
    )
    doctor.set_defaults(func=_cmd_doctor)

    guide = commands.add_parser(
        "guide",
        help="собрать гайд «Установка на Mac» из docs/install-mac.md одним html-файлом для пересылки",
    )
    guide.add_argument(
        "--out", type=Path, default=None,
        help="куда сохранить файл (по умолчанию out/Установка на Mac.html)",
    )
    guide.set_defaults(func=_cmd_guide)

    args = parser.parse_args(argv)
    try:
        home = find_home()
    except HomeError as error:
        print(f"корень данных не найден: {error}", file=sys.stderr)
        return 1
    try:
        return args.func(args, home)
    except MissingKeyError as error:
        print(f"ключ обезличивания не найден: {error}", file=sys.stderr)
        return 1
    except (
        ExportError, ParametersError, ModelError, ConfigError,
        RecalculationError, NoticeError, EditError,
    ) as error:
        print(f"выгрузка не подходит: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
