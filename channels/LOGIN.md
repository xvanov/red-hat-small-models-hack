# Logging in to the real platforms (owner only)

The browser adapters never type a password. Each platform gets its own saved browser profile in
`channels/.profiles/<platform>/` (gitignored). You log in by hand once; the adapters reuse that session.
Nothing is ever posted or sent: listing forms stop before the final button, email and SMS replies are
saved as drafts.

## 5-minute checklist

On a machine without a screen (this one), use **Headless login** below instead. Run everything from the
repo root (`~/red-hat-small-models-hack`). Each `channels.login` line opens a browser window: log in (pass any "verify you are human" check), then **close the window**.

| # | Platform | Command | What it unlocks |
|---|---|---|---|
| 1 | craigslist | `channels/.venv/bin/python -m channels.login craigslist` | Past the details form to images and the preview page (stops before **publish**). Works without this up to the filled details form. |
| 2 | Roomies | `channels/.venv/bin/python -m channels.login roomies` | Clears Roomies' Cloudflare check and logs in. Without it every run returns `LOGIN_REQUIRED` (bot check). |
| 3 | PadSplit (host) | `channels/.venv/bin/python -m channels.login padsplit` | The host add-room form. Without it `/host` bounces to the home page: `LOGIN_REQUIRED`. |
| 4 | Facebook Marketplace | `channels/.venv/bin/python -m channels.login marketplace` | Marketplace "create listing" form. |
| 5 | Email inbox | see "Email" below | Platform lead emails become threads; replies are drafts. |

Then dry-run each listing (fills, screenshots to `channels/screenshots/`, stops before the final button):

```bash
channels/.venv/bin/python -m channels.publish craigslist --target live --listing my-listing.json
channels/.venv/bin/python -m channels.publish roomies    --target live --listing my-listing.json
channels/.venv/bin/python -m channels.publish padsplit   --target live --listing my-listing.json
```

`my-listing.json` is a contract listing plus its room and real photo paths, for example:

```json
{"listing_id": "L-appling", "title": "Private room with its own bath, Appling Way", "body": "...", "price": 750,
 "room": {"room_id": "appling-way-a", "area": "Durham", "zip": "27703", "address_public": "Appling Way, Durham, NC",
          "type": "private_room", "private_bath": true, "furnished": true, "available_from": "2026-11-01",
          "laundry": "w/d in unit", "parking": "off-street parking", "lease_min_months": 6},
 "photos": ["/path/to/photo1.jpg", "/path/to/photo2.jpg"]}
```

You click the final Publish/Post button yourself if you want it live. The adapter refuses `submit` on
live targets, and a guard refuses any click on a button that reads like publish, submit or send.

Only facts in the room record are filled. Laundry, parking, housing type, room size, furnished, pets and
minimum stay stay unset (or unchecked) unless the record has them and does not list them under
`unconfirmed`; the screenshot shows what was filled.

If a session expires, the adapter returns `LOGIN_REQUIRED` with the exact login command in its `hint`
(`details.reason` is `login_page`, `bot_challenge` or `redirected`).

## Headless login (no screen: this machine)

This machine has no display, so `channels.login <site>` (which opens a browser window) refuses and points
here. Instead you copy your logged-in session from your laptop's browser. You need the **Cookie-Editor**
browser extension (Chrome or Firefox). Never paste cookies into a chat: they are a live login.

For each site:

1. On your laptop, open the URL below **logged in** (log in there first if needed, pass any "verify you are
   human" check).
2. Click Cookie-Editor > **Export** > **JSON** (copies the site's cookies to the clipboard).
3. In a laptop terminal: `ssh k@100.64.38.18 'cat > ~/<site>-cookies.json'`, paste, press Enter, then Ctrl-D.
4. On this machine, from `~/red-hat-small-models-hack`, run the import command. It keeps only that site's
   cookies, loads them into the adapter's profile (`channels/.profiles/<site>/`), deletes the file, and
   checks the session. It prints counts and `logged_in: true/false`, never a cookie value.

| Site | Open on the laptop, logged in | Import command |
|---|---|---|
| Facebook (Marketplace **and** Messenger, one export) | https://www.facebook.com/marketplace/create/rental | `channels/.venv/bin/python -m channels.login import-cookies marketplace ~/marketplace-cookies.json` |
| Roomies | https://www.roomies.com/rooms/new | `channels/.venv/bin/python -m channels.login import-cookies roomies ~/roomies-cookies.json` |
| PadSplit (host) | https://www.padsplit.com/host | `channels/.venv/bin/python -m channels.login import-cookies padsplit ~/padsplit-cookies.json` |
| craigslist | https://accounts.craigslist.org/login/home | `channels/.venv/bin/python -m channels.login import-cookies craigslist ~/craigslist-cookies.json` |

- The Facebook export must include `c_user` and `xs` (it does when you are logged in on www.facebook.com);
  the import refuses otherwise. The same import also logs in `channels/.profiles/messenger_web/`, so you
  do not need `python -m channels.messenger_web import-cookies` separately (`--no-messenger` skips it; if
  the Messenger worker is running it keeps its own session and the output says so).
- Check any site later: `channels/.venv/bin/python -m channels.login check <site>` (yes/no only).
- Roomies is behind Cloudflare. Headless live sessions present a desktop Chrome user agent (override with
  `CHANNELS_USER_AGENT`), which passed with an imported session on 2026-10-18; if it ever meets the check
  again, `check roomies` says `bot_challenge`.
- Roomies' listing page is `roomies.com/rooms/create`: the adapter fills address, Room, House, rent and
  available date and stops before **Create room**; description and photos come after that click.
- craigslist (logged in) goes through the details form, map and photos to the unpublished-draft preview and
  stops before **publish**. craigslist requires laundry and parking: if the room record has no `laundry` /
  `parking`, the run stops at the details form and says so instead of inventing them. Each run that gets
  past the details form leaves an unpublished draft in your craigslist account.
- "profile in use by process N": an adapter or check is still running on that profile. Stop it, retry.
  A lock left by a crashed browser is cleared automatically.
- `--keep` keeps the file after import; `-` instead of a file name reads the export from stdin.

## What already works without logging in (checked 2026-10-18, 03:50 ET)

- **craigslist**: the real anonymous flow at `post.craigslist.org/c/ral` (Raleigh) > housing offered >
  rooms & shares > the posting-details form, every field filled (title, area, ZIP, description, rent,
  per month, private room, house, private bath, laundry, parking, furnished, available date). It stops
  there with `stage: details_form_filled` because continuing needs your account (or a contact email in
  `CHANNELS_CONTACT_EMAIL`). Nothing is created or published.
- **Roomies**: returns `LOGIN_REQUIRED` (Cloudflare "Just a moment..." check) with the login command.
- **PadSplit**: returns `LOGIN_REQUIRED` (redirect to the home page sign-in) with the login command.

The Roomies and PadSplit form selectors are unverified until your first logged-in run; the repair loop
(the operator model) fixes broken selectors on that run and logs each change in the selector file's
`changelog` and in `channels/repair/changelog.jsonl`.

## Email (read-only, replies are drafts)

The reader opens the mailbox read-only (nothing is marked read, moved or deleted) and only picks up
mail from platform domains (Roomies, Furnished Finder, Zillow/Trulia/HotPads, craigslist relays,
PadSplit, Facebook). It refuses to run until you confirm which inbox it is.

Put these in the repo `.env` (gitignored), with a Gmail **app password**, not your account password:

```bash
CHANNELS_IMAP_CONFIRMED=1
CHANNELS_IMAP_USER=you@gmail.com
CHANNELS_IMAP_PASSWORD=your-app-password
# CHANNELS_IMAP_HOST=imap.gmail.com     (default for gmail.com)
# CHANNELS_IMAP_FOLDER=INBOX
```

Or reuse a login that already exists in another env file, by variable name (values are never printed).
`~/rental-management/.env.production` has `GMAIL_USER` / `GMAIL_PASS`, and `.env.local` also has
`GMAIL_USER2` / `GMAIL_PASS2`; nothing reads them until you pick one:

```bash
CHANNELS_IMAP_CONFIRMED=1
CHANNELS_IMAP_ENV_FILE=~/rental-management/.env.production
CHANNELS_IMAP_USER_VAR=GMAIL_USER
CHANNELS_IMAP_PASSWORD_VAR=GMAIL_PASS
```

```bash
channels/.venv/bin/python -m channels.inbound email-check      # which settings are present (true/false only)
channels/.venv/bin/python -m channels.inbound email-poll       # last 14 days of lead emails -> threads
channels/.venv/bin/python -m channels.inbound threads          # thread ids, platform, message count
channels/.venv/bin/python -m channels.inbound drafts           # every reply the operator drafted, with its reason
```

## Showings calendar (Google)

Showings go on a Google calendar you choose, 8 AM-8 PM, no overlaps. The operator only ever creates events
titled `PROPOSED: Showing with <first name>`, never invites anyone, and writes nothing until you name the calendar:

1. In Google Calendar, open the calendar's **Settings and sharing > Share with specific people**, add the
   rental-management service account (`GOOGLE_SERVICE_ACCOUNT_EMAIL` in `~/rental-management/.env.production`)
   with **Make changes to events**.
2. Put the calendar's id (Settings > Integrate calendar > Calendar ID) in the repo `.env` as
   `CHANNELS_SHOWINGS_CALENDAR_ID=...`.

```bash
PYTHONPATH=tools channels/.venv/bin/python -m rentus_tools.live.calendar_adapter slots   # tomorrow's free slots, read-only
```

## SMS (drafts only)

There is no SMS reader and no sender. Record a text you received, and read the drafted replies:

```bash
channels/.venv/bin/python -m channels.inbound sms-add --phone "919-555-0101" --text "Is the room still available?"
channels/.venv/bin/python -m channels.inbound drafts --channel sms     # channels/.inbox/sms_outbox.jsonl
```

## Facebook Page (Graph API, no browser)

Uses `FACEBOOK_PAGE_ID` and `FACEBOOK_PAGE_ACCESS_TOKEN`, loaded from `~/rental-management/.env.production`
(override with `FB_ENV_FILE`). Values are never printed.

```bash
channels/.venv/bin/python -m channels.facebook_page check           # page name + id
channels/.venv/bin/python -m channels.facebook_page draft-post      # UNPUBLISHED photo post, prints its id
channels/.venv/bin/python -m channels.facebook_page conversations   # count only, no message content
```
