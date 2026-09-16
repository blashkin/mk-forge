"""Поля формы поверх конфига акции.

Неверный ввод — нормальный исход, а не сбой: человек стирает цифру в поле, и на
полсекунды доли не дают единицу. Поэтому здесь ничего не бросается наружу,
а возвращается список ошибок по полям.

Что законно, решает не этот модуль. Сумму долей, повторы глубин и «5 вместо
0.05» проверяет `Distribution` в ядре, и его русский текст идет на страницу
дословно. Повторить эти проверки здесь значило бы завести вторую правду о том,
что допустимо, и однажды они разойдутся.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, replace
from typing import Any, Mapping

from mkforge.config import HANDOUT_ASSUMPTION, HANDOUT_BY_VOLUME, CampaignConfig
from mkforge.core.allocation import AllocationError, DepthShare, Distribution
from mkforge.task.fields import BY_NAME, handout_of


@dataclass(frozen=True)
class FieldError:
    """Что не так и с каким полем. Пустое имя — ошибка всей формы."""

    field: str
    message: str

    def payload(self) -> dict:
        return {"field": self.field, "message": self.message}


def _number(value: Any, name: str, errors: list[FieldError]) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        errors.append(FieldError(name, "нужно число"))
        return None


def _date(value: Any, name: str, errors: list[FieldError]) -> dt.date | None:
    if isinstance(value, dt.date):
        return value
    try:
        return dt.date.fromisoformat(str(value))
    except ValueError:
        errors.append(FieldError(name, "нужна дата в виде 2026-03-01"))
        return None


def _bounded(value: float, name: str, errors: list[FieldError]) -> float | None:
    field = BY_NAME[name]
    if field.low is not None and value < field.low:
        errors.append(FieldError(name, f"не меньше {field.low:g}"))
        return None
    if field.high is not None and value > field.high:
        errors.append(FieldError(name, f"не больше {field.high:g}"))
        return None
    return value


def _distribution(
    config: CampaignConfig, overrides: Mapping[str, Any], errors: list[FieldError]
) -> Distribution | None:
    """Собрать распределение из строк таблицы и переключателя раздачи.

    Оба поля влияют на один объект, поэтому строится он один раз и здесь:
    иначе переключатель менял бы слово в допущении, а расчет оставался прежним.
    """
    rows = overrides.get("distribution")
    handout = str(overrides.get("handout", handout_of(config)))
    if handout not in {value for value, _ in BY_NAME["handout"].options}:
        errors.append(FieldError("handout", "неизвестный способ раздачи"))
        return None

    if rows is None:
        if config.distribution is None:
            return None
        shares = config.distribution.shares
    else:
        if not isinstance(rows, (list, tuple)):
            errors.append(FieldError("distribution", "нужен список строк"))
            return None
        shares = []
        for index, row in enumerate(rows, start=1):
            if not isinstance(row, Mapping) or "depth" not in row or "share" not in row:
                errors.append(
                    FieldError("distribution", f"в строке {index} нужны глубина и доля")
                )
                return None
            depth = _number(row["depth"], "distribution", errors)
            share = _number(row["share"], "distribution", errors)
            if depth is None or share is None:
                return None
            shares.append(DepthShare(depth=depth, share=share))
        shares = tuple(shares)

    try:
        return Distribution(shares=tuple(shares), by_volume=handout == HANDOUT_BY_VOLUME)
    except AllocationError as error:
        errors.append(FieldError("distribution", str(error)))
        return None


def _assumptions(config: CampaignConfig, handout: str) -> tuple:
    """Слово в допущении о раздаче должно совпадать с флагом распределения.

    Это не украшение: допущения печатаются на витрине книги, и расхождение
    означало бы книгу, которая говорит одно, а считает другое.
    """
    return tuple(
        replace(assumption, value=handout)
        if assumption.name == HANDOUT_ASSUMPTION
        else assumption
        for assumption in config.assumptions
    )


def apply(
    config: CampaignConfig, overrides: Mapping[str, Any]
) -> tuple[CampaignConfig | None, list[FieldError]]:
    """Наложить поля формы на конфиг. Ошибки — по полям, исключений нет."""
    errors: list[FieldError] = []
    changes: dict[str, Any] = {}

    unknown = [name for name in overrides if name not in BY_NAME]
    for name in unknown:
        errors.append(FieldError(name, "неизвестное поле"))

    for name, value in overrides.items():
        field = BY_NAME.get(name)
        if field is None or field.kind in {"table", "choice"}:
            continue  # распределение и раздача собираются вместе, ниже
        if field.kind == "date":
            parsed = _date(value, name, errors)
            if parsed is not None:
                changes[name] = parsed
        elif field.kind == "levels":
            if not isinstance(value, (list, tuple)) or not value:
                errors.append(FieldError(name, "нужен непустой список уровней"))
                continue
            levels = [_number(item, name, errors) for item in value]
            if any(level is None for level in levels):
                continue
            if any(not 0 < level < 1 for level in levels):
                errors.append(FieldError(name, "уровни задаются долями, 0.01 вместо 1"))
                continue
            changes[name] = tuple(levels)
        else:
            number = _number(value, name, errors)
            if number is None:
                continue
            number = _bounded(number, name, errors)
            if number is None:
                continue
            changes[name] = int(number) if field.kind == "count" else number

    distribution = _distribution(config, overrides, errors)
    if distribution is not None:
        changes["distribution"] = distribution
    handout = str(overrides.get("handout", handout_of(config)))
    if "handout" in overrides and not errors:
        changes["assumptions"] = _assumptions(config, handout)

    start = changes.get("start", config.start)
    end = changes.get("end", config.end)
    if end < start:
        errors.append(FieldError("end", "окончание раньше начала"))

    if errors:
        return None, errors
    return replace(config, **changes), []
