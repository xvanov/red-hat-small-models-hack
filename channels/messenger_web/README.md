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

## Headless login (cookie import from your laptop)

This machine has no screen, so `login` (which needs a visible browser) refuses here. Copy your session from your
laptop instead:

1. On the laptop, in Chrome, install the **Cookie-Editor** extension (cookie-editor.com). EditThisCookie also works.
2. Open https://www.facebook.com logged in as yourself, click the Cookie-Editor icon, then Export, then
   **JSON**. The export is copied to the clipboard.
3. Put it on this machine as `~/fb-cookies.json`. Either run `ssh k@100.64.38.18 'cat > ~/fb-cookies.json'`,
   paste, and press Ctrl-D, or save it to a file and copy it with `scp`.
4. On this machine, run `channels/.venv/bin/python -m channels.messenger_web import-cookies ~/fb-cookies.json`.
   It loads only the facebook.com and messenger.com cookies into the profile, opens the inbox headless, prints
   `{"ok": true, "state": "ok", "threads_visible": N}`, and deletes the file.
5. Run `... read` (prints counts only), then `... serve`.

The export is your live session, so treat it like a password. Facebook can still ask for a checkpoint
because the session comes from a new IP address. The worker then reports `login_required` and does nothing more.
`login`, `check`, `read`, `serve` and `import-cookies` all refuse with the blocking PID if another process holds
the profile, and they clear a stale `SingletonLock` left by a crashed one.

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

## Registering in `channels/live`

`channels/live/registry.py` loads it from the repo `.env`. No code changes are needed:

```bash
LIVE_EXTRA_CHANNELS=messenger_personal=channels.messenger_web.adapter:make_live_provider
LIVE_PERSONAL_DRAFTS=1                      # every non-allowlisted chat becomes a thread with replies held as drafts
LIVE_ALLOW_MESSENGER_NAMES=Test Account     # names allowed to auto-send (empty by default)
LIVE_ALLOW_MESSENGER_PERSONAL_IDS=...       # what channels/live actually checks: the thread ids of those names
```

`channels/live` allowlists by contact id, which here is the Facebook thread id. After the worker has read the
inbox, `python -m channels.messenger_web ids` prints the thread ids that match `LIVE_ALLOW_MESSENGER_NAMES`, along
with the ready-made `LIVE_ALLOW_MESSENGER_PERSONAL_IDS=` line. `renter_name` is the participant's display name,
and `meta` carries `listing_title`, `marketplace`, `thread_url` and `autosend` (whether the name is allowlisted).
In code, the same registration is
`registry.register_channel("messenger_personal", make_live_provider())`.

`send()` blocks for up to `MESSENGER_WEB_SEND_WAIT` (120 s by default) while the worker types and verifies.
The usual wait is 5 to 20 s. Statuses are `sent` (verified), `sent_unverified` (the box cleared but the bubble
was not found) or `failed` with an `error_code`: `login_required`, `box_busy`, `typing_mismatch`, `rate_cap`,
`stopped`, `timeout`, `worker_unavailable`, `unknown_thread`, `page_changed` or `not_sent`.

## Tests

`channels/tests/test_messenger_web.py` runs on synthetic HTML fixtures with fake names, served at facebook.com
URLs through Playwright routing, so no network is used. The tests cover parsing, direction, system-text
filtering, login walls, the full outbox send, refusals and the cancel-on-timeout path.
