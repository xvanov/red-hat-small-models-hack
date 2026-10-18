# Live channels (`channels/live/`)

Real two-way conversations run by the operator (Nemotron 3.5 Lightning via `OPERATOR_BASE_URL`, final config:
prompt v4 + concierge tool descriptions + renter guard with stand-down + style pre-check + reasoning history +
verifier + reader) on:

| Channel | Out | In (polling only, no webhook or provider setting is changed) |
|---|---|---|
| `sms`, line `tollfree` (888) | Twilio Messages API, creds from `~/rental-management/.env.production` | Twilio Messages list, `To=<line>&From=<allowlisted phone>` |
| `sms`, line `local` (910, 10DLC; opt-in: `LIVE_SMS_LINES=tollfree,local`, another business's campaign) | Twilio, creds + messaging service from `~/ivanovstroy/.env.sms` | same |
| `email` | Resend, From `info@rentus.homes`, Reply-To `<GMAIL_USER>+rentus@gmail.com` | Gmail IMAP (read-only, `[Gmail]/All Mail`): mail FROM an allowlisted address addressed to `info@` / the Reply-To, or whose subject carries the thread's `[ref xxxxxx]` tag |
| `messenger` | Graph Send API `POST /{page-id}/messages`, `messaging_type=RESPONSE` (24 h window) | Graph `/{page-id}/conversations`; conversations without an allowlisted participant are skipped before any message text is read |
| extra channels | `registry.register_channel(...)` (e.g. `messenger_personal`, see `registry.py`) | provider's `poll()` |

Why the email Reply-To is a Gmail plus-address: the test renter inbox (`DEMO_TEST_EMAIL`) is the same Gmail
account as `GMAIL_USER`, and replies to `info@rentus.homes` would land in the production app's inbound webhook.
The reader looks in All Mail, so the renter's reply is found either way; threading uses the `[ref]` subject tag,
and outbound replies set `In-Reply-To`/`References` to the renter's last Message-ID so Gmail threads them.

## Safety

- **Allowlist.** Only `DEMO_TEST_PHONE`, `DEMO_TEST_EMAIL`, `LIVE_ALLOW_PHONES`, `LIVE_ALLOW_EMAILS`,
  `LIVE_ALLOW_MESSENGER_PSIDS` (and `LIVE_ALLOW_<CHANNEL>_IDS` for extra channels). Inbound from anyone else is
  dropped before it is stored or shown to a model. Exception: an extra channel with `drafts_env` (for
  `messenger_personal`: `LIVE_PERSONAL_DRAFTS=1`) stores non-allowlisted chats and runs the operator, but every
  reply becomes an approval draft (`awaiting_approval`) that only the owner's Approve sends.
- **Kill switch.** `LIVE_SEND_ENABLED=0` or the file `runs/live/STOP` (`python -m channels.live stop|resume`).
  While off, every send (operator or owner) becomes an approval item; nothing goes out.
- **Rate cap.** `LIVE_MAX_PER_HOUR` (default 30) real send attempts per hour across all channels; over it, sends
  become approval items.
- **Opt-out.** An SMS of STOP/UNSUBSCRIBE/... marks the thread opted out; nothing more is sent on it.
- **Data.** Conversation text lives only in `runs/live/` (gitignored). `sends.jsonl` holds no message text.
  Credentials are loaded with `dotenv_values` into the process and never printed or stored.
- The live World holds one room, the real Appling Way listing (as in the D20 pilot); calendar writes are not
  registered (showing slots come from the sandbox calendar).

## Run

```bash
.venv/bin/python -m channels.live status            # channels, connected?, send_enabled, allowlist size
.venv/bin/python -m channels.live                   # daemon: poll every LIVE_POLL_SECONDS (8), run turns
.venv/bin/python -m channels.live --once            # one poll + turns
.venv/bin/python -m channels.live start sms +1XXXXXXXXXX "Hi ..." --line tollfree|local
.venv/bin/python -m channels.live start email someone@example.com "Hi ..."
.venv/bin/python -m channels.live deliveries        # Twilio delivery status / email arrived in the test inbox
.venv/bin/python -m channels.live messenger-whoami  # names + PSIDs of recently active Page chats (find the owner's PSID)
.venv/bin/python -m pytest -q channels/tests/test_live_channels_daemon.py
```

Only one daemon runs per store (`runs/live/daemon.pid`, fcntl lock; a second daemon or `--once` exits with
code 3). Live turns run with reasoning off (`enable_thinking=False` per request) for chat speed;
`LIVE_REASONING=1` restores the server default. Provider sends happen outside the store lock (reserve, send,
record), so console calls never wait on the network. The daemon log is wherever you redirect it (we use `runs/live/daemon.log`). A thread's operator World and model
history persist in its thread file, so a restart continues the conversation; the first run only answers
messages from the last 30 minutes. A failed turn (endpoint down) is retried on the next polls, then after 3
failures becomes an approval item asking the owner to reply by hand.

## Console contract (`channels/live/api.py`)

All functions read/write the store on disk (fcntl lock on `runs/live/.lock`), so console and daemon can be
separate processes. Sends from the API go out immediately with the same gates.

- `status() -> dict`: `{"channels": [{"channel", "line", "connected": bool, "detail": str, ("line_name")}],
  "send_enabled", "allowlist_size", "sent_last_hour", "max_per_hour", "last_poll", "poll_errors"}`.
  `line` is `+1888…2046` / `+1910…5341` / `info@rentus.homes` / the Page name. Connectivity checks are cached 60 s.
- `list_threads() -> list[dict]`: `{"thread_id"` (`sms:<line_last4>:<hash>` / `email:<hash>` / `messenger:<hash>` /
  `<extra channel>:<hash>`), `"channel", "contact_display"` (masked phone / masked email / first name),
  `"renter_name", "last_text", "last_ts"` (ISO), `"unread": int, "stage"` (`inquiry|qualifying|qualified|showing|
  application|lost`), `"gate": {"lease","move_in","phone","reason","people"}` each `exact|vague|missing`,
  `"needs_owner": bool}` plus extras `"line", "opted_out", "busy"` (an operator turn is running now: show
  "Operator is typing…"), `"busy_since"` (ISO, or null), `"queued"` (a reply waits for a turn). Newest first.
- `get_thread(thread_id, mark_read=True) -> dict`: the summary plus `"messages": [{"id","direction":"in"|"out",
  "text","ts","status":"received"|"sent"|"draft"|"failed"|"awaiting_approval","channel"(,"error")}]` and
  `"trace": [{"ts","actor":"operator"|"reader"|"verifier"|"tool","name","summary","ok"}]`. Returns `unread` as it
  was, then marks the thread read.
- `list_approvals() -> list[dict]`: pending items `{"id","thread_id","reason","draft_text","created","kind"}`;
  `kind` is `draft` (a send a gate stopped), `escalation` (operator's `escalate_to_owner`, draft = its draft),
  `report` (`report_to_owner`, no draft; at most one pending per thread, internal ids removed) or `error` (the
  operator failed 3 times, including model errors: reply by hand).
- `decide(approval_id, "approve"|"edit"|"deny", text=None) -> dict`: approve/edit send `text` when given, else
  `draft_text` (on the approval's thread/channel); deny marks it denied (no send). The item is claimed
  (`sending`) under the lock before anything is sent, so it can never go out twice; deciding a non-pending item
  returns `ok: false`. Approve/edit of an item with no text just closes it. Returns
  `{"ok","decision","sent","status","error"}`; if a gate still blocks (kill switch, rate cap) the item goes back
  to pending with `ok: false`. Owner approval lifts only the allowlist check, never the kill switch, opt-out or cap.
- `send_owner_message(thread_id, text) -> dict`: manual reply on the thread's channel; the operator sees it in its
  next turn. Returns `{"ok","status","message_id","provider_id","error"}`.
- `start_conversation(channel, to, text, line=None) -> dict`: first outbound message to an allowlisted contact
  (`channel` = `sms|email|messenger|<extra>`; `line` = `tollfree|local` for SMS). Returns the send result plus
  `"thread_id"`.

## Roles, lease link, archive (later additions)

- Roles per channel from `.env`: `LIVE_ROLE_SMS` / `LIVE_ROLE_EMAIL` / `LIVE_ROLE_MESSENGER` = `prospect` (default) |
  `tenant` | `lease_signing` (`roles.py`). Stage values: `inquiry|qualifying|qualified|showing|application|lost`
  (prospect), `tenant`, `lease_signing` -> `lease_sent`. Threads also carry `role` and a short `context` string.
- `send_lease_link` (live-only tool, registered in-process by `roles.install_lease_tool`; no file under tools/ or
  operator/ changes): adds `LIVE_LEASE_LINK_URL` (a real signing link the owner made) or else
  `https://app.rentus.homes/apply` to the turn's reply. See `lease_link.py` for why no link is minted here.
- Each turn's send_message calls go out as one composed reply (`compose.py`).
- `api.archive_thread(id|"all")`, `api.unarchive_thread(id)`, `api.dismiss_approval(id)`,
  `list_threads(include_archived=False)`; CLI `python -m channels.live archive <thread_id|all>`. A new message from
  an archived thread's contact starts a new thread `<id>:2` with fresh history in the same role.
