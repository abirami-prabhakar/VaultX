from pathlib import Path
import os
from secrets import token_hex
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
# A test-process-only credential lets direct pytest runs import the ASGI app.
# No default credential exists in application configuration.
os.environ.setdefault('API_KEY', token_hex(32))

import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app


@pytest.fixture
def settings(tmp_path):
    return Settings(database_url=f'sqlite:///{(tmp_path / "test.db").as_posix()}',
                    storage_dir=tmp_path / 'private', api_key='test-key', extraction_mode='demo',
                    gemma_base_url='', gemma_model='', gemma_api_key='', ocr_enabled=False)


@pytest.fixture
def client(settings):
    app = create_app(settings)
    with TestClient(app, headers={'X-API-Key': 'test-key', 'X-Actor': 'Test reviewer'}) as test_client:
        yield test_client
    app.state.engine.dispose()
