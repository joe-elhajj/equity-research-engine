// Offline synthetic FIXTURE only. All HTTP is intercepted; no model/vendor requests.
const fs = require('fs'), path = require('path'), assert = require('node:assert/strict');
const {chromium} = require('playwright');
const root = path.resolve(__dirname, '..');
const out = process.env.RANKS_SCREENSHOT_DIR || '/tmp/scoped-ranks-screenshots';
fs.mkdirSync(out,{recursive:true});
const fields = ['composite','cat_reinvestment','cat_quality','cat_resilience','cat_discipline','cat_optionality'];
const rows = Array.from({length:120}, (_,i)=>({ticker:['MSFT','ANET','LULU','AAPL'][i] || 'T'+String(i).padStart(3,'0'),
 name:['Microsoft','Arista Networks','Lululemon','Apple'][i] || 'Reference company '+i,
 scores:Object.fromEntries(fields.map((f,j)=>[f, (j===1 && i<10) || (j===4 && i>=110) ? null : ((i*(j+3))%100)]))}));
const distributions = Object.fromEntries(fields.map(f=>[f,rows.map(r=>r.scores[f]).filter(v=>v!==null).sort((a,b)=>a-b)]));
function percentile(value,f) {const d=distributions[f];return 100*(d.filter(v=>v<value).length+d.filter(v=>v===value).length/2)/d.length;}
function leaderboard(selected,order,all,asof,expires) {
 const entries=rows.filter(r=>selected.every(f=>r.scores[f]!==null)).map(r=>{
  const p=Object.fromEntries(selected.map(f=>[f,percentile(r.scores[f],f)]));
  return {...r, score:selected.length===1?r.scores[selected[0]]:null,
   percentile:selected.length===1?Number(p[selected[0]].toFixed(1)):null,
   percentiles:Object.fromEntries(selected.map(f=>[f,Number(p[f].toFixed(1))])),
   average_selected_percentiles:Number((Object.values(p).reduce((a,b)=>a+b,0)/selected.length).toFixed(1)),
   key:selected.length===1?r.scores[selected[0]]:Object.values(p).reduce((a,b)=>a+b,0)/selected.length};
 });
 entries.sort((a,b)=>(order==='asc'?a.key-b.key:b.key-a.key)||a.ticker.localeCompare(b.ticker));
 return {fields:selected,as_of:asof,expires_at:expires,version:'2026-Q3 · FIXTURE',snapshot_date:'2026-07-02',scored:120,total:120,
  intersection_count:entries.length,peer_counts:Object.fromEntries(selected.map(f=>[f,distributions[f].length])),rows:entries.slice(0,all?120:25)};
}
(async()=>{
 const browser=await chromium.launch({headless:true,channel:'chrome'});
 const checks=[];
 try {for(const [name,width,height] of [['desktop',1440,1050],['mobile',390,844]]) {
  const ctx=await browser.newContext({viewport:{width,height},deviceScaleFactor:1,reducedMotion:'reduce'});
  const page=await ctx.newPage(), errors=[], requests=[]; let mode='fresh', slow=false;
  page.setDefaultTimeout(15000);
  page.on('pageerror',e=>errors.push(e.message));
  const now=Date.now(),asof=new Date(now-86400000).toISOString(),expires=new Date(now+89*86400000).toISOString();
  await ctx.route('**/*',async route=>{
   const req=route.request(),url=new URL(req.url());requests.push([req.method(),url.pathname,url.search]);
   const json=x=>route.fulfill({contentType:'application/json',body:JSON.stringify(x)});
   if(url.hostname!=='ranks.fixture') {errors.push('External request '+url.hostname);return route.abort();}
   if(url.pathname==='/api/watchlist')return json({tickers:['NVO','QNT','SPCX','SECZ'],etfs:['VOO']});
   if(url.pathname==='/api/screen')return json({job_id:'fixture'});
   if(url.pathname==='/api/screen/status/fixture')return json({status:'done',result:{
    equities:[{ticker:'NVO',name:'Novo Nordisk — FIXTURE',composite:84.83931600204866,completeness:.8,
     ...Object.fromEntries(fields.slice(1).map((f,i)=>[f,70+i*5])),is_stable:true,stability_delta:1,flag:'',
     universe_reference_snapshot_date:'2026-07-02',universe_reference_member:false,universe_reference_version:'2026-Q3 · FIXTURE',
     universe_rank_as_of:asof,universe_rank_expires_at:mode==='stale'?'2020-01-01':expires,
     universe_ranks:mode==='missing'?{}:Object.fromEntries(fields.map(f=>[f,{percentile:98.5,peers:389}]))}],
    etfs:[{ticker:'VOO',name:'Fund — FIXTURE',expense_ratio:.0003,aum:1000000,overlap_with_screen:0,flag:'fund: N-PORT observed'}],
    excluded:[{ticker:'QNT',name:'Quantinuum — FIXTURE',flag:'Recent IPO filing; first annual report not yet available',limited_analysis:true},
     {ticker:'SPCX',name:'Space company — FIXTURE',flag:'Recent IPO filing; first annual report not yet available',limited_analysis:true},
     {ticker:'SECZ',name:'Securitize — FIXTURE',flag:'Financial issuer; operating-company durability model is not comparable.',limited_analysis:true},
     {ticker:'ERR',name:'Unknown — FIXTURE',flag:'error:secret raw exception must not appear'}],
    universe:'2026-Q3 · FIXTURE',generated_at:'FIXTURE: synthetic browser data'}});
   if(url.pathname==='/api/universe/leaderboard'){
    if(mode==='missing')return json({available:false});
    const selected=(url.searchParams.get('fields')||'composite').split(',');
    const result=leaderboard(selected,url.searchParams.get('order'),url.searchParams.get('all_names')==='true',asof,mode==='stale'?'2020-01-01':expires);
    if(slow && selected.includes('cat_quality'))await new Promise(r=>setTimeout(r,350));
    return json(result);
   }
   if(/^\/api\/analyze\/[^/]+\/fragment$/.test(url.pathname))return route.fulfill({contentType:'text/html',body:
    '<div class="report-fragment"><p>FIXTURE analysis — no vendor/model calls</p><details class="report-section"><summary>Financial position</summary><p>Offline synthetic evidence.</p></details></div>'});
   if(url.pathname.startsWith('/api/')){errors.push('Unexpected API '+req.method()+' '+url.pathname);return json({});}
   const f=url.pathname==='/'?'index.html':url.pathname.slice(1);
   if(!['index.html','app.js','styles.css'].includes(f))return route.fulfill({status:404,body:''});
   return route.fulfill({contentType:f.endsWith('.js')?'application/javascript':f.endsWith('.css')?'text/css':'text/html',body:fs.readFileSync(path.join(root,'frontend',f))});
  });
  const noOverflow=async()=>assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth),true);
  const shot=async label=>{await noOverflow();await page.screenshot({path:path.join(out,'FIXTURE-'+name+'-'+label+'.png'),fullPage:true});};
  const select=async selected=>{
   await page.locator('#leaderboard-fields').evaluate((el,selected)=>{
    el.querySelectorAll('input').forEach(i=>i.checked=selected.includes(i.value));
    el.dispatchEvent(new Event('change',{bubbles:true}));
   },selected);
  };
  const loaded=async()=>page.waitForFunction(()=>document.querySelector('#leaderboard-status').textContent.startsWith('Showing'));
  await page.goto('http://ranks.fixture/');
  await page.locator('#equities-table tbody tr').first().waitFor();
  assert.equal(requests.filter(r=>r[1]==='/api/universe/leaderboard').length,0);
  assert.equal(await page.locator('.universe-rank').count(),6);
  for(const badge of await page.locator('.universe-rank').all()){
   assert.equal(await badge.textContent(),'S&P P98.5');
   assert((await badge.getAttribute('title')).includes('not in this reference index'));
   assert((await badge.getAttribute('title')).includes('dated') || (await badge.getAttribute('title')).includes('Dated'));
  }
  assert(!(await page.locator('#excluded-table').innerText()).includes('secret raw exception'));
  await shot('watchlist');
  await page.getByRole('tab',{name:'S&P rankings'}).click();await loaded();
  assert.equal(await page.locator('#watchlist-panel').isVisible(),false);
  for(const field of fields){
   await select([field]);await loaded();
   const expected=leaderboard([field],'desc',false,asof,expires);
   assert.equal(await page.locator('#leaderboard-body tr').count(),25);
   assert((await page.locator('#leaderboard-body tr').first().innerText()).includes(expected.rows[0].ticker));
   checks.push(name+': '+field+' single-field order');
  }
  await select(['composite']);await loaded();await shot('rankings');
  await page.getByLabel('Total durability',{exact:true}).uncheck();
  await page.getByText('Select at least one field to rank by.',{exact:true}).waitFor();
  assert.equal(await page.locator('#leaderboard-body tr').count(),0);
  await page.getByLabel('Reinvestment',{exact:true}).check();
  await page.getByLabel('Discipline',{exact:true}).check();await loaded();
  assert((await page.locator('#leaderboard-coverage').textContent()).includes('Eligible intersection 100'));
  assert((await page.locator('#leaderboard-statistic').textContent()).includes('NOT a fresh S&P percentile'));
  await page.getByRole('button',{name:'Show all eligible names'}).click();await loaded();
  assert.equal(await page.locator('#leaderboard-body tr').count(),100);
  await page.selectOption('#leaderboard-order','asc');await loaded();
  const expected=leaderboard(['cat_reinvestment','cat_discipline'],'asc',true,asof,expires);
  assert((await page.locator('#leaderboard-body tr').first().innerText()).includes(expected.rows[0].ticker));
  assert.equal(await page.locator('#leaderboard-head th').first().textContent(),'Order');
  // Screenshot top of all/bottom mode, not a 100-row tall artifact.
  await noOverflow();await page.screenshot({path:path.join(out,'FIXTURE-'+name+'-multi-bottom.png')});
  const hash=await page.evaluate(()=>location.hash);
  await page.reload();await loaded();
  assert.equal(await page.evaluate(()=>location.hash),hash);
  assert.equal(await page.locator('#leaderboard-body tr').count(),100);
  await page.locator('#leaderboard-body button').first().click();
  await page.getByText('FIXTURE analysis — no vendor/model calls').waitFor();
  assert((await page.locator('#company-view-back').textContent()).includes('S&P rankings'));
  await page.goBack();await page.waitForFunction(()=>document.querySelector('#company-view').classList.contains('hidden'));
  assert.equal(await page.evaluate(()=>location.hash),hash);
  assert.equal(await page.locator('#leaderboard-body tr').count(),100);
  await page.goForward();await page.getByText('FIXTURE analysis — no vendor/model calls').waitFor();
  await page.locator('#company-view-back').click();
  await page.waitForFunction(()=>document.querySelector('#company-view').classList.contains('hidden'));
  await page.getByRole('button',{name:'Show top 25'}).click();await loaded();
  assert.equal(await page.locator('#leaderboard-body tr').count(),25);
  await shot('multi-top25-low');
  if(name==='mobile'){
   await page.locator('#leaderboard-results .scroll').evaluate(el=>el.scrollLeft=el.scrollWidth);
   await page.locator('#leaderboard-results').scrollIntoViewIfNeeded();
   await page.screenshot({path:path.join(out,'FIXTURE-mobile-multi-values.png')});
   await page.locator('#leaderboard-results .scroll').evaluate(el=>el.scrollLeft=0);
  }
  slow=true; await select(['cat_quality']);await select(['cat_discipline']);await loaded();
  await page.waitForTimeout(450); // Deliberately deliver obsolete fixture response last.
  assert((await page.locator('#leaderboard-coverage').textContent()).includes('Peers: Discipline'));
  slow=false;
  await page.getByRole('tab',{name:'Watchlist',exact:true}).click();
  await page.reload();await page.locator('#equities-table tbody tr').first().waitFor();
  assert.equal(await page.locator('#watchlist-tab').getAttribute('aria-selected'),'true');
  await page.goBack();await loaded(); // back restores rankings and filters
  checks.push(name+': lazy load, URL/refresh/back/forward, zero selection, AND intersection, all/top25, low/high, race rejection, no overflow');
  for(const bad of ['missing','stale']){
   console.log(name+': checking '+bad);
   mode=bad;await page.reload();
   await page.getByText(/Reference unavailable or expired/).waitFor();
   await page.locator('#equities-table tbody tr').first().waitFor({state:'attached'});
   assert.equal(await page.locator('.universe-rank').count(),0);
   assert.equal(await page.locator('#leaderboard-body tr').count(),0);
   await shot(bad);
  }
  // Expire a loaded cache without navigation: interval removes rows and badges.
  mode='fresh';await page.reload();await loaded();
  await page.locator('#universe-leaderboard').evaluate(el=>el.dataset.expiresAt='2020-01-01');
  await page.locator('.universe-rank').evaluateAll(es=>es.forEach(e=>e.dataset.expiresAt='2020-01-01'));
  await page.getByText(/Reference unavailable or expired/).waitFor();
  assert.equal(await page.locator('.universe-rank').count(),0);
  assert.equal(requests.filter(([method])=>method!=='GET').length,0);
  assert.deepEqual(errors,[]);
  checks.push(name+': absent/stale/live-expiry hidden; no unexpected POST/model requests');
  await ctx.close();
 }}finally{await browser.close();}
 fs.writeFileSync(path.join(out,'browser-checks.json'),JSON.stringify(checks,null,2));
 console.log(JSON.stringify(checks,null,2));
})().catch(e=>{console.error(e);process.exit(1)});
