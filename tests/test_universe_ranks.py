"""Offline reference eligibility, consistency, freshness and read-only API checks."""
from datetime import datetime, timezone, timedelta
import copy
import json
from types import SimpleNamespace

import pytest
from engine import universe_ranks as U


def _cfg(tmp_path):
    names = [f'T{i}' for i in range(120)]
    path = tmp_path / 'universe.txt'
    path.write_text('\n'.join(names))
    return {'universe': {'version': 'test-q', 'file': str(path)},
            'sec': {'user_agent': 'Test tests@example.org'}}, names


def _payload(cfg, names):
    now = datetime.now(timezone.utc)
    rows = {t: {**{f: i / 2 for f in U.FIELDS}, 'name': t, 'completeness': .8}
            for i, t in enumerate(names)}
    return {'key': U.key(cfg), 'status': 'complete', 'total': len(names), 'processed': len(names),
            'scored': len(names), 'started_at': now.isoformat(), 'built_at': now.isoformat(),
            'expires_at': (now + timedelta(days=90)).isoformat(), 'rows': rows,
            'exclusions': {}, 'scores': {f: [i / 2 for i in range(120)] for f in U.FIELDS}}


def test_rank_midpoint_and_missing():
    data = {'scores': {'composite': [50.] * 120}}
    assert U.rank(50, 'composite', data) == {'percentile': 50., 'peers': 120}
    assert U.rank(49, 'composite', data)['percentile'] == 0
    assert U.rank(51, 'composite', data)['percentile'] == 100
    assert U.rank(None, 'composite', data)['percentile'] is None
    assert U.rank(float('nan'), 'composite', data)['percentile'] is None
    assert U.rank(50, 'composite', None)['peers'] == 0


@pytest.mark.parametrize('damage', [
    lambda d: d.update(status='building'),
    lambda d: d.update(scored=119),
    lambda d: d.update(processed=119),
    lambda d: d.update(total=True),
    lambda d: d.update(rows=[]),
    lambda d: d.update(exclusions={'T0': 'spurious'}),
    lambda d: d['rows']['T0'].update(completeness=.7999),
    lambda d: d['rows']['T0'].update(completeness=float('nan')),
    lambda d: d['rows']['T0'].update(composite=True),
    lambda d: d['rows']['T0'].update(cat_quality=101),
    lambda d: d['rows']['T0'].pop('cat_quality'),
    lambda d: d['scores']['composite'].reverse(),
    lambda d: d['scores']['composite'].__setitem__(0, .1),
    lambda d: d['key'].update(schema=1),
    lambda d: d.update(built_at='2026-01-01'),
    lambda d: d.update(built_at=(datetime.now(timezone.utc)+timedelta(days=1)).isoformat()),
    lambda d: d.update(expires_at=(datetime.now(timezone.utc)-timedelta(days=1)).isoformat()),
])
def test_cache_fails_closed(tmp_path, damage):
    cfg, names = _cfg(tmp_path)
    payload = _payload(cfg, names)
    path = tmp_path / 'ranks.json'
    path.write_text(json.dumps(payload))
    assert U.load(cfg, path)
    damage(payload)
    path.write_text(json.dumps(payload))
    assert U.load(cfg, path) is None


def test_missing_malformed_and_mismatched_reference(tmp_path):
    cfg, names = _cfg(tmp_path)
    path = tmp_path / 'ranks.json'
    assert U.load(cfg, path) is None
    for value in ('[]', 'null', '{', '1'):
        path.write_text(value)
        assert U.load(cfg, path) is None
    path.write_text(json.dumps(_payload(cfg, names)))
    changed = copy.deepcopy(cfg)
    changed['extra'] = True
    assert U.load(changed, path) is None
    (tmp_path / 'universe.txt').write_text('\n'.join(reversed(names)))
    assert U.load(cfg, path) is None


def test_build_eligibility_exclusions_checkpoint_and_no_paid_calls(tmp_path, monkeypatch):
    cfg, names = _cfg(tmp_path)
    monkeypatch.setattr(U, 'EdgarClient', lambda **kw: None)
    calls = []
    def process(t, *_):
        calls.append(t)
        if t == 'T0': return None, object()
        completeness = .7999 if t == 'T1' else .8
        return SimpleNamespace(**{f: 60. for f in U.FIELDS}, completeness=completeness,
                               name='Example', flag=''), None
    monkeypatch.setattr(U, '_process_one', process)
    path = tmp_path / 'aggregate.json'
    def interrupt(n, *_):
        if n == 3: raise KeyboardInterrupt()
    with pytest.raises(KeyboardInterrupt): U.build(cfg, path, progress=interrupt)
    assert not path.exists()
    checkpoint = json.loads(path.with_name('aggregate.progress.json').read_text())
    data = U.build(cfg, path)
    assert calls == names
    assert data['scored'] == 118
    assert data['started_at'] == checkpoint['started_at']
    assert data['exclusions']['T0'] == 'fund'
    assert '80%' in data['exclusions']['T1']
    assert U.load(cfg, path)
    assert not path.with_name('aggregate.progress.json').exists()


def test_insufficient_coverage_keeps_existing_cache(tmp_path, monkeypatch):
    cfg, names = _cfg(tmp_path)
    monkeypatch.setattr(U, 'EdgarClient', lambda **kw: None)
    monkeypatch.setattr(U, '_process_one', lambda *_: (None, None))
    path = tmp_path / 'ranks.json'
    path.write_text('previous cache')
    with pytest.raises(ValueError, match='coverage'): U.build(cfg, path)
    assert path.read_text() == 'previous cache'


def test_leaderboard_all_fields_and_tie_order(tmp_path):
    cfg, names = _cfg(tmp_path)
    data = _payload(cfg, names)
    for field in U.FIELDS:
        result = U.leaderboard(data, field, 3)
        assert [r['ticker'] for r in result['rows']] == names[-1:-4:-1]
        assert result['peers'] == 120
    data['rows']['T118']['composite'] = data['rows']['T119']['composite']
    data['scores']['composite'][-2] = data['scores']['composite'][-1]
    result = U.leaderboard(data, 'composite', 2)
    assert [r['ticker'] for r in result['rows']] == ['T118', 'T119']
    assert result['rows'][0]['percentile'] == result['rows'][1]['percentile']
    assert U.leaderboard(None) is None


def test_api_read_only_and_cached_screen_revalidation(tmp_path, monkeypatch):
    from app import main
    cfg, names = _cfg(tmp_path)
    data = _payload(cfg, names)
    monkeypatch.setattr(main.app.state, 'cfg', cfg, raising=False)
    monkeypatch.setattr(U, 'build', lambda *_: pytest.fail('read launched build'))
    monkeypatch.setattr(U, '_process_one', lambda *_: pytest.fail('read launched processing'))
    monkeypatch.setattr(U, 'load', lambda *_: data)
    for field in U.FIELDS:
        assert main.universe_leaderboard(field)['field'] == field
    row = dict(data['rows']['T1'], ticker='T1', universe_ranks={'composite': {'percentile': 99}})
    monkeypatch.setattr(main.app.state, 'screen_jobs', {'test': {'status': 'done', 'result': {'equities': [row]}}}, raising=False)
    assert main.screen_status('test')['result']['equities'][0]['universe_ranks']
    monkeypatch.setattr(U, 'load', lambda *_: None)
    assert main.universe_leaderboard() == {'available': False}
    assert main.screen_status('test')['result']['equities'][0]['universe_ranks'] == {}


def test_rate_limit_checkpoints_current_ticker_and_resumes(tmp_path, monkeypatch):
    cfg, names = _cfg(tmp_path)
    monkeypatch.setattr(U, 'EdgarClient', lambda **kw: None)
    calls = []
    def process(t, *_):
        calls.append(t)
        if t == 'T2': raise U.ReferencePaused('Yahoo HTTP 429', 900)
        return SimpleNamespace(**{f: 60. for f in U.FIELDS}, completeness=.8, name=t, flag=''), None
    monkeypatch.setattr(U, '_process_one', process)
    path = tmp_path / 'aggregate.json'
    with pytest.raises(U.ReferencePaused): U.build(cfg, path)
    checkpoint = json.loads(path.with_name('aggregate.progress.json').read_text())
    assert set(checkpoint['rows']) == {'T0', 'T1'}
    assert not path.exists()
    with pytest.raises(U.ReferencePaused, match='Cooldown'): U.build(cfg, path)
    assert calls == ['T0', 'T1', 'T2']
    retry_path = path.with_name('aggregate.retry.json')
    retry = json.loads(retry_path.read_text())
    retry['retry_at'] = (datetime.now(timezone.utc)-timedelta(seconds=1)).isoformat()
    retry_path.write_text(json.dumps(retry))
    monkeypatch.setattr(U, '_process_one', lambda t, *_: (SimpleNamespace(**{f: 60. for f in U.FIELDS}, completeness=.8, name=t, flag=''), None))
    result = U.build(cfg, path)
    assert result['scored'] == 120
    assert result['started_at'] == checkpoint['started_at']
    assert not retry_path.exists()


def test_request_throttle_backoff_and_rate_limit():
    from engine.reference_transport import RequestBudget, ReferencePaused
    now = [0.]
    starts = []
    def sleep(delay): now[0] += delay
    budget = RequestBudget(clock=lambda: now[0], sleep=sleep)
    statuses = iter([200, 503, 200, 429])
    def request(*args, **kwargs):
        assert kwargs['allow_redirects'] is False
        starts.append(now[0])
        return SimpleNamespace(status_code=next(statuses), headers={'Retry-After': '1200'})
    budget.send(request, 'GET', 'https://query1.finance.yahoo.com/test')
    budget.send(request, 'GET', 'https://query1.finance.yahoo.com/test')
    with pytest.raises(ReferencePaused) as error:
        budget.send(request, 'GET', 'https://query1.finance.yahoo.com/test')
    assert error.value.retry_after == 1200
    assert len(starts) == 4
    assert all(b-a >= 1.05-1e-9 for a,b in zip(starts,starts[1:]))
    assert starts[2]-starts[1] == pytest.approx(2)
