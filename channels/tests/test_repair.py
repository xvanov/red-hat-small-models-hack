import json
import re
import socket
import threading
import time

import httpx
import pytest

from channels.adapters import api
from channels.mock_sites.app import STATE
from channels.mock_sites.specs import PLATFORMS, dom_name
from channels.repair.proposers import HeuristicProposer, OperatorProposer, parse_json_object
from channels.tests.conftest import set_layout
from channels.tests.test_adapters import EXPECT


def _v2_expect(platform):
    """EXPECT is keyed by v1 field names; map them to the v2 names the redesigned form submits."""
    v1_to_key = {dom_name(platform, f.key, "v1"): f.key for st in PLATFORMS[platform].steps for f in st.fields}
    return {dom_name(platform, v1_to_key[k], "v2"): v for k, v in EXPECT[platform].items()}


@pytest.mark.parametrize("platform", api.PLATFORMS)
def test_redesign_breaks_then_repairs_offline(platform, base_url, sel_dir, changelog, listing):
    set_layout(base_url, "v2", [platform])
    broken = api.publish_listing(listing, platform, base_url=base_url, selectors_dir=sel_dir, repair=False)
    assert not broken["ok"] and broken["error"]["code"] == "PAGE_CHANGED"

    r = api.publish_listing(listing, platform, base_url=base_url, selectors_dir=sel_dir, submit=True,
                            proposer=HeuristicProposer(), changelog_path=changelog)
    assert r["ok"], r
    posted = STATE.listings[platform][0]
    for k, v in _v2_expect(platform).items():
        assert posted["fields"].get(k) == v, (k, posted["fields"])
    spec = json.loads((sel_dir / "mock" / f"{platform}.json").read_text())
    assert len(spec["changelog"]) >= 5 and all(e["proposed_by"] in ("heuristic", "verifier") for e in spec["changelog"])
    assert changelog.read_text().count('"repaired"') >= 5

    # the repaired file now works with no repair at all
    STATE.listings[platform].clear()
    again = api.publish_listing(listing, platform, base_url=base_url, selectors_dir=sel_dir, repair=False)
    assert again["ok"] and again["data"]["repairs"] == []


def test_inbox_redesign_repairs(base_url, sel_dir, changelog):
    set_layout(base_url, "v2", ["marketplace"])
    kw = dict(base_url=base_url, selectors_dir=sel_dir, proposer=HeuristicProposer(), changelog_path=changelog)
    threads = api.list_threads("marketplace", unanswered_only=True, **kw)
    assert threads["ok"] and len(threads["data"]["threads"]) == 2
    tid = threads["data"]["threads"][0]["thread_id"]
    sent = api.send_message(tid, "Yes, it is available from November 1.", **kw)
    assert sent["ok"], sent
    th = api.read_thread(tid, **kw)["data"]["thread"]
    assert [m["from"] for m in th["messages"]] == ["renter", "operator"]


class WrongFirstProposer(HeuristicProposer):
    """Proposes a plausible-but-wrong click target first (the photo drop zone), like a model might."""

    def propose(self, task):
        props = super().propose(task)
        if task["element"]["action"] == "click" and not task.get("rejected"):
            zone = next((e for e in task["snapshot"]["elements"] if "photo" in (e["text"] + e["aria"]).lower()
                         and e["role"] == "button"), None)
            if zone:
                return [{"selector": zone["selector"], "reason": "looks like a button", "by": "test"}] + props
        return props


def test_wrong_click_repair_is_reverted(base_url, sel_dir, changelog, listing):
    set_layout(base_url, "v2", ["marketplace"])
    r = api.publish_listing(listing, "marketplace", base_url=base_url, selectors_dir=sel_dir,
                            proposer=WrongFirstProposer(), changelog_path=changelog)
    assert r["ok"], r
    spec = json.loads((sel_dir / "mock" / "marketplace.json").read_text())
    assert any(e["proposed_by"] == "verifier" for e in spec["changelog"])
    assert "aria-label=\"Continue\"" in spec["elements"]["next_1"]["selector"]


def test_parse_json_object_handles_thinking_and_fences():
    assert parse_json_object('<think>{"no": 1}</think>Sure: ```json\n{"index": 3, "reason": "x"}\n```') == \
        {"index": 3, "reason": "x"}
    assert parse_json_object("no json here") is None


# ---------------------------------------------------------------- operator path over HTTP

V2_LABEL = {"rent": "Rent per month", "available_date": "Move-in date", "min_stay": "Shortest lease",
            "private_bath": "Bathroom is private", "furnished": "Comes furnished", "address": "Location",
            "headline": "Title", "description": "Tell renters about it", "photos": "Add pictures",
            "next_1": "Save & continue", "next_2": "Save & continue", "next_3": "Save & continue",
            "publish": "Go live"}


def _fake_operator():
    """A scripted stand-in for the vLLM server: answers like a model would, from the prompt text."""
    from fastapi import FastAPI, Request

    app = FastAPI()
    calls = []

    @app.get("/v1/models")
    def models():
        return {"data": [{"id": "fake-nemotron"}]}

    @app.post("/v1/chat/completions")
    async def chat(req: Request):
        body = await req.json()
        prompt = body["messages"][-1]["content"]
        calls.append(prompt)
        key = re.search(r"Broken element key: (\S+)", prompt).group(1)
        want = V2_LABEL.get(key, "")
        idx = None
        for line in prompt.split("Candidates on the current page:")[1].splitlines():
            m = re.match(r"\[(\d+)\]", line)
            if m and want and (f"'{want}" in line or f"'{want} *'" in line):
                idx = int(m.group(1))
                break
        content = f"<think>looking for {want}</think>" + json.dumps({"index": idx, "reason": f"label is {want}"})
        return {"choices": [{"message": {"role": "assistant", "content": content}}]}

    return app, calls


def test_operator_proposer_over_openai_api(base_url, sel_dir, changelog, listing):
    import uvicorn

    app, calls = _fake_operator()
    s = socket.socket(); s.bind(("127.0.0.1", 0)); port = s.getsockname()[1]; s.close()
    srv = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning"))
    threading.Thread(target=srv.run, daemon=True).start()
    for _ in range(50):
        try:
            httpx.get(f"http://127.0.0.1:{port}/v1/models", timeout=1); break
        except Exception:
            time.sleep(0.1)
    try:
        prop = OperatorProposer(base_url=f"http://127.0.0.1:{port}/v1")
        assert prop.available() and prop.model == "fake-nemotron"
        set_layout(base_url, "v2", ["roomies"])
        r = api.publish_listing(listing, "roomies", base_url=base_url, selectors_dir=sel_dir, submit=True,
                                proposer=prop, changelog_path=changelog)
        assert r["ok"], r
        assert STATE.listings["roomies"][0]["fields"]["ro_rent_x"] == "750"
        spec = json.loads((sel_dir / "mock" / "roomies.json").read_text())
        assert all(e["proposed_by"] == "operator:fake-nemotron" for e in spec["changelog"])
        assert len(calls) == len(spec["changelog"]) >= 10
        assert "What it is:" in calls[0] and "Old selector" in calls[0]
    finally:
        srv.should_exit = True
