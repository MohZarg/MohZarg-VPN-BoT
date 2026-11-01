import tempfile
import os
import pytest

from repository.sqlite.connection import init_schema
from repository.sqlite.unit_of_work import SqliteUnitOfWork

OWNER_ID = 999999


@pytest.fixture()
def db_path(tmp_path):
    path = str(tmp_path / "test_ghyiab.db")
    init_schema(path, owner_user_id=OWNER_ID)
    return path


@pytest.fixture()
def uow_factory(db_path):
    def _factory():
        return SqliteUnitOfWork(db_path)
    return _factory
