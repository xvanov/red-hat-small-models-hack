# Logging in to the real platforms (owner only, once per platform)

The browser adapters never type a password. Each platform gets its own saved browser profile in
`channels/.profiles/<platform>/` (gitignored). You log in by hand once; the adapters reuse that session.

From the repo root, run the line for each platform, log in in the window that opens, then **close the window**:

```bash
channels/.venv/bin/python -m channels.login marketplace   # Facebook (Marketplace)
channels/.venv/bin/python -m channels.login craigslist    # craigslist account
channels/.venv/bin/python -m channels.login roomies       # Roomies
channels/.venv/bin/python -m channels.login padsplit      # PadSplit host account
```

If a session expires, the adapter returns `LOGIN_REQUIRED` with that same command in its `hint`.

## Then try a real platform (stops before the final button)

```bash
channels/.venv/bin/python -m channels.publish craigslist --target live --listing my-listing.json
```

`my-listing.json` needs real photo paths in `"photos"`. The browser opens on your profile, fills the form,
takes a screenshot (`channels/screenshots/`), and stops with `status: ready_to_submit`. **You** click the
final Publish/Post button if you want it live. The adapter refuses `submit` on live targets.

The live selector files (`channels/adapters/selectors/live/*.json`) are unverified guesses written without
an account. The first run will likely repair several selectors through the operator model; each fix is
logged in that file's `changelog` and in `channels/repair/changelog.jsonl`.

## Facebook Page (Graph API, no browser)

Uses `FACEBOOK_PAGE_ID` and `FACEBOOK_PAGE_ACCESS_TOKEN`, loaded from `~/rental-management/.env.production`
(override with `FB_ENV_FILE`). Values are never printed.

```bash
channels/.venv/bin/python -m channels.facebook_page check           # page name + id
channels/.venv/bin/python -m channels.facebook_page draft-post      # UNPUBLISHED photo post, prints its id
channels/.venv/bin/python -m channels.facebook_page conversations   # count only, no message content
```
