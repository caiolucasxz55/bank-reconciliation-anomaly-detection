from pathlib import Path

import pytest

from bankrecon.db.session import database_url, make_engine, sqlite_url


@pytest.fixture(autouse=True)
def clean_env(monkeypatch):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.delenv("BANKRECON_DATA_DIR", raising=False)


def test_database_url_prefers_the_environment(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "postgresql+psycopg://u:p@db/x")
    assert database_url(Path("anything")) == "postgresql+psycopg://u:p@db/x"


def test_default_is_an_absolute_sqlite_file_in_the_data_dir(tmp_path):
    url = database_url(tmp_path / "data")
    assert url == sqlite_url(tmp_path / "data")
    assert Path(url.removeprefix("sqlite:///")).is_absolute()
    assert url.endswith("/data/bankrecon.db")


def test_api_and_cli_share_the_default(monkeypatch, tmp_path):
    monkeypatch.setenv("BANKRECON_DATA_DIR", str(tmp_path))
    assert database_url() == sqlite_url(tmp_path)


def test_sqlite_engine_creates_the_parent_directory(tmp_path):
    engine = make_engine(sqlite_url(tmp_path / "new" / "dir"))
    with engine.connect():
        pass
    engine.dispose()
    assert (tmp_path / "new" / "dir" / "bankrecon.db").exists()
