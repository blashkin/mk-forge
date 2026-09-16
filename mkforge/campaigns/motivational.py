"""Мотивационная акция: надбавка к СТП под целевую эффективную скидку.

Уровень задается не номиналом надбавки, а тем, какую эффективную скидку должен
получить клиент. Номинал подбирается так, чтобы средневзвешенная эффективная
скидка равнялась цели ровно.

Вывод формулы. Эффективная скидка это (скидка - сервисный сбор) / выручка.
Надбавка m увеличивает скидку на m x выручка и уменьшает сбор на m x снижение_сбора,
потому что сбор берется с выручки после скидки. Значит

    цель = (скидка_при_0 + m x выручка - сбор_при_0 + m x снижение_сбора) / выручка

откуда

    m = (цель x выручка - скидка_при_0 + сбор_при_0) / (выручка + снижение_сбора)
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass
from typing import TYPE_CHECKING

from mkforge.core.allocation import (
    Distribution,
    DepthShare,
    allocate,
    cut_by_shares,
)
from mkforge.core.calendar import month_shares
from mkforge.core.economics import (
    Basis,
    Economics,
    Effect,
    NewClients,
    Scenario,
    basis,
    combine,
    scaled,
    scaled_scenario,
    scenario,
)
from mkforge.core.forecast import ForecastPool, build_forecast
from mkforge.core.growth import (
    DEFAULT_WINDOW_MONTHS,
    ConnectionRate,
    connection_rate,
    expected_new_clients,
)
from mkforge.core.margin import margin_for_current, margin_for_new
from mkforge.core.models import Inputs

if TYPE_CHECKING:  # pragma: no cover
    from mkforge.config import CampaignConfig
from mkforge.core.pool import Pool, build_pool, segment_mix, shift_to_large


@dataclass(frozen=True)
class Assumptions:
    """Допущения расчета. Все приходят из конфига, ни одно не из данных."""

    plan_participants: int
    share_without: float
    share_with: float
    comms_per_client: float = 0.0
    # Доля новых в сценарии без акции. По умолчанию ноль: без акции их бы не было.
    new_share_without: float = 0.0
    # Состав новых: на сколько процентных пунктов крупных больше, чем в текущем пуле.
    large_threshold_thousand_liters: float = 150.0
    large_shift_points: float = 0.0


@dataclass(frozen=True)
class Level:
    """Один уровень глубины скидки."""

    target: float
    markup: float
    without: Scenario
    with_campaign: Scenario

    @property
    def effect(self) -> Effect:
        return Effect(without=self.without, with_campaign=self.with_campaign)

    @property
    def effective_discount(self) -> float:
        """Фактическая эффективная скидка. Должна совпадать с целью."""
        return self.with_campaign.effective_discount


@dataclass(frozen=True)
class Plan:
    """Результат расчета: пул, прогноз новых и уровни глубины скидки."""

    product: str
    pool: Pool
    new: NewClients
    economics: Economics
    months_current: float
    levels: tuple[Level, ...]


def markup_for_target(base: Basis, target: float) -> float:
    """Номинал надбавки, при котором эффективная скидка равна цели."""
    denominator = base.revenue + base.fee_drop_per_point
    if denominator <= 0:
        return 0.0
    return (target * base.revenue - base.discount + base.service_fee) / denominator


def forecast_new_clients(
    inputs: Inputs,
    pool: Pool,
    product: str,
    start: dt.date,
    end: dt.date,
    plan_participants: int,
    large_threshold_thousand_liters: float = 150.0,
    large_shift_points: float = 0.0,
) -> NewClients:
    """Прогноз новых участников по составу сегментов текущего пула.

    Без сдвига состав повторяет текущий пул, и результат совпадает со средним
    по пулу. Сдвиг нужен потому, что скидку скорее дадут тем, кто везет больше:
    крупный клиент приносит больше объема, но сидит в сегменте с меньшей СТП
    и меньшей ставкой сбора. Поэтому считается состав целиком, а не множитель
    на средний объем — множитель завысил бы скидку этим клиентам.

    Срок короче срока акции, потому что подключение идет равномерно.
    """
    shares = month_shares(start, end)
    mix = shift_to_large(
        segment_mix(pool),
        threshold_thousand_liters=large_threshold_thousand_liters,
        points=large_shift_points,
    )
    return NewClients.homogeneous(
        count=max(0, plan_participants - pool.size),
        tons_per_client=mix.tons_per_contract,
        term_months=sum(s.new for s in shares),
        stp_rate=mix.stp_rate,
        fee_rate=mix.fee_rate,
        margin_per_ton=margin_for_new(inputs, product, shares),
    )


def build_plan(
    inputs: Inputs,
    product: str,
    start: dt.date,
    end: dt.date,
    assumptions: Assumptions,
    targets: tuple[float, ...],
    new: NewClients | None = None,
) -> Plan:
    """Посчитать акцию на всех уровнях глубины скидки.

    `new` подменяет прогноз новых участников. Нужно там, где прогноз пришел
    не из плана, а из прогнозного пула строками: таблица уровней в книге тогда
    тоже считает по нему, и сверять ее надо с тем же прогнозом.
    """
    shares = month_shares(start, end)
    months_current = sum(s.current for s in shares)

    pool = build_pool(inputs, product)
    product_economics = inputs.economics[product]
    economics = Economics(
        price_per_ton=product_economics.gross_revenue,
        opex_per_ton=product_economics.opex,
        margin_per_ton=margin_for_current(inputs, product, shares),
        comms_per_client=assumptions.comms_per_client,
    )
    if new is None:
        new = forecast_new_clients(
            inputs,
            pool,
            product,
            start,
            end,
            assumptions.plan_participants,
            large_threshold_thousand_liters=assumptions.large_threshold_thousand_liters,
            large_shift_points=assumptions.large_shift_points,
        )

    common = dict(
        pool=pool, new=new, economics=economics, months_current=months_current
    )
    base_without = basis(
        **common,
        current_share=assumptions.share_without,
        new_share=assumptions.new_share_without,
        with_comms=False,
    )
    base_with = basis(
        **common,
        current_share=assumptions.share_with,
        new_share=assumptions.share_with,
        with_comms=True,
    )

    levels = tuple(
        Level(
            target=target,
            markup=(markup := markup_for_target(base_with, target)),
            without=scenario(base_without, markup=0.0),
            with_campaign=scenario(base_with, markup=markup),
        )
        for target in targets
    )

    return Plan(
        product=product,
        pool=pool,
        new=new,
        economics=economics,
        months_current=months_current,
        levels=levels,
    )


# --------------------------------------------------------------------------
# Раздача скидки менеджерами: глубина не одна на пул, а распределена.
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class DistributedAssumptions:
    """Допущения расчета с распределенной глубиной скидки."""

    share_without: float
    share_with: float = 1.0
    new_share_without: float = 0.0
    comms_per_client: float = 0.0
    # Сколько участников должно быть в акции всего. Задан — новые считаются
    # вычитанием пула из плана, и темп подключения не используется.
    plan_participants: int | None = None
    # Во сколько раз менеджеры подключают быстрее обычного ритма.
    uplift: float = 1.0
    # Насколько состав новых смещен от «как средний договор» к «как средняя тонна».
    tilt_to_volume: float = 0.5
    rate_window_months: int = DEFAULT_WINDOW_MONTHS


@dataclass(frozen=True)
class DepthResult:
    """Один срез пула: своя глубина, свои участники, своя надбавка."""

    depth: float
    share: float
    contracts: float
    forecast_contracts: float
    markup: float
    without: Scenario
    with_campaign: Scenario

    @property
    def effect(self) -> Effect:
        return Effect(without=self.without, with_campaign=self.with_campaign)

    @property
    def effective_discount(self) -> float:
        """Фактическая эффективная скидка среза. Должна совпадать с глубиной."""
        return self.with_campaign.effective_discount


@dataclass(frozen=True)
class DistributedPlan:
    """Результат расчета: срезы по глубине и один итог на всю акцию."""

    product: str
    pool: Pool
    forecast: ForecastPool
    rate: ConnectionRate
    economics: Economics
    months_current: float
    distribution: Distribution
    depths: tuple[DepthResult, ...]
    without: Scenario
    with_campaign: Scenario
    breakeven_payback: float | None
    breakeven_roi: float | None

    @property
    def effect(self) -> Effect:
        return Effect(without=self.without, with_campaign=self.with_campaign)

    @property
    def effective_discount(self) -> float:
        """Итоговая эффективная скидка акции. Здесь это выход, а не задание."""
        return self.with_campaign.effective_discount

    @property
    def markup(self) -> float:
        """Средний номинал надбавки, взвешенный по выручке срезов."""
        return self.with_campaign.markup

    @property
    def depth(self) -> float:
        """Глубина акции целиком. Равна взвешенной по объему — это инвариант:
        итог не может отличаться от того, что дали срезы."""
        return self.volume_weighted_depth

    @property
    def volume_weighted_depth(self) -> float:
        """Глубина, взвешенная по объему: во что распределение обошлось."""
        revenue = sum(d.with_campaign.revenue for d in self.depths)
        if revenue <= 0:
            return 0.0
        return sum(d.depth * d.with_campaign.revenue for d in self.depths) / revenue


def _slice_inputs(
    pool: Pool, forecast: ForecastPool, distribution: Distribution
) -> tuple[tuple[DepthShare, Pool, ForecastPool, float], ...]:
    """Разложить пул и прогноз по глубинам скидки.

    В режиме «по объему» каждый срез получает свои договоры, поэтому вес единица.
    Иначе срез — доля от всего пула, и вес равен этой доле: подмножеством
    договоров такой срез не выделяется.
    """
    ordered = distribution.deepest_first()
    shares = tuple(s.share for s in ordered.shares)

    if not ordered.by_volume:
        return tuple((s, pool, forecast, s.share) for s in ordered.shares)

    pool_slices = allocate(pool, ordered)
    forecast_groups = cut_by_shares(
        forecast.members, shares, key=lambda m: -m.tons_per_month
    )
    return tuple(
        (share, piece.pool, forecast.subset(group), 1.0)
        for share, piece, group in zip(
            ordered.shares, pool_slices, forecast_groups, strict=True
        )
    )


def _breakeven(
    intercept: float, slope: float, target: float
) -> float | None:
    """Доля, при которой линейная величина достигает цели, если она достижима."""
    if abs(slope) < 1e-12:
        return None
    share = (target - intercept) / slope
    return share if 0.0 <= share <= 1.0 else None


def _new_count(
    assumptions: DistributedAssumptions,
    pool: Pool,
    rate: ConnectionRate,
    months_current: float,
) -> int:
    """Сколько новых участников брать в прогноз.

    Если задан план на всю акцию, новые — это разница между планом и текущим
    пулом: так план и понимают те, кто его ставит. Плана нет — берем
    фактический темп подключения по датам договоров.
    """
    if assumptions.plan_participants is not None:
        return max(0, assumptions.plan_participants - pool.size)
    return expected_new_clients(rate, months_current, assumptions.uplift)


def build_distributed_plan(
    inputs: Inputs,
    product: str,
    start: dt.date,
    end: dt.date,
    assumptions: DistributedAssumptions,
    distribution: Distribution,
) -> DistributedPlan:
    """Посчитать акцию, в которой глубину скидки раздают по одному.

    Эффективная скидка перестает быть заданием и становится результатом:
    она складывается из срезов. Надбавка подбирается срезу, а не пулу, —
    у крупных клиентов СТП ниже, и одна надбавка дала бы им другую глубину.
    """
    shares = month_shares(start, end)
    months_current = sum(s.current for s in shares)

    pool = build_pool(inputs, product)
    product_economics = inputs.economics[product]
    economics = Economics(
        price_per_ton=product_economics.gross_revenue,
        opex_per_ton=product_economics.opex,
        margin_per_ton=margin_for_current(inputs, product, shares),
        comms_per_client=assumptions.comms_per_client,
    )

    rate = connection_rate(inputs.contracts, assumptions.rate_window_months)
    forecast = build_forecast(
        mix=segment_mix(pool).tilted(assumptions.tilt_to_volume),
        count=_new_count(assumptions, pool, rate, months_current),
        product=product,
        start=start,
        end=end,
        margin_per_ton=margin_for_new(inputs, product, shares),
    )

    depths: list[DepthResult] = []
    for share, slice_pool, slice_forecast, weight in _slice_inputs(
        pool, forecast, distribution
    ):
        common = dict(
            pool=slice_pool,
            new=slice_forecast.new_clients(),
            economics=economics,
            months_current=months_current,
        )
        base_with = scaled(
            basis(
                **common,
                current_share=assumptions.share_with,
                new_share=assumptions.share_with,
                with_comms=True,
            ),
            weight,
        )
        base_without = scaled(
            basis(
                **common,
                current_share=assumptions.share_without,
                new_share=assumptions.new_share_without,
                with_comms=False,
            ),
            weight,
        )
        markup = markup_for_target(base_with, share.depth)
        depths.append(
            DepthResult(
                depth=share.depth,
                share=share.share,
                contracts=slice_pool.size * weight,
                forecast_contracts=slice_forecast.size * weight,
                markup=markup,
                without=scenario(base_without, markup=0.0),
                with_campaign=scenario(base_with, markup=markup),
            )
        )

    with_campaign = combine(tuple(d.with_campaign for d in depths))
    without = combine(tuple(d.without for d in depths))

    # Порог безубыточности. Сценарий без акции линеен по доле объема, поэтому
    # достаточно посчитать его в двух точках и решить уравнение, а не искать
    # перебором. Так же это считается и в книге — одной формулой.
    def without_at(share_value: float) -> Scenario:
        return scenario(
            basis(
                pool=pool,
                new=forecast.new_clients(),
                economics=economics,
                months_current=months_current,
                current_share=share_value,
                new_share=assumptions.new_share_without,
                with_comms=False,
            ),
            markup=0.0,
        )

    floor, ceiling = without_at(0.0), without_at(1.0)
    return DistributedPlan(
        product=product,
        pool=pool,
        forecast=forecast,
        rate=rate,
        economics=economics,
        months_current=months_current,
        distribution=distribution,
        depths=tuple(depths),
        without=without,
        with_campaign=with_campaign,
        breakeven_payback=_breakeven(
            intercept=floor.net_margin,
            slope=ceiling.net_margin - floor.net_margin,
            target=with_campaign.net_margin,
        ),
        breakeven_roi=_breakeven(
            intercept=floor.net_margin - floor.costs,
            slope=(ceiling.net_margin - ceiling.costs) - (floor.net_margin - floor.costs),
            target=with_campaign.net_margin - with_campaign.costs,
        ),
    )


def assumptions_from(config: "CampaignConfig") -> DistributedAssumptions:
    """Допущения расчета из конфига. Одно место на ядро и на книгу."""
    return DistributedAssumptions(
        share_without=config.share_without,
        share_with=config.share_with,
        new_share_without=config.new_share_without,
        comms_per_client=config.comms_per_client,
        plan_participants=config.plan_participants or None,
        uplift=config.uplift,
        tilt_to_volume=config.tilt_to_volume,
        rate_window_months=config.rate_window_months,
    )


def forecast_pool_from(inputs: Inputs, config: "CampaignConfig") -> ForecastPool:
    """Прогнозный пул по конфигу.

    Вызывается и ядром, и сборщиком книги: если бы каждый строил его сам,
    книга и ядро разошлись бы на первом же расхождении в аргументах.
    """
    assumptions = assumptions_from(config)
    shares = month_shares(config.start, config.end)
    months_current = sum(s.current for s in shares)
    pool = build_pool(inputs, config.product)
    rate = connection_rate(inputs.contracts, assumptions.rate_window_months)
    return build_forecast(
        mix=segment_mix(pool).tilted(assumptions.tilt_to_volume),
        count=_new_count(assumptions, pool, rate, months_current),
        product=config.product,
        start=config.start,
        end=config.end,
        margin_per_ton=margin_for_new(inputs, config.product, shares),
    )


def plan_from_config(inputs: Inputs, config: "CampaignConfig") -> DistributedPlan:
    """Расчет с распределенной глубиной по конфигу."""
    if config.distribution is None:
        raise ValueError("в конфиге не задано распределение глубины скидки")
    return build_distributed_plan(
        inputs,
        config.product,
        config.start,
        config.end,
        assumptions_from(config),
        config.distribution,
    )


@dataclass(frozen=True)
class BlendedLevel:
    """Уровень, взятый долей пула: срез акции при раздаче без учета размера."""

    target: float
    share: float
    markup: float
    without: Scenario
    with_campaign: Scenario

    @property
    def effect(self) -> Effect:
        return Effect(without=self.without, with_campaign=self.with_campaign)


@dataclass(frozen=True)
class Blend:
    """Акция, в которой пул получает разные скидки одновременно.

    Считается как смесь уровней: срез с глубиной 5% — это доля пула, прошедшая
    по строке «уровень 5%». Ничего нового считать не нужно, потому что раздача
    не зависит от размера клиента: доля берется от каждого договора.

    Так это видно и в книге: строка распределения — строка таблицы уровней,
    умноженная на долю. Проверяется глазами, без пересчета.
    """

    levels: tuple[BlendedLevel, ...]
    without: Scenario
    with_campaign: Scenario

    @property
    def effect(self) -> Effect:
        return Effect(without=self.without, with_campaign=self.with_campaign)

    @property
    def effective_discount(self) -> float:
        """Средняя скидка акции. Результат распределения, а не задание."""
        return self.with_campaign.effective_discount


def blend_levels(plan: Plan, distribution: Distribution) -> Blend:
    """Смешать уровни по долям пула.

    Доли распределения относятся к уровням расчета по глубине: на каждую глубину
    в распределении обязан быть уровень, иначе смешивать нечего.
    """
    by_target = {level.target: level for level in plan.levels}
    missing = [s.depth for s in distribution.shares if s.depth not in by_target]
    if missing:
        raise ValueError(
            f"в расчете нет уровней для глубин {missing}; "
            f"добавь их в «уровни_эффективной_скидки»"
        )

    levels = tuple(
        BlendedLevel(
            target=share.depth,
            share=share.share,
            markup=by_target[share.depth].markup,
            without=scaled_scenario(by_target[share.depth].without, share.share),
            with_campaign=scaled_scenario(
                by_target[share.depth].with_campaign, share.share
            ),
        )
        for share in distribution.deepest_first().shares
    )
    return Blend(
        levels=levels,
        without=combine(tuple(level.without for level in levels)),
        with_campaign=combine(tuple(level.with_campaign for level in levels)),
    )
