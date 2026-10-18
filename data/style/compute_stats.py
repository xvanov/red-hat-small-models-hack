"""Aggregate style statistics of the owner's own messages (lane 5).

Reads the PRIVATE anonymized export locally and prints ONLY aggregate numbers (counts, medians,
shares, a histogram, and generic greeting words). No message text is written out.

    python3 -I data/style/compute_stats.py ~/rentus-private-data/raw/anonymized-2026-10-18/ > data/style/owner_style_stats.json

Owner messages are rows with sender == "me" in tenants/ and contractors/ (landlords/ is ignored).
Tapback reactions and attachment-only rows are dropped. Language is a crude keyword heuristic
(Cyrillic -> ru; Spanish function words outnumbering English ones -> es), so treat language
shares as estimates within roughly +-30%.
"""
import json, re, sys, statistics as st, collections
BASE = sys.argv[1].rstrip("/") + "/"
TAP = re.compile(r'^(Liked|Loved|Laughed at|Emphasized|Disliked|Questioned|Le gustó|Le encantó|Me gusta|Me encanta|Reacted|Removed)\b|^\S{1,3} (to|a) “')
EMOJI = re.compile("[\U0001F300-\U0001FAFF\U00002600-\U000027BF\U0001F000-\U0001F2FF]")
CYR = re.compile('[Ѐ-ӿ]')
ES = re.compile(r"\b(hola|gracias|el|la|los|las|que|para|por|usted|cuarto|renta|mes|está|estoy|buenos|buenas|sí|pero|tiene|tengo|puede|pago)\b", re.I)
EN = re.compile(r"\b(the|is|you|and|to|room|rent|for|it|thanks|please|will|can)\b", re.I)
def lang(t):
    if CYR.search(t): return "ru"
    e=len(ES.findall(t)); n=len(EN.findall(t))
    if e>=2 and e>n: return "es"
    return "en"
def sents(t):
    parts=[p for p in re.split(r'(?<=[.!?])\s+|\n+', t.strip()) if re.search(r'\w',p)]
    return max(1,len(parts))
def pct(xs,p):
    xs=sorted(xs); return xs[min(len(xs)-1,int(p/100*len(xs)))]
rows=[]
convfolder={}
for ds in ["tenants","contractors"]:
    for line in open(BASE+ds+"/messages.jsonl"):
        r=json.loads(line); r["ds"]=ds; rows.append(r)
# folder: prospects/tenants by conv type isn't in jsonl; use type
out={}
groups=collections.defaultdict(list)
prev_lang={}  # last counterpart lang per conv
conv_counter_lang=collections.defaultdict(collections.Counter)
for r in rows:
    t=(r.get("text") or "").strip()
    if not t or TAP.search(t): continue
    if r["sender"]!="me":
        conv_counter_lang[r["conv"]][lang(t)]+=1; continue
    key = "contractors" if r["ds"]=="contractors" else ("tenants_group" if r["type"]=="group" else "tenants_1to1")
    groups[key].append(r); groups["all"].append(r)
res={}
for k,ms in groups.items():
    texts=[m["text"].strip() for m in ms]
    words=[len(t.split()) for t in texts]; chars=[len(t) for t in texts]
    sc=[sents(t) for t in texts]
    q=[t.count("?") for t in texts]
    first=[t.split()[0].lower().strip(",.!") if t.split() else "" for t in texts]
    greet=collections.Counter(f for f in first if f in ("hello","hi","hey","hola","buenos","buenas","good","привет","здравствуйте","dear"))
    gname=sum(1 for t in texts if re.match(r'(?i)(hello|hi|hey|hola)[ ,]+[A-Z][a-z]+',t))
    ngreet=sum(greet.values())
    thanks=sum(1 for t in texts if re.search(r'(?i)\b(thank|thanks|gracias|спасибо)',t))
    sorry=sum(1 for t in texts if re.search(r'(?i)\b(sorry|apolog|disculp|perd[oó]n|извин)',t))
    L=collections.Counter(lang(t) for t in texts)
    acks=sum(1 for t in texts if re.fullmatch(r'(?i)(ok|okay|ok\.|sounds good|got it|received|great|perfect|thank you|thanks|cool|sure|yes|no problem)[.!]?',t))
    res[k]=dict(n=len(texts),
      words_median=st.median(words),words_p25=pct(words,25),words_p75=pct(words,75),words_p90=pct(words,90),
      chars_median=st.median(chars),
      sentences_median=st.median(sc),share_over_2_sentences=round(sum(s>2 for s in sc)/len(sc),3),
      share_with_question=round(sum(x>0 for x in q)/len(q),3),share_multi_question=round(sum(x>1 for x in q)/len(q),3),
      share_ending_on_question_given_question=round(sum(1 for t,x in zip(texts,q) if x>0 and t.rstrip().endswith("?"))/max(1,sum(x>0 for x in q)),3),
      share_emoji=round(sum(bool(EMOJI.search(t)) for t in texts)/len(texts),4),
      share_exclamation=round(sum("!" in t for t in texts)/len(texts),3),
      share_long_dash=round(sum(("—" in t or "–" in t) for t in texts)/len(texts),4),
      share_hyphen_as_dash=round(sum(" - " in t for t in texts)/len(texts),3),
      share_line_breaks=round(sum("\n" in t for t in texts)/len(texts),3),
      share_greeting=round(ngreet/len(texts),3),greeting_words=dict(greet.most_common(8)),
      share_greetings_with_name=round(gname/max(1,ngreet),3),
      share_thanks=round(thanks/len(texts),3),share_apology=round(sorry/len(texts),3),
      share_short_ack=round(acks/len(texts),3),
      language=dict(L),
      share_all_lowercase_start=round(sum(1 for t in texts if t[:1].islower())/len(texts),3),
      share_no_final_punct=round(sum(1 for t in texts if t[-1:].isalnum())/len(texts),3),
    )
# language mirroring: owner msgs in conv where counterpart mostly es
mir=collections.Counter()
for m in groups["all"]:
    c=conv_counter_lang[m["conv"]]
    if not c: continue
    dom=c.most_common(1)[0][0]
    mir[(dom,lang(m["text"]))]+=1
res["mirroring_owner_lang_by_counterpart_dominant_lang"]={f"{a}->{b}":v for (a,b),v in mir.items()}
# consecutive owner messages (burst)
bursts=[];cur=0;last=None
for r in rows:
    t=(r.get("text") or "").strip()
    if r["conv"]!=last: 
        if cur: bursts.append(cur)
        cur=0; last=r["conv"]
    if r["sender"]=="me": cur+=1
    else:
        if cur: bursts.append(cur)
        cur=0
if cur: bursts.append(cur)
res["owner_turns"]=dict(n=len(bursts),share_2plus=round(sum(b>=2 for b in bursts)/len(bursts),3),share_3plus=round(sum(b>=3 for b in bursts)/len(bursts),3))
# hour of day
hrs=collections.Counter(int(m["ts"][11:13]) for m in groups["all"])
res["owner_hour_histogram_local"]={h:hrs[h] for h in range(24)}

# greeting breakdown: what follows the greeting word
gb=collections.Counter()
G=re.compile(r'(?i)(hello|hi|hey|hola|good morning|good afternoon|good evening|buenos d[ií]as|buenas tardes|привет)\b[ ,!.]*(\S*)')
for m in groups["all"]:
    g=G.match(m["text"].strip())
    if not g: continue
    w=g.group(2).strip(",.!:").lower()
    if w in ("all","everyone","everybody","guys","team","todos","chicos","folks","housemates","there"): gb["followed_by_group_word"]+=1
    elif w=="": gb["bare"]+=1
    elif g.group(2)[:1].isupper(): gb["followed_by_capitalized_word_likely_name"]+=1
    else: gb["followed_by_other_text"]+=1
res["greeting_breakdown"]=dict(gb)
u=sum(1 for m in groups["tenants_1to1"]+groups["tenants_group"] if re.search(r'(?i)utilit(y|ies)\b.*\$\d',m["text"]))
res["utility_notice_messages_with_amount"]=u
res["_meta"]={"source":"private anonymized export, tenants/ + contractors/, owner rows only","generated":"2026-10-18","note":"aggregates only; regex estimates"}
json.dump(res,sys.stdout,indent=1,ensure_ascii=False)
