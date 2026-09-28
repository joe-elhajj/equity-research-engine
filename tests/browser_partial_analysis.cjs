// Uses real cached SEC fragments produced by the local offline verification.
const fs=require('fs'),path=require('path'),assert=require('node:assert/strict');
const {chromium}=require('playwright');
const root=path.resolve(__dirname,'..');
const data=JSON.parse(fs.readFileSync(process.env.LIMITED_VIEWS || path.join(root,'.cache/limited-validation/views.json')));
const out=process.env.RANKS_SCREENSHOT_DIR || '/tmp/limited-screenshots';fs.mkdirSync(out,{recursive:true});
(async()=>{
 const browser=await chromium.launch({headless:true,channel:'chrome'});
 try{
 for(const [label,width,height] of [['desktop',1440,1000],['mobile',390,844]]){
  const ctx=await browser.newContext({viewport:{width,height},reducedMotion:'reduce'});
  const page=await ctx.newPage();const errors=[],requests=[];page.on('pageerror',e=>errors.push(e.message));
  await ctx.route('**/*',async r=>{
   const req=r.request(),url=new URL(req.url());requests.push([req.method(),url.pathname]);
   if(url.hostname!=='filing.local')return r.abort();
   const json=x=>r.fulfill({contentType:'application/json',body:JSON.stringify(x)});
   if(url.pathname==='/api/watchlist')return json({tickers:data.rows.map(r=>r.ticker),etfs:[]});
   if(url.pathname==='/api/screen')return json({job_id:'offline'});
   if(url.pathname==='/api/screen/status/offline')return json({status:'done',result:{equities:[],etfs:[],excluded:data.rows}});
   if(url.pathname==='/api/universe/leaderboard')return json({available:false});
   const m=url.pathname.match(/^\/api\/analyze\/(QNT|SPCX|SECZ)\/fragment$/);
   if(m)return r.fulfill({contentType:'text/html',body:data.html[m[1]]});
   if(url.pathname.startsWith('/api/')){errors.push('Unexpected request '+url.pathname);return r.abort();}
   const f=url.pathname==='/'?'index.html':url.pathname.slice(1);
   if(!['index.html','app.js','styles.css'].includes(f))return r.fulfill({status:404,body:''});
   return r.fulfill({contentType:f.endsWith('.js')?'application/javascript':f.endsWith('.css')?'text/css':'text/html',body:fs.readFileSync(path.join(root,'frontend',f))});
  });
  await page.goto('http://filing.local/');
  await page.locator('#excluded-table tr[role="button"]').first().waitFor();
  assert.equal(await page.locator('.universe-rank').count(),0);
  const color=await page.locator('#excluded-table .tk-name').first().evaluate(e=>getComputedStyle(e).color);
  assert.equal(color,'rgb(82, 100, 122)');
  await page.screenshot({path:path.join(out,'limited-'+label+'-excluded.png'),fullPage:true});
  for(const ticker of ['QNT','SPCX','SECZ']){
   const row=page.getByRole('button',{name:'Open limited filing view for '+ticker,exact:true});
   await row.focus();await row.press('Enter');
   await page.locator('.partial-analysis').waitFor();
   const text=await page.locator('.partial-analysis').innerText();
   assert(text.includes('No durability score'));
   assert.equal(await page.locator('.partial-analysis .universe-rank').count(),0);
   assert.equal(await page.getByRole('heading',{name:'Valuation & sensitivity',exact:true}).count(),0);
   if(ticker==='QNT')assert(text.includes('7,998,000')&&text.includes('0001628280-26-056743'));
   if(ticker==='SPCX')assert(text.includes('7,814,000,000')&&text.includes('0001628280-26-052535'));
   if(ticker==='SECZ')assert(text.includes('pre-combination shell')&&!text.includes('Total assets'));
   await page.screenshot({path:path.join(out,'limited-'+label+'-'+ticker+'.png')});
   await page.locator('#company-view-back').click();
   assert.equal(await row.evaluate(e=>e===document.activeElement),true);
  }
  assert.deepEqual(errors,[]);
  assert.equal(requests.filter(([method])=>method!=='GET').length,0);
  assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth),true);
  console.log(label+': QNT/SPCX real quarterly facts, SECZ shell withheld, no scores/ranks/DCF, Excluded contrast, keyboard/back, no mutations/paid calls');
  await ctx.close();
 }
 }finally{await browser.close();}
})().catch(e=>{console.error(e);process.exit(1)});
