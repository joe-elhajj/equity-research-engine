"""Derived-only release export/import is fail-closed and leaves local builds intact."""
import json
from datetime import datetime, timedelta, timezone

from engine import universe_rank_release as R
from engine import universe_ranks as U


def cohort(tmp_path):
    names = [f"T{i}" for i in range(120)]
    universe = tmp_path / "universe.txt"
    universe.write_text("\n".join(names))
    cfg = {"universe": {"version": "test-q", "file": str(universe)},
           "sec": {"user_agent": "Private Name private@host.test"},
           "valuation": {"min_history_years": 4}}
    rows = {name: {**{f: float(i / 2) for f in U.FIELDS},
                   "name": name + " Corp", "completeness": .8} for i, name in enumerate(names)}
    data = {"key": U.key(cfg), "status": "complete", "total": len(names),
            "processed": len(names), "scored": len(names),
            "started_at": (datetime.now(timezone.utc)-timedelta(days=2)).isoformat(),
            "built_at": (datetime.now(timezone.utc)-timedelta(days=1)).isoformat(),
            "exclusions": {},
            "scores": {f: [float(i / 2) for i in range(120)] for f in U.FIELDS},
            "rows": rows}
    data["expires_at"] = (datetime.fromisoformat(data["started_at"])+timedelta(days=90)).isoformat()
    path = tmp_path / "local.json"
    path.write_text(json.dumps(data))
    return cfg, path


def test_export_contains_only_approved_derived_fields(tmp_path):
    cfg, local = cohort(tmp_path)
    output = tmp_path / "universe-ranks.json"
    result = R.export(cfg, output, local)
    payload = output.read_text()
    assert set(result) == {"schema", "source_schema", "version", "file_hash", "scoring_hash", "built_at", "started_at", "expires_at",
                           "total", "scored", "rows", "scores", "peer_counts"}
    assert "price" not in payload and "market_cap" not in payload
    assert "Private Name" not in payload and "private@host.test" not in payload
    assert "Corp" not in payload and "config_hash" not in payload
    assert R.validate(cfg, result)["scored"] == 120


def test_release_rejects_mismatch_staleness_and_tampering(tmp_path):
    cfg, local = cohort(tmp_path)
    data = R.export(cfg, tmp_path / "public.json", local)
    new_cfg = {**cfg, "sec": {"user_agent": "Another local SEC user another@host.test"}}
    assert R.validate(new_cfg, data) is not None
    new_cfg["valuation"] = {"min_history_years": 5}
    assert R.validate(new_cfg, data) is None
    data["built_at"] = (datetime.now(timezone.utc) - timedelta(days=91)).isoformat()
    assert R.validate(cfg, data) is None
    data["built_at"] = datetime.now(timezone.utc).isoformat()
    data["rows"]["T0"]["quote"] = 123
    assert R.validate(cfg, data) is None


def test_local_wins_offline_and_fresher_download_wins(tmp_path, monkeypatch):
    cfg, local = cohort(tmp_path)
    public = tmp_path / "public.json"
    payload = R.export(cfg, public, local)
    monkeypatch.setattr(R, "refresh", lambda *a, **k: (_ for _ in ()).throw(AssertionError("network")))
    result = R.load_reference(cfg, local=local, downloaded=public)
    assert result["built_at"] == json.loads(local.read_text())["built_at"]
    payload["built_at"] = (datetime.now(timezone.utc) + timedelta(seconds=1)).isoformat()
    public.write_text(json.dumps(payload))
    # Future-dated releases are rejected, rather than winning as fresher.
    assert R.load_reference(cfg, local=local, downloaded=public)["built_at"] == result["built_at"]
    payload["built_at"] = (datetime.now(timezone.utc) - timedelta(days=1,seconds=1)).isoformat()
    public.write_text(json.dumps(payload))
    assert R.load_reference(cfg, local=local, downloaded=public)["built_at"] == result["built_at"]


def test_public_used_without_local_and_bounded_refresh(tmp_path, monkeypatch):
    cfg, local = cohort(tmp_path)
    public = tmp_path / "public.json"
    R.export(cfg, public, local)
    calls = []
    monkeypatch.setattr(R, "_checked_at", -R.CHECK_SECONDS)
    monkeypatch.setattr(R, "refresh", lambda *a, **k: (calls.append(True), None)[1])
    first = R.load_reference(cfg, local=tmp_path / "missing", downloaded=public)
    second = R.load_reference(cfg, local=tmp_path / "missing", downloaded=public)
    assert first is not None and second is not None and len(calls) == 0
    public.unlink()
    R.load_reference(cfg, local=tmp_path / "missing", downloaded=public)
    R.load_reference(cfg, local=tmp_path / "missing", downloaded=public)
    assert len(calls) == 1


def test_downloaded_newer_compatible_build_wins(tmp_path, monkeypatch):
    cfg, local = cohort(tmp_path)
    public = tmp_path / "public.json"
    payload = R.export(cfg, public, local)
    original = json.loads(local.read_text())["built_at"]
    payload["built_at"] = datetime.now(timezone.utc).isoformat()
    public.write_text(json.dumps(payload))
    monkeypatch.setattr(R, "refresh", lambda *a, **k: (_ for _ in ()).throw(AssertionError("network")))
    result = R.load_reference(cfg, local=local, downloaded=public)
    assert result["built_at"] >= original


def test_invalid_public_asset_cannot_replace_local(tmp_path, monkeypatch):
    cfg, local = cohort(tmp_path)
    public = tmp_path / "public.json"
    payload = R.export(cfg, public, local)
    payload["rows"]["T4"]["cat_quality"] = 101.0
    public.write_text(json.dumps(payload))
    monkeypatch.setattr(R, "_checked_at", -R.CHECK_SECONDS)
    monkeypatch.setattr(R, "refresh", lambda *a, **k: (_ for _ in ()).throw(AssertionError("network")))
    assert R.load_reference(cfg, local=local, downloaded=public)["built_at"] == json.loads(local.read_text())["built_at"]


def test_clone_with_different_universe_path_can_use_matching_bytes(tmp_path):
    cfg, local = cohort(tmp_path)
    public = tmp_path / "public.json"
    payload = R.export(cfg, public, local)
    other = tmp_path / "clone-universe.txt"
    other.write_bytes((tmp_path / "universe.txt").read_bytes())
    clone_cfg = {**cfg, "universe": {**cfg["universe"], "file": str(other)}}
    assert R.validate(clone_cfg, payload) is not None


def test_refresh_accepts_only_named_uploaded_asset_on_dedicated_release(tmp_path, monkeypatch):
    cfg, local = cohort(tmp_path)
    payload = R.export(cfg, tmp_path / "export.json", local)
    class Session:
        pass
    calls = []
    def get_json(_session, url, *, asset=False):
        calls.append((url, asset))
        if not asset:
            return {"tag_name": "equity-ranks", "draft": False, "prerelease": False,
                    "assets": [{"name": R.ASSET, "state": "uploaded", "size": 5000,
                                "browser_download_url": "https://github.com/joe-elhajj/equity-research-engine/releases/download/equity-ranks/universe-ranks.json"}]}
        return payload
    monkeypatch.setattr(R, "_get_json_bounded", get_json)
    result = R.refresh(cfg, tmp_path / "downloaded.json", Session())
    assert result is not None and calls == [(R.API, False),
        ("https://github.com/joe-elhajj/equity-research-engine/releases/download/equity-ranks/universe-ranks.json", True)]


def test_refresh_rejects_unexpected_release(tmp_path, monkeypatch):
    cfg, local = cohort(tmp_path)
    monkeypatch.setattr(R, "_get_json_bounded", lambda *a, **k: {"tag_name": "latest", "assets": []})
    assert R.refresh(cfg, tmp_path / "downloaded.json", object()) is None


import pytest

@pytest.mark.parametrize('damage', [
    lambda d: d['rows']['T0'].update(completeness=.7999),
    lambda d: d['rows']['T0'].pop('completeness'),
    lambda d: d['rows']['T0'].update(composite=None),
    lambda d: d['rows']['T0'].update(cat_quality=101),
    lambda d: d['rows']['T0'].update(cat_quality=True),
    lambda d: d['rows']['T0'].update(cat_quality=float('nan')),
    lambda d: d['peer_counts'].update(composite=119),
    lambda d: d['scores']['composite'].__setitem__(0,.1),
    lambda d: d.update(scored=119),
    lambda d: d.update(source_schema=1),
    lambda d: d.update(expires_at=(datetime.now(timezone.utc)+timedelta(days=100)).isoformat()),
    lambda d: d.update(started_at='2026-01-01'),
    lambda d: d.update(sec={'user_agent':'private'}),
])
def test_public_uses_hardened_gates(tmp_path, damage):
    cfg,local=cohort(tmp_path)
    data=R.export(cfg,tmp_path/'export.json',local)
    damage(data)
    assert R.validate(cfg,data) is None


def test_export_cannot_overwrite_source(tmp_path):
    cfg,local=cohort(tmp_path)
    original=local.read_bytes()
    with pytest.raises(ValueError,match='overwrite'): R.export(cfg,local,local)
    assert local.read_bytes()==original


def test_download_never_follows_untrusted_redirect():
    class Response:
        status_code=302
        headers={'Location':'https://evil.invalid/universe-ranks.json'}
        def __enter__(self):return self
        def __exit__(self,*a):pass
    class Session:
        def __init__(self):self.calls=[]
        def get(self,url,**kw):
            assert kw['allow_redirects'] is False
            self.calls.append(url);return Response()
    session=Session()
    with pytest.raises(ValueError,match='redirect'): R._get_json_bounded(session,R.API)
    assert session.calls==[R.API]


def test_503_reference_requires_302_and_100_per_field(tmp_path):
    import copy
    cfg,local=cohort(tmp_path)
    names=[f'T{i}' for i in range(503)]
    (tmp_path/'universe.txt').write_text('\n'.join(names))
    data=json.loads(local.read_text())
    data.update(key=U.key(cfg),total=503,processed=503,scored=302,
                rows={t: ({**{f:50. for f in U.FIELDS},'name':None,'completeness':.8} if i<302 else {}) for i,t in enumerate(names)},
                exclusions={t:'ineligible' for t in names[302:]},
                scores={f:[50.]*302 for f in U.FIELDS})
    local.write_text(json.dumps(data))
    public=R.export(cfg,tmp_path/'public.json',local)
    assert R.validate(cfg,public)
    poor=copy.deepcopy(public)
    poor['rows']['T301']={};poor['scored']=301
    poor['scores']={f:[50.]*301 for f in U.FIELDS};poor['peer_counts']={f:301 for f in U.FIELDS}
    assert R.validate(cfg,poor) is None
    poor=copy.deepcopy(public)
    for t in names[99:302]:poor['rows'][t]['cat_reinvestment']=None
    poor['scores']['cat_reinvestment']=[50.]*99;poor['peer_counts']['cat_reinvestment']=99
    assert R.validate(cfg,poor) is None
