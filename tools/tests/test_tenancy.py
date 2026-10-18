"""Tenancy tools and guards (owner decisions D29)."""
import pytest

import rentus_tools as rt
from rentus_tools.impl.demand_owner import owner_call

from conftest import call_err, call_ok

NOTICE = ("Notice of late rent: rent of {rent} for {period} was due on {due_date}. "
          "The balance owed is {balance}. Please pay it or contact me.")


def tenant(**over):
    t = {"tenant_id": "TEN1", "name": "Dana", "thread_ids": ["t_dana"], "room_id": "R005", "language": "en",
         "lease": {"rent": 800, "due_day": 1, "deposit": 800, "late_fee": 50, "late_fee_after_days": 5,
                   "notices": {"late_rent": {"after_days": 3, "template": NOTICE}}},
         "paycheck_day": 15,
         "ledger": [{"date": "2026-09-01", "kind": "charge", "amount": 800, "period": "2026-09", "note": "rent"},
                    {"date": "2026-09-01", "kind": "payment", "amount": 800, "period": "2026-09"}]}
    t.update(over)
    return t


def make(now="2026-10-04T10:00:00", text="Hi, sorry I'm short this month.", lang="en", **over):
    th = {"thread_id": "t_dana", "channel": "sms", "renter_name": "Dana", "language": lang, "room_id": "R005",
          "messages": [{"from": "renter", "text": text, "ts": "2026-10-04T09:00:00"}]}
    return rt.load(patch={"clock": {"now": now}, "threads": [th], "tenants": [tenant(**over)]})


def send(w, text, tid="t_dana"):
    return rt.call(w, "send_message", {"thread_id": tid, "text": text})


# ----------------------------------------------------------------------------- policy defaults

def test_policy_defaults_d29():
    p = rt.load().policy
    assert p["spend_limit_usd"] == 0 and p["sourcing_window_days"] == 7 and p["money_followups_before_owner"] == 2
    assert p["grace_days"] == 5 and p["showing_hours"]["start"] == "08:00" and p["showing_hours"]["end"] == "20:00"
    assert p["showing_hours"]["days"] == list(range(7)) and p["languages"]["draft_for_owner"] == ["ru"]


def test_tenancy_tools_only_in_concierge_variant():
    names = {t["function"]["name"] for t in rt.tool_schemas("concierge")}
    assert {"get_ledger", "record_payment", "rent_ladder", "send_notice", "propose_payment_plan",
            "triage_maintenance", "compare_quotes"} <= names
    assert "get_ledger" not in {t["function"]["name"] for t in rt.tool_schemas("verbose")}


def test_no_overlapping_showings_across_rooms():
    w = rt.load(patch={"clock": {"now": "2026-10-17T07:00:00"},
                       "calendar": [{"event_id": "E001", "start": "2026-10-17T08:00", "end": "2026-10-17T08:30",
                                     "status": "proposed", "renter_id": "x", "room_id": "R001"}]})
    slots = call_ok(w, "find_showing_slots", {"room_id": "R005", "date_from": "2026-10-17", "date_to": "2026-10-17"})["slots"]
    assert slots[0]["start"] == "2026-10-17T08:30" and slots[-1]["end"] == "2026-10-17T20:00"


# ----------------------------------------------------------------------------- ledger and payments

def test_ledger_exact_figures_and_lease_late_fee():
    w = make()
    v = call_ok(w, "get_ledger", {"thread_id": "t_dana"})
    assert v["rent_due_this_period"] == 800 and v["received_this_period"] == 0 and v["balance"] == 800
    assert v["days_late"] == 3 and v["late_fee"]["amount"] == 50 and v["late_fee"]["applies"] is False
    w2 = make(lease={"rent": 800, "due_day": 1, "late_fee": None})
    assert call_ok(w2, "get_ledger", {"tenant_id": "TEN1"})["late_fee"]["amount"] is None


def test_partial_payment_acknowledgement_is_exact():
    w = make()
    d = call_ok(w, "record_payment", {"tenant_id": "TEN1", "amount": 450})
    assert d["received"] == 450 and d["remainder"] == 350
    assert "$450" in d["acknowledgement"][0] and "$350" in d["acknowledgement"][0]
    for m in d["acknowledgement"]:
        assert send(w, m)["ok"]
    full = call_ok(w, "record_payment", {"tenant_id": "TEN1", "amount": 350})
    assert full["remainder"] == 0 and len(full["acknowledgement"]) == 1


def test_partial_payment_spanish():
    w = make(text="Hola, te mandé una parte de la renta hoy.", lang="es")
    d = call_ok(w, "record_payment", {"tenant_id": "TEN1", "amount": 300})
    assert "recibí $300" in d["acknowledgement"][0] and "$500" in d["acknowledgement"][0]
    assert send(w, d["acknowledgement"][0])["ok"]


def test_figures_not_in_ledger_refused():
    w = make()
    e = send(w, "You owe $875 now.")
    assert not e["ok"] and "price_not_in_record" in e["error"]["details"]["rules"]
    assert send(w, "Rent was $800 and the balance is $800 right now.")["ok"]


def test_late_fee_only_from_lease():
    w = make(lease={"rent": 800, "due_day": 1, "late_fee": None})
    e = send(w, "Just a reminder that a late fee applies after the 5th.")
    assert not e["ok"] and e["error"]["details"]["rules"] == ["late_fee_not_in_lease"]


# ----------------------------------------------------------------------------- ladder and notices

def test_ladder_reminder_then_notice_then_followups_then_owner():
    w = make()
    s = call_ok(w, "rent_ladder", {"tenant_id": "TEN1"})
    acts = [a["action"] for a in s["actions"]]
    assert acts[:2] == ["send_notice", "reminder"] and "report_to_owner" in acts and s["notice_due"]
    n = call_ok(w, "send_notice", {"tenant_id": "TEN1"})
    assert n["notice"]["type"] == "notice" and "$800" in n["notice"]["text"] and "2026-10-01" in n["notice"]["text"]
    call_err(w, "send_notice", {"tenant_id": "TEN1"}, "CONFLICT")
    w.advance(minutes=60)
    s = call_ok(w, "rent_ladder", {"tenant_id": "TEN1", "event": "reminder_sent"})
    assert s["actions"][0]["action"] == "followup"
    for _ in range(2):
        s = call_ok(w, "rent_ladder", {"tenant_id": "TEN1", "event": "followup_sent"})
    assert s["actions"][0]["action"] == "escalate_to_owner"


def test_notice_not_before_lease_allows():
    w = make(now="2026-10-02T10:00:00")
    e = call_err(w, "send_notice", {"tenant_id": "TEN1"}, "POLICY_BLOCKED")
    assert "2026-10-04" in e["message"]


def test_notice_still_due_while_plan_awaits_owner():
    w = make()
    call_ok(w, "propose_payment_plan", {"tenant_id": "TEN1", "shape": "split",
                                        "installments": [{"date": "2026-10-09", "amount": 400}, {"date": "2026-10-23", "amount": 400}]})
    s = call_ok(w, "rent_ladder", {"tenant_id": "TEN1"})
    assert [a["action"] for a in s["actions"]] == ["send_notice", "wait_owner"]


def test_warned_within_grace_goes_to_owner():
    w = make(now="2026-09-29T10:00:00",
             ledger=[{"date": "2026-09-01", "kind": "charge", "amount": 800, "period": "2026-09"},
                     {"date": "2026-09-01", "kind": "payment", "amount": 800, "period": "2026-09"}])
    s = call_ok(w, "rent_ladder", {"tenant_id": "TEN1", "event": "warned", "promised_date": "2026-10-04"})
    assert s["actions"][0]["action"] == "escalate_to_owner" and "this time" in s["actions"][0]["draft"]
    assert not send(w, "That works this time, thanks for the heads-up.")["ok"]
    owner_call(w, "owner_approve", {"kind": "grace", "ref_id": "TEN1", "decision": "approve"})
    assert send(w, "That works this time, thanks for the heads-up.")["ok"]


# ----------------------------------------------------------------------------- payment plans

@pytest.mark.parametrize("shape,inst,kw,ok", [
    ("split", [("2026-10-09", 400), ("2026-10-23", 400)], {}, True),
    ("split", [("2026-10-09", 300), ("2026-10-16", 250), ("2026-10-23", 250)], {}, False),   # 3 payments
    ("split", [("2026-10-09", 400), ("2026-11-03", 400)], {}, False),                        # crosses the month
    ("due_date_shift", [("2026-10-16", 800)], {"new_due_day": 16, "paycheck_day": 15}, True),
    ("due_date_shift", [("2026-10-25", 800)], {"new_due_day": 25, "paycheck_day": 15}, False),
])
def test_plan_bounds(shape, inst, kw, ok):
    w = make()
    d = call_ok(w, "propose_payment_plan", {"tenant_id": "TEN1", "shape": shape,
                                            "installments": [{"date": a, "amount": b} for a, b in inst], **kw})
    assert d["in_bounds"] is ok and d["plan"]["status"] == "awaiting_owner"
    assert ("OUTSIDE" in d["owner_draft"]) is (not ok)


def test_catch_up_bounds_three_months():
    led = [{"date": "2026-09-01", "kind": "charge", "amount": 800, "period": "2026-09"}]
    w = make(ledger=led)   # September unpaid (arrears 800) + October rent 800 = 1600 owed
    good = call_ok(w, "propose_payment_plan", {"tenant_id": "TEN1", "shape": "catch_up", "installments": [
        {"date": "2026-10-15", "amount": 1200}, {"date": "2026-11-15", "amount": 1200}]})
    assert good["in_bounds"], good["reasons"]
    four = [{"date": d, "amount": 1000} for d in ("2026-10-15", "2026-11-15", "2026-12-15", "2027-01-15")]
    bad = call_ok(w, "propose_payment_plan", {"tenant_id": "TEN1", "shape": "catch_up", "installments": four})
    assert not bad["in_bounds"] and bad["reasons"] == ["arrears spread over 4 months; the bound is 3"]


def test_plan_wording_refused_until_owner_approves_then_tracked():
    w = make()
    inst = [{"date": "2026-10-09", "amount": 400}, {"date": "2026-10-23", "amount": 400}]
    call_ok(w, "propose_payment_plan", {"tenant_id": "TEN1", "shape": "split", "installments": inst})
    e = send(w, "Sure, a payment plan works: $400 on Oct 9 and $400 on Oct 23.")
    assert not e["ok"] and "promise_not_approved" in e["error"]["details"]["rules"]
    assert "escalate_to_owner" in e["error"]["hint"]
    call_err(w, "rent_ladder", {"tenant_id": "TEN1", "event": "plan_sent"}, "POLICY_BLOCKED")
    r = owner_call(w, "owner_approve", {"kind": "payment_plan", "ref_id": "TEN1", "decision": "approve"})
    assert r["ok"] and w.tenants[0]["plan"]["status"] == "approved"
    assert call_ok(w, "rent_ladder", {"tenant_id": "TEN1"})["actions"][-1]["action"] == "send_plan"
    assert send(w, "Your payment plan is approved: $400 on Oct 9 and $400 on Oct 23.")["ok"]
    call_ok(w, "rent_ladder", {"tenant_id": "TEN1", "event": "plan_sent"})
    call_ok(w, "record_payment", {"tenant_id": "TEN1", "amount": 400})
    assert w.tenants[0]["plan"]["installments"][0]["status"] == "paid"
    w.clock["now"] = "2026-10-24T10:00:00"
    acts = [a["action"] for a in call_ok(w, "rent_ladder", {"tenant_id": "TEN1"})["actions"]]
    assert "checkin" in acts and "report_to_owner" in acts


# ----------------------------------------------------------------------------- guardrailed promises

@pytest.mark.parametrize("text,kind", [
    ("I'll waive the late fee this month.", "waive_fee"),
    ("I can give you a $50 discount on the first month.", "discount"),
    ("I'll hold the room for you until Friday.", "hold"),
    ("I'll return your full deposit next week.", "deposit_return"),
    ("The plumber will come tomorrow at 10.", "repair_date"),
    ("I'll make an exception for your dog.", "rule_exception"),
    ("If you don't pay I will start an eviction.", "enforcement"),
    ("Te puedo dar un descuento de $50.", "discount"),
])
def test_promises_need_owner_approval(text, kind):
    w = make(text="hola" if "Te" in text else "Hi", lang="es" if "Te" in text else "en")
    e = send(w, text)
    assert not e["ok"] and e["error"]["details"]["rules"] == ["promise_not_approved"], e
    assert kind in e["error"]["details"]["kinds"]


def test_hedged_and_question_wording_passes():
    w = make()
    assert send(w, "Let me check on the late fee and get back to you today.")["ok"]
    assert send(w, "How do you plan to pay the rest, a paycheck or help from family?")["ok"]


def test_owner_bound_and_approval_allow_promise():
    w = make()
    w.policy["promise_bounds"] = {"discount": {"max_usd": 25}}
    assert send(w, "I can do a $25 discount on the first month.")["ok"] is False   # $25 is not a record figure
    w2 = make()
    owner_call(w2, "owner_approve", {"kind": "waive_fee", "ref_id": "TEN1", "decision": "approve"})
    assert send(w2, "I'll waive the late fee this month.")["ok"]
    w3 = make()
    w3.policy["promise_bounds"] = {"hold": {}}
    assert send(w3, "I'll hold the room for you until Friday.")["ok"]


def test_repair_date_allowed_once_vendor_booked():
    w = make()
    w.jobs.append({"job_id": "J009", "room_id": "R005", "status": "booked", "scheduled_for": "2026-10-05"})
    assert send(w, "The plumber will come tomorrow at 10.")["ok"]


# ----------------------------------------------------------------------------- languages

def test_russian_is_drafted_for_owner():
    w = make(text="Здравствуйте, я задержу оплату на неделю.")
    e = send(w, "Hi, thanks for letting me know.")
    assert not e["ok"] and e["error"]["details"]["rules"] == ["draft_for_owner_language"]
    assert call_ok(w, "escalate_to_owner", {"reason": "Russian message, draft for owner", "ref_id": "t_dana",
                                            "draft": "Спасибо, что предупредили."})


# ----------------------------------------------------------------------------- maintenance triage

def test_gas_emergency_alerts_owner_and_safety_goes_first():
    w = make(text="I smell gas in the kitchen!")
    d = call_ok(w, "triage_maintenance", {"thread_id": "t_dana"})
    assert d["emergency"] and d["category"] == "gas"
    esc = w.get("escalations", d["owner_alerted"])
    assert esc["status"] == "open" and "SAFETY EMERGENCY" in esc["reason"]
    e = send(w, "Thanks, I'm sending someone over.")
    assert not e["ok"] and e["error"]["details"]["rules"] == ["safety_first"]
    assert send(w, d["safety_message"])["ok"]
    assert send(w, "I'm arranging help right now.")["ok"]


def test_spanish_flood_emergency():
    w = make(text="¡Se reventó un tubo y hay agua por todas partes!", lang="es")
    d = call_ok(w, "triage_maintenance", {"thread_id": "t_dana"})
    assert d["category"] == "flooding" and "llave de paso" in d["safety_message"]
    assert send(w, d["safety_message"])["ok"]


def test_non_emergency_gets_triage_questions():
    w = make(text="The kitchen sink is leaking a little.")
    d = call_ok(w, "triage_maintenance", {"thread_id": "t_dana"})
    assert not d["emergency"] and d["trade"] == "plumber" and d["next_question"].endswith("?")
    assert send(w, d["next_question"])["ok"] and not w.escalations


# ----------------------------------------------------------------------------- vendor spend

def test_spend_limit_zero_quotes_side_by_side_then_owner_approval():
    w = make()
    job = call_ok(w, "create_job", {"property": "R005", "issue": "kitchen sink leak", "severity": "medium"})["job"]
    vs = call_ok(w, "find_vendors", {"trade": "plumber", "job_id": job["job_id"]})["vendors"]
    qs = []
    for v in vs:
        r = rt.call(w, "request_quote", {"vendor_id": v["vendor_id"], "job_id": job["job_id"], "description": "leak"})
        if r["ok"]:
            qs.append(r["data"]["quote"])
        if len(qs) == 2:
            break
    e = call_err(w, "book_vendor", {"quote_id": qs[0]["quote_id"]}, "BUDGET_EXCEEDED")
    assert "compare_quotes" in e["hint"]
    side = call_ok(w, "compare_quotes", {"job_id": job["job_id"]})
    assert len(side["quotes"]) == 2 and side["quotes"][0]["amount"] <= side["quotes"][1]["amount"]
    owner_call(w, "owner_approve", {"kind": "spend", "ref_id": side["quotes"][0]["quote_id"], "decision": "approve"})
    assert call_ok(w, "book_vendor", {"quote_id": side["quotes"][0]["quote_id"]})["job"]["status"] == "booked"
