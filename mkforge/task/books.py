"""Готовые книги: что лежит в папке готовых и что можно скачать.

В том руками не ходят, поэтому книга уходит со страницы. В списке только готовые
книги — файлы прямо в out/. Рабочие копии на псевдонимах и правки чужих книг
лежат уровнем ниже и в список не попадают, как и временные папки сборки.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

BOOK_SUFFIX = ".xlsx"
# Временная папка сборки и замок, который Excel кладет рядом с открытой книгой.
HIDDEN_PREFIXES = (".", "~$")


@dataclass(frozen=True)
class Book:
    name: str
    path: Path
    size: int
    modified: float  # секунды эпохи: в какой зоне показывать, решает браузер

    def payload(self) -> dict:
        return {"name": self.name, "size": self.size, "modified": self.modified}


def ready_books(out_dir: Path) -> list[Book]:
    """Готовые книги, свежие первыми."""
    if not out_dir.is_dir():
        return []
    books = []
    for path in out_dir.iterdir():
        if path.suffix.lower() != BOOK_SUFFIX or path.name.startswith(HIDDEN_PREFIXES):
            continue
        if not path.is_file():
            continue
        stat = path.stat()
        books.append(Book(path.name, path, stat.st_size, stat.st_mtime))
    return sorted(books, key=lambda book: (-book.modified, book.name))


def find_book(out_dir: Path, name: str) -> Book | None:
    """Книга по имени из запроса.

    Имя сверяется со списком, а не склеивается в путь: так из запроса нельзя
    дотянуться ни до рабочих копий, ни за пределы папки.
    """
    return next((book for book in ready_books(out_dir) if book.name == name), None)
