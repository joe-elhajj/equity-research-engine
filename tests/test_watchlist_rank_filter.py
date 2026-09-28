"""Watchlist scores compare with the same validated reference; no scoring I/O."""
import copy
import json
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient
from app import main
from engine import universe_rank_release as release, universe_ranks as U
from tests.test_universe_ranks import _cfg, _payload


@pytest.fixture
def ranking(tmp_path, monkeypatch):
    cfg, names = _cfg(tmp_path)
    data = _payload(cfg, names)
    path = tmp_path / 'reference.json'
    path.write_text(json.dumps(data))
    monkeypatch.setattr(main.app.state, 'cfg', cfg, raising=False)
    monkeypatch.setattr(release, 'load_reference', lambda cfg: U.load(cfg, path))
    def forbidden(*a, **kw):
        pytest.fail('Read path must never score or build')
    monkeypatch.setattr(main, 'run_screen', forbidden)
    monkeypatch.setattr(U, 'build', forbidden)
    wl = {'tickers':['NVO','ASML','T1','PART','LOW','UNSCORED','NEW','FUND'], 'etfs':['ETF']}
    monkeypatch.setattr(main.watchlist, 'load', lambda: copy.deepcopy(wl))
    def row(t, value, **kw):
        return dict(ticker=t, name=t, completeness=.8, **{f:value for f in U.FIELDS}) | kw
    screen = {'equities':[row('NVO',50.01),row('ASML',50.02),row('T1',50.01),
                           row('PART',50,cat_discipline=None),row('LOW',50,completeness=.79)],
              'excluded':[{'ticker':'UNSCORED','flag':'do not expose raw error'}],
              'etfs':[{'ticker':'FUND'}], 'generated_at':datetime.now(timezone.utc).isoformat()}
    jobs = {'old':{'status':'done','result':screen}}
    monkeypatch.setattr(main.app.state, 'screen_jobs', jobs, raising=False)
    return TestClient(main.app), wl, jobs, data, path, row


def get(client, query=''):
    r=client.get('/api/universe/leaderboard?watchlist_only=true&'+query)
    assert r.status_code==200
    return r.json()


def test_screen_scores_membership_counts_and_off_unchanged(ranking):
    client, wl, jobs, data, path, row = ranking
    off=client.get('/api/universe/leaderboard').json()
    assert off == U.leaderboard(data) | {'snapshot_date':None}
    assert 'watchlist_only' not in off and 'reference_member' not in off['rows'][0]
    result=get(client)
    assert [r['ticker'] for r in result['rows']]==['ASML','NVO','T1','PART']
    assert [r['reference_member'] for r in result['rows']]==[False,False,True,False]
    assert result['rows'][2]['score']==50.01 != data['rows']['T1']['composite']
    assert result['rows'][0]['percentile']==U.rank(50.02,'composite',data)['percentile']
    assert result['scored']==120 and result['total']==120 and result['peer_counts']=={'composite':120}
    assert result['watchlist_equity_count']==7 and result['fund_count']==2
    assert result['omitted']=={'no_current_score':1,'not_scored':1,'incomplete_scores':1}
    assert 'raw error' not in json.dumps(result)
    wl['tickers'].remove('ASML')
    assert 'ASML' not in [r['ticker'] for r in get(client)['rows']]
    wl['tickers'].append('ADDED')
    assert get(client)['omitted']['no_current_score']==2
    jobs['refresh']={'status':'done','result':dict(jobs['old']['result'],equities=[row('ADDED',99)])}
    assert [r['ticker'] for r in get(client)['rows']]==['ADDED']


def test_multi_intersection_full_precision_ties_and_limits(ranking):
    client, wl, jobs, data, path, row = ranking
    fields=('cat_reinvestment','cat_discipline')
    result=get(client,'fields='+','.join(fields))
    assert result['intersection_count']==3 and result['omitted']['incomplete_scores']==2
    # Equal percentiles at 50.01/50.02 intentionally tie: ticker, not raw score.
    assert [r['ticker'] for r in result['rows']]==['ASML','NVO','T1']
    for r in result['rows']:
        assert r['score'] is None and r['percentile'] is None
        expected=sum(U._percentile(r['scores'][f],f,data) for f in fields)/2
        assert r['average_selected_percentiles']==round(expected,1)
    assert [r['ticker'] for r in get(client,'order=asc')['rows']]==['PART','NVO','T1','ASML']
    many=[row('W'+str(i).zfill(3),i/10) for i in range(130)]
    wl['tickers']=[r['ticker'] for r in many];wl['etfs']=[]
    jobs['old']['result'].update(equities=many,excluded=[],etfs=[])
    assert len(get(client)['rows'])==25
    assert len(get(client,'all_names=true')['rows'])==130  # bounded by live list, not constituents
    assert get(client,'all_names=true&order=asc')['rows'][0]['ticker']=='W000'
    assert client.get('/api/universe/leaderboard?watchlist_only=true&fields=bad').status_code==400
    assert client.get('/api/universe/leaderboard?watchlist_only=bad').status_code==422


@pytest.mark.parametrize('state',['not_run','running','error'])
def test_no_current_completed_screen_never_falls_back(ranking,state):
    client, wl, jobs, *_=ranking
    if state=='not_run': jobs.clear()
    else: jobs['new']={'status':state,'result':None}
    result=get(client)
    assert result['screen_state']==state and result['rows']==[]
    assert result['scored']==120 and result['total']==120
    latest=client.get('/api/screen/latest').json()
    assert latest['status']==state
    if state!='not_run': assert latest['job_id']=='new'


def test_expiry_missing_and_latest_read_only(ranking):
    client, wl, jobs, data, path, row=ranking
    wl['tickers'].remove('ASML')
    latest=client.get('/api/screen/latest').json()['result']['equities']
    assert 'ASML' not in [r['ticker'] for r in latest]
    assert latest[0]['universe_ranks']
    data['started_at']=(datetime.now(timezone.utc)-timedelta(days=91)).isoformat()
    data['expires_at']=(datetime.now(timezone.utc)-timedelta(days=1)).isoformat()
    path.write_text(json.dumps(data))
    assert get(client)=={'available':False}
    assert client.get('/api/screen/latest').json()['result']['equities'][0]['universe_ranks']=={}
    path.unlink()
    assert get(client)=={'available':False}
