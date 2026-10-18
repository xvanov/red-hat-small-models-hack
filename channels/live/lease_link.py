"""The lease-signing link for an approved applicant (live-only tool send_lease_link).

rental-management (the owner's app at app.rentus.homes) makes a real signing link only through operator-session
routes (POST /api/leases/generate, then POST /api/leases/sign with deliver="link", which returns
<app>/sign/<token>). No API key can call them, and they write real Lease and SigningToken rows, so this daemon does
not create one. Instead:

  LIVE_LEASE_LINK_URL   a real signing link the owner made in his dashboard (Leases > send for signature, "link"
                        delivery), e.g. https://app.rentus.homes/sign/<token>. Used as is when set.
  otherwise             the app's public application page, <NEXT_PUBLIC_APP_URL>/apply (https://app.rentus.homes/apply),
                        read from ~/rental-management/.env.production. Opening it starts a draft application in the
                        app (the renter's own action); this daemon creates no record.
"""
from __future__ import annotations

from . import config

DEFAULT_APP = "https://app.rentus.homes"


def app_url() -> str:
    e = config._file_env(config.env("LIVE_EMAIL_ENV") or config.HOME / "rental-management" / ".env.production")
    u = (e.get("NEXT_PUBLIC_APP_URL") or "").strip().rstrip("/")
    return u if u.startswith("https://") else DEFAULT_APP


def get_link(thread: dict | None = None) -> str:
    u = (config.env("LIVE_LEASE_LINK_URL") or "").strip()
    if u.startswith("https://"):
        return u
    return app_url() + "/apply"


def link_kind() -> str:
    return "signing" if (config.env("LIVE_LEASE_LINK_URL") or "").startswith("https://") else "apply_page"
