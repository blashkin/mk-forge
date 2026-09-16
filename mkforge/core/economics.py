"""Экономика акции: объем, выручка, скидка, сервисный сбор, маржа, окупаемость.

Повторяет раздел 5 листа «Расчет акции» эталонной книги. Два сценария — без акции
и с акцией, эффектом считается разница между ними. Какая доля объема относится
к каждому сценарию, задается допущением в конфиге.

Сервисный сбор здесь доход: он прибавляется к марже, а не вычитается.
Надбавка к СТП его уменьшает, потому что сбор берется с выручки после скидки.
"""

from __future__ import annotations

from dataclasses import dataclass

from mkforge.core.pool import Pool


@dataclass(frozen=True)
class NewClients:
    """Прогноз новых участников. Весь профиль — допущение, а не данные.

    Объем задан клиентомесяцами и тонно-месяцами, а не средними на клиента.
    Причина: прогнозный пул теперь лежит в книге строками, у каждой свой срок
    с даты подключения, и сумма по строкам равна произведению средних только
    если срок и объем не связаны между собой. Полагаться на это не нужно —
    достаточно суммировать то, что в строках и написано.
    """

    count: int
    ton_months: float  # сумма «объем в месяц x срок» по прогнозным строкам
    client_months: float  # сумма сроков всех прогнозных строк
    discount_ton_months: float  # сумма «объем x срок x СТП»
    fee_base_ton_months: float  # сумма «объем x срок x (1 - СТП) x ставка сбора»
    fee_ton_months: float  # сумма «объем x срок x ставка сбора»
    margin_per_ton: float

    @classmethod
    def homogeneous(
        cls,
        count: int,
        tons_per_client: float,
        term_months: float,
        stp_rate: float,
        fee_rate: float,
        margin_per_ton: float,
    ) -> "NewClients":
        """Однородный прогноз: у всех новых один объем и один срок.

        Так считала эталонная книга, и на этом пути числа с ней сходятся точно.
        """
        ton_months = count * term_months * tons_per_client
        return cls(
            count=count,
            ton_months=ton_months,
            client_months=count * term_months,
            discount_ton_months=ton_months * stp_rate,
            fee_base_ton_months=ton_months * (1 - stp_rate) * fee_rate,
            fee_ton_months=ton_months * fee_rate,
            margin_per_ton=margin_per_ton,
        )

    @property
    def tons(self) -> float:
        """Объем всех новых за их срок действия."""
        return self.ton_months

    @property
    def term_months(self) -> float:
        """Средний срок нового участника."""
        return self.client_months / self.count if self.count else 0.0

    @property
    def tons_per_client(self) -> float:
        """Среднемесячный объем одного нового участника."""
        return self.ton_months / self.client_months if self.client_months else 0.0

    @property
    def stp_rate(self) -> float:
        """СТП новых, взвешенная по объему."""
        return self.discount_ton_months / self.ton_months if self.ton_months else 0.0

    @property
    def fee_rate(self) -> float:
        """Ставка сервисного сбора новых, взвешенная по объему."""
        return self.fee_ton_months / self.ton_months if self.ton_months else 0.0


@dataclass(frozen=True)
class Economics:
    """Экономика продукта: цена, OPEX, маржа действующих, затраты коммуникации."""

    price_per_ton: float
    opex_per_ton: float
    margin_per_ton: float
    comms_per_client: float = 0.0


@dataclass(frozen=True)
class Basis:
    """Величины при нулевой надбавке — то, от чего считается любой уровень акции.

    Отделены намеренно: механика акции подбирает надбавку именно по ним и больше
    ничего об экономике знать не обязана.
    """

    participants: int
    participant_months: float
    tons: float
    revenue: float
    discount: float
    service_fee: float
    fee_drop_per_point: float
    gross_margin: float
    opex: float
    comms: float


@dataclass(frozen=True)
class Scenario:
    """Один сценарий акции при заданной надбавке."""

    markup: float
    participants: int
    participant_months: float
    tons: float
    revenue: float
    discount: float
    service_fee: float
    gross_margin: float
    opex: float
    comms: float

    @property
    def costs(self) -> float:
        """Затраты акции: скидка плюс OPEX плюс коммуникация."""
        return self.discount + self.opex + self.comms

    @property
    def net_margin(self) -> float:
        """Маржа нетто: валовая минус затраты плюс сервисный сбор как доход."""
        return self.gross_margin - self.costs + self.service_fee

    @property
    def total_discount_rate(self) -> float:
        """Итоговая скидка как доля выручки: СТП плюс надбавка."""
        return self.discount / self.revenue if self.revenue else 0.0

    @property
    def effective_discount(self) -> float:
        """Эффективная скидка: скидка за вычетом сервисного сбора, к выручке."""
        return (self.discount - self.service_fee) / self.revenue if self.revenue else 0.0


@dataclass(frozen=True)
class Effect:
    """Разница двух сценариев — то, что акция принесла."""

    without: Scenario
    with_campaign: Scenario

    @property
    def tons(self) -> float:
        return self.with_campaign.tons - self.without.tons

    @property
    def costs(self) -> float:
        return self.with_campaign.costs - self.without.costs

    @property
    def margin(self) -> float:
        return self.with_campaign.net_margin - self.without.net_margin

    @property
    def service_fee(self) -> float:
        return self.with_campaign.service_fee - self.without.service_fee

    @property
    def payback(self) -> float:
        """Окупаемость: сколько возвращается на рубль затрат, включая сам рубль."""
        return (self.margin + self.costs) / self.costs if self.costs else 0.0

    @property
    def roi(self) -> float:
        """ROI: сколько зарабатывается на рубль затрат сверх самого рубля."""
        return self.margin / self.costs if self.costs else 0.0


def basis(
    pool: Pool,
    new: NewClients,
    economics: Economics,
    months_current: float,
    current_share: float,
    new_share: float,
    with_comms: bool,
) -> Basis:
    """Собрать величины сценария при нулевой надбавке.

    Доли эффекта заданы отдельно для действующих и для новых, потому что это
    разные утверждения. В эталонной книге доля была одна на всех — она получается
    при равных значениях, и этот случай воспроизводится точно.

    Раздельные доли нужны для честного сценария: объем действующих клиентов
    частично сохранился бы и без акции, а новых без акции не было бы вовсе.
    """
    price = economics.price_per_ton
    current_tons = pool.total_tons_per_month * months_current * current_share
    new_tons = new.tons * new_share

    tons = current_tons + new_tons
    participants = pool.size + new.count
    participant_months = (
        pool.size * months_current * current_share + new.client_months * new_share
    )

    # По новым участникам суммы берутся готовыми, а не через средние ставки:
    # произведение средних не равно среднему произведений, и на прогнозном пуле
    # строками это дало бы расхождение с книгой.
    discount = price * (
        pool.discount_tons * months_current * current_share
        + new.discount_ton_months * new_share
    )
    service_fee = price * (
        pool.fee_base_tons * months_current * current_share
        + new.fee_base_ton_months * new_share
    )
    fee_drop_per_point = price * (
        pool.fee_tons * months_current * current_share
        + new.fee_ton_months * new_share
    )
    gross_margin = (
        current_tons * economics.margin_per_ton + new_tons * new.margin_per_ton
    )

    return Basis(
        participants=participants,
        participant_months=participant_months,
        tons=tons,
        revenue=tons * price,
        discount=discount,
        service_fee=service_fee,
        fee_drop_per_point=fee_drop_per_point,
        gross_margin=gross_margin,
        opex=tons * economics.opex_per_ton,
        # Коммуникация есть только в сценарии с акцией: без нее ее не на что тратить.
        comms=(
            current_share * participants * economics.comms_per_client
            if with_comms
            else 0.0
        ),
    )


def scenario(base: Basis, markup: float) -> Scenario:
    """Применить надбавку к базе.

    Надбавка увеличивает скидку на свою долю выручки и на столько же уменьшает
    базу сервисного сбора — поэтому сбор падает на `fee_drop_per_point x надбавка`.
    """
    return Scenario(
        markup=markup,
        participants=base.participants,
        participant_months=base.participant_months,
        tons=base.tons,
        revenue=base.revenue,
        discount=base.discount + markup * base.revenue,
        service_fee=base.service_fee - markup * base.fee_drop_per_point,
        gross_margin=base.gross_margin,
        opex=base.opex,
        comms=base.comms,
    )


def scaled(base: Basis, factor: float) -> Basis:
    """Взять долю базы. Все величины аддитивны, поэтому масштабируются линейно.

    Нужно для раздачи скидки, не зависящей от размера клиента: там срез — это
    доля от каждого договора, а не подмножество договоров, и выделить его
    подпулом нельзя.
    """
    return Basis(
        participants=round(base.participants * factor),
        participant_months=base.participant_months * factor,
        tons=base.tons * factor,
        revenue=base.revenue * factor,
        discount=base.discount * factor,
        service_fee=base.service_fee * factor,
        fee_drop_per_point=base.fee_drop_per_point * factor,
        gross_margin=base.gross_margin * factor,
        opex=base.opex * factor,
        comms=base.comms * factor,
    )


def scaled_scenario(source: Scenario, factor: float) -> Scenario:
    """Доля сценария. Надбавка не масштабируется: это ставка, а не величина."""
    return Scenario(
        markup=source.markup,
        participants=round(source.participants * factor),
        participant_months=source.participant_months * factor,
        tons=source.tons * factor,
        revenue=source.revenue * factor,
        discount=source.discount * factor,
        service_fee=source.service_fee * factor,
        gross_margin=source.gross_margin * factor,
        opex=source.opex * factor,
        comms=source.comms * factor,
    )


def combine(scenarios: tuple[Scenario, ...]) -> Scenario:
    """Сложить сценарии срезов в один.

    Надбавка у срезов разная, поэтому в итоге она взвешивается по выручке:
    это средний номинал, с которым акция прошла, а не параметр расчета.
    """
    if not scenarios:
        raise ValueError("нечего складывать: срезов ноль")

    def total(field: str) -> float:
        return sum(getattr(s, field) for s in scenarios)

    revenue = total("revenue")
    markup = (
        sum(s.markup * s.revenue for s in scenarios) / revenue if revenue else 0.0
    )
    return Scenario(
        markup=markup,
        participants=sum(s.participants for s in scenarios),
        participant_months=total("participant_months"),
        tons=total("tons"),
        revenue=revenue,
        discount=total("discount"),
        service_fee=total("service_fee"),
        gross_margin=total("gross_margin"),
        opex=total("opex"),
        comms=total("comms"),
    )
