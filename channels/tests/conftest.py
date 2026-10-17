import os
import shutil
import socket
import sys
import threading
import time
from pathlib import Path

import httpx
import pytest

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))
os.environ.setdefault("CHANNELS_TIMEOUT_MS", "800")

from channels.mock_sites.app import STATE, app  # noqa: E402


def _free_port() -> int:
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


@pytest.fixture(scope="session")
def base_url():
    import uvicorn

    port = _free_port()
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning"))
    t = threading.Thread(target=server.run, daemon=True)
    t.start()
    url = f"http://127.0.0.1:{port}"
    for _ in range(50):
        try:
            httpx.get(url + "/_admin/config", timeout=1)
            break
        except Exception:
            time.sleep(0.1)
    yield url
    server.should_exit = True


@pytest.fixture(autouse=True)
def fresh_state():
    STATE.reset()
    yield


@pytest.fixture
def sel_dir(tmp_path):
    d = tmp_path / "selectors"
    shutil.copytree(REPO / "channels" / "adapters" / "selectors", d)
    return d


@pytest.fixture
def changelog(tmp_path):
    return tmp_path / "changelog.jsonl"


@pytest.fixture
def listing():
    return {
        "listing_id": "L1", "title": "Private room with own bath, Appling Way",
        "body": "Quiet furnished room in a shared house. Utilities included.", "price": 750,
        "room": {"room_id": "appling-a", "area": "Durham", "zip": "27703", "address_public": "Appling Way, Durham NC",
                 "private_bath": True, "furnished": True, "available_from": "2026-11-01", "lease_min_months": 6},
        "photos": [],
    }


def set_layout(base_url, layout, platforms=("marketplace", "roomies", "craigslist", "padsplit")):
    httpx.post(base_url + "/_admin/config", json={p: {"layout": layout} for p in platforms})
