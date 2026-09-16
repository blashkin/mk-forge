"""Темп подключения новых договоров по факту, а не по плану.

План участников задавался брифом: «акция на столько-то договоров». Когда плана нет,
выдумывать число нельзя, но и не надо — в выгрузке договоров есть дата
подключения, и по ней виден фактический темп.

Берется медиана, а не среднее: в истории есть месяцы-всплески, и среднее они
тянут за собой. Последний месяц выгрузки отбрасывается — он почти всегда
неполный, и считать его наравне с остальными значит занижать темп.
"""

from __future__ import annotations

import datetime as dt
import statistics
from collections import Counter
from dataclasses import dataclass

from mkforge.core.models import Contract, ModelError

DEFAULT_WINDOW_MONTHS = 12


@dataclass(frozen=True)
class ConnectionRate:
    """Сколько договоров подключалось в месяц и на чем это посчитано."""

    per_month: float
    mean_per_month: float
    months: int
    first_month: dt.date
    last_month: dt.date
    counts: tuple[int, ...]

    def report(self) -> str:
        return (
            f"темп подключения: {self.per_month:.1f} договоров в месяц "
            f"(медиана за {self.months} мес. "
            f"с {self.first_month:%m.%Y} по {self.last_month:%m.%Y}, "
            f"среднее {self.mean_per_month:.1f})"
        )


def connection_rate(
    contracts: tuple[Contract, ...], window_months: int = DEFAULT_WINDOW_MONTHS
) -> ConnectionRate:
    """Фактический темп подключения за последние полные месяцы выгрузки."""
    if not contracts:
        raise ModelError("нет договоров, темп подключения не посчитать")
    if window_months < 1:
        raise ModelError(f"окно должно быть хотя бы в один месяц, получено {window_months}")

    by_month = Counter(
        (contract.connected.year, contract.connected.month) for contract in contracts
    )
    ordered = sorted(by_month)
    # Последний месяц выгрузки неполный: договоры в нем еще добавятся.
    complete = ordered[:-1] if len(ordered) > 1 else ordered
    window = complete[-window_months:]
    counts = tuple(by_month[month] for month in window)

    return ConnectionRate(
        per_month=float(statistics.median(counts)),
        mean_per_month=statistics.fmean(counts),
        months=len(window),
        first_month=dt.date(window[0][0], window[0][1], 1),
        last_month=dt.date(window[-1][0], window[-1][1], 1),
        counts=counts,
    )


def expected_new_clients(
    rate: ConnectionRate, campaign_months: float, uplift: float
) -> int:
    """Сколько новых участников ждать за срок акции.

    Множитель — единственное место, где вера в акцию превращается в число.
    Единица означает обычный ритм: менеджеры подключают столько же, сколько
    подключали без акции.
    """
    if uplift < 0:
        raise ModelError(f"множитель ускорения не может быть отрицательным: {uplift}")
    return max(0, round(rate.per_month * campaign_months * uplift))
