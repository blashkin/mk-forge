"""Чтение конфига акции.

Конфиг — источник истины для конкретного запуска. Данные приходят из выгрузки,
параметры и допущения из этого файла.

Раздел «допущения» обязателен, и у каждого допущения обязательно поле «почему».
Без него сборка не идет: допущение без объяснения — это то, из-за чего потом
нельзя понять, откуда в книге взялись числа.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from mkforge.core.allocation import AllocationError, DepthShare, Distribution

EFFECT_ASSUMPTION = "что_считать_эффектом"
STRUCTURE_ASSUMPTION = "структура_новых"
CONNECTION_ASSUMPTION = "подключение_новых"
HANDOUT_ASSUMPTION = "раздача_скидки"
HANDOUT_BY_VOLUME = "по_объему"
REQUIRED_ASSUMPTIONS = (
    "структура_новых",
    "подключение_новых",
    EFFECT_ASSUMPTION,
    "маржа_новых",
)


class ConfigError(Exception):
    """Конфиг неполный или противоречивый."""


@dataclass(frozen=True)
class Assumption:
    """Одно допущение: что выбрано, что это дает и почему."""

    name: str
    value: str
    why: str
    gives: str = ""
    alternative: str = ""

    def showcase_line(self) -> str:
        """Строка для витрины: экономист должен видеть, на чем стоит расчет."""
        tail = f" ({self.gives})" if self.gives else ""
        return f"{self.name}: {self.value}{tail}. {self.why.strip()}"


@dataclass(frozen=True)
class CampaignConfig:
    """Все, что задает человек для одного запуска акции."""

    name: str
    mechanic: str
    product: str
    start: dt.date
    end: dt.date
    plan_participants: int
    targets: tuple[float, ...]
    showcase_level: float
    comms_per_client: float
    share_without: float
    share_with: float
    new_share_without: float
    large_threshold_thousand_liters: float
    large_shift_points: float
    max_service_fee: float | None
    products_excluded: tuple[str, ...]
    rules: tuple[str, ...]
    assumptions: tuple[Assumption, ...]
    # Распределение глубины скидки. Пусто — глубина одна на пул, как раньше.
    distribution: Distribution | None = None
    uplift: float = 1.0
    tilt_to_volume: float = 0.0
    rate_window_months: int = 12

    def rules_text(self) -> tuple[str, ...]:
        """Правила с подставленными уровнем и датами."""
        return tuple(
            rule.format(
                уровень=f"{self.showcase_level * 100:g}",
                начало=self.start.strftime("%d.%m.%Y"),
                окончание=self.end.strftime("%d.%m.%Y"),
            )
            for rule in self.rules
        )


def _section(raw: dict[str, Any], name: str, path: Path) -> dict[str, Any]:
    value = raw.get(name)
    if not isinstance(value, dict):
        raise ConfigError(f"{path.name}: нет раздела «{name}»")
    return value


def _required(section: dict[str, Any], key: str, where: str, path: Path) -> Any:
    if key not in section:
        raise ConfigError(f"{path.name}: в разделе «{where}» нет поля «{key}»")
    return section[key]


def _date(value: Any, key: str, path: Path) -> dt.date:
    if isinstance(value, dt.datetime):
        return value.date()
    if isinstance(value, dt.date):
        return value
    raise ConfigError(f"{path.name}: «{key}» должно быть датой, а не {value!r}")


def _assumptions(raw: dict[str, Any], path: Path) -> tuple[Assumption, ...]:
    section = _section(raw, "допущения", path)
    missing = [name for name in REQUIRED_ASSUMPTIONS if name not in section]
    if missing:
        raise ConfigError(f"{path.name}: не хватает допущений {missing}")

    built = []
    for name, body in section.items():
        if not isinstance(body, dict):
            raise ConfigError(f"{path.name}: допущение «{name}» должно быть разделом")
        if not str(body.get("почему", "")).strip():
            raise ConfigError(
                f"{path.name}: у допущения «{name}» нет поля «почему»; "
                f"допущение без объяснения в расчет не берется"
            )
        built.append(
            Assumption(
                name=name,
                value=str(_required(body, "значение", f"допущения.{name}", path)),
                why=str(body["почему"]),
                gives=str(body.get("что_дает", "")),
                alternative=str(body.get("альтернатива", "")),
            )
        )
    return tuple(built)


def _distribution(
    parameters: dict[str, Any], assumptions: dict[str, Any], path: Path
) -> Distribution | None:
    """Распределение глубины скидки, если оно задано.

    Задается списком «глубина — доля», а не отображением: у отображения с
    числовыми ключами слишком легко потерять строку и не заметить этого.
    """
    raw = parameters.get("распределение_глубины")
    if raw is None:
        return None
    if not isinstance(raw, list) or not raw:
        raise ConfigError(
            f"{path.name}: «распределение_глубины» должно быть непустым списком"
        )

    shares = []
    for index, item in enumerate(raw, start=1):
        if not isinstance(item, dict) or "глубина" not in item or "доля" not in item:
            raise ConfigError(
                f"{path.name}: в строке {index} распределения нужны «глубина» и «доля»"
            )
        shares.append(DepthShare(depth=float(item["глубина"]), share=float(item["доля"])))

    handout = assumptions.get(HANDOUT_ASSUMPTION, {})
    try:
        return Distribution(
            shares=tuple(shares),
            by_volume=str(handout.get("значение", HANDOUT_BY_VOLUME)) == HANDOUT_BY_VOLUME,
        )
    except AllocationError as error:
        raise ConfigError(f"{path.name}: {error}") from error


def load_config(path: Path) -> CampaignConfig:
    """Прочитать конфиг акции и проверить его полноту."""
    if not path.exists():
        raise ConfigError(f"нет конфига {path}")
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ConfigError(f"{path.name}: пустой или не разобрался")

    campaign = _section(raw, "кампания", path)
    parameters = _section(raw, "параметры", path)
    assumptions = _assumptions(raw, path)
    limits = raw.get("ограничения") or {}

    assumptions_section = _section(raw, "допущения", path)
    effect = assumptions_section[EFFECT_ASSUMPTION]
    structure = assumptions_section.get(STRUCTURE_ASSUMPTION, {})
    for key in ("доля_пула_без_акции", "доля_пула_с_акцией"):
        if key not in effect:
            raise ConfigError(
                f"{path.name}: в допущении «{EFFECT_ASSUMPTION}» нет поля «{key}»"
            )

    targets = _required(parameters, "уровни_эффективной_скидки", "параметры", path)
    if not isinstance(targets, list) or not targets:
        raise ConfigError(f"{path.name}: «уровни_эффективной_скидки» должно быть списком")
    if any(not 0 < float(t) < 1 for t in targets):
        raise ConfigError(
            f"{path.name}: уровни задаются долями, 0.01 вместо 1 — получено {targets}"
        )

    return CampaignConfig(
        name=str(_required(campaign, "название", "кампания", path)),
        mechanic=str(_required(campaign, "механика", "кампания", path)),
        product=str(_required(campaign, "продукт", "кампания", path)),
        start=_date(_required(campaign, "начало", "кампания", path), "начало", path),
        end=_date(_required(campaign, "окончание", "кампания", path), "окончание", path),
        # План нужен только там, где новых считают вычитанием из плана.
        # При заданном распределении глубины прогноз берется из темпа подключения.
        plan_participants=int(parameters.get("план_участников", 0)),
        targets=tuple(float(t) for t in targets),
        showcase_level=float(parameters.get("уровень_на_витрине", targets[0])),
        comms_per_client=float(parameters.get("затраты_коммуникации_на_клиента", 0)),
        share_without=float(effect["доля_пула_без_акции"]),
        share_with=float(effect["доля_пула_с_акцией"]),
        new_share_without=float(effect.get("доля_новых_без_акции", 0)),
        large_threshold_thousand_liters=float(
            structure.get("порог_крупного_тыс_л", 150)
        ),
        large_shift_points=float(structure.get("сдвиг_доли_крупных_пп", 0)),
        max_service_fee=(
            float(limits["сервисный_сбор_максимум"])
            if "сервисный_сбор_максимум" in limits
            else None
        ),
        products_excluded=tuple(limits.get("продукты_вне_акции") or ()),
        rules=tuple(raw.get("правила") or ()),
        assumptions=assumptions,
        distribution=_distribution(parameters, assumptions_section, path),
        uplift=float(
            assumptions_section.get(CONNECTION_ASSUMPTION, {}).get("множитель", 1)
        ),
        tilt_to_volume=float(structure.get("смещение_к_объему", 0)),
        rate_window_months=int(
            assumptions_section.get(CONNECTION_ASSUMPTION, {}).get("окно_месяцев", 12)
        ),
    )
