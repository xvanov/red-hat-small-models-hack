"""Download a room's listing photos from the owner's Google Drive into a gitignored folder.

Usage (system python3 with Pillow + cryptography, or any env that has them):
  python3 channels/photos/fetch_drive.py --folder "3606 Appling" --out runs/photos/appling/_raw
  python3 channels/photos/fetch_drive.py --folder "3606 Appling" --list        # names only, no download

Auth: a Google service account (JWT bearer, scope drive.readonly). Credentials are read from env files,
never printed. Candidates, tried in order until one can see the folder:
  --env-file FILE (repeatable)  holding GOOGLE_SERVICE_ACCOUNT_EMAIL + GOOGLE_PRIVATE_KEY, or a JSON key
  blob in the variable named by --json-var (default GOOGLE_CALENDAR_CREDENTIALS).
A service account only sees files shared with it, so the owner shares the folder with its email.

Every downloaded image is re-encoded without metadata (EXIF, GPS, XMP) before it is written.
"""
from __future__ import annotations

import argparse
import base64
import io
import json
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

TOKEN_URL = "https://oauth2.googleapis.com/token"
API = "https://www.googleapis.com/drive/v3"
SCOPE = "https://www.googleapis.com/auth/drive.readonly"
FOLDER_MIME = "application/vnd.google-apps.folder"
DEFAULT_ENV_FILES = ["~/rental-management/.env.production", "~/rental-management/.env.local", ".env"]


def _b64(b: bytes) -> str:
    return base64.urlsafe_b64encode(b).rstrip(b"=").decode()


def read_env_file(path: str) -> dict:
    p = Path(path).expanduser()
    out: dict[str, str] = {}
    if not p.exists():
        return out
    for line in p.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        v = v.strip()
        if len(v) >= 2 and v[0] == v[-1] and v[0] in "\"'":
            v = v[1:-1]
        out[k.strip()] = v
    return out


def candidates(env_files: list[str], json_var: str) -> list[tuple[str, str, str]]:
    """(label, client_email, private_key) per usable credential; label never contains secrets."""
    out = []
    for f in env_files:
        env = read_env_file(f)
        if env.get(json_var):
            try:
                j = json.loads(env[json_var])
                out.append((f"{f}:{json_var}", j["client_email"], j["private_key"]))
            except Exception as e:  # noqa: BLE001
                print(f"[skip] {f}:{json_var} is not a service-account JSON ({type(e).__name__})", file=sys.stderr)
        if env.get("GOOGLE_SERVICE_ACCOUNT_EMAIL") and env.get("GOOGLE_PRIVATE_KEY"):
            out.append((f"{f}:GOOGLE_SERVICE_ACCOUNT_EMAIL", env["GOOGLE_SERVICE_ACCOUNT_EMAIL"],
                        env["GOOGLE_PRIVATE_KEY"].replace("\\n", "\n")))
    return out


def token(email: str, key_pem: str) -> str:
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import padding

    now = int(time.time())
    head = _b64(json.dumps({"alg": "RS256", "typ": "JWT"}).encode())
    claims = _b64(json.dumps({"iss": email, "scope": SCOPE, "aud": TOKEN_URL, "iat": now, "exp": now + 3600}).encode())
    key = serialization.load_pem_private_key(key_pem.encode(), password=None)
    sig = key.sign(f"{head}.{claims}".encode(), padding.PKCS1v15(), hashes.SHA256())
    body = urllib.parse.urlencode({"grant_type": "urn:ietf:params:oauth:grant-type:jwt-bearer",
                                   "assertion": f"{head}.{claims}.{_b64(sig)}"}).encode()
    req = urllib.request.Request(TOKEN_URL, data=body, method="POST",
                                 headers={"Content-Type": "application/x-www-form-urlencoded"})
    with urllib.request.urlopen(req, timeout=20) as r:
        return json.loads(r.read())["access_token"]


def api_get(tok: str, path: str, params: dict | None = None, raw: bool = False):
    url = API + path + ("?" + urllib.parse.urlencode(params) if params else "")
    req = urllib.request.Request(url, headers={"Authorization": f"Bearer {tok}"})
    with urllib.request.urlopen(req, timeout=60) as r:
        data = r.read()
    return data if raw else json.loads(data)


def list_files(tok: str, q: str) -> list[dict]:
    files, page = [], None
    while True:
        params = {"q": q, "fields": "nextPageToken,files(id,name,mimeType,size,parents)", "pageSize": 200,
                  "supportsAllDrives": "true", "includeItemsFromAllDrives": "true", "corpora": "allDrives"}
        if page:
            params["pageToken"] = page
        d = api_get(tok, "/files", params)
        files += d.get("files", [])
        page = d.get("nextPageToken")
        if not page:
            return files


def images_under(tok: str, folder_id: str, prefix: str = "", depth: int = 2) -> list[tuple[str, dict]]:
    out = []
    for f in list_files(tok, f"'{folder_id}' in parents and trashed=false"):
        if f["mimeType"] == FOLDER_MIME and depth > 0:
            out += images_under(tok, f["id"], prefix + f["name"] + "/", depth - 1)
        elif f["mimeType"].startswith("image/"):
            out.append((prefix + f["name"], f))
    return out


def strip_metadata(data: bytes) -> tuple[bytes, str]:
    """Re-encode pixels only (applies EXIF rotation first), so no EXIF/GPS/XMP survives."""
    from PIL import Image, ImageOps

    try:
        from pillow_heif import register_heif_opener  # optional, for iPhone HEIC
        register_heif_opener()
    except ImportError:
        pass
    im = ImageOps.exif_transpose(Image.open(io.BytesIO(data)))
    im = im.convert("RGB")
    if max(im.size) > 2400:
        im.thumbnail((2400, 2400))
    buf = io.BytesIO()
    im.save(buf, "JPEG", quality=88)
    return buf.getvalue(), ".jpg"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--folder", required=True, help="text the Drive folder name contains, e.g. '3606 Appling'")
    ap.add_argument("--out", default="runs/photos/appling/_raw")
    ap.add_argument("--env-file", action="append", help="env file(s) with service-account credentials")
    ap.add_argument("--json-var", default="GOOGLE_CALENDAR_CREDENTIALS")
    ap.add_argument("--only", default="pictures/",
                    help="download only images under this subfolder path (default 'pictures/'; the folder also "
                         "holds tenant documents, which must never be downloaded)")
    ap.add_argument("--list", action="store_true", help="only list the images found")
    a = ap.parse_args()

    creds = candidates(a.env_file or DEFAULT_ENV_FILES, a.json_var)
    if not creds:
        print("no service-account credentials found in the env files", file=sys.stderr)
        return 2
    name_q = a.folder.replace("'", "\\'")
    for label, email, key in creds:
        try:
            tok = token(email, key)
            folders = list_files(tok, f"mimeType='{FOLDER_MIME}' and name contains '{name_q}' and trashed=false")
        except urllib.error.HTTPError as e:
            print(f"[{label}] {e.code}: {e.read()[:300].decode(errors='replace')}", file=sys.stderr)
            continue
        print(f"[{label}] service account {email}: {len(folders)} matching folder(s)")
        if not folders:
            continue
        out = Path(a.out)
        for fo in folders:
            imgs = images_under(tok, fo["id"])
            print(f"  folder '{fo['name']}': {len(imgs)} image(s), {sum(r.startswith(a.only) for r, _ in imgs)} under {a.only!r}")
            for rel, f in imgs:
                if not rel.startswith(a.only):
                    continue  # tenant IDs/leases etc. live elsewhere in the folder: never listed by name or fetched
                print(f"    {rel}  {f.get('size', '?')} bytes")
                if a.list:
                    continue
                data = api_get(tok, f"/files/{f['id']}", {"alt": "media", "supportsAllDrives": "true"}, raw=True)
                try:
                    clean, ext = strip_metadata(data)
                except Exception as e:  # noqa: BLE001
                    print(f"      [skip] could not decode ({type(e).__name__})", file=sys.stderr)
                    continue
                dest = out / (Path(rel.replace("/", "__")).stem + ext)
                dest.parent.mkdir(parents=True, exist_ok=True)
                dest.write_bytes(clean)
        return 0
    print("no credential could see a folder whose name contains " + repr(a.folder) +
          "; share it (Viewer) with one of the service accounts above", file=sys.stderr)
    return 1


if __name__ == "__main__":
    sys.exit(main())
