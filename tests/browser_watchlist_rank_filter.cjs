// Synthetic FIXTURE regression only; real-data review screenshots are separate.
const fs=require('fs'),path=require('path'),assert=require('node:assert/strict');
const {chromium}=require('playwright');
const root=path.resolve(__dirname,'..'),out=process.env.WATCHLIST_SCREENSHOT_DIR||'/tmp/watchlist-filter-fixture';
const fields=['composite','cat_reinvestment','cat_quality','cat_resilience','cat_discipline','cat_optionality'];
const peers=Array.from({length:120},(_,i)=>i*100/119);
const pct=v=>100*(peers.filter(x=>x<v).length+peers.filter(x=>x===v).length/2)/peers.length;
(async()=>{fs.mkdirSync(out,{recursive:true});const browser=await chromium.launch({headless:true,channel:'chrome'});const checks=[];
try{for(const [device,width] of [['desktop',1280],['mobile',390]]){
 const ctx=await browser.newContext({viewport:{width,height:1000},reducedMotion:'reduce'}),page=await ctx.newPage();
 let mode='done',slow=false,scoreCalls=0,removed=false,added=false,refreshes=0,allowRefresh=false,resumeRunning=false;const unexpected=[],errors=[];
 page.on('pageerror',e=>errors.push(e.message));
 const asof=new Date(Date.now()-86400000).toISOString(),expiry=new Date(Date.now()+86400000).toISOString();
 const rows=['NVO','ASML',...Array.from({length:30},(_,i)=>'T'+String(i).padStart(3,'0')),'PART'].map((t,i)=>({ticker:t,name:t+' FIXTURE',completeness:.8,
  ...Object.fromEntries(fields.map((f,j)=>[f,t==='PART'&&j===4?null:99-i-j/10])),reference_member:t.startsWith('T')}));
 const screen=()=>({equities:rows.filter(r=>!removed||r.ticker!=='NVO'),etfs:[],excluded:[],generated_at:asof});
 function result(u){
  if(mode==='stale')return {available:false};
  const selected=(u.searchParams.get('fields')||'composite').split(','),watch=u.searchParams.get('watchlist_only')==='true';
  let eligible=rows.filter(r=>(!removed||r.ticker!=='NVO')&&selected.every(f=>Number.isFinite(r[f])));
  if(added)eligible.push({...rows[0],ticker:'ADDED',name:'ADDED FIXTURE',reference_member:false});
  let ranked=eligible.map(r=>{const p=Object.fromEntries(selected.map(f=>[f,pct(r[f])]));const avg=Object.values(p).reduce((a,b)=>a+b,0)/selected.length;
   return {...r,scores:Object.fromEntries(selected.map(f=>[f,r[f]])),percentiles:p,score:r[selected[0]],percentile:p[selected[0]],average_selected_percentiles:avg,key:selected.length===1?r[selected[0]]:avg};});
  ranked.sort((a,b)=>(u.searchParams.get('order')==='asc'?a.key-b.key:b.key-a.key)||a.ticker.localeCompare(b.ticker));
  if(mode!=='done')ranked=[];
  const n=ranked.length;
  return {as_of:asof,expires_at:expiry,snapshot_date:'2026-07-02',version:'FIXTURE',scored:120,total:120,
   peer_counts:Object.fromEntries(selected.map(f=>[f,120])),intersection_count:n,rows:ranked.slice(0,u.searchParams.get('all_names')==='true'?n:25),
   ...(watch?{watchlist_only:true,screen_state:mode,screen_generated_at:asof,watchlist_equity_count:35+(added?1:0)-(removed?1:0),fund_count:1,
    omitted:{no_current_score:1,not_scored:1,incomplete_scores:selected.includes('cat_discipline')?1:0}}:{})};
 }
 await ctx.route('**/*',async route=>{const req=route.request(),u=new URL(req.url());const json=x=>route.fulfill({contentType:'application/json',body:JSON.stringify(x)});
  if(u.hostname!=='filter.fixture'){unexpected.push(u.href);return route.abort();}
  if(u.pathname==='/api/watchlist')return json({tickers:allowRefresh?['NVO']:[],etfs:[]}); // initial OFF view does not need a screen
  if(u.pathname==='/api/screen/latest')return json({status:mode,result:mode==='done'?screen():null,...(resumeRunning&&mode==='running'?{job_id:'fixture'}:{})});
  if(u.pathname==='/api/screen'){scoreCalls++;refreshes++;mode='running';return json({job_id:'fixture'});}
  if(u.pathname==='/api/screen/status/fixture'){mode='done';added=true;return json({status:'done',result:screen()});}
  if(u.pathname==='/api/universe/leaderboard'){
   const payload=result(u);if(slow&&u.searchParams.get('fields')==='cat_quality')await new Promise(r=>setTimeout(r,300));return json(payload);
  }
  if(/^\/api\/analyze\/.+\/fragment$/.test(u.pathname))return route.fulfill({contentType:'text/html',body:'<div class="report-fragment"><p>FIXTURE analysis</p></div>'});
  if(req.method()!=='GET'||u.pathname.startsWith('/api/')){unexpected.push(req.method()+' '+u.pathname);return route.abort();}
  const f=u.pathname==='/'?'index.html':u.pathname.slice(1);
  if(!['index.html','styles.css','app.js'].includes(f)){unexpected.push(f);return route.abort();}
  return route.fulfill({body:fs.readFileSync(path.join(root,'frontend',f)),contentType:f.endsWith('.js')?'application/javascript':f.endsWith('.css')?'text/css':'text/html'});
 });
 const loaded=()=>page.waitForFunction(()=>document.querySelector('#leaderboard-status').textContent.startsWith('Showing'));
 const select=async names=>{await page.locator('#leaderboard-fields').evaluate((el,names)=>{el.querySelectorAll('input').forEach(i=>i.checked=names.includes(i.value));el.dispatchEvent(new Event('change',{bubbles:true}));},names);};
 await page.goto('http://filter.fixture/#tab=rankings');await loaded();assert.equal(await page.getByLabel('My watchlist only').isChecked(),false);
 await page.getByLabel('My watchlist only').check();await loaded();assert.equal(scoreCalls,0);
 assert((await page.locator('#leaderboard-body tr').first().innerText()).includes('NVO'));
 assert.equal(await page.locator('#leaderboard-body tr').count(),25);
 for(const ticker of ['NVO','ASML'])assert((await page.locator('#leaderboard-body tr').filter({hasText:ticker}).innerText()).includes('not in this reference index'));
 assert((await page.locator('#leaderboard-body tr').filter({hasText:'T000'}).innerText()).includes('In this reference index'));
 assert((await page.locator('#leaderboard-coverage').textContent()).includes('Overall reference coverage 120/120'));
 await page.reload();await loaded();assert(await page.getByLabel('My watchlist only').isChecked());assert.equal(scoreCalls,0);
 await select(['cat_reinvestment','cat_discipline']);await loaded();
 assert((await page.locator('#leaderboard-watchlist-count').innerText()).includes('Eligible 32/35'));
 assert((await page.locator('#leaderboard-statistic').innerText()).includes('NOT a fresh S&P percentile'));
 await page.getByRole('button',{name:'Show all eligible names'}).click();await loaded();assert.equal(await page.locator('#leaderboard-body tr').count(),32);
 await page.selectOption('#leaderboard-order','asc');await loaded();assert((await page.locator('#leaderboard-body tr').first().innerText()).includes('T029'));
 const hash=await page.evaluate(()=>location.hash);
 await page.locator('#leaderboard-body button').first().click();await page.getByText('FIXTURE analysis',{exact:true}).waitFor();
 await page.goBack();await loaded();assert.equal(await page.evaluate(()=>location.hash),hash);
 await page.goForward();await page.getByText('FIXTURE analysis',{exact:true}).waitFor();await page.locator('#company-view-back').click();await loaded();
 await page.getByRole('button',{name:'Show top 25'}).click();await loaded();assert.equal(await page.locator('#leaderboard-body tr').count(),25);
 await select([]);await page.getByText('Select at least one field to rank by.',{exact:true}).waitFor();assert.equal(await page.locator('#leaderboard-body tr').count(),0);
 slow=true;await select(['cat_quality']);await select(['cat_discipline']);await loaded();await page.waitForTimeout(350);assert((await page.locator('#leaderboard-coverage').innerText()).includes('Discipline 120'));slow=false;
 removed=true;await page.getByRole('tab',{name:'Watchlist',exact:true}).click();await page.getByRole('tab',{name:'S&P rankings'}).click();await loaded();assert(!(await page.locator('#leaderboard-body').innerText()).includes('NVO'));
 assert.equal(scoreCalls,0); // toggles, history and membership rereads never score
 for(mode of ['not_run','error','running','stale']){
  await page.reload();await page.waitForFunction(()=>!document.querySelector('#leaderboard-status').textContent.startsWith('Loading'));
  assert.equal(await page.locator('#leaderboard-body tr').count(),0);
  if(mode==='running')assert(await page.locator('#leaderboard-refresh').isDisabled());
  if(mode==='not_run')await page.screenshot({path:path.join(out,'FIXTURE-'+device+'-no-screen.png'),fullPage:true});
 }
 mode='not_run';await page.reload();await page.locator('#leaderboard-refresh').waitFor();allowRefresh=true;await page.locator('#leaderboard-refresh').click();await loaded();await page.selectOption('#leaderboard-order','desc');await loaded();assert.equal(scoreCalls,1);assert.equal(refreshes,1);
 assert((await page.locator('#leaderboard-body').innerText()).includes('ADDED'));
 mode='running';resumeRunning=true;await page.reload();await loaded();assert.equal(scoreCalls,1); // resume polling an existing job only
 await page.getByLabel('My watchlist only').uncheck();await loaded();assert.equal(await page.locator('.leaderboard-membership').count(),0);assert.equal(scoreCalls,1);
 await page.getByLabel('My watchlist only').check();await loaded();
 assert(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth));
 await page.locator('#leaderboard-results .scroll').evaluate(el=>el.scrollLeft=el.scrollWidth);
 assert(await page.locator('#leaderboard-results .scroll').evaluate(el=>el.scrollLeft+el.clientWidth>=el.scrollWidth-1));
 await page.screenshot({path:path.join(out,'FIXTURE-'+device+'-filter.png'),fullPage:true});
 assert.deepEqual(unexpected,[]);assert.deepEqual(errors,[]);
 checks.push(device+': OFF default, outside/in-index labels, AND fields, all/top25, high/low, URL refresh/history/drilldown, zero selection, races, membership/screen refresh, empty/stale states, mobile scroll, no implicit scoring/mutations/model calls');
 await ctx.close();
}}finally{await browser.close();}console.log(checks.join('\n'));})().catch(e=>{console.error(e);process.exit(1)});
