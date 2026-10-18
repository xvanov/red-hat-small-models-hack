"""Email channel: parsers on fake fixture emails, the store, drafts, and a fake read-only IMAP server."""
from pathlib import Path

import pytest

from channels.inbound import email_channel
from channels.inbound.email_parse import parse_email
from channels.inbound.imap_reader import ImapConfig, ImapNotConfigured, config_status, fetch_leads
from channels.inbound.store import ChannelStore

FIX = Path(__file__).parent / "fixtures" / "email"


def raw(name: str) -> bytes:
    return (FIX / name).read_bytes()


@pytest.fixture
def store(tmp_path):
    return ChannelStore(tmp_path / "inbox")


@pytest.mark.parametrize("name,platform,renter,snippet,via", [
    ("roomies_message.eml", "roomies", "Jordan", "still available for November 1st", "platform"),
    ("furnished_finder_lead.eml", "furnished_finder", "Casey Morgan", "travel nurse", "email"),
    ("zillow_contact.eml", "zillow", "Riley Chen", "6 month lease", "email"),
    ("craigslist_reply.eml", "craigslist", "Sam P", "move in mid November", "relay"),
    ("direct_spanish.eml", "direct", "Maria Lopez", "Sigue disponible", "email"),
])
def test_lead_emails_parse(name, platform, renter, snippet, via):
    lead = parse_email(raw(name))
    assert lead is not None
    assert lead.platform == platform and lead.renter_name == renter and lead.reply_via == via
    assert snippet in lead.text
    # notification chrome never leaks into the renter's message
    for chrome in ("Reply on Roomies", "Reply directly", "To reply", "original craigslist post", "You're receiving"):
        assert chrome not in lead.text


def test_structured_fields():
    ff = parse_email(raw("furnished_finder_lead.eml"))
    assert ff.renter_email == "casey.traveler@example.com" and ff.renter_phone == "(919) 555-0142"
    assert ff.move_in == "11/01/2026" and ff.listing_ref == "Appling Way Room" and ff.extra["stay_length"] == "13 weeks"
    assert "parking" in ff.text  # a labeled message keeps its second line
    z = parse_email(raw("zillow_contact.eml"))
    assert z.reply_to.endswith("@convo.zillow.com") and z.move_in == "2026-12-01" and z.renter_phone == "919-555-0177"


@pytest.mark.parametrize("name", ["newsletter.eml", "password_reset.eml"])
def test_non_leads_are_skipped(name):
    assert parse_email(raw(name)) is None


def test_ingest_is_idempotent_and_detects_language(store):
    files = sorted(FIX.glob("*.eml"))
    first = email_channel.ingest_files(store, files)
    assert first["leads"] == 5 and first["skipped"] == 2 and first["new_messages"] == 5
    again = email_channel.ingest_files(store, files)
    assert again["new_messages"] == 0 and len(store.list_threads("email")) == 5
    es = [t for t in store.list_threads("email") if t["source_platform"] == "direct"][0]
    assert es["language"] == "es"
    assert all(t["language"] == "en" for t in store.list_threads("email") if t["source_platform"] != "direct")


def test_reply_is_a_draft_with_a_reason(store):
    t, _ = email_channel.ingest_raw(store, raw("roomies_message.eml"))
    d = email_channel.save_reply_draft(store, t["thread_id"], "Yes, it is available November 1.")
    assert d["status"] == "draft_saved" and d["sent"] is False
    assert "reply inside Roomies" in d["reason"]
    t2, _ = email_channel.ingest_raw(store, raw("furnished_finder_lead.eml"))
    d2 = email_channel.save_reply_draft(store, t2["thread_id"], "It is furnished, with parking.")
    assert d2["to"] == "casey.traveler@example.com" and d2["subject"].startswith("Re: ")
    assert [x["draft_id"] for x in store.drafts("email")] == ["email-draft-1", "email-draft-2"]


# ---------------------------------------------------------------- IMAP (fake server, no network)

class FakeImap:
    def __init__(self, messages):
        self.messages = messages
        self.calls = []

    def login(self, user, pw):
        self.calls.append(("login",))
        return "OK", [b""]

    def select(self, folder, readonly=False):
        self.calls.append(("select", folder, readonly))
        return "OK", [str(len(self.messages)).encode()]

    def search(self, charset, *crit):
        self.calls.append(("search",) + crit)
        return "OK", [" ".join(str(i + 1) for i in range(len(self.messages))).encode()]

    def fetch(self, mid, what):
        self.calls.append(("fetch", mid, what))
        return "OK", [(b"1 (BODY[] {n}", self.messages[int(mid) - 1]), b")"]

    def store(self, *a):  # pragma: no cover - must never be called
        raise AssertionError("the reader must not change flags")

    def logout(self):
        self.calls.append(("logout",))


ENV = {"CHANNELS_IMAP_CONFIRMED": "1", "CHANNELS_IMAP_USER": "owner@example.com",
       "CHANNELS_IMAP_PASSWORD": "not-a-real-password", "CHANNELS_IMAP_HOST": "imap.example.com"}


def test_imap_fetch_is_read_only_and_parses():
    msgs = [raw(n) for n in ("roomies_message.eml", "newsletter.eml", "zillow_contact.eml")]
    fake = FakeImap(msgs)
    leads, stats = fetch_leads(ImapConfig.from_env(ENV), imap_factory=lambda h, p: fake)
    assert [lead.platform for lead in leads] == ["roomies", "zillow"]
    assert stats == {"scanned": 3, "leads": 2, "skipped": 1}
    sel = [c for c in fake.calls if c[0] == "select"][0]
    assert sel[2] is True  # READONLY
    assert all(c[2] == "(BODY.PEEK[])" for c in fake.calls if c[0] == "fetch")
    assert fake.calls[-1] == ("logout",)


def test_imap_refuses_without_owner_confirmation():
    with pytest.raises(ImapNotConfigured):
        ImapConfig.from_env({k: v for k, v in ENV.items() if k != "CHANNELS_IMAP_CONFIRMED"})


def test_imap_aliases_and_no_values_exposed(tmp_path):
    f = tmp_path / "owner.env"
    f.write_text('GMAIL_USER="someone@gmail.com"\nGMAIL_PASS=abcd efgh\n')
    env = {"CHANNELS_IMAP_CONFIRMED": "1", "CHANNELS_IMAP_ENV_FILE": str(f),
           "CHANNELS_IMAP_USER_VAR": "GMAIL_USER", "CHANNELS_IMAP_PASSWORD_VAR": "GMAIL_PASS"}
    cfg = ImapConfig.from_env(env)
    assert cfg.host == "imap.gmail.com" and cfg.user == "someone@gmail.com"
    assert "someone" not in repr(cfg) and "abcd" not in repr(cfg)
    st = config_status(env)
    assert st["user_set"] and st["password_set"] and st["user_var"] == "GMAIL_USER"
    assert "someone" not in str(st) and "abcd" not in str(st)


def test_env_file_strips_trailing_comments(tmp_path):
    from channels.inbound.imap_reader import _read_env_file
    f = tmp_path / "e.env"
    f.write_text('A="abcd efgh ijkl mnop"  # app password, regenerated\nB=plain # note\nC=\'x#y\'\nD="q"\n')
    env = _read_env_file(f)
    assert env == {"A": "abcd efgh ijkl mnop", "B": "plain", "C": "x#y", "D": "q"}
