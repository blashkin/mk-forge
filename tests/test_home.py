"""Корень данных: переменная или папка проекта, текущая папка — никогда, иначе отказ."""

from __future__ import annotations

from pathlib import Path

import pytest

from mkforge.home import HOME_ENV_VAR, Home, HomeError, find_home, seed_configs

OUR_PROJECT = '[project]\nname = "mk-forge"\n'


def project_tree(where: Path, pyproject: str | None = OUR_PROJECT) -> Path:
    """Папка проекта с кодом внутри. Возвращает папку кода."""
    code = where / "проект" / "mkforge"
    code.mkdir(parents=True)
    if pyproject is not None:
        (where / "проект" / "pyproject.toml").write_text(pyproject, encoding="utf-8")
    return code


def test_variable_sets_the_root(tmp_path: Path):
    home = find_home({HOME_ENV_VAR: str(tmp_path)}, code_dir=project_tree(tmp_path))
    assert home.root == tmp_path.resolve()
    assert HOME_ENV_VAR in home.source


def test_variable_wins_over_the_project(tmp_path: Path):
    """В образе код лежит рядом со своим pyproject.toml — корнем должен стать том."""
    volume = tmp_path / "том"
    volume.mkdir()
    home = find_home({HOME_ENV_VAR: str(volume)}, code_dir=project_tree(tmp_path))
    assert home.root == volume.resolve()


@pytest.mark.parametrize("value", ["", "   ", "data", "./том"])
def test_empty_or_relative_variable_is_refused(tmp_path: Path, value: str):
    with pytest.raises(HomeError, match=HOME_ENV_VAR):
        find_home({HOME_ENV_VAR: value}, code_dir=project_tree(tmp_path))


def test_variable_to_missing_folder_is_refused(tmp_path: Path):
    with pytest.raises(HomeError, match="такой папки нет"):
        find_home({HOME_ENV_VAR: str(tmp_path / "нет")}, code_dir=project_tree(tmp_path))


def test_without_variable_the_project_is_the_root(tmp_path: Path, monkeypatch):
    code = project_tree(tmp_path)
    elsewhere = tmp_path / "где-то"
    elsewhere.mkdir()
    monkeypatch.chdir(elsewhere)
    home = find_home({}, code_dir=code)
    assert home.root == code.parent
    assert home.source == "папка проекта"


def test_current_folder_is_never_the_root(tmp_path: Path, monkeypatch):
    """Даже если в текущей папке лежит pyproject.toml проекта."""
    code = project_tree(tmp_path / "код")
    decoy = tmp_path / "копия"
    decoy.mkdir()
    (decoy / "pyproject.toml").write_text(OUR_PROJECT, encoding="utf-8")
    monkeypatch.chdir(decoy)
    assert find_home({}, code_dir=code).root == code.parent


def test_foreign_project_is_refused(tmp_path: Path):
    code = project_tree(tmp_path, pyproject='[project]\nname = "чужой"\n')
    with pytest.raises(HomeError, match="не от mk-forge"):
        find_home({}, code_dir=code)


def test_no_project_is_refused(tmp_path: Path):
    code = project_tree(tmp_path, pyproject=None)
    with pytest.raises(HomeError):
        find_home({}, code_dir=code)


def test_real_code_finds_the_same_root_from_any_folder(tmp_path: Path, monkeypatch):
    """Без переменной корень — папка с кодом mk-forge, откуда бы ни запускали."""
    first = find_home({})
    monkeypatch.chdir(tmp_path)
    second = find_home({})
    assert first == second
    assert (first.root / "mkforge" / "home.py").is_file()


def test_paths_count_from_the_root(tmp_path: Path):
    home = Home(root=tmp_path, source="проверка")
    assert home.resolve(Path("configs/акция.yaml")) == tmp_path / "configs" / "акция.yaml"
    assert home.resolve(Path("/абсолютный/путь.xlsx")) == Path("/абсолютный/путь.xlsx")
    assert home.inputs == tmp_path / "data" / "anon"
    assert home.mapping == tmp_path / "data" / "contracts.mapping.json"
    assert home.work == tmp_path / "out" / "рабочие"


# --- образцы конфигов в пустом корне ------------------------------------


@pytest.fixture
def samples(tmp_path: Path) -> Path:
    folder = tmp_path / "образцы"
    folder.mkdir()
    (folder / "example_levels.yaml").write_text("образец: 1\n", encoding="utf-8")
    (folder / "настоящая_акция.yaml").write_text("настоящий: 1\n", encoding="utf-8")
    return folder


def test_samples_go_into_an_empty_root(tmp_path: Path, samples: Path):
    """Только образцы: рядом с ними в папке проекта лежат настоящие конфиги."""
    root = tmp_path / "том"
    root.mkdir()
    copied = seed_configs(Home(root=root, source="тест"), samples)
    assert [path.name for path in copied] == ["example_levels.yaml"]
    assert sorted(p.name for p in (root / "configs").iterdir()) == ["example_levels.yaml"]


def test_samples_never_overwrite_what_the_page_edited(tmp_path: Path, samples: Path):
    """Обновление образа не должно стирать параметры: копия — один раз."""
    root = tmp_path / "том"
    home = Home(root=root, source="тест")
    (root / "configs").mkdir(parents=True)
    edited = root / "configs" / "example_levels.yaml"
    edited.write_text("правлено страницей: 2\n", encoding="utf-8")

    assert seed_configs(home, samples) == []
    assert edited.read_text(encoding="utf-8") == "правлено страницей: 2\n"
