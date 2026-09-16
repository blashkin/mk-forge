"""mk-forge: генератор расчетных моделей маркетинговых кампаний топливной программы."""

from __future__ import annotations

import os

VERSION_ENV_VAR = "MK_FORGE_VERSION"
LOCAL_BUILD = "сборка на месте"


def release() -> str:
    """Версия выпуска. Ее задает тег vX.Y.Z: CI передает ее в образ при сборке.

    Запуск из исходников и образ, собранный на месте, версии не имеют — так
    опубликованный образ не спутать с локальным. В pyproject версия не ведется.
    """
    return os.environ.get(VERSION_ENV_VAR, "").strip() or LOCAL_BUILD
