import importlib

import pytest

from rentus_operator import shim

BACKENDS = ["shim"]
try:
    importlib.import_module("rentus_tools")
    BACKENDS.append("real")
except Exception:  # real tools package not installed or broken: shim only
    pass

THREAD = {"thread_id": "T001", "channel": "marketplace", "renter_name": "Ana Ruiz", "language": "en",
          "messages": [{"id": "T001-m1", "from": "renter", "text": "Hi, is the room still available?",
                        "attachments": [], "ts": "2026-10-17T08:55:00"}]}


@pytest.fixture(params=BACKENDS)
def be(request):
    if request.param == "shim":
        return shim
    import rentus_tools
    return rentus_tools


@pytest.fixture
def make_world(be):
    def _make(faults=None, threads=True, **patch):
        p = dict(patch)
        if threads:
            p["threads"] = [dict(THREAD, messages=[dict(m) for m in THREAD["messages"]])]
        w = be.load(patch=p)
        if faults:
            if isinstance(w, dict):
                w["faults"] = faults
            else:
                w.faults = faults
        return w
    return _make
