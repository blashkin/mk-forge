"""Долгие задания: сборка книги идет минутами, а страница ждать не должна.

Одно задание за раз. Два параллельных прогона писали бы в один и тот же файл
рабочей книги и запускали бы два пересчета сразу — а пересчет и в одиночку
занимает столько, что запас в таймауте заложен в десять минут.

Прогресс отдается шагами, а не процентами: сколько займет пересчет, мы не знаем,
и рисовать полоску, которая врет, незачем.

Упавшая и прерванная сборка пишут строку в журнал: страница, которая ее видела,
могла быть уже закрыта, а в контейнере журнал — единственное, что остается.
"""

from __future__ import annotations

import threading
import time
import uuid
from dataclasses import dataclass, field
from typing import Callable

from mkforge.trace import log, where


@dataclass(frozen=True)
class Step:
    """Один шаг задания в словах, понятных человеку."""

    name: str
    text: str
    state: str  # running | done | failed | skipped
    seconds: float = 0.0

    def payload(self) -> dict:
        return {
            "name": self.name,
            "text": self.text,
            "state": self.state,
            "seconds": round(self.seconds, 1),
        }


@dataclass
class Job:
    """Что происходит с заданием прямо сейчас."""

    id: str
    state: str = "running"  # running | done | failed
    started: float = field(default_factory=time.monotonic)
    steps: list[Step] = field(default_factory=list)
    result: dict | None = None
    error: str | None = None

    def payload(self) -> dict:
        return {
            "id": self.id,
            "state": self.state,
            "seconds": round(time.monotonic() - self.started, 1),
            "steps": [step.payload() for step in self.steps],
            "result": self.result,
            "error": self.error,
        }


class Busy(Exception):
    """Задание уже идет. Второе пришлось бы писать в тот же файл."""


class Jobs:
    """Реестр заданий. Про HTTP не знает: его зовут и опрашивают."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._jobs: dict[str, Job] = {}
        self._running: str | None = None

    def running(self) -> Job | None:
        with self._lock:
            return self._jobs.get(self._running) if self._running else None

    def get(self, job_id: str) -> Job | None:
        with self._lock:
            return self._jobs.get(job_id)

    def interrupt(self) -> Job | None:
        """Страница останавливается посреди сборки — сказать об этом в журнал.

        Поток сборки фоновый и уходит вместе с процессом. Недособранная книга
        в готовые не попадает: туда она переносится одним переименованием.
        """
        job = self.running()
        if job is None or job.state != "running":
            return None
        log(f"сборка {job.id} прервана: страница остановлена")
        return job

    def start(self, run: Callable[[Callable[[Step], None]], dict]) -> Job:
        """Запустить задание в отдельном потоке.

        `run` получает функцию, которой сообщает о шагах. Шаг с тем же именем
        заменяет прежний: так «пересчитываю» превращается в «пересчитал»,
        а не добавляется второй строкой.
        """
        with self._lock:
            if self._running and self._jobs[self._running].state == "running":
                raise Busy("сборка книги уже идет")
            job = Job(id=uuid.uuid4().hex[:12])
            self._jobs[job.id] = job
            self._running = job.id

        def report(step: Step) -> None:
            with self._lock:
                for index, shown in enumerate(job.steps):
                    if shown.name == step.name:
                        job.steps[index] = step
                        return
                job.steps.append(step)

        def work() -> None:
            try:
                result = run(report)
            except Exception as error:  # noqa: BLE001 — сообщаем все, чем бы ни было
                # До смены состояния: кто ждет конца задания, застанет строку в журнале.
                log(f"сборка {job.id} упала: {where(error)}")
                with self._lock:
                    job.state = "failed"
                    job.error = str(error) or error.__class__.__name__
                    job.steps = [
                        step if step.state != "running"
                        else Step(step.name, step.text, "failed", step.seconds)
                        for step in job.steps
                    ]
                return
            with self._lock:
                job.state = "done"
                job.result = result

        threading.Thread(target=work, daemon=True).start()
        return job
