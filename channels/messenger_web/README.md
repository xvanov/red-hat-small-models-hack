# Personal Messenger (web) channel: `messenger_personal`

Facebook Marketplace room listings are posted from the owner's personal Facebook account, so renter inquiries
arrive in his personal Messenger. Personal accounts have no API, so this channel reads and writes
`facebook.com/messages` in a real browser logged in as the owner.

## Pieces

| File | What it does |
|---|---|
| `worker.py` | The browser worker. The only process that drives the browser. It polls the inbox (every 30 s by default, never under 20 s), opens at most 3 changed threads per poll with 3 to 7 s gaps between them, and runs send requests from the outbox. |
| `adapter.py` | `MessengerPersonal`, the provider for `channels/live`. It reads the worker's files and writes send requests. It never touches a browser, so the daemon and console processes stay Playwright-free. |
| `extract.js` | Read-only page extractors (thread list, messages with in/out direction, login-wall detection). |
| `selectors.json` | All selectors (ARIA roles and labels first) and the Messenger system-text filters. Fix selectors here, not in the code. |
| `__main__.py` | CLI: `login`, `check`, `read`, `serve`, `test-send`. |

Data lives in `runs/live/messenger_web/`, which is gitignored and checked with `git check-ignore` before anything is
written. It holds `threads.json` (the real conversation text), `status.json`, `outbox/` and `sends.jsonl` (an
audit log without message text). The browser profile is `channels/.profiles/messenger_web/` (also gitignored).

## Owner steps

```bash
channels/.venv/bin/python -m channels.messenger_web login   # log in to facebook.com by hand, open Messages, close the window
channels/.venv/bin/python -m channels.messenger_web check   # {"state": "ok", "threads_visible": N, ...}
channels/.venv/bin/python -m channels.messenger_web serve   # keep running next to `python -m channels.live`
```

On a VNC desktop, prefix `login` with `DISPLAY=:2`. `serve` shows its browser window by default. Set
`MESSENGER_WEB_HEADLESS=1` to hide it. Facebook is more likely to challenge a headless browser.

## Safety

- Every thread is read. The operator's reply on any thread becomes a draft that waits for the owner's approval.
- Auto-send happens only for threads whose participant display name is in `LIVE_ALLOW_MESSENGER_NAMES`
  (comma-separated, repo `.env`, empty by default). The match ignores case and extra spaces.
- If a login page, checkpoint or captcha appears, the worker stops and sets status `login_required`. It looks
  again only every 5 minutes and never interacts with the page.
- On a send, the worker clicks only the message box, then types with human-like delays and presses Enter.
  - Before typing, it refuses if the box already holds text, because the owner may be typing.
  - Before pressing Enter, it checks that the box holds exactly the approved text. If not, it clears the box and
    sends nothing.
  - After sending, it checks that a new outgoing bubble with that text appears in the thread.
- The worker has its own checks too: it honors the kill switch `runs/live/STOP` and caps sends at
  `MESSENGER_WEB_MAX_SENDS_HOUR` (10 by default).
- If the worker does not pick up a send within `MESSENGER_WEB_SEND_WAIT` seconds, the request is cancelled
  (atomic rename), so it can never go out later without anyone seeing it.
- Opening a thread to read it marks it as seen on Facebook, just as it would if the owner read it himself.

## Registering in `channels/live` (for the live worker)

The contact is the Facebook thread id, and `renter_name` is the participant's display name.

```python
# store.py
CHANNEL_WORLD = {..., "messenger_personal": "marketplace"}

# outbound.get_providers()
from channels.messenger_web.adapter import MessengerPersonal
_PROVIDERS = {..., "messenger_personal": MessengerPersonal()}

# daemon.poll_all(): add the source, and keep EVERY messenger_personal item (all threads become drafts)
sources += [(k, provs[k]) for k in ("email", "messenger", "messenger_personal") if provs.get(k) is not None]
...
            if it["channel"] != "messenger_personal" and not allow.allows(it["channel"], it["contact"]):
                continue

# config.Allowlist.allows(): the auto-send gate used by outbound._gate
        if channel == "messenger_personal":
            from channels.messenger_web.adapter import allows_autosend
            return allows_autosend(contact)          # name in LIVE_ALLOW_MESSENGER_NAMES

# outbound._provider_send()
    if ch == "messenger_personal":
        prov = p.get("messenger_personal")
        return prov.send(t["contact"], text) if prov else {"ok": False, "status": "failed", "error": "not configured"}

# api.status(): add "messenger_personal" to the ("email", "messenger") loop
```

`send()` blocks for up to `MESSENGER_WEB_SEND_WAIT` (120 s by default) while the worker types and verifies.
The usual wait is 5 to 20 s. Statuses are `sent` (verified), `sent_unverified` (the box cleared but the bubble
was not found) or `failed` with an `error_code`: `login_required`, `box_busy`, `typing_mismatch`, `rate_cap`,
`stopped`, `timeout`, `worker_unavailable`, `unknown_thread`, `page_changed` or `not_sent`.

## Tests

`channels/tests/test_messenger_web.py` runs on synthetic HTML fixtures with fake names, served at facebook.com
URLs through Playwright routing, so no network is used. The tests cover parsing, direction, system-text
filtering, login walls, the full outbox send, refusals and the cancel-on-timeout path.
