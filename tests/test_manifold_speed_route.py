from benchbase.manifold_speed_route import assess_route_card


def test_assess_ok_when_allow_complete():
    route = {"name": "seat", "allow": ["min_tokens", "ignore_eos"], "clients": ["benchbase"]}
    out = assess_route_card(route, "seat")
    assert out["ok"] is True


def test_assess_fail_shared_route():
    route = {"name": "seat", "allow": [], "clients": ["hermes", "openwebui", "benchbase"]}
    out = assess_route_card(route, "seat")
    assert out["ok"] is False
    assert out["reason"] == "shared_route_strips_forcing"


def test_assess_fail_bench_only_missing_allow():
    route = {"name": "seat", "allow": [], "clients": ["benchbase"]}
    out = assess_route_card(route, "seat")
    assert out["ok"] is False
    assert out["reason"] == "bench_only_missing_allow"


def test_assess_fail_route_missing():
    out = assess_route_card(None, "missing")
    assert out["ok"] is False
    assert out["reason"] == "route_not_listed"