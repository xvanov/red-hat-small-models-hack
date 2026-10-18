"""Tenancy tools (owner decisions D29, docs/playbooks/owner-decisions.md, playbook 08).

A tenant lives in `world.tenants` (one record per tenant; never deleted):

    {tenant_id, name, thread_ids[], room_id, language,
     lease: {rent, due_day, deposit, late_fee (number or null: ONLY the lease's fee), late_fee_after_days,
             notices: {late_rent: {after_days, template}}, due_shift_deposit_rule},
     paycheck_day?,                                   # day of month the tenant is paid, when known
     ledger: [{date, kind: charge|payment, amount, period: YYYY-MM, note, auto?}],
     ladder: {period, stage, events[{event, at, note?}], followups_silent, promised_date, deadline,
              notices_sent[{kind, period, at}]},
     plan: null | {plan_id, shape, installments[{date, amount, status}], proposed_by, tenant_words, in_bounds,
                   reasons[], status: awaiting_owner|approved|rejected|sent|done|broken, created_at}}

Tools: get_ledger, record_payment, rent_ladder, send_notice, propose_payment_plan. Every figure is computed
from the ledger and the lease; the late fee is the lease's own fee or nothing. Payment plans are collaborative:
the tenant proposes, the tool checks the owner's bounds (two payments inside the month; a due date moved to a
paycheck; arrears over at most 3 months on top of rent), the owner approves, then the agent sends and tracks.
A late-rent notice is sent exactly as the lease's template says, even while a plan is being made. Notices are
recorded as thread messages of type "notice"; no model writes them, and they carry no legal advice.
Deterministic; tools never read the wall clock.
"""
from __future__ import annotations

import copy
import re
from datetime import date, timedelta

from ..core import tool
from ..errors import ToolError
from ._util import num

STAGES = ("current", "warned", "late", "reminder_sent", "assessed", "plan_proposed", "plan_approved", "plan_sent",
          "escalated")
EVENTS = ("warned", "reminder_sent", "assessed", "tenant_replied", "followup_sent", "checkin_sent", "plan_sent",
          "escalated")
SHAPES = ("split", "due_date_shift", "catch_up")
EPS = 0.005


# ----------------------------------------------------------------------------- lookups and money

def find_tenant(world, tenant_id: str | None = None, thread_id: str | None = None) -> dict:
    if not tenant_id and not thread_id:
        raise ToolError("INVALID_ARGS", "give tenant_id or thread_id")
    for t in world.tenants:
        if (tenant_id and t.get("tenant_id") == tenant_id) or (thread_id and thread_id in t.get("thread_ids", [])):
            return t
    raise ToolError("NOT_FOUND", f"no tenant for {tenant_id or thread_id!r}",
                    hint="tenant records hold the lease and ledger; a prospect has no tenant record")


def tenant_for_thread(world, thread_id: str) -> dict | None:
    return next((t for t in world.tenants if thread_id in t.get("thread_ids", [])), None)


def money(v) -> str:
    f = float(v)
    return f"${f:,.0f}" if abs(f - round(f)) < EPS else f"${f:,.2f}"


def _r2(v) -> float:
    return round(float(v) + 0.0, 2)


def _period(d: date) -> str:
    return d.strftime("%Y-%m")


def due_date_for(tenant: dict, d: date) -> date:
    lease = tenant.get("lease") or {}
    day = int(lease.get("due_day") or 1)
    plan = tenant.get("plan") or {}
    if plan.get("shape") == "due_date_shift" and plan.get("status") in ("approved", "sent") and plan.get("new_due_day"):
        day = int(plan["new_due_day"])
    return date(d.year, d.month, min(day, 28))


def _ensure_rent_charge(world, tenant: dict) -> None:
    """The current period's rent is charged on its due date (written once, marked auto)."""
    today = world.now().date()
    due = due_date_for(tenant, today)
    per = _period(today)
    rent = num((tenant.get("lease") or {}).get("rent"))
    if rent is None or today < due:
        return
    led = tenant.setdefault("ledger", [])
    if not any(e.get("kind") == "charge" and e.get("period") == per and e.get("note", "rent") == "rent" for e in led):
        led.append({"date": due.isoformat(), "kind": "charge", "amount": rent, "period": per, "note": "rent", "auto": True})


def ledger_view(world, tenant: dict) -> dict:
    """Exact figures: what is due this period, what was received, the remainder, arrears, the lease's late fee."""
    _ensure_rent_charge(world, tenant)
    today = world.now().date()
    per = _period(today)
    lease = tenant.get("lease") or {}
    led = tenant.get("ledger", [])
    charged = sum(float(e["amount"]) for e in led if e.get("kind") == "charge")
    paid = sum(float(e["amount"]) for e in led if e.get("kind") == "payment")
    balance = _r2(charged - paid)
    period_charges = _r2(sum(float(e["amount"]) for e in led if e.get("kind") == "charge" and e.get("period") == per))
    received_period = _r2(sum(float(e["amount"]) for e in led if e.get("kind") == "payment" and e.get("period") == per))
    this_period_unpaid = _r2(max(0.0, min(balance, period_charges)))
    arrears = _r2(max(0.0, balance - this_period_unpaid))
    due = due_date_for(tenant, today)
    days_late = (today - due).days if balance > EPS and today > due else 0
    fee = num(lease.get("late_fee"))
    fee_after = int(lease.get("late_fee_after_days") or 0)
    late_fee = {"amount": fee, "after_days": fee_after if fee is not None else None, "source": "lease",
                "applies": bool(fee is not None and days_late > fee_after),
                "note": ("the lease's late fee; quote it only as written, never compute more" if fee is not None else
                         "the lease has NO late fee: never mention or charge one")}
    return {"tenant_id": tenant["tenant_id"], "name": tenant.get("name"), "period": per, "due_date": due.isoformat(),
            "rent": num(lease.get("rent")), "rent_due_this_period": period_charges, "received_this_period": received_period,
            "remainder_this_period": this_period_unpaid, "arrears": arrears, "balance": balance, "days_late": days_late,
            "late_fee": late_fee, "deposit": num(lease.get("deposit")),
            "entries": copy.deepcopy(led[-12:]), "plan": copy.deepcopy(tenant.get("plan")),
            "ladder_stage": (tenant.get("ladder") or {}).get("stage", "current")}


def tenant_figures(world, thread: dict) -> set[float]:
    """Dollar figures the agent may quote on a tenant's thread: ledger and lease facts, an approved plan."""
    t = tenant_for_thread(world, thread.get("thread_id", ""))
    if not t:
        return set()
    v = ledger_view(world, t)
    out = {x for x in (v["rent"], v["rent_due_this_period"], v["received_this_period"], v["remainder_this_period"],
                       v["arrears"], v["balance"], v["deposit"]) if x is not None}
    if v["late_fee"]["amount"] is not None:
        out.add(float(v["late_fee"]["amount"]))
    out |= {float(e["amount"]) for e in t.get("ledger", [])}
    plan = t.get("plan") or {}
    if plan.get("status") in ("approved", "sent", "done"):
        out |= {float(i["amount"]) for i in plan.get("installments", [])}
    return {round(x, 2) for x in out if x is not None}


def _lang(world, tenant: dict) -> str:
    from .guards import thread_language
    for tid in tenant.get("thread_ids", []):
        th = world.get("threads", tid)
        if th:
            lang = thread_language(th)
            if lang:
                return lang
    return tenant.get("language") or "en"


def _ladder(tenant: dict, per: str) -> dict:
    lad = tenant.get("ladder")
    if not isinstance(lad, dict) or lad.get("period") not in (None, per) and lad.get("stage") in ("current", None):
        lad = {"period": per, "stage": "current", "events": [], "followups_silent": 0, "promised_date": None,
               "deadline": None, "notices_sent": (lad or {}).get("notices_sent", []) if isinstance(lad, dict) else []}
        tenant["ladder"] = lad
    lad.setdefault("period", per)
    lad.setdefault("stage", "current")
    lad.setdefault("events", [])
    lad.setdefault("followups_silent", 0)
    lad.setdefault("notices_sent", [])
    return lad


def _tenant_wrote_since(world, tenant: dict, since: str | None) -> bool:
    for tid in tenant.get("thread_ids", []):
        th = world.get("threads", tid)
        for m in (th or {}).get("messages", []):
            if m.get("from") == "renter" and (since is None or str(m.get("ts", "")) > since):
                return True
    return False


# ----------------------------------------------------------------------------- tools

@tool("get_ledger")
def get_ledger(world, tenant_id: str | None = None, thread_id: str | None = None):
    t = find_tenant(world, tenant_id, thread_id)
    v = ledger_view(world, t)
    v["thread_ids"] = list(t.get("thread_ids", []))
    v["next_step"] = ("quote only these exact figures (received, remainder, balance); the late fee only if the lease has "
                      "one; call rent_ladder for what to do next")
    return v


@tool("record_payment")
def record_payment(world, amount: float, tenant_id: str | None = None, thread_id: str | None = None,
                   date: str | None = None, method: str | None = None, note: str | None = None):
    t = find_tenant(world, tenant_id, thread_id)
    amt = num(amount)
    if amt is None or amt <= 0:
        raise ToolError("INVALID_ARGS", "amount must be a positive number of dollars")
    _ensure_rent_charge(world, t)
    today = world.now().date()
    when = date or today.isoformat()
    entry = {"date": when, "kind": "payment", "amount": _r2(amt), "period": _period(today), "note": note or "rent payment"}
    if method:
        entry["method"] = method
    t.setdefault("ledger", []).append(entry)
    # an installment of a sent plan is paid in date order
    plan = t.get("plan") or {}
    left = amt
    for inst in plan.get("installments", []) if plan.get("status") in ("approved", "sent") else []:
        if inst.get("status") == "paid" or left <= EPS:
            continue
        owed = float(inst["amount"]) - float(inst.get("paid", 0))
        take = min(owed, left)
        inst["paid"] = _r2(float(inst.get("paid", 0)) + take)
        left -= take
        if inst["paid"] + EPS >= float(inst["amount"]):
            inst["status"] = "paid"
    if plan and plan.get("installments") and all(i.get("status") == "paid" for i in plan["installments"]):
        plan["status"] = "done"
    lad = _ladder(t, _period(today))
    lad["followups_silent"] = 0
    v = ledger_view(world, t)
    es = _lang(world, t) == "es"
    month_en = today.strftime("%B")
    month_es = ["enero", "febrero", "marzo", "abril", "mayo", "junio", "julio", "agosto", "septiembre", "octubre",
                "noviembre", "diciembre"][today.month - 1]
    rem = v["balance"]
    if rem <= EPS:
        lad["stage"] = "current"
        msgs = ([f"Gracias, recibí {money(amt)} y ya estás al día."] if es else
                [f"Thanks, I received {money(amt)} and you're all caught up."])
    else:
        msgs = ([f"Gracias, recibí {money(amt)}, así que quedan {money(rem)} pendientes de {month_es}.",
                 "¿Cuándo puedes enviar el resto?"] if es else
                [f"Thanks, I received {money(amt)}, so {money(rem)} is left for {month_en}.",
                 "When can you send the rest?"])
    return {"tenant_id": t["tenant_id"], "received": _r2(amt), "received_this_period": v["received_this_period"],
            "remainder": rem, "balance": rem, "plan": copy.deepcopy(t.get("plan")), "acknowledgement": msgs,
            "next_step": ("send the acknowledgement messages as written (exact amount received, exact remainder, one question); "
                          "no new terms" if rem > EPS else "send the acknowledgement; nothing is owed")}


def _actions(world, t: dict, v: dict, lad: dict) -> list[dict]:
    pol = world.policy
    today = world.now().date()
    due = date.fromisoformat(v["due_date"])
    grace = int(pol.get("grace_days", 5))
    max_fu = int(pol.get("money_followups_before_owner", 2))
    acts: list[dict] = []
    stage = lad.get("stage", "current")
    if stage == "warned" and lad.get("promised_date") and today <= date.fromisoformat(lad["promised_date"]):
        # warned before the due date: judge the date they named against the upcoming due date
        upcoming = due if today <= due else due_date_for(t, (due.replace(day=1) + timedelta(days=32)).replace(day=1))
        pd = lad["promised_date"]
        within = date.fromisoformat(pd) <= upcoming + timedelta(days=grace)
        if within and approved(world, "grace", _ids(t)):
            return [{"action": "send", "what": f"'that works this time' (the owner approved it), with the date they named ({pd})",
                     "why": "the owner said yes to the grace request: tell them that works this time"}]
        if within:
            return [{"action": "escalate_to_owner", "reason": "grace request within the window",
                     "draft": f"That works this time, thanks for the heads-up. I'll expect it by {pd}.",
                     "why": f"they warned before the due date ({upcoming.isoformat()}) and named {pd}, within {grace} days: "
                            "the owner says yes first; tell them thanks for the heads-up and that you'll confirm"}]
        return [{"action": "ask_plan", "why": f"{pd} is beyond the {grace}-day grace window: ask how they plan to pay"}]
    if v["balance"] <= EPS:
        return [{"action": "none", "why": "nothing is owed"}]
    # the lease's notice, when the lease allows it: always, even while a plan is being made
    notice = ((t.get("lease") or {}).get("notices") or {}).get("late_rent")
    if notice and v["days_late"] >= int(notice.get("after_days", 0)) and v["days_late"] > 0 and not any(
            n.get("kind") == "late_rent" and n.get("period") == v["period"] for n in lad.get("notices_sent", [])):
        acts.append({"action": "send_notice", "kind": "late_rent",
                     "why": f"the lease requires its late-rent notice after {notice.get('after_days', 0)} days; send it even if a plan is being made"})
    plan = t.get("plan") or {}
    last_ev = lad["events"][-1]["at"] if lad.get("events") else None
    replied = _tenant_wrote_since(world, t, last_ev) if last_ev else False
    if today <= due:
        return acts or [{"action": "none", "why": f"rent is not late yet (due {v['due_date']})"}]
    if plan.get("status") == "awaiting_owner":
        acts.append({"action": "wait_owner", "why": "the plan is with the owner; one holding line at most"})
        return acts
    if plan.get("status") == "approved":
        acts.append({"action": "send_plan", "why": "the owner approved the plan: send the exact schedule, then rent_ladder plan_sent",
                     "installments": plan.get("installments")})
        return acts
    if plan.get("status") == "sent":
        nxt = next((i for i in plan.get("installments", []) if i.get("status") != "paid"), None)
        if nxt:
            d = date.fromisoformat(nxt["date"])
            if today > d:
                if nxt.get("status") != "missed":
                    nxt["status"] = "missed"
                    plan["missed"] = int(plan.get("missed", 0)) + 1
                if plan["missed"] >= 2:
                    plan["status"] = "broken"
                    acts.append({"action": "escalate_to_owner", "reason": "payment plan broken twice",
                                 "why": "two missed installments: facts to the owner, who decides the next step"})
                    return acts
                acts.append({"action": "checkin", "why": f"the {nxt['date']} installment of {money(nxt['amount'])} was missed: "
                                                          "ask what happened and when it is coming, and tell the owner"})
                acts.append({"action": "report_to_owner", "why": "missed installment"})
            elif (d - today).days <= 1:
                acts.append({"action": "checkin", "why": f"installment of {money(nxt['amount'])} is due {nxt['date']}: a short reminder"})
            else:
                acts.append({"action": "none", "why": f"plan on track; next installment {nxt['date']}"})
        return acts
    deadline = lad.get("deadline") or (lad.get("promised_date")) or (due + timedelta(days=grace)).isoformat()
    lad["deadline"] = deadline
    if stage == "escalated":
        acts.append({"action": "none", "why": "already with the owner"})
        return acts
    if today > date.fromisoformat(deadline) and stage in ("reminder_sent", "assessed") and not replied:
        acts.append({"action": "escalate_to_owner", "reason": "late rent past the deadline",
                     "why": f"past the {deadline} deadline with {money(v['balance'])} owed and no plan: owner decides"})
        return acts
    if stage in ("current", "late", "warned"):
        acts.append({"action": "reminder", "why": f"{v['days_late']} days late: one friendly factual reminder with the exact amount "
                                                   f"({money(v['balance'])}) and one question (when is it coming); alert the owner"})
        acts.append({"action": "report_to_owner", "why": "owner is told about late rent at the first reminder"})
    elif stage == "reminder_sent":
        if replied:
            acts.append({"action": "ask_plan", "why": "they answered: ask how they plan to pay (paycheck and when, help from "
                                                      "family or friends, other income); one question, then rent_ladder assessed"})
        elif lad.get("followups_silent", 0) >= max_fu:
            acts.append({"action": "escalate_to_owner", "reason": "no answer on rent after follow-ups",
                         "why": f"{max_fu} follow-ups with no answer: the owner takes over"})
        else:
            acts.append({"action": "followup", "why": f"no answer yet: follow up with NEW wording "
                                                      f"({lad.get('followups_silent', 0) + 1} of {max_fu}), then rent_ladder followup_sent"})
    elif stage == "assessed":
        if replied:
            acts.append({"action": "propose_payment_plan", "why": "they told you how they can pay: put their schedule into "
                                                                  "propose_payment_plan (their own proposal first)"})
        elif lad.get("followups_silent", 0) >= max_fu:
            acts.append({"action": "escalate_to_owner", "reason": "no answer on rent after follow-ups",
                         "why": f"{max_fu} follow-ups with no answer: the owner takes over"})
        else:
            acts.append({"action": "checkin", "why": "check in once with new wording, then rent_ladder checkin_sent"})
    return acts


def _ids(t: dict) -> set[str]:
    return {t["tenant_id"], *t.get("thread_ids", []), *( [t["room_id"]] if t.get("room_id") else [])}


def approved(world, kind: str, ids: set[str]) -> dict | None:
    """An owner approval of `kind` for any of these ids (or for everyone, ref_id '*')."""
    for a in world.approvals:
        if a.get("status", "approved") == "approved" and a.get("kind") == kind and (a.get("ref_id") in ids or a.get("ref_id") == "*"):
            return a
    return None


@tool("rent_ladder")
def rent_ladder(world, tenant_id: str | None = None, thread_id: str | None = None, event: str | None = None,
                promised_date: str | None = None, note: str | None = None):
    t = find_tenant(world, tenant_id, thread_id)
    v = ledger_view(world, t)
    lad = _ladder(t, v["period"])
    now = world.clock["now"]
    if event is not None:
        if event not in EVENTS:
            raise ToolError("INVALID_ARGS", f"event must be one of {', '.join(EVENTS)}")
        if event == "warned":
            if not promised_date:
                raise ToolError("INVALID_ARGS", "warned needs promised_date (the date they said they can pay)",
                                hint="ask for the exact date first")
            lad["stage"] = "warned"
            lad["promised_date"] = promised_date
        elif event == "reminder_sent":
            lad["stage"] = "reminder_sent"
        elif event == "assessed":
            lad["stage"] = "assessed"
            lad["followups_silent"] = 0
        elif event == "tenant_replied":
            lad["followups_silent"] = 0
            if promised_date:
                lad["promised_date"] = promised_date
                lad["deadline"] = promised_date
        elif event in ("followup_sent", "checkin_sent"):
            lad["followups_silent"] = int(lad.get("followups_silent", 0)) + 1
        elif event == "plan_sent":
            plan = t.get("plan") or {}
            if plan.get("status") != "approved":
                raise ToolError("POLICY_BLOCKED", "no owner-approved plan to send",
                                hint="propose_payment_plan, then escalate_to_owner; send only after the owner approves")
            plan["status"] = "sent"
            plan["sent_at"] = now
            lad["stage"] = "plan_sent"
        elif event == "escalated":
            lad["stage"] = "escalated"
        lad["events"].append({"event": event, "at": now, **({"note": note} if note else {}),
                              **({"promised_date": promised_date} if promised_date else {})})
    acts = _actions(world, t, v, lad)
    first = next((a for a in acts if a["action"] not in ("send_notice", "report_to_owner")), acts[0] if acts else None)
    return {"tenant_id": t["tenant_id"], "stage": lad["stage"], "balance": v["balance"], "due_date": v["due_date"],
            "days_late": v["days_late"], "deadline": lad.get("deadline"), "promised_date": lad.get("promised_date"),
            "followups_silent": lad.get("followups_silent", 0),
            "money_followups_before_owner": int(world.policy.get("money_followups_before_owner", 2)),
            "notice_due": any(a["action"] == "send_notice" for a in acts), "actions": acts,
            "next_step": "; ".join(a["why"] for a in acts) if acts else (first or {}).get("why", "")}


_PLACEHOLDER = re.compile(r"\{(\w+)\}")


@tool("send_notice")
def send_notice(world, tenant_id: str | None = None, thread_id: str | None = None, kind: str = "late_rent"):
    t = find_tenant(world, tenant_id, thread_id)
    notice = ((t.get("lease") or {}).get("notices") or {}).get(kind)
    if not notice or not notice.get("template"):
        raise ToolError("NOT_FOUND", f"the lease has no {kind!r} notice template",
                        hint="notices go out only as the lease writes them; escalate_to_owner instead")
    v = ledger_view(world, t)
    if v["balance"] <= EPS:
        raise ToolError("CONFLICT", "nothing is owed; no notice")
    after = int(notice.get("after_days", 0))
    if v["days_late"] < max(1, after):
        allowed_on = (date.fromisoformat(v["due_date"]) + timedelta(days=max(1, after))).isoformat()
        raise ToolError("POLICY_BLOCKED", f"the lease allows this notice from {allowed_on} ({after} days after the due date)",
                        hint="send the friendly reminder now; the notice goes out on its date", details={"rules": ["notice_too_early"]})
    lad = _ladder(t, v["period"])
    if any(n.get("kind") == kind and n.get("period") == v["period"] for n in lad.get("notices_sent", [])):
        raise ToolError("CONFLICT", f"the {kind} notice for {v['period']} was already sent")
    from .demand_guards import public_street
    room = world.get("rooms", t.get("room_id")) if t.get("room_id") else None
    fields = {"name": t.get("name") or "", "rent": money(v["rent"] or 0), "balance": money(v["balance"]),
              "due_date": v["due_date"], "period": v["period"], "days_late": str(v["days_late"]),
              "street": public_street((room or {}).get("address", "")) if room else ""}
    if v["late_fee"]["amount"] is not None:
        fields["late_fee"] = money(v["late_fee"]["amount"])
    missing = [k for k in _PLACEHOLDER.findall(notice["template"]) if k not in fields]
    if missing:
        raise ToolError("CONFLICT", f"the template needs {', '.join(missing)}, which the lease and ledger do not have",
                        hint="escalate_to_owner: the notice template needs fixing")
    text = _PLACEHOLDER.sub(lambda m: fields[m.group(1)], notice["template"])
    tid = (thread_id if thread_id in t.get("thread_ids", []) else None) or (t.get("thread_ids") or [None])[0]
    th = world.get("threads", tid) if tid else None
    if th is None:
        raise ToolError("NOT_FOUND", "the tenant has no thread to send the notice on")
    msg = {"id": f"{tid}-m{len(th['messages']) + 1}", "from": "operator", "type": "notice", "kind": kind, "text": text,
           "attachments": [], "ts": world.clock["now"], "status": "ready_to_submit" if world.mode == "live" else "sent"}
    th["messages"].append(msg)
    lad["notices_sent"].append({"kind": kind, "period": v["period"], "at": world.clock["now"], "message_id": msg["id"]})
    return {"notice": copy.deepcopy(msg), "tenant_id": t["tenant_id"],
            "next_step": "the notice does not end the conversation: keep working toward a plan with the tenant"}


def _check_plan(world, t: dict, v: dict, shape: str, inst: list[dict], new_due_day, paycheck_day) -> list[str]:
    b = world.policy.get("payment_plan_bounds") or {}
    max_split = int(b.get("split_max_payments", 2))
    max_months = int(b.get("arrears_max_months", 3))
    rent = float(v["rent"] or 0)
    today = world.now().date()
    total = sum(float(i["amount"]) for i in inst)
    reasons = []
    if shape == "split":
        if len(inst) > max_split:
            reasons.append(f"{len(inst)} payments; the bound is {max_split} inside the month")
        if any(i["date"][:7] != v["period"] for i in inst):
            reasons.append(f"every payment must fall inside {v['period']}")
        if abs(total - v["balance"]) > EPS:
            reasons.append(f"payments add up to {money(total)}, not the {money(v['balance'])} owed")
    elif shape == "due_date_shift":
        pd = paycheck_day or t.get("paycheck_day")
        if not new_due_day:
            reasons.append("needs new_due_day")
        elif not pd:
            reasons.append("needs the tenant's paycheck day: ask when they are paid")
        elif not (0 <= (int(new_due_day) - int(pd)) % 31 <= 3):
            reasons.append(f"new due day {new_due_day} is not aligned to the paycheck on day {pd} (0 to 3 days after)")
        if abs(total - v["balance"]) > EPS:
            reasons.append(f"payments add up to {money(total)}, not the {money(v['balance'])} owed")
    elif shape == "catch_up":
        months = sorted({i["date"][:7] for i in inst})
        if len(months) != len(inst):
            reasons.append("one catch-up payment per month")
        if len(months) > max_months:
            reasons.append(f"arrears spread over {len(months)} months; the bound is {max_months}")
        if any(float(i["amount"]) + EPS < rent for i in inst):
            reasons.append(f"each month must cover at least the {money(rent)} rent")
        want = v["balance"] + rent * max(0, len(months) - (1 if v["period"] in months else 0))
        if abs(total - want) > EPS:
            reasons.append(f"payments add up to {money(total)}, but the balance plus the rent of the later months is {money(want)}")
    if any(date.fromisoformat(i["date"]) < today for i in inst):
        reasons.append("a payment date is in the past")
    return reasons


@tool("propose_payment_plan")
def propose_payment_plan(world, shape: str, installments: list, tenant_id: str | None = None, thread_id: str | None = None,
                         proposed_by: str = "tenant", tenant_words: str | None = None, new_due_day: int | None = None,
                         paycheck_day: int | None = None):
    t = find_tenant(world, tenant_id, thread_id)
    if shape not in SHAPES:
        raise ToolError("INVALID_ARGS", f"shape must be one of {', '.join(SHAPES)}")
    inst = []
    for i in installments or []:
        if not isinstance(i, dict) or num(i.get("amount")) is None or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", str(i.get("date", ""))):
            raise ToolError("INVALID_ARGS", "installments are [{\"date\": \"YYYY-MM-DD\", \"amount\": number}, ...]")
        inst.append({"date": i["date"], "amount": _r2(i["amount"]), "status": "due"})
    if not inst:
        raise ToolError("INVALID_ARGS", "give at least one installment")
    inst.sort(key=lambda x: x["date"])
    v = ledger_view(world, t)
    reasons = _check_plan(world, t, v, shape, inst, new_due_day, paycheck_day)
    plan = {"plan_id": world.next_id("PLAN"), "shape": shape, "installments": inst, "proposed_by": proposed_by,
            "tenant_words": tenant_words, "in_bounds": not reasons, "reasons": reasons, "status": "awaiting_owner",
            "created_at": world.clock["now"], "balance_at_proposal": v["balance"]}
    if new_due_day:
        plan["new_due_day"] = int(new_due_day)
        rule = (t.get("lease") or {}).get("due_shift_deposit_rule")
        plan["deposit_adjustment"] = rule or "as the lease requires (owner sets it)"
    t["plan"] = plan
    lad = _ladder(t, v["period"])
    lad["stage"] = "plan_proposed"
    sched = ", ".join(f"{money(i['amount'])} on {i['date']}" for i in inst)
    words = f" Their words: \"{tenant_words}\"." if tenant_words else ""
    if not reasons:
        draft = (f"Payment plan for {t.get('name') or t['tenant_id']} ({shape}, inside your bounds): {sched}. "
                 f"Owed now {money(v['balance'])}.{words} Approve and I'll send it and track it.")
        nxt = ("escalate_to_owner(reason 'payment plan for approval', ref_id the tenant's thread, draft) and tell the tenant in "
               "one line that you'll come back to them today; do not confirm the plan before the owner approves")
    else:
        draft = (f"Payment plan OUTSIDE your bounds for {t.get('name') or t['tenant_id']} ({shape}): {sched}. "
                 f"Why: {'; '.join(reasons)}. Owed now {money(v['balance'])}.{words} Your call.")
        nxt = ("out of bounds: escalate_to_owner with this draft (the owner decides exceptions); tell the tenant in one line "
               "that you'll come back to them; never agree it yourself")
    return {"tenant_id": t["tenant_id"], "plan": copy.deepcopy(plan), "in_bounds": not reasons, "reasons": reasons,
            "owner_draft": draft, "next_step": nxt}
