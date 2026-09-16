"""Гайд «Установка на Mac» одним html-файлом — для пересылки в мессенджере.

Текст живет в docs/install-mac.md: правда одна, html пересобирается командой,
руками его не правят. Ссылка на GitHub человеку, которому нужны три команды,
выглядит чужеродно: вокруг файла код и коммиты. Файл md в мессенджере
открывается сырым текстом. Поэтому html: открывается в браузере как страница,
у каждой команды кнопка «Копировать», внешних ресурсов нет — файл открывают
без сети и без доверия к ней. Тот же файл CI публикует на GitHub
Pages (.github/workflows/pages.yml): вместо файла можно переслать ссылку.

Разметки в гайде немного: заголовки, абзацы, нумерованные списки, команды
в ограждениях, ссылки, код и жирный в строке. Все остальное — отказ, а не
молчаливый пропуск: иначе новая конструкция в тексте уехала бы получателю кривой.
"""

from __future__ import annotations

import html
import re
from pathlib import Path

CODE_DIR = Path(__file__).resolve().parent
# Текст лежит рядом с кодом в папке проекта; в образе его нет, и гайд там не собрать.
SOURCE = CODE_DIR.parent / "docs" / "install-mac.md"
TITLE = "Установка на Mac"
OUT_NAME = f"{TITLE}.html"
COPY = "Копировать"
COPIED = "Скопировано"

_HEADING = re.compile(r"^(#{1,6}) (.+)$")
_FENCE = re.compile(r"^```(\w*)$")
_ITEM = re.compile(r"^\d+\. (.*)$")
_URL = re.compile(r"https?://[^\s<]+")
_CODE = re.compile(r"`([^`]+)`")
_BOLD = re.compile(r"\*\*(.+?)\*\*")


class GuideError(Exception):
    """Текст не найден или в нем разметка, которую гайд не умеет."""


def render_body(lines: list[str]) -> str:
    """Тело страницы из строк гайда."""
    out: list[str] = []
    i = 0
    while i < len(lines):
        line = lines[i]
        if not line.strip():
            i += 1
            continue
        heading = _HEADING.match(line)
        if heading:
            level = len(heading.group(1))
            out.append(f"<h{level}>{_inline(heading.group(2))}</h{level}>")
            i += 1
            continue
        if _FENCE.match(line):
            i += 1
            code = []
            while i < len(lines) and lines[i] != "```":
                code.append(lines[i])
                i += 1
            if i == len(lines):
                raise GuideError("ограждение кода не закрыто")
            i += 1
            out.append(_command("\n".join(code)))
            continue
        if _ITEM.match(line):
            items = []
            while i < len(lines) and (item := _ITEM.match(lines[i])):
                text = item.group(1)
                i += 1
                while i < len(lines) and lines[i].startswith("   ") and lines[i].strip():
                    tail = lines[i].strip()
                    if tail.startswith("```") or tail[0] in "-*>|":
                        raise GuideError(f"гайд не умеет вложенную разметку в пункте: {tail!r}")
                    text += " " + tail
                    i += 1
                items.append(f"<li>{_inline(text)}</li>")
            out.append("<ol>" + "".join(items) + "</ol>")
            continue
        para = []
        while i < len(lines) and lines[i].strip() and not _block_start(lines[i]):
            _refuse_unknown(lines[i])
            para.append(lines[i].strip())
            i += 1
        out.append(f"<p>{_inline(' '.join(para))}</p>")
    return "\n".join(out)


def render_page(lines: list[str]) -> str:
    """Страница целиком: разметка, стили и кнопки копирования в одном файле."""
    if not lines or lines[0] != f"# {TITLE}":
        raise GuideError(f"гайд должен начинаться с заголовка «# {TITLE}»")
    title = html.escape(f"mk-forge: {TITLE[0].lower()}{TITLE[1:]}")
    return (
        _PAGE.replace("@@TITLE@@", title)
        .replace("@@BODY@@", render_body(lines))
        .replace("@@COPY@@", COPY)
        .replace("@@COPIED@@", COPIED)
    )


def build_guide(source: Path = SOURCE, out: Path | None = None) -> Path:
    """Собрать гайд из текста в html-файл; вернуть, куда положен."""
    if not source.is_file():
        raise GuideError(f"текст гайда не найден: {source}")
    out = out if out is not None else CODE_DIR.parent / "out" / OUT_NAME
    page = render_page(source.read_text(encoding="utf-8").split("\n"))
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(page, encoding="utf-8")
    return out


def _block_start(line: str) -> bool:
    return bool(_HEADING.match(line) or _FENCE.match(line) or _ITEM.match(line))


def _refuse_unknown(line: str) -> None:
    if line[0] in " \t#-*>|":
        raise GuideError(f"гайд не умеет такую разметку: {line!r}")


def _command(code: str) -> str:
    return (
        '<figure class="cmd"><pre><code>' + html.escape(code, quote=False) + "</code></pre>"
        f'<button type="button">{COPY}</button></figure>'
    )


def _inline(text: str) -> str:
    """Экранировать html; код в строке остается как есть, вокруг — жирный и ссылки."""
    text = html.escape(text, quote=False)
    parts = []
    last = 0
    for found in _CODE.finditer(text):
        parts.append(_links(_BOLD.sub(r"<strong>\1</strong>", text[last:found.start()])))
        parts.append(f"<code>{found.group(1)}</code>")
        last = found.end()
    parts.append(_links(_BOLD.sub(r"<strong>\1</strong>", text[last:])))
    return "".join(parts)


def _links(text: str) -> str:
    def link(found: re.Match[str]) -> str:
        url = found.group(0)
        tail = ""
        # Точка или скобка после адреса — знак препинания, не часть ссылки.
        while url and url[-1] in ".,;:)»":
            tail = url[-1] + tail
            url = url[:-1]
        return f'<a href="{url}">{url}</a>{tail}'

    return _URL.sub(link, text)


_PAGE = """<!doctype html>
<html lang="ru">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>@@TITLE@@</title>
<style>
:root { color-scheme: light dark; --bg: #ffffff; --fg: #1d1d1f; --box: #f5f5f7; --line: #d2d2d7; --accent: #0a60c2; }
@media (prefers-color-scheme: dark) {
  :root { --bg: #1c1c1e; --fg: #f5f5f7; --box: #2c2c2e; --line: #3a3a3c; --accent: #6cb4ff; }
}
html { background: var(--bg); color: var(--fg); font: 17px/1.5 -apple-system, BlinkMacSystemFont, "Helvetica Neue", Arial, sans-serif; }
body { margin: 0; }
main { max-width: 40rem; margin: 0 auto; padding: 1.5rem 1rem 3rem; }
h1 { font-size: 1.8rem; line-height: 1.2; margin: 0 0 1rem; }
h2 { font-size: 1.25rem; margin: 2rem 0 .5rem; }
p, ol { margin: .6rem 0; }
ol { padding-left: 1.4rem; }
li { margin: .35rem 0; }
a { color: var(--accent); }
code { font: .92em ui-monospace, "SF Mono", Menlo, monospace; background: var(--box); padding: .1em .3em; border-radius: 4px; }
figure.cmd { position: relative; margin: .8rem 0; background: var(--box); border: 1px solid var(--line); border-radius: 8px; }
figure.cmd pre { margin: 0; padding: .8rem 7.5rem .8rem 1rem; white-space: pre-wrap; overflow-wrap: anywhere; }
figure.cmd pre code { background: none; padding: 0; font-size: .95em; }
figure.cmd button { position: absolute; top: .5rem; right: .5rem; font: inherit; font-size: .85rem; padding: .25rem .6rem; border: 1px solid var(--line); border-radius: 6px; background: var(--bg); color: var(--fg); cursor: pointer; }
</style>
</head>
<body>
<main>
@@BODY@@
</main>
<script>
(function () {
  function fallback(text) {
    var area = document.createElement('textarea');
    area.value = text;
    document.body.appendChild(area);
    area.select();
    try { document.execCommand('copy'); } catch (e) {}
    document.body.removeChild(area);
  }
  document.querySelectorAll('figure.cmd button').forEach(function (button) {
    button.addEventListener('click', function () {
      var text = button.parentNode.querySelector('code').textContent;
      var done = function () {
        button.textContent = '@@COPIED@@';
        setTimeout(function () { button.textContent = '@@COPY@@'; }, 1500);
      };
      if (navigator.clipboard && navigator.clipboard.writeText) {
        navigator.clipboard.writeText(text).then(done, function () { fallback(text); done(); });
      } else {
        fallback(text);
        done();
      }
    });
  });
})();
</script>
</body>
</html>
"""
