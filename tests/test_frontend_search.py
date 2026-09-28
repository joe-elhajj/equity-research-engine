"""Exercise the real search handlers against async response orders and DOM nodes."""
import json
import shutil
import subprocess
from pathlib import Path

import pytest

pytestmark = pytest.mark.skipif(shutil.which("node") is None, reason="node unavailable")
JS = (Path(__file__).resolve().parents[1] / "frontend/app.js").read_text()
SEARCH = '  var searchDebounce = null;' + JS.split("  var searchDebounce = null;", 1)[1].split("  // ---- export: CSV + PDF ----", 1)[0]


def _run(order):
    script = r"""
function node() {
  const n = {value:'', textContent:'', className:'', children:[], listeners:{}};
  const classes = new Set(['hidden']);
  n.classList = {add(c){classes.add(c)}, remove(c){classes.delete(c)},
    contains(c){return classes.has(c)}, toggle(c,v){if(v)classes.add(c);else classes.delete(c)}};
  n.addEventListener=(t,f)=>{n.listeners[t]=f};
  n.dispatchEvent=(ev)=>n.listeners[ev.type] && n.listeners[ev.type](ev);
  n.appendChild=(child)=>n.children.push(child);
  n.setAttribute=()=>{};
  Object.defineProperty(n,'innerHTML',{set(){n.children=[]}});
  return n;
}
global.document={createElement:node};
global.Event=function(type){this.type=type};
const els={searchInput:node(),searchStatus:node(),searchCandidates:node(),
 searchConfirm:node(),searchConfirmText:node(),searchClassificationBadge:node(),searchAddBtn:node()};
let currentSearchTicker=null;
let pending={};
function apiGet(url){return new Promise(resolve=>pending[url]=resolve)}
function showBanner(){};
function runScreen(){};
global.setTimeout=(fn)=>{fn();return 1};
global.clearTimeout=()=>{};
""" + SEARCH + r"""
(async()=>{
 els.searchInput.value='AAPL';
 els.searchInput.dispatchEvent(new Event('input'));
 const exact='/api/search/AAPL', candidates='/api/search_candidates/AAPL';
 const fulfill=async (type)=>{
  if(type==='candidate') pending[candidates]({candidates:[{ticker:'AAPL',name:'Apple Inc.'},{ticker:'AA',name:'Alcoa'}]});
  else pending[exact]({found:true,name:'Apple Inc.'});
  await Promise.resolve(); await Promise.resolve();
 };
 for(const type of ORDER) await fulfill(type);
 const state1={confirm:!els.searchConfirm.classList.contains('hidden'),
   candidates:!els.searchCandidates.classList.contains('hidden'),
   ticker:currentSearchTicker, label:els.searchConfirmText.textContent};
 els.searchInput.value='apple'; els.searchInput.dispatchEvent(new Event('input'));
 pending['/api/search_candidates/apple']({candidates:[{ticker:'AAPL',name:'Apple Inc.'}]});
 await Promise.resolve();await Promise.resolve();
 const state2={confirm:!els.searchConfirm.classList.contains('hidden'),
   candidates:!els.searchCandidates.classList.contains('hidden'),
   count:els.searchCandidates.children.length};
 console.log(JSON.stringify({state1,state2}));
})();
""".replace('ORDER', json.dumps(order))
    proc = subprocess.run(['node', '-e', script], text=True, capture_output=True, timeout=10)
    assert proc.returncode == 0, proc.stderr
    return json.loads(proc.stdout.strip().splitlines()[-1])


@pytest.mark.parametrize('order', [('candidate', 'exact'), ('exact', 'candidate')])
def test_exact_card_wins_both_response_orders_and_name_search_still_works(order):
    result = _run(order)
    assert result['state1'] == {
        'confirm': True, 'candidates': False, 'ticker': 'AAPL', 'label': 'AAPL — Apple Inc.'}
    assert result['state2'] == {'confirm': False, 'candidates': True, 'count': 1}


def test_popover_not_allowed_to_cover_add_button():
    styles = (Path(__file__).resolve().parents[1] / 'frontend/styles.css').read_text()
    assert 'if (currentSearchTicker) return; // exact card won the async race' in JS
    assert 'hideSearchCandidates();\n            var label' in JS
    assert 'max-width:min(480px,calc(100vw - 24px))' in styles
