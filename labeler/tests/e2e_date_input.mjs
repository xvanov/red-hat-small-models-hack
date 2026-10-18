// Playwright check of the move-in date input (month names + day + year, date in words). Run like e2e_hydration.mjs, on a COPY of the labels.
const { chromium } = await import(process.env.PLAYWRIGHT);
import fs from 'fs';
const [base, dir] = process.argv.slice(2);
let fails = 0; const ok = (c, m) => { console.log((c ? 'PASS ' : 'FAIL ') + m); if (!c) fails++; };
const b = await chromium.launch(); const p = await b.newPage({ viewport: { width: 390, height: 844 } });
const log = () => fs.readFileSync(dir + '/labels_log.fixture.jsonl', 'utf8').trim().split('\n').map(JSON.parse);
// item 9 (twin-a3b427d581-04, today 2026-12-16), saved 2026-12-09: hydrates into the three inputs
await p.goto(base + '/#i=9'); await p.waitForSelector('.msgcard');
ok(await p.locator('#mi_month').inputValue() === '12' && await p.locator('#mi_day').inputValue() === '9' && await p.locator('#mi_year').inputValue() === '2026', 'saved date hydrates month/day/year');
ok((await p.locator('#mi_words').textContent()).includes('December 9, 2026') && (await p.locator('#mi_words').getAttribute('class')).includes('bad'), 'words shown, flagged before conversation date');
ok((await p.locator('.drub').textContent()).includes('No year in the message?'), 'rubric line shown');
// item 22 (twin-7dcb5f6f51-04, today 2026-10-28) via a fresh unsaved flow: clear to vague then exact
await p.goto(base + '/#i=10'); await p.waitForSelector('.msgcard');   // a3b427d581-06, no date saved, today 2026-12-16
await p.click('button[data-f=move_in][data-v=exact]');
ok(await p.locator('#mi_year').inputValue() === '2026', 'year prefilled from conversation date');
await p.selectOption('#mi_month', '1'); await p.fill('#mi_day', '9');
ok(await p.locator('#mi_year').inputValue() === '2027', 'Jan 9 after Dec 16 -> next occurrence year 2027');
ok((await p.locator('#mi_words').textContent()).trim() === 'January 9, 2027', 'words: January 9, 2027');
await p.fill('#mi_day', '31'); await p.selectOption('#mi_month', '2');
ok((await p.locator('#mi_words').textContent()).includes('not a real date'), 'Feb 31 rejected');
await p.fill('#mi_day', '9'); await p.selectOption('#mi_month', '1');
await p.fill('#mi_year', '2028'); ok((await p.locator('#mi_words').textContent()).trim() === 'January 9, 2028', 'year editable');
await p.click('#save'); await p.waitForTimeout(400);
const r = log().filter(x => x.id === 'twin-a3b427d581-06').at(-1);
ok(r.output.move_in.date === '2028-01-09' && r.output.move_in.status === 'answered', 'saved 2028-01-09');
await p.click('#back'); await p.waitForTimeout(400);
ok((await p.locator('#mi_words').textContent()).trim() === 'January 9, 2028', 're-opened item shows saved date in words');
console.log('overflow', await p.evaluate(() => document.documentElement.scrollWidth - innerWidth));
await p.screenshot({ path: dir + '/../date.png' });
await b.close(); console.log(fails ? fails + ' FAILED' : 'ALL PASS');
