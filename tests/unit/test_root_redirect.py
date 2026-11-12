"""The bare host (data0.smalltech.in) sends visitors to the app at /app/."""
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

FRONTEND_OUT = Path(__file__).resolve().parents[2] / "frontend" / "out"


def test_root_redirects_to_the_app_when_the_frontend_is_built():
    if not FRONTEND_OUT.exists():
        pytest.skip("frontend/out is not built; the API-only server has no app to redirect to")
    from api import create_app

    res = TestClient(create_app()).get("/", follow_redirects=False)
    assert res.status_code == 307
    assert res.headers["location"] == "/app/"


def test_root_is_absent_in_api_only_mode():
    if FRONTEND_OUT.exists():
        pytest.skip("frontend/out is built")
    from api import create_app

    assert TestClient(create_app()).get("/", follow_redirects=False).status_code == 404
