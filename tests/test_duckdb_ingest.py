import pytest

from jevops.duckdb_ingest import MAX_BATCH_ROWS, insert_batch

pytestmark = pytest.mark.no_seal(reason="exercise batch transport and failure boundaries")


class Connection:
    def __init__(self):
        self.calls = []

    def execute(self, sql, params):
        self.calls.append(("execute", sql, params))

    def executemany(self, sql, params):
        self.calls.append(("executemany", sql, params))


def test_columnar_is_one_bound_call_and_preserves_null_unicode_and_sql_text():
    connection = Connection()
    rows = [(1, "cid", "α", "lib", "'); DROP TABLE entries; --", 1, None),
            (2, "other", "β", "lib", "e\u0301", 2, None)]
    insert_batch(connection, "entries", rows, mode="columnar")
    kind, sql, params = connection.calls[0]
    assert len(connection.calls) == 1 and kind == "execute"
    assert sql.count("unnest(?::") == 7 and "DROP" not in sql
    assert params[-1] == [None, None] and list(zip(*params)) == rows


@pytest.mark.parametrize("mode", ["columnar", "executemany"])
def test_empty_batch_does_not_execute(mode):
    connection = Connection()
    insert_batch(connection, "owners", [], mode=mode)
    assert not connection.calls


@pytest.mark.parametrize("table,rows,mode", [
    ("owners; DROP TABLE entries", [("A", 1)], "columnar"),
    ("owners", [("A", 1), ("B",)], "columnar"),
    ("owners", [("A", 1, None)], "executemany"),
    ("owners", [("A", 1)] * (MAX_BATCH_ROWS + 1), "columnar"),
    ("owners", iter([("A", 1)]), "columnar"),
    ("owners", [], "auto"),
    ("owners", [], True),
])
def test_invalid_batches_fail_before_any_execution(table, rows, mode):
    connection = Connection()
    with pytest.raises(ValueError):
        insert_batch(connection, table, rows, mode=mode)
    assert not connection.calls


def test_columnar_failure_does_not_retry_in_another_mode():
    class Failing(Connection):
        def execute(self, *args):
            raise RuntimeError("insertion failed")
    connection = Failing()
    with pytest.raises(RuntimeError, match="insertion failed"):
        insert_batch(connection, "owners", [("A", 1)], mode="columnar")
    assert not connection.calls
