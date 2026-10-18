"""Write a tiny FAKE input set (10 invented threads) to data/twins/fixtures/input/, in the three
formats ingest.py reads, so the whole twins pipeline can be tested end to end without real data.

Every line below was invented for this fixture. Names are "Fake ..." / "Fixture Owner", phone
numbers are 555-01xx, addresses are "Example" streets and emails are @example.com. Nothing here
comes from a real conversation.

  3 iMazing CSVs   input/imazing/Messages - Fake Renter *.csv   (one is a non-rental chat, to test the filter)
  4 Facebook dirs  input/facebook/your_facebook_activity/messages/inbox/<thread>/message_1.json
                   (3 in the classic format with Facebook's latin-1 mojibake, 1 in the newer E2EE format)
  3 generic        input/generic/fake_threads.csv (1 thread) + fake_threads.jsonl (2 threads)

Owner name for the fixture: "Fixture Owner" (ingest.py --fixture uses it automatically).

Usage: data/twins/.venv/bin/python data/twins/make_fixture.py
"""
from __future__ import annotations

import csv
import json
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

HERE = Path(__file__).resolve().parent
OUT = HERE / "fixtures" / "input"
OWNER = "Fixture Owner"
TZ = ZoneInfo("America/New_York")

# (role, minutes after thread start, text). "O" = owner, "R" = renter.
THREADS = {
    # 1. EN, full gate answered in order, showing booked.
    "imazing_a": ("Fake Renter Ana", datetime(2025, 3, 3, 18, 5), [
        ("R", 0, "Hi! Saw your ad for the room off Example Rd, is it still available?"),
        ("O", 12, "Hi, yes it is. Are you ok with a one year lease?"),
        ("R", 20, "Yes a year is fine with me"),
        ("O", 22, "Great. When would you want to move in?"),
        ("R", 31, "April 1st ideally"),
        ("O", 33, "What's the best number to reach you?"),
        ("R", 40, "919-555-0142"),
        ("O", 41, "Thanks. What brings you to the area?"),
        ("R", 55, "I start a nursing job at the hospital in April"),
        ("O", 57, "Congrats! Will it be just you?"),
        ("R", 60, "Just me"),
        ("O", 62, "Want to come see it Thursday at 6?"),
        ("R", 70, "Thursday at 6 works, see you then"),
    ]),
    # 2. EN, vague move-in, price push, then ghosts after the owner answers.
    "imazing_b": ("Fake Renter Ben", datetime(2025, 5, 14, 9, 30), [
        ("R", 0, "hey is the room w private bath still up"),
        ("O", 40, "Hey, it is! When are you looking to move?"),
        ("R", 95, "sometime in june probably, not sure yet"),
        ("O", 97, "No problem. It's $750 a month with utilities included."),
        ("R", 130, "could you do 650? thats my max rn"),
        ("O", 180, "I can't go that low, but it's a great deal for a private bath. Want to see it this weekend?"),
    ]),
    # 3. Non-rental chat: must be dropped by the rental filter.
    "imazing_c": ("Fake Friend Cal", datetime(2025, 6, 1, 20, 0), [
        ("R", 0, "you watching the game tonight?"),
        ("O", 3, "Yeah, at my brother's place. You?"),
        ("R", 5, "same, go team lol"),
        ("O", 6, "haha see you saturday for the cookout"),
    ]),
    # 4. ES, full answers, applied (Facebook classic, mojibake).
    "fb_dani": ("Fake Renter Dani", datetime(2025, 7, 20, 11, 0), [
        ("R", 0, "Hola, ¿sigue disponible el cuarto?"),
        ("O", 15, "Hola, sí. ¿Te parece bien un contrato de un año?"),
        ("R", 25, "Sí, claro, un año está bien"),
        ("O", 26, "¿Para qué fecha te quieres mudar?"),
        ("R", 40, "El 15 de agosto"),
        ("O", 41, "¿Cuántas personas serían?"),
        ("R", 50, "Solo yo"),
        ("O", 51, "¿Y por qué te mudas?"),
        ("R", 70, "Empiezo la maestría en la universidad"),
        ("O", 72, "Perfecto. ¿Me pasas tu teléfono?"),
        ("R", 80, "Es el 984 555 0177"),
        ("O", 90, "Gracias. Te mando el enlace de la solicitud."),
        ("R", 300, "Listo, ya la llené. ¡Gracias!"),
    ]),
    # 5. EN then switches to ES, asks a shorter lease, then not now.
    "fb_eli": ("Fake Renter Eli", datetime(2025, 8, 2, 16, 45), [
        ("R", 0, "Hello, is the room near downtown open?"),
        ("O", 20, "Hi! Yes. Would a one year lease work for you?"),
        ("R", 33, "Could I do 4 months instead? I'm only here for a project"),
        ("O", 35, "The shortest I can do is 6 months."),
        ("R", 60, "Perdón, es más fácil en español. Seis meses es mucho para mí."),
        ("O", 62, "Entiendo. ¿Te aviso si cambia algo?"),
        ("R", 90, "Sí, quizás en enero vuelva a buscar. Gracias"),
    ]),
    # 6. EN hard no.
    "fb_fran": ("Fake Renter Fran", datetime(2025, 9, 9, 13, 10), [
        ("R", 0, "Is this still available? How much is the deposit?"),
        ("O", 30, "Yes! Deposit is one month's rent. When would you move in?"),
        ("R", 45, "Actually I found another place, please take me off your list"),
        ("O", 47, "No problem, good luck with the move!"),
    ]),
    # 7. EN, volunteers info out of order, asks about utilities, showing (Facebook E2EE format).
    "fb_gus": ("Fake Renter Gus", datetime(2025, 10, 5, 10, 20), [
        ("R", 0, "Hi, I'm moving for a job at the research park, it would be just me, I'd want to move in Nov 1. Are utilities included?"),
        ("O", 25, "Hi Gus, yes utilities are included. Are you good with a 12 month lease?"),
        ("R", 40, "yep 12 months works"),
        ("O", 41, "Great, and a good phone number for you?"),
        ("R", 50, "(336) 555-0119"),
        ("O", 52, "Could you come by Saturday at 11 to see it?"),
        ("R", 58, "Saturday 11 is perfect"),
    ]),
    # 8. ES vague, then ghosts after the owner asks the next question (generic CSV).
    "gen_hilda": ("Fake Renter Hilda", datetime(2025, 11, 12, 19, 0), [
        ("R", 0, "Buenas, me interesa la habitación"),
        ("O", 10, "¡Hola! ¿Para cuándo la necesitas?"),
        ("R", 25, "Pues a fines de mes o algo así"),
        ("O", 27, "Va. ¿Estarías bien con un contrato de un año?"),
    ]),
    # 9. EN small talk + lease with a sublet condition, applied (generic JSONL).
    "gen_ivy": ("Fake Renter Ivy", datetime(2026, 1, 8, 8, 15), [
        ("R", 0, "Good morning! Love the photos of the room 😍"),
        ("O", 30, "Thank you! Are you looking for a one year lease?"),
        ("R", 42, "Yes, as long as I can sublet for the summer when I'm away"),
        ("O", 45, "That can work. When would you move in?"),
        ("R", 60, "February 1"),
        ("O", 61, "Why are you moving?"),
        ("R", 75, "My current lease is ending"),
        ("O", 76, "How many people?"),
        ("R", 80, "just me"),
        ("O", 81, "And your number? fake.ivy@example.com is fine for the application link too"),
        ("R", 90, "704-555-0163, thanks!!"),
        ("O", 95, "Sent you the application."),
        ("R", 400, "Done 🙂"),
    ]),
    # 10. EN, occupants exception, partial phone then full, showing (generic JSONL).
    "gen_jules": ("Fake Renter Jules", datetime(2026, 2, 16, 14, 0), [
        ("R", 0, "Hi, is the room at 12 Example Ct still free? I'd need it March 15"),
        ("O", 20, "Hi, it is. How many people would be living there?"),
        ("R", 30, "Just me, my boyfriend would stay some weekends"),
        ("O", 31, "Ok. Are you fine with a one year lease?"),
        ("R", 45, "probably, depends on my job"),
        ("O", 47, "Understood. What's your phone number?"),
        ("R", 60, "555-0108, I'll send the full one later"),
        ("O", 61, "Thanks! Why are you moving?"),
        ("R", 80, "need a change honestly"),
        ("O", 82, "Fair enough. Can you see it Monday at 5?"),
        ("R", 90, "Monday at 5 works. Full number is 828-555-0108"),
    ]),
}


def msgs(key):
    name, start, turns = THREADS[key]
    start = start.replace(tzinfo=TZ)
    return name, [(OWNER if r == "O" else name, start + timedelta(minutes=m), t) for r, m, t in turns]


def write_imazing(key, fname):
    name, rows = msgs(key)
    path = OUT / "imazing" / fname
    path.parent.mkdir(parents=True, exist_ok=True)
    hdr = ["Chat Session", "Message Date", "Delivered Date", "Read Date", "Edited Date", "Deleted Date", "Service",
           "Type", "Sender ID", "Sender Name", "Status", "Replying to", "Subject", "Text", "Reactions",
           "Attachment", "Attachment type"]
    with open(path, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f)
        w.writerow(hdr)
        for sender, ts, text in rows:
            out = sender == OWNER
            w.writerow([name, ts.strftime("%Y-%m-%d %H:%M:%S"), "", "", "", "", "SMS",
                        "Outgoing" if out else "Incoming", "" if out else "+15555550100", "" if out else name,
                        "Delivered" if out else "Read", "", "", text, "", "", ""])
        # a system row that ingest must skip
        w.writerow([name, rows[-1][1].strftime("%Y-%m-%d %H:%M:%S"), "", "", "", "", "SMS", "Notification",
                    "", "", "", "", "", "", "", "", ""])


def mojibake(s: str) -> str:
    """What Facebook's export does: UTF-8 bytes written as latin-1 code points."""
    return s.encode("utf-8").decode("latin-1")


def write_fb_classic(key, folder):
    name, rows = msgs(key)
    d = OUT / "facebook" / "your_facebook_activity" / "messages" / "inbox" / folder
    d.mkdir(parents=True, exist_ok=True)
    messages = [{"sender_name": mojibake(s), "timestamp_ms": int(ts.timestamp() * 1000), "content": mojibake(t),
                 "is_geoblocked_for_viewer": False} for s, ts, t in rows]
    messages.append({"sender_name": name, "timestamp_ms": messages[-1]["timestamp_ms"] + 1000,
                     "photos": [{"uri": "messages/inbox/x/photos/fake.jpg"}]})  # no text: skipped
    messages.reverse()  # Facebook writes newest first
    obj = {"participants": [{"name": name}, {"name": OWNER}], "messages": messages, "title": name,
           "is_still_participant": True, "thread_path": f"inbox/{folder}"}
    (d / "message_1.json").write_text(json.dumps(obj, indent=2), encoding="utf-8")  # ensure_ascii, like Facebook


def write_fb_e2ee(key, folder):
    name, rows = msgs(key)
    d = OUT / "facebook" / "your_facebook_activity" / "messages" / "e2ee_cutover" / folder
    d.mkdir(parents=True, exist_ok=True)
    obj = {"participants": [OWNER, name], "threadName": name,
           "messages": [{"isUnsent": False, "media": [], "reactions": [], "senderName": s,
                         "text": t, "timestamp": int(ts.timestamp() * 1000), "type": "text"} for s, ts, t in rows]}
    (d / "message_1.json").write_text(json.dumps(obj, indent=2, ensure_ascii=False), encoding="utf-8")


def main():
    write_imazing("imazing_a", "Messages - Fake Renter Ana.csv")
    write_imazing("imazing_b", "Messages - Fake Renter Ben.csv")
    write_imazing("imazing_c", "Messages - Fake Friend Cal.csv")
    write_fb_classic("fb_dani", "fakerenterdani_1001")
    write_fb_classic("fb_eli", "fakerentereli_1002")
    write_fb_classic("fb_fran", "fakerenterfran_1003")
    write_fb_e2ee("fb_gus", "fakerentergus_1004")
    g = OUT / "generic"
    g.mkdir(parents=True, exist_ok=True)
    name, rows = msgs("gen_hilda")
    with open(g / "fake_threads.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["thread_id", "ts", "sender", "text", "channel"])
        for s, ts, t in rows:
            w.writerow(["fake-hilda", ts.isoformat(), s, t, "sms"])
    with open(g / "fake_threads.jsonl", "w", encoding="utf-8") as f:
        for key, tid in (("gen_ivy", "fake-ivy"), ("gen_jules", "fake-jules")):
            name, rows = msgs(key)
            for s, ts, t in rows:
                f.write(json.dumps({"thread_id": tid, "ts": int(ts.timestamp()), "sender": s, "text": t,
                                    "channel": "craigslist"}, ensure_ascii=False) + "\n")
    (OUT / "README.md").write_text(
        "# FAKE fixture input\n\nEvery thread here was invented by `data/twins/make_fixture.py` to test the twins "
        "pipeline. No real conversation, person, phone number or address. Regenerate with "
        "`data/twins/.venv/bin/python data/twins/make_fixture.py`.\n")
    print(f"wrote 10 fake threads under {OUT}")


if __name__ == "__main__":
    main()
