// Offline layout FIXTURE. No live SEC/market data, mutations or model requests.
// LAYOUT_BASELINE_CSS captures a before image without changing the checkout.
const fs = require('fs'), path = require('path'), assert = require('node:assert/strict');
const {chromium} = require('playwright');
const root = path.resolve(__dirname, '..');
const out = process.env.LAYOUT_SCREENSHOT_DIR || '/tmp/dashboard-layout-screenshots';
const baseline = process.env.LAYOUT_BASELINE_CSS;
const fields = ['composite','cat_reinvestment','cat_quality','cat_resilience','cat_discipline','cat_optionality'];
(async () => {
 fs.mkdirSync(out, {recursive:true});
 const browser = await chromium.launch({channel:'chrome', headless:true});
 const results = [];
 try {
  for (const width of [1280,1366,1440,1024,768,390]) {
   const ctx = await browser.newContext({viewport:{width,height:1000}, reducedMotion:'reduce'});
   const page = await ctx.newPage(), unexpected = [], errors = [];
   page.on('pageerror', e => errors.push(e.message));
   const asof = new Date(Date.now()-86400000).toISOString(), expires = new Date(Date.now()+86400000).toISOString();
   const equities = ['NVO','MSFT','LONG','ZERO'].map((ticker,i) => ({ticker,
    name:['Novo Nordisk — FIXTURE','Microsoft — FIXTURE','Long company name for layout checks — FIXTURE','Zero and missing values — FIXTURE'][i],
    ...Object.fromEntries(fields.map((f,j)=>[f,i===3?(j===2?null:0):100-i*7-j])),
    expectations_gap_band_status:i===1?'COMPLETE':i===2?'PARTIAL':null,expectations_gap_fragile:'FRAGILE',
    implied_growth_note:i===2?'Fixture bracket limit':null,gap_bracket_bound:i===2?'upper':null,
    completeness:.9,is_stable:true,stability_delta:1,flag:'',
    implied_fcf_growth:i===3?null:.123,delivered_fcf_growth:i===3?0:-.234,expectations_gap:i===3?null:i===1?-.234:.357,
    universe_reference_member:i!==0,universe_reference_snapshot_date:'2026-07-02',universe_reference_version:'FIXTURE',
    universe_rank_as_of:asof,universe_rank_expires_at:expires,
    universe_ranks:Object.fromEntries(fields.map(f=>[f,{percentile:i===0?98.5:100,peers:389}]))
   }));
   await ctx.route('**/*', async route => {
    const req=route.request(), u=new URL(req.url());
    const json=x=>route.fulfill({contentType:'application/json',body:JSON.stringify(x)});
    if(u.hostname!=='layout.fixture' || req.method()!=='GET') {unexpected.push(req.method()+' '+u.href);return route.abort();}
    if(u.pathname==='/api/watchlist')return json({tickers:equities.map(r=>r.ticker),etfs:[]});
    if(u.pathname==='/api/screen')return json({job_id:'fixture'});
    if(u.pathname==='/api/screen/status/fixture')return json({status:'done',result:{equities,etfs:[],excluded:[],universe:'FIXTURE',generated_at:'FIXTURE — synthetic layout data'}});
    if(u.pathname==='/api/universe/leaderboard')return json({available:false});
    const file=u.pathname==='/'?'index.html':u.pathname.slice(1);
    if(!['index.html','styles.css','app.js'].includes(file)){unexpected.push(u.pathname);return route.abort();}
    return route.fulfill({contentType:file.endsWith('.css')?'text/css':file.endsWith('.js')?'application/javascript':'text/html',body:fs.readFileSync(file==='styles.css'&&baseline?baseline:path.join(root,'frontend',file))});
   });
   await page.goto('http://layout.fixture/');
   await page.locator('#equities-table tbody tr').first().waitFor();
   const measure=()=>page.evaluate(()=>{
    const rect=e=>{const r=e.getBoundingClientRect();return {left:r.left,right:r.right,top:r.top,bottom:r.bottom,width:r.width,height:r.height};};
    const table=document.querySelector('#equities-table'),scroll=table.parentElement;
    const cells=[...table.querySelectorAll('th,td')];
    const badContents=[];
    for(const cell of cells){
     const bounds=rect(cell);
     // Only visible text: tooltips and the intentional company-name ellipsis are excluded.
     const walker=document.createTreeWalker(cell,NodeFilter.SHOW_TEXT);
     while(walker.nextNode()){
      const n=walker.currentNode,p=n.parentElement;
      if(!n.textContent.trim() || p.closest('.th-tooltip,.tk-name,.remove-btn,.expand-hint'))continue;
      if(getComputedStyle(p).visibility==='hidden' || getComputedStyle(p).display==='none')continue;
      const range=document.createRange();range.selectNodeContents(n);
      for(const r of range.getClientRects())if(r.width && (r.left<bounds.left-1 || r.right>bounds.right+1))badContents.push(n.textContent);
     }
    }
    const gapControls=[...table.querySelectorAll('td.gap-cell')].map(c=>({pill:rect(c.querySelector('.gap-pill')),remove:rect(c.querySelector('.row-remove'))}));
    const buttons=[...document.querySelectorAll('.nav-shell button')].map(rect);
    const overlap=buttons.some((a,i)=>buttons.slice(i+1).some(b=>a.left<b.right && a.right>b.left && a.top<b.bottom && a.bottom>b.top));
    const brand=rect(document.querySelector('.wordmark')),tabs=rect(document.querySelector('.workspace-tabs'));
    return {width:innerWidth,brandGap:tabs.left-brand.right,brand,tabs,table:rect(table),scroll:rect(scroll),scrollWidth:scroll.scrollWidth,clientWidth:scroll.clientWidth,
     gap:rect(table.querySelector('th:last-child')),overflow:document.documentElement.scrollWidth>innerWidth,badContents,overlap,gapControls,actions:rect(document.querySelector('.topnav-actions')),
     minDataFont:Math.min(...[...table.querySelectorAll('td')].map(e=>parseFloat(getComputedStyle(e).fontSize)))};
   });
   const m=await measure();results.push(m);
   if(!baseline)assert(!m.overflow,'document overflow at '+width);
   if(!baseline)assert(!m.overlap,'header controls overlap at '+width);
   if(!baseline){
    if(width>700)assert(m.brandGap>=24,'wordmark/tab gap at '+width);
    else assert(m.tabs.top>=m.brand.bottom && m.tabs.left>=0 && m.tabs.right<=width,'mobile tabs remain stacked');
    assert(m.actions.right<=width && m.actions.left>=0,'header actions in viewport');
    if(width>=1280)assert(Math.abs((m.actions.top+m.actions.bottom)-(m.tabs.top+m.tabs.bottom))<2,'desktop actions stay aligned');
    if(width>=1280){assert(m.scrollWidth<=m.clientWidth+1,'desktop table scrolls at '+width);assert(m.gap.right<=m.scroll.right+1,'GAP clipped');}
    assert.deepEqual(m.badContents,[],'cell content overflow at '+width);
    assert(m.gapControls.every(c=>c.pill.right<=c.remove.left),'GAP pill/remove overlap at '+width);
    assert(m.minDataFont>=13.6,'data type must remain legible');
   }
   if(width===1280 || width===390)await page.screenshot({path:path.join(out,`FIXTURE-${baseline?'before':'after'}-${width}.png`),fullPage:true});
   if(width<1280){
    await page.locator('#equities-section .scroll').evaluate(el=>el.scrollLeft=el.scrollWidth);
    const end=await measure();assert(end.gap.right<=end.scroll.right+1,'mobile/narrow scroll must reach GAP');
    if(width===390)await page.screenshot({path:path.join(out,`FIXTURE-${baseline?'before':'after'}-390-gap.png`),fullPage:true});
   }
   await page.getByRole('tab',{name:'S&P rankings'}).click();
   await page.getByRole('tab',{name:'Watchlist',exact:true}).click();
   await page.getByRole('button',{name:'Chip legend'}).click();
   assert.equal(await page.locator('#equities-table').isVisible(),true);
   assert.deepEqual(errors,[]);assert.deepEqual(unexpected,[]);
   await ctx.close();
  }
 } finally {await browser.close();}
 fs.writeFileSync(path.join(out,`${baseline?'before':'after'}-measurements.json`),JSON.stringify(results,null,2));
 console.log(JSON.stringify(results.map(({width,brandGap,scrollWidth,clientWidth,badContents,minDataFont})=>({width,brandGap,scrollWidth,clientWidth,badContents,minDataFont})),null,2));
 console.log(baseline?'Baseline captured (known desktop clipping and touching tabs).':'PASS: header controls, tabs, document bounds, desktop GAP fit, cell text bounds and narrow-width GAP scroll; no unexpected requests.');
})().catch(e=>{console.error(e);process.exit(1);});
