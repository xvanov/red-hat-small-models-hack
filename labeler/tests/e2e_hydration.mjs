// Playwright check of the labeler: hydration on Back / browser back-forward / reload, stale-tab refusal,
// append-only undo, and the /audit Keep/Change flow. Run ONLY against a server on a COPY of the labels:
//   mkdir /tmp/lab && cp labeler/out/owner_labels.fixture.jsonl labeler/out/history.fixture.jsonl /tmp/lab/
//   LABELER_OUT=/tmp/lab labeler/.venv/bin/python labeler/server.py --source fixture --port 8191 &
//   PLAYWRIGHT=/path/to/node_modules/playwright/index.mjs node labeler/tests/e2e_hydration.mjs http://127.0.0.1:8191 /tmp/lab
// (written against the 29-row fixture sample as labeled on 2026-10-18)
const { chromium } = await import(process.env.PLAYWRIGHT || 'playwright');
import fs from 'fs';
const base = process.argv[2], dir = process.argv[3];
let fails = 0; const ok = (c, m) => { console.log((c ? 'PASS ' : 'FAIL ') + m); if (!c) fails++; };
const b = await chromium.launch(); const ctx = await b.newContext(); const p = await ctx.newPage();
const st = async (pg = p) => ({ item: Number((await pg.locator('.today').textContent()).match(/item (\d+)/)[1]),
  lang: await pg.locator('button[data-f=language].on').getAttribute('data-v'),
  lease: await pg.locator('button[data-f=lease].on').getAttribute('data-v'),
  intents: await pg.locator('button[data-f=intents].on').evaluateAll(es => es.map(e => e.dataset.v).sort().join(',')) });
const wait = (ms = 300) => p.waitForTimeout(ms);
const log = () => fs.readFileSync(dir + '/labels_log.fixture.jsonl', 'utf8').trim().split('\n').map(JSON.parse);

await p.goto(base + '/#i=4'); await p.waitForSelector('.msgcard');
let s = await st(); ok(s.item === 4 && s.lang === 'es', `deep link #i=4 hydrates language es (${JSON.stringify(s)})`);
await p.click('#back'); await wait(); s = await st();
ok(s.item === 3 && s.lang === 'es' && s.lease === 'no' && s.intents === 'question,shorter_lease', `Back -> item 3 shows saved es/no/intents (${JSON.stringify(s)})`);
const n0 = log().length;
await p.click('#save'); await wait(); s = await st(); ok(s.item === 4 && s.lang === 'es', 'Save & next -> item 4 still es');
ok(log().length === n0 + 1, 'save appended one log line (append-only)');
await p.click('#back'); await wait(); s = await st(); ok(s.item === 3 && s.lang === 'es', 're-opened item 3 keeps es after re-save');
ok((await p.locator('#saved').textContent()).includes('2 versions'), 'item 3 shows 2 versions kept');
// browser history
await p.goBack(); await wait(); s = await st(); ok(s.item === 4 && s.lang === 'es', `browser Back -> item 4, es (${JSON.stringify(s)})`);
await p.goBack(); await wait(); s = await st(); ok(s.item === 3 && s.lang === 'es', `browser Back -> item 3, es`);
await p.goForward(); await wait(); s = await st(); ok(s.item === 4 && s.lang === 'es', `browser Forward -> item 4, es`);
// leave the page and come back (reload or bfcache)
await p.goto('about:blank'); await p.goBack(); await p.waitForSelector('.msgcard'); await wait();
s = await st(); ok(s.item === 4 && s.lang === 'es', `away and Back -> item 4, es (${JSON.stringify(s)})`);
// stale second tab must not overwrite a newer label
const p2 = await ctx.newPage(); await p2.goto(base + '/#i=3'); await p2.waitForSelector('.msgcard');
await p.goto(base + '/#i=3'); await p.waitForSelector('.msgcard'); await wait();
await p.click('button[data-f=language][data-v=en]'); await p.click('#save'); await wait();
const n1 = log().length;
await p2.click('#save'); await p2.waitForTimeout(400);
ok((await p2.locator('#err').textContent()).includes('saved since'), 'stale tab save refused (409)');
ok(log().length === n1, 'refused save appended nothing');
await p2.waitForTimeout(1600); s = await st(p2); ok(s.item === 3 && s.lang === 'en', `stale tab reloads latest label (en) (${JSON.stringify(s)})`);
// undo is append-only: item 3 falls back to its previous version (es)
await p.click('#undo'); await wait(); s = await st(); ok(s.item === 3 && s.lang === 'es', `Undo -> item 3 back to previous save es (${JSON.stringify(s)})`);
const L = log(); ok(L.at(-1).event === 'undo' && L.filter(r => r.id === 'twin-ead3cc19fb-04' && r.event === 'save').length === 3, 'undo appended; all 3 saves of item 3 kept');
const snap = fs.readFileSync(dir + '/owner_labels.fixture.jsonl', 'utf8').trim().split('\n').map(JSON.parse);
ok(snap.length === 29 && snap.find(r => r.id === 'twin-ead3cc19fb-04').output.language === 'es', 'snapshot = latest per item (29 rows, item 3 es)');
// a never-saved field set: every field hydrated for an item with phone + date
await p.goto(base + '/#i=12'); await p.waitForSelector('.msgcard'); await wait();
ok(await p.locator('#mi_date').inputValue() === '2027-01-09' && (await p.locator('#ph_val').inputValue()) === '704 555 0142', 'date and phone hydrated on item 12');
// audit page
await p.goto(base + '/audit'); await p.waitForSelector('.item');
const nItems = await p.locator('.item').count(); ok(nItems >= 3, `audit lists ${nItems} items`);
const card = p.locator('.item', { hasText: '9 de enero' }).filter({ hasText: 'move_in_date_mismatch' }).first();
await card.locator('button.change').first().click(); await wait(600);
const A = log().filter(r => r.id === 'twin-a3b427d581-04' && r.event === 'save').at(-1);
ok(A.save_reason === 'audit' && A.ui.move_in_date === '2027-01-09' && A.output.move_in.date === '2027-01-09' && A.audit_rule === 'move_in_date_mismatch', 'Change appended an audit label with 2027-01-09');
ok(log().filter(r => r.id === 'twin-a3b427d581-04' && r.event === 'save').length === 2, 'the original label is kept in the log');
const before = await p.locator('button[data-a=keep]').count();
await p.locator('button[data-a=keep]').first().click(); await wait(600);
ok(await p.locator('button[data-a=keep]').count() === before - 1, 'Keep records a decision and hides the flag');
const dec = fs.readFileSync(dir + '/audit_decisions.fixture.jsonl', 'utf8').trim().split('\n').map(JSON.parse);
ok(dec.length === 2 && dec.some(d => d.action === 'keep') && dec.some(d => d.action === 'change'), 'decisions file has keep + change');
// edit-in-labeler link carries reason audit
await p.goto(base + '/#i=1&audit=question_without_question'); await p.waitForSelector('.msgcard'); await wait();
await p.click('button[data-f=intents][data-v=question]'); await p.click('#save'); await wait();
const E = log().filter(r => r.id === 'twin-ead3cc19fb-00' && r.event === 'save').at(-1);
ok(E.save_reason === 'audit' && E.audit_rule === 'question_without_question' && E.ui.intents.length === 0, 'labeler save from audit link has reason audit');
await b.close();
console.log(fails ? `${fails} FAILED` : 'ALL PASS'); process.exit(fails ? 1 : 0);
