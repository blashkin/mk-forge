"""Поля, которые человек меняет на странице.

Таблица одна на троих: по ней проверяется ввод, по ней же правится yaml и по ней
же страница рисует форму. Разойтись им негде — а разойдись они, появилось бы
поле, которое видно, но не сохраняется, или сохраняется не туда.

`path` — путь ключа в конфиге акции. Он здесь не для красоты: точечный редактор
yaml ходит именно по нему, поэтому опечатка в пути — это не косметика, а правка,
которая уедет в соседнюю секцию.

Единицы храним долями, как во всем проекте. Проценты человек видит процентами,
но это забота страницы, а не этого модуля.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass
from typing import Any

from mkforge.config import (
    CONNECTION_ASSUMPTION,
    EFFECT_ASSUMPTION,
    HANDOUT_ASSUMPTION,
    HANDOUT_BY_VOLUME,
    STRUCTURE_ASSUMPTION,
    CampaignConfig,
)

HANDOUT_ANY_SIZE = "вне_зависимости_от_размера"

# Разделы формы. Порядок — порядок на странице.
SECTIONS = (
    ("campaign", "Акция"),
    ("depths", "Кому какая скидка"),
    ("participants", "Участники"),
    ("effect", "Что считать эффектом"),
    ("costs", "Затраты"),
    ("reference", "Справочно"),
)


@dataclass(frozen=True)
class Field:
    """Одно поле формы и его место в конфиге."""

    name: str
    path: tuple[str, ...]
    kind: str  # date | fraction | money | count | ratio | choice | table | levels
    label: str
    section: str
    hint: str = ""
    low: float | None = None
    high: float | None = None
    step: float | None = None
    options: tuple[tuple[str, str], ...] = ()

    def optional_in_yaml(self) -> bool:
        """Можно ли дописать ключ, если его в конфиге нет.

        Дописываем только то, что законно отсутствует: конфиг мог быть написан
        до появления этой ручки. Обязательные ключи не дописываем никогда —
        `load_config` молча игнорирует незнакомые, и запись не туда дала бы файл,
        который читается по-старому, но выглядит исправленным.
        """
        return self.name in OPTIONAL


OPTIONAL = frozenset(
    {"distribution", "handout", "tilt_to_volume", "uplift", "rate_window_months",
     "new_share_without", "showcase_level", "comms_per_client"}
)

FIELDS: tuple[Field, ...] = (
    Field("start", ("кампания", "начало"), "date", "Начало", "campaign"),
    Field("end", ("кампания", "окончание"), "date", "Окончание", "campaign"),

    Field("distribution", ("параметры", "распределение_глубины"), "table",
          "Глубина скидки и доля пула", "depths",
          hint="Доли по договорам, сумма должна давать единицу"),
    Field("handout", ("допущения", HANDOUT_ASSUMPTION, "значение"), "choice",
          "Как раздают скидку", "depths",
          hint="Глубже крупным — консервативный случай: пул концентрирован, "
               "и глубокие проценты приходятся на большую часть объема",
          options=((HANDOUT_BY_VOLUME, "Глубже тем, кто больше везет"),
                   (HANDOUT_ANY_SIZE, "Вне зависимости от размера клиента"))),

    Field("plan_participants", ("параметры", "план_участников"), "count",
          "План участников, всего", "participants", low=0, step=1,
          hint="Новые — это план минус текущий пул. Ноль означает «плана нет»: "
               "тогда прогноз идет от фактического темпа подключения"),
    Field("uplift", ("допущения", CONNECTION_ASSUMPTION, "множитель"), "ratio",
          "Множитель ускорения подключения", "participants", low=0, step=0.1,
          hint="Работает только когда плана нет. Единственное место, где вера "
               "в акцию превращается в число"),
    Field("rate_window_months", ("допущения", CONNECTION_ASSUMPTION, "окно_месяцев"),
          "count", "Окно темпа подключения, мес.", "participants", low=1, step=1),
    Field("tilt_to_volume", ("допущения", STRUCTURE_ASSUMPTION, "смещение_к_объему"),
          "fraction", "Состав новых: к объему", "participants", low=0, high=1, step=0.05,
          hint="Ноль — новый похож на типичный договор пула, единица — на того, "
               "за кем объем"),

    Field("share_without", ("допущения", EFFECT_ASSUMPTION, "доля_пула_без_акции"),
          "fraction", "Доля объема, которая сохранилась бы без акции", "effect",
          low=0, high=1, step=0.01,
          hint="Главный рычаг: это единственное число, которое решает знак результата"),
    Field("share_with", ("допущения", EFFECT_ASSUMPTION, "доля_пула_с_акцией"),
          "fraction", "Доля объема, которая считается с акцией", "effect",
          low=0, high=1, step=0.01),
    Field("new_share_without", ("допущения", EFFECT_ASSUMPTION, "доля_новых_без_акции"),
          "fraction", "Доля новых, которые пришли бы и без акции", "effect",
          low=0, high=1, step=0.01),

    Field("comms_per_client", ("параметры", "затраты_коммуникации_на_клиента"), "money",
          "Коммуникация на клиента, руб.", "costs", low=0, step=100),

    Field("targets", ("параметры", "уровни_эффективной_скидки"), "levels",
          "Уровни эффективной скидки", "reference",
          hint="Кормят справочную таблицу уровней в книге, на расчет акции не влияют"),
    Field("showcase_level", ("параметры", "уровень_на_витрине"), "fraction",
          "Уровень на витрине", "reference", low=0, high=1, step=0.01),
)

BY_NAME: dict[str, Field] = {field.name: field for field in FIELDS}


def handout_of(config: CampaignConfig) -> str:
    """Как раздают скидку — по допущению, а не по флагу распределения.

    Флаг `by_volume` производный: конфиг задает раздачу словом в допущении,
    и менять их надо вместе, иначе витрина книги напечатает одно, а раздел
    расчета посчитает другое.
    """
    if config.distribution is not None:
        return HANDOUT_BY_VOLUME if config.distribution.by_volume else HANDOUT_ANY_SIZE
    for assumption in config.assumptions:
        if assumption.name == HANDOUT_ASSUMPTION:
            return assumption.value
    return HANDOUT_BY_VOLUME


def value_of(config: CampaignConfig, field: Field) -> Any:
    """Текущее значение поля — то, что показать в форме при открытии."""
    if field.name == "distribution":
        if config.distribution is None:
            return []
        return [
            {"depth": share.depth, "share": share.share}
            for share in config.distribution.shares
        ]
    if field.name == "handout":
        return handout_of(config)
    if field.name == "targets":
        return list(config.targets)
    value = getattr(config, field.name)
    if isinstance(value, dt.date):
        return value.isoformat()
    return value


def values(config: CampaignConfig) -> dict[str, Any]:
    """Все поля формы разом."""
    return {field.name: value_of(config, field) for field in FIELDS}
