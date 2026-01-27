import db_storage as db


def test_paid_date_column_defaults_on_error(monkeypatch):
    def raise_conn(_):
        raise RuntimeError("fail")

    monkeypatch.setattr(db, "get_connection", raise_conn)
    key = ("h", "1", "d", "u")
    db._PAID_DATE_COLUMN_CACHE.pop(key, None)
    column = db._paid_date_column({"host": "h", "port": 1, "database": "d", "user": "u"})
    assert column == "paid_date"
