import datetime as dt

import pytest
from fastapi.testclient import TestClient

from app.clock import FrozenClock
from app.config import AppConfig
from app.db.connection import Database
from app.db.migrate import migrate
from app.main import create_app

TEST_PORT = 8765
ORIGIN = f"http://127.0.0.1:{TEST_PORT}"


@pytest.fixture
def data_root(tmp_path):
    return tmp_path / "PaymentManagerData"


@pytest.fixture
def clock():
    return FrozenClock(dt.datetime(2026, 11, 12, 9, 0))


@pytest.fixture
def config(data_root):
    return AppConfig(data_root=data_root, port=TEST_PORT)


@pytest.fixture
def app(config, clock):
    return create_app(config, clock)


@pytest.fixture
def client(app):
    with TestClient(app, base_url=ORIGIN) as c:
        yield c


@pytest.fixture
def db(tmp_path):
    database = Database(tmp_path / "test.sqlite3")
    migrate(database)
    return database


@pytest.fixture
def conn(db):
    c = db.connect()
    yield c
    db.close(c)


# ---------------------------------------------------------------- Phase B: services and web

PDF_BYTES = b"%PDF-1.4\n% test invoice\n1 0 obj << /Type /Catalog >> endobj\ntrailer\n%%EOF\n"
PNG_BYTES = b"\x89PNG\r\n\x1a\n" + b"\x00\x00\x00\rIHDR" + b"\x00" * 40
JPG_BYTES = b"\xff\xd8\xff\xe0\x00\x10JFIF\x00" + b"\x00" * 40


class Svc:
    """Service-layer test context: a migrated database inside a real data-root layout."""

    def __init__(self, root, clock):
        from app.paths import DataPaths
        self.paths = DataPaths(root)
        self.paths.ensure_layout()
        self.db = Database(self.paths.db_file)
        migrate(self.db)
        self.conn = self.db.connect()
        self.clock = clock

    def stage(self, data: bytes = PDF_BYTES, name: str = "invoice.pdf"):
        import io
        from app.services import attachments
        return attachments.stage_upload(self.paths, io.BytesIO(data), name, 25 * 1024 * 1024)


@pytest.fixture
def svc(tmp_path, clock):
    s = Svc(tmp_path / "data", clock)
    yield s
    s.db.close(s.conn)


class Web:
    """HTTP client that behaves like the real browser page: same origin + CSRF token."""

    def __init__(self, client, app):
        self.client = client
        self.app = app

    def get(self, url, **kw):
        return self.client.get(url, **kw)

    def post(self, url, data=None, files=None, follow=False):
        data = {**(data or {}), "csrf_token": self.app.state.csrf_token}
        return self.client.post(url, data=data, files=files, headers={"origin": ORIGIN},
                                follow_redirects=follow)

    def conn(self):
        return self.app.state.db.connect()


@pytest.fixture
def web(client, app):
    return Web(client, app)
