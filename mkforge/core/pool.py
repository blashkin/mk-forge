"""Пул акции: к какому сегменту шкалы относится каждый договор и что он приносит.

Повторяет вспомогательные колонки листа «База участников» эталонной книги:
среднемесячный объем топлива, сегмент шкалы и СТП, объем продукта акции,
собственную ставку сервисного сбора клиента.

Период транзакций один на всю выгрузку, как и в книге: он считается по разбегу
месяцев во всех транзакциях, а не по каждому договору отдельно.
"""

from __future__ import annotations

from dataclasses import dataclass, replace

from mkforge.core.models import FUEL_CLASS, Inputs, ModelError, StpBracket, Transaction

LITERS_IN_THOUSAND = 1000


@dataclass(frozen=True)
class PoolMember:
    """Договор пула с величинами, от которых зависит его скидка."""

    contract: str
    segment: str
    fuel_liters_per_month: float
    product_tons_per_month: float
    stp_rate: float
    service_fee_rate: float
    bracket: StpBracket

    @property
    def effective_discount_without_campaign(self) -> float:
        """Эффективная скидка без акции: шкала СТП против сервисного сбора."""
        return 1 - (1 - self.stp_rate) * (1 + self.service_fee_rate)

    def effective_discount(self, markup: float) -> float:
        """Эффективная скидка при надбавке к СТП."""
        return 1 - (1 - self.stp_rate - markup) * (1 + self.service_fee_rate)


@dataclass(frozen=True)
class Pool:
    """Пул акции целиком."""

    product: str
    period_months: int
    members: tuple[PoolMember, ...]

    @property
    def size(self) -> int:
        return len(self.members)

    @property
    def total_tons_per_month(self) -> float:
        return sum(m.product_tons_per_month for m in self.members)

    @property
    def tons_per_contract(self) -> float:
        """Средний объем на договор пула, включая договоры без продукта акции.

        Делим на весь пул, а не на договоры с объемом: так считает эталонная книга,
        и так получается консервативнее.
        """
        return self.total_tons_per_month / self.size if self.size else 0.0

    @property
    def contracts_with_volume(self) -> int:
        return sum(1 for m in self.members if m.product_tons_per_month > 0)

    @property
    def discount_tons(self) -> float:
        """Сумма «объем x СТП» по пулу. Колонка S эталонной книги."""
        return sum(m.product_tons_per_month * m.stp_rate for m in self.members)

    @property
    def fee_base_tons(self) -> float:
        """База сервисного сбора без акции: объем после СТП, умноженный на ставку.

        Колонка U эталонной книги.
        """
        return sum(
            m.product_tons_per_month * (1 - m.stp_rate) * m.service_fee_rate
            for m in self.members
        )

    @property
    def fee_tons(self) -> float:
        """Сумма «объем x ставка сбора». На столько падает сбор с каждого п.п. надбавки."""
        return sum(m.product_tons_per_month * m.service_fee_rate for m in self.members)

    def weighted(self, attribute: str) -> float:
        """Средневзвешенное по объему продукта: так книга считает СТП и ставку сбора."""
        weight = self.total_tons_per_month
        if weight <= 0:
            return 0.0
        return sum(getattr(m, attribute) * m.product_tons_per_month for m in self.members) / weight


@dataclass(frozen=True)
class SegmentShare:
    """Один сегмент шкалы в составе пула: сколько договоров и что они приносят."""

    bracket: StpBracket
    contracts: int
    share: float  # доля договоров, не объема
    tons_per_contract: float
    stp_rate: float
    fee_rate: float

    @property
    def tons(self) -> float:
        """Вклад сегмента в объем на одного условного участника."""
        return self.share * self.tons_per_contract


@dataclass(frozen=True)
class Mix:
    """Состав участников по сегментам шкалы.

    Нужен, чтобы не считать новых по средним по пулу. Крупный клиент приносит
    больше объема, но сидит в сегменте с меньшей СТП и меньшей ставкой сбора —
    поэтому множитель на средний объем дал бы неверный ответ, и состав приходится
    держать целиком.
    """

    segments: tuple[SegmentShare, ...]

    @property
    def tons_per_contract(self) -> float:
        """Объем одного участника такого состава."""
        return sum(segment.tons for segment in self.segments)

    def _weighted(self, attribute: str) -> float:
        """Средневзвешенное по объему: так же, как книга считает СТП и сбор."""
        weight = self.tons_per_contract
        if weight <= 0:
            return 0.0
        return sum(getattr(s, attribute) * s.tons for s in self.segments) / weight

    @property
    def stp_rate(self) -> float:
        return self._weighted("stp_rate")

    @property
    def fee_rate(self) -> float:
        return self._weighted("fee_rate")

    def by_volume(self) -> "Mix":
        """Тот же состав, но доли считаются по объему, а не по числу договоров.

        Два разных утверждения о том, кого приведут менеджеры. По договорам —
        «новые будут как пул в среднем»: пул состоит в основном из мелких, значит
        и новые будут мелкими. По объему — «новые будут похожи на тех, кто везет»:
        крупные сегменты держат доли процента договоров, но больше половины
        объема, и в составе они выходят на первый план.

        Второе утверждение и заявлено: скидку раздают менеджеры, и приводить они
        будут тех, за кем объем.
        """
        weight = sum(segment.share * segment.tons_per_contract for segment in self.segments)
        if weight <= 0:
            return self
        return Mix(
            segments=tuple(
                replace(
                    segment,
                    share=segment.share * segment.tons_per_contract / weight,
                )
                for segment in self.segments
            )
        )

    def tilted(self, toward_volume: float) -> "Mix":
        """Состав между «как средний договор» и «как средняя тонна».

        Ноль — новые похожи на типичный договор пула, а пул состоит в основном
        из мелких. Единица — новые похожи на тех, за кем объем, и состав уезжает
        в верх шкалы. Промежуточные значения смешивают доли линейно.

        Одна ручка вместо порога и сдвига: у нее понятны оба конца, и выбор
        видно на витрине как число, а не как пара технических параметров.
        """
        if toward_volume <= 0:
            return self
        weighted = self.by_volume()
        share = min(1.0, toward_volume)
        return Mix(
            segments=tuple(
                replace(
                    segment,
                    share=segment.share * (1 - share) + volume_segment.share * share,
                )
                for segment, volume_segment in zip(
                    self.segments, weighted.segments, strict=True
                )
            )
        )

    def large_share(self, threshold_thousand_liters: float) -> float:
        """Доля договоров в сегментах от порога и выше."""
        return sum(
            s.share for s in self.segments if s.bracket.low >= threshold_thousand_liters
        )


def segment_mix(pool: Pool) -> Mix:
    """Разложить пул по сегментам шкалы."""
    groups: dict[str, list[PoolMember]] = {}
    for member in pool.members:
        groups.setdefault(member.bracket.label, []).append(member)

    segments = []
    for members in groups.values():
        tons = sum(m.product_tons_per_month for m in members)
        fee = (
            sum(m.service_fee_rate * m.product_tons_per_month for m in members) / tons
            if tons > 0
            else 0.0
        )
        segments.append(
            SegmentShare(
                bracket=members[0].bracket,
                contracts=len(members),
                share=len(members) / pool.size if pool.size else 0.0,
                tons_per_contract=tons / len(members),
                stp_rate=members[0].stp_rate,
                fee_rate=fee,
            )
        )
    return Mix(segments=tuple(sorted(segments, key=lambda s: s.bracket.low)))


def shift_to_large(mix: Mix, threshold_thousand_liters: float, points: float) -> Mix:
    """Передвинуть долю договоров из мелких сегментов в крупные.

    `points` — насколько процентных пунктов растет доля сегментов от порога и выше.
    Внутри групп доли меняются пропорционально уже имеющимся, то есть форма
    распределения сохраняется, смещается только вес между группами.

    Сдвиг ограничен тем, что есть: больше, чем осталось у мелких, забрать нельзя.
    """
    if points <= 0:
        return mix

    large = [s for s in mix.segments if s.bracket.low >= threshold_thousand_liters]
    small = [s for s in mix.segments if s.bracket.low < threshold_thousand_liters]
    if not large or not small:
        return mix

    small_share = sum(s.share for s in small)
    large_share = sum(s.share for s in large)
    moved = min(points / 100, small_share)
    if moved <= 0 or large_share <= 0:
        return mix

    shifted = []
    for segment in mix.segments:
        if segment.bracket.low >= threshold_thousand_liters:
            share = segment.share * (large_share + moved) / large_share
        else:
            share = segment.share * (small_share - moved) / small_share
        shifted.append(replace(segment, share=share))
    return Mix(segments=tuple(shifted))


def period_months(transactions: tuple[Transaction, ...]) -> int:
    """Сколько месяцев покрывает выгрузка.

    Повторяет DATEDIF(MIN, MAX, "m") + 1 эталонной книги: разбег месяцев плюс один.
    """
    months = {(t.month.year, t.month.month) for t in transactions}
    if not months:
        raise ModelError("в выгрузке нет транзакций, период не определить")
    first, last = min(months), max(months)
    return (last[0] - first[0]) * 12 + (last[1] - first[1]) + 1


def build_pool(inputs: Inputs, product: str) -> Pool:
    """Собрать пул по договорам и транзакциям.

    В пул входят все договоры из выгрузки договоров, даже без транзакций: в книге
    они тоже остаются строками с нулевым объемом и влияют на средние.
    """
    months = period_months(inputs.transactions)

    fuel_liters: dict[str, float] = {}
    product_tons: dict[str, float] = {}
    product_revenue: dict[str, float] = {}
    product_fee: dict[str, float] = {}

    for transaction in inputs.transactions:
        contract = transaction.contract
        if transaction.product_class == FUEL_CLASS:
            fuel_liters[contract] = fuel_liters.get(contract, 0.0) + transaction.liters
        if transaction.product == product:
            product_tons[contract] = product_tons.get(contract, 0.0) + transaction.tons
            product_revenue[contract] = product_revenue.get(contract, 0.0) + transaction.revenue
            product_fee[contract] = product_fee.get(contract, 0.0) + transaction.service_fee

    members = []
    for contract in inputs.contracts:
        key = contract.contract
        liters = fuel_liters.get(key, 0.0) / months
        tons = product_tons.get(key, 0.0) / months
        revenue = product_revenue.get(key, 0.0)
        fee = product_fee.get(key, 0.0)

        thousands = liters / LITERS_IN_THOUSAND
        bracket = inputs.scale.bracket_for(thousands)
        members.append(
            PoolMember(
                contract=key,
                segment=contract.segment,
                fuel_liters_per_month=liters,
                product_tons_per_month=tons,
                stp_rate=bracket.rate(product),
                service_fee_rate=abs(fee / revenue) if revenue else 0.0,
                bracket=bracket,
            )
        )

    return Pool(product=product, period_months=months, members=tuple(members))
