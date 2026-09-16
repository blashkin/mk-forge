"""Типизированные модели входных данных.

Имена полей английские, имена колонок в csv русские — связка через алиасы pydantic.
Колонки csv менять нельзя: это контракт с обезличенной выгрузкой.

Проценты везде доли: 0.025, а не 2.5.
"""

from __future__ import annotations

from datetime import date

from pydantic import BaseModel, ConfigDict, Field, field_validator

PRODUCTS = ("АБ", "ДТ", "СУГ")
FUEL_CLASS = "НП"

_CONFIG = ConfigDict(populate_by_name=True, frozen=True, extra="forbid")


class ModelError(Exception):
    """Входные данные не той формы."""


class Transaction(BaseModel):
    """Строка обезличенной выгрузки транзакций: договор за месяц по виду продукта."""

    model_config = _CONFIG

    contract: str = Field(alias="договор")
    segment: str = Field(alias="сегмент")
    month: date = Field(alias="месяц")
    product: str = Field(alias="вид_продукта")
    product_class: str = Field(alias="класс_продукта")
    liters: float = Field(alias="количество_л")
    tons: float = Field(alias="объем_т")
    revenue: float = Field(alias="выручка_со_скидкой")
    raw_service_fee: float = Field(alias="сервисный_сбор")
    branch: str = Field(alias="отделение", default="")

    @field_validator("segment", "product", "product_class", "branch", mode="before")
    @classmethod
    def _blank_instead_of_missing(cls, value: object) -> str:
        """В выгрузке попадаются строки с незаполненной разметкой.

        Эталонная книга их молча игнорирует: SUMIFS по виду продукта или отделению
        на них не срабатывает. Принимаем такую строку, но `check` о ней сообщает —
        молчать об этом нельзя.
        """
        return "" if value is None else str(value)

    @property
    def service_fee(self) -> float:
        """В выгрузке сбор приходит со знаком минус, в расчете берется по модулю.

        Эталонная книга делает то же самое через ABS. Храним как пришло, чтобы
        не терять исходный знак, а наружу отдаем по модулю.
        """
        return abs(self.raw_service_fee)

    @property
    def is_fuel(self) -> bool:
        """Топливо, а не сопутствующие товары и услуги."""
        return self.product_class == FUEL_CLASS

    @property
    def is_classified(self) -> bool:
        """Разметка заполнена: строка вообще попадет хоть в один итог."""
        return bool(self.product and self.product_class)


class Contract(BaseModel):
    """Договор из пула акции."""

    model_config = _CONFIG

    contract: str = Field(alias="договор")
    segment: str = Field(alias="сегмент")
    connected: date = Field(alias="дата_подключения")


class StpBracket(BaseModel):
    """Сегмент шкалы СТП: границы объема выборки и скидка по каждому продукту."""

    model_config = _CONFIG

    label: str = Field(alias="сегмент")
    low: float = Field(alias="мин_тыс_л")
    high: float = Field(alias="макс_тыс_л")
    ab: float = Field(alias="аб")
    dt: float = Field(alias="дт")
    lpg: float = Field(alias="суг")
    # Трассовая шкала есть только в уведомлении. Ноль означает, что шкалу взяли
    # из книги, где эта колонка не заведена, а не что скидки на трассе нет.
    dt_highway: float = Field(alias="дт_трасса", default=0.0)

    def rate(self, product: str, highway: bool = False) -> float:
        """Скидка сегмента. На трассовых АЗС у ДТ своя, более глубокая шкала."""
        match product:
            case "АБ":
                return self.ab
            case "ДТ":
                return self.dt_highway if highway else self.dt
            case "СУГ":
                return self.lpg
        raise ModelError(f"нет скидки для вида продукта «{product}», ожидались {PRODUCTS}")


class StpScale(BaseModel):
    """Шкала СТП целиком. Сегменты идут по возрастанию нижней границы."""

    model_config = ConfigDict(frozen=True)

    brackets: tuple[StpBracket, ...]

    @field_validator("brackets")
    @classmethod
    def _ascending(cls, brackets: tuple[StpBracket, ...]) -> tuple[StpBracket, ...]:
        if not brackets:
            raise ValueError("шкала СТП пустая")
        lows = [b.low for b in brackets]
        if lows != sorted(lows) or len(set(lows)) != len(lows):
            raise ValueError("нижние границы шкалы СТП не возрастают строго")
        return brackets

    def bracket_for(self, volume_thousand_liters: float) -> StpBracket:
        """Сегмент шкалы для объема выборки клиента.

        Повторяет MATCH(объем, нижние границы, 1) эталонной книги: берется последний
        сегмент, чья нижняя граница не превышает объем.
        """
        found = None
        for bracket in self.brackets:
            if bracket.low <= volume_thousand_liters:
                found = bracket
            else:
                break
        if found is None:
            raise ModelError(
                f"объем {volume_thousand_liters} ниже первого сегмента шкалы "
                f"({self.brackets[0].low})"
            )
        return found

    def rate(
        self, product: str, volume_thousand_liters: float, highway: bool = False
    ) -> float:
        """Скидка для объема выборки клиента."""
        return self.bracket_for(volume_thousand_liters).rate(product, highway=highway)

    @property
    def has_highway(self) -> bool:
        """Есть ли в шкале трассовые ставки. Их приносит только уведомление."""
        return any(bracket.dt_highway > 0 for bracket in self.brackets)


class ProductEconomics(BaseModel):
    """Экономика вида продукта. Собирается сведением таблицы показателей."""

    model_config = _CONFIG

    product: str
    stp_without_campaign: float
    gross_revenue: float
    cost: float
    opex: float
    base_margin: float
    service_fee_rate: float
    stiu_margin: float


class MarginForecast(BaseModel):
    """Строка прогноза маржи экономистов: месяц, продукт, регион."""

    model_config = _CONFIG

    month: str = Field(alias="месяц")
    product: str = Field(alias="вид_продукта")
    margin: float = Field(alias="маржа_руб_т")
    region: str = Field(alias="регион")


class BranchRegion(BaseModel):
    """Строка таблицы отделений: к какому региону прогноза маржи относится отделение."""

    model_config = _CONFIG

    branch: str = Field(alias="отделение")
    region: str = Field(alias="регион")


class Inputs(BaseModel):
    """Все входные данные одной сборки."""

    model_config = ConfigDict(frozen=True, arbitrary_types_allowed=True)

    transactions: tuple[Transaction, ...]
    contracts: tuple[Contract, ...]
    scale: StpScale
    economics: dict[str, ProductEconomics]
    margin: tuple[MarginForecast, ...]
    # Отделение в транзакциях -> регион в прогнозе маржи.
    branch_regions: dict[str, str]

    def fuel(self, product: str) -> tuple[Transaction, ...]:
        """Транзакции по топливу заданного вида продукта."""
        return tuple(t for t in self.transactions if t.is_fuel and t.product == product)
