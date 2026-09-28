const fs = require('fs');
const assert = require('node:assert/strict');
const {chromium} = require('playwright');
const root = require('path').resolve(__dirname, '..');
const out = process.env.RANKS_SCREENSHOT_DIR || '/tmp/ranks-screenshots';
fs.mkdirSync(out,{recursive:true});
const fields = ['composite','cat_reinvestment','cat_quality','cat_resilience','cat_discipline','cat_optionality'];
(async()=>{
 const browser = await chromium.launch({headless:true,channel:"chrome"});
 const checks=[];
 for (const [name,width,height] of [['desktop',1440,1000],['mobile',390,844]]) {
  const ctx=await browser.newContext({viewport:{width,height},deviceScaleFactor:1,reducedMotion:"reduce"});
  const page=await ctx.newPage(); const errors=[]; const requests=[]; let mode='fresh';
  page.on('pageerror',e=>errors.push(e.message));
  const fixtureNow=Date.now();
  const asof=new Date(fixtureNow-86400000).toISOString(), expires=new Date(fixtureNow+89*86400000).toISOString();
  await ctx.route('**/*', async route=>{
   const req=route.request(), url=new URL(req.url()); requests.push([req.method(),url.pathname]);
   const json=x=>route.fulfill({contentType:'application/json',body:JSON.stringify(x)});
   if(url.hostname!=='ranks.fixture') return route.abort();
   if(url.pathname==='/api/watchlist') return json({tickers:['AAPL'],etfs:[]});
   if(url.pathname==='/api/screen') return json({job_id:'fixture',status:'running'});
   if(url.pathname==='/api/screen/status/fixture') {
    const row={ticker:'AAPL',name:'Apple Inc. — fixture',composite:82.5,completeness:1,is_stable:true,stability_delta:1,flag:'',config_hash:'fixture',universe_version:'2026-Q3',provenance_notes:[],durability_gaps:[],universe_rank_as_of:mode==='stale'? '2020-01-01T00:00:00Z':asof,universe_rank_expires_at:mode==='stale'?'2020-04-01T00:00:00Z':expires,universe_ranks:mode==='missing'?{}:Object.fromEntries(fields.map(f=>[f,{percentile:91.2,peers:380}]))};
    fields.slice(1).forEach((f,i)=>row[f]=70+i*5);
    return json({status:'done',result:{equities:[row],etfs:[],excluded:[],universe:'2026-Q3',config_hash:'fixture',generated_at:'Fixture data'}});
   }
   if(url.pathname==='/api/universe/leaderboard') {
    if(mode==='missing') return json({available:false});
    const field=url.searchParams.get('field');
    return json({field,as_of:mode==='stale'?'2020-01-01T00:00:00Z':asof,expires_at:mode==='stale'?'2020-04-01T00:00:00Z':expires,version:'2026-Q3 · FIXTURE',peers:380,scored:395,total:503,rows:[{ticker:'MSFT',name:'Microsoft — fixture',score:90-fields.indexOf(field),percentile:99.1},{ticker:'AAPL',name:'Apple — fixture',score:82.5,percentile:91.2},{ticker:'COST',name:'Costco — fixture',score:81,percentile:90}]});
   }
   if(url.pathname==='/api/analyze/MSFT/fragment') return route.fulfill({contentType:'text/html',body:'<div class="report-fragment"><h2>Microsoft — fixture analysis</h2><section class="report-section"><h3>Financial position</h3><p>Offline fixture. No market, SEC or paid requests.</p></section></div>'});
   if(url.pathname.startsWith('/api/')) {errors.push('Unexpected API '+req.method()+' '+url.pathname);return json({});}
   const path=url.pathname==='/'?'/index.html':url.pathname;
   if(!['/index.html','/app.js','/styles.css'].includes(path)) return route.fulfill({status:404,body:''});
   return route.fulfill({contentType:path.endsWith('.js')?'application/javascript':path.endsWith('.css')?'text/css':'text/html',body:fs.readFileSync(root+'/frontend'+path)});
  });
  await page.goto('http://ranks.fixture/');
  await page.locator('#equities-table tbody tr').first().waitFor();
  assert.equal(await page.locator('.universe-rank').count(),6);
  for(const field of fields) {
   await page.selectOption('#leaderboard-field',field);
   await page.waitForFunction(()=>!document.querySelector('#universe-leaderboard').classList.contains('hidden'));
   await page.waitForFunction(score=>document.querySelector('#leaderboard-body tr td:nth-child(3)').textContent===score,(90-fields.indexOf(field)).toFixed(1));
   checks.push(name+': '+field+' switched');
  }
  await page.selectOption('#leaderboard-field','composite');
  await page.waitForFunction(()=>document.querySelector('#leaderboard-body tr td:nth-child(3)').textContent==='90.0');
  await page.screenshot({path:out+'/ranks-'+name+'.png',fullPage:true});
  await page.locator('#leaderboard-body tr td:nth-child(3)').first().click();
  await page.getByText('Microsoft — fixture analysis').waitFor();
  await page.screenshot({path:out+'/ranks-'+name+'-analysis.png',fullPage:true});
  await page.locator('#company-view-back').click();
  assert.equal(await page.locator('#company-view').evaluate(e=>e.classList.contains('hidden')),true);
  assert.equal(requests.filter(([method])=>method!=='GET').length,0);
  checks.push(name+': analysis click/back, no watchlist mutation or paid calls');
  for(const missing of ['missing','stale']) {
   mode=missing; await page.reload();
   await page.locator('#equities-table tbody tr').first().waitFor();
   assert.equal(await page.locator('#universe-leaderboard').evaluate(e=>e.classList.contains('hidden')),true);
   assert.equal(await page.locator('.universe-rank').count(),0);
   await page.screenshot({path:out+'/ranks-'+name+'-'+mode+'.png',fullPage:true});
   checks.push(name+': '+mode+' leaderboard and badges hidden');
  }
  assert.deepEqual(errors,[]);
  assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth),true);
  await ctx.close();
 }
 await browser.close();
 fs.writeFileSync(out+'/ranks-browser-checks.json',JSON.stringify(checks,null,2));
 console.log(JSON.stringify(checks,null,2));
})().catch(e=>{console.error(e);process.exit(1)});
