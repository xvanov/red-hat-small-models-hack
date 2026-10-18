# channels/photos: room photos from the owner's Google Drive

`fetch_drive.py` downloads a room's listing photos from the owner's Drive folder into a gitignored folder
under `runs/`, with all metadata (EXIF, GPS, XMP) removed by re-encoding the pixels. Photos are never committed.

## Auth

A Google service account, the same kind the showings calendar uses (`tools/rentus_tools/live/calendar_adapter.py`):
JWT bearer grant with scope `drive.readonly`. The script reads `GOOGLE_SERVICE_ACCOUNT_EMAIL` + `GOOGLE_PRIVATE_KEY`
(or a JSON key in `GOOGLE_CALENDAR_CREDENTIALS`) from the env files given with `--env-file` (default: the owner's
existing `~/rental-management/.env.production`, `.env.local`, then the repo `.env`). Values are never printed.
A service account sees only what is shared with it; the owner's property folder is already shared with it.

## Run

HEIC (iPhone) decoding needs `pillow-heif`, which is not in the project venv, so install it to a scratch dir:

```bash
uv pip install --target /tmp/heif pillow-heif==0.18.0
PYTHONPATH=/tmp/heif python3 channels/photos/fetch_drive.py --folder "3606 Appling" --list
PYTHONPATH=/tmp/heif python3 channels/photos/fetch_drive.py --folder "3606 Appling" --out runs/photos/appling_raw
```

Only images under `pictures/` are listed or downloaded (`--only`). The property folder also holds a `tenants/`
folder with ID documents and leases: those are never fetched.

## Choosing the listing photos (done by hand, Oct 18)

The listed room (`R_APPLING`, D20) is the master bedroom (`pictures/room1`): it has the private bathroom, and the
D20 pilot post's lead photo is the same room. Copied into `runs/photos/appling/`, numbered so the first four are
the ones the Facebook path posts:

| file | source |
|---|---|
| 01_bedroom.jpg | room1/IMG_0853 |
| 02_bedroom_french_doors.jpg | room1/IMG_0854 |
| 03_private_bath.jpg | room1/IMG_0855 |
| 04_private_bath_shower.jpg | room1/IMG_0856 |
| 05_walk_in_closet.jpg | room1/IMG_0857 |

Left out: the exterior shot (`common/IMG_0871`: house, driveway, a parked truck; same reason as D20), the other
bedrooms (rooms 3, 4, 5: not this listing), the `OLD/` set (older duplicates of this room and close-ups of wall
damage and outlets). Common areas (living room, kitchen, foyer) are in `runs/photos/appling_common/` but not in
the listing folder, because the room record says shared spaces are not owner-confirmed; add them only if the
owner confirms.

## Wiring

`console/live_world.py` reads `CONSOLE_ROOM_PHOTO_DIR` (else `CHANNELS_PHOTO_DIR`), an absolute directory of
`.jpg/.jpeg/.png/.webp` files (top level only), and puts their names on the room record; the channel adapter
resolves those names against the same directory. Set, before starting the console:

```
CONSOLE_ROOM_PHOTO_DIR=/home/k/red-hat-small-models-hack/runs/photos/appling
```
