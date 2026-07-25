"""The frozen-corpus provenance sidecar must DESCRIBE the corpus, not just accompany it.

A provenance file that drifts from the data it documents is worse than no provenance file:
it launders a stale claim as a verified one. So every measurable field in
`data/real_oos_corpus_polymarket_meta.json` is re-derived here FROM THE COMMITTED BYTES and
compared. If someone re-freezes the corpus without updating the sidecar, this fails.

This is the same class of check the independent Quality Auditor's `artifact_integrity`
dimension grades: doc statements reconciled against the thing they describe.

All offline — reads two committed files, no network.
"""

import hashlib
import json
import statistics
from collections import Counter
from datetime import datetime
from pathlib import Path

import pytest

DATA = Path(__file__).resolve().parents[2] / "data"
CORPUS = DATA / "real_oos_corpus_polymarket.json"
SIDECAR = DATA / "real_oos_corpus_polymarket_meta.json"


@pytest.fixture(scope="module")
def corpus():
    if not CORPUS.exists():
        pytest.skip("frozen corpus not committed")
    rows = json.loads(CORPUS.read_text())
    if isinstance(rows, dict):
        rows = rows.get("records") or rows.get("markets") or rows
    return rows


@pytest.fixture(scope="module")
def meta():
    if not SIDECAR.exists():
        pytest.fail(
            "the frozen corpus has NO provenance sidecar — the corpus behind the project's "
            "only real OOS number must carry its fetch source, parameters and bias disclosures"
        )
    return json.loads(SIDECAR.read_text())


def test_sidecar_sha256_matches_the_committed_corpus_bytes(meta):
    """The strongest binding: if the corpus is re-frozen, this fails immediately."""
    actual = hashlib.sha256(CORPUS.read_bytes()).hexdigest()
    assert meta["corpus_sha256"] == actual, (
        "sidecar sha256 does not match the committed corpus — the sidecar describes a "
        f"DIFFERENT file. sidecar={meta['corpus_sha256']} actual={actual}"
    )


def test_sidecar_record_count_matches(corpus, meta):
    assert meta["records"] == len(corpus)


def test_sidecar_decision_lead_matches_the_data(corpus, meta):
    leads = [
        (
            datetime.fromisoformat(r["resolution_time"])
            - datetime.fromisoformat(r["decision_time"])
        ).total_seconds()
        / 86400.0
        for r in corpus
    ]
    declared = meta["measured"]["decision_lead_days"]
    assert declared["min"] == pytest.approx(min(leads))
    assert declared["max"] == pytest.approx(max(leads))
    assert declared["median"] == pytest.approx(statistics.median(leads))
    assert declared["uniform"] is (min(leads) == max(leads)), (
        "the sidecar's `uniform` flag disagrees with the data"
    )


def test_sidecar_distribution_stats_match(corpus, meta):
    m = meta["measured"]
    outs = [r["outcome"] for r in corpus]
    prices = [r["market_price"] for r in corpus]
    assert m["yes_base_rate"] == pytest.approx(sum(outs) / len(outs), abs=5e-5)
    assert m["market_price_median"] == pytest.approx(statistics.median(prices), abs=5e-5)
    assert m["categories"] == dict(Counter(r.get("category") for r in corpus)), (
        "sidecar category histogram drifted from the corpus"
    )


def test_sidecar_liquidity_and_play_money_claims_are_true(corpus, meta):
    """Both are load-bearing honesty claims, not trivia: `liquidity_non_null == 0` is WHY
    the market-impact path is untested on real data, and `research_only == 0` is what makes
    this corpus eligible for the real-money floor lane at all."""
    m = meta["measured"]
    assert m["liquidity_non_null"] == sum(
        1 for r in corpus if r.get("liquidity") is not None
    )
    assert m["research_only_records"] == sum(
        1 for r in corpus if r.get("research_only")
    )
    assert m["research_only_records"] == 0, (
        "a play-money record in the REAL-MONEY floor corpus (ROADMAP A8 guardrail)"
    )


def test_sidecar_leakage_claims_hold_on_the_data(corpus, meta):
    """Spot-verify the leakage-safety assertions rather than taking them on faith."""
    assert all(
        datetime.fromisoformat(r["decision_time"])
        < datetime.fromisoformat(r["resolution_time"])
        for r in corpus
    ), "a record has decision_time >= resolution_time"
    assert not any(
        r["market_price"] in (0.0, 1.0) for r in corpus
    ), "a decision price sits exactly at a settled outcome value"


def test_sidecar_does_not_dress_the_refutation_up_as_an_edge(meta):
    """The headline result on this corpus is significantly NEGATIVE. The sidecar must say
    so — an optimistic-by-omission provenance file on a refuted result is exactly the
    failure mode the honesty discipline exists to prevent."""
    h = meta["headline_result"]
    assert h["net_pnl_usd"] < 0
    assert h["f11_verdict"] == "significant_negative"
    assert "REFUTATION" in h["note"] or "not an edge" in h["note"].lower()
    assert meta["disclosures"], "a provenance file with no disclosed biases is a red flag"


def test_sidecar_resolution_span_matches(corpus, meta):
    """Re-derived, not trusted. A reviewer mutated this field to
    ["2000-01-01", "2099-01-01"] and every test still passed — the coverage did not match
    the claim that every measurable field is compared."""
    res = sorted(datetime.fromisoformat(r["resolution_time"]) for r in corpus)
    declared = meta["measured"]["resolution_time_span"]
    assert declared == [res[0].date().isoformat(), res[-1].date().isoformat()]


def test_sidecar_leakage_bullet_counts_are_true(meta, corpus):
    """The anti-leak sanity bullet quotes SPECIFIC counts ("46 outcome=1 of which 14 priced
    < 0.50; 141 outcome=0 of which 9 priced > 0.50"). Those numbers are the evidence that the
    decision price is not the settled outcome, so they must be re-derived — a reviewer proved
    they could be replaced with "999/999/999/999" undetected."""
    yes = [r for r in corpus if r["outcome"] == 1]
    no = [r for r in corpus if r["outcome"] == 0]
    counts = (
        len(yes),
        sum(1 for r in yes if r["market_price"] < 0.50),
        len(no),
        sum(1 for r in no if r["market_price"] > 0.50),
    )
    bullet = next(
        (b for b in meta["leakage_safety"] if "anti-leak sanity" in b), None
    )
    assert bullet is not None, "the anti-leak sanity bullet is missing from the sidecar"
    for n in counts:
        assert str(n) in bullet, (
            f"the anti-leak sanity bullet does not mention the true count {n}; "
            f"derived counts are {counts} and the bullet reads: {bullet!r}"
        )


def test_sidecar_headline_result_reproduces_exactly():
    """The load-bearing block: the sidecar's headline IS "the project's only real OOS
    number". A reviewer mutated trades / net_pnl_usd / seed_hash / hit_rate to nonsense and
    every test still passed, because nothing re-ran the evaluation. Now it does.

    This is the difference between a provenance file that is checked and one that merely
    looks checked.
    """
    import sys

    repo_root = Path(__file__).resolve().parents[2]
    sys.path.insert(0, str(repo_root))
    sys.path.insert(0, str(repo_root / "backend"))
    v = __import__("scripts.validate_real_oos", fromlist=["x"])
    wf = __import__("app.prediction_markets.walk_forward", fromlist=["x"])
    cal = __import__("app.prediction_markets.calibration_bucket_strategy", fromlist=["x"])

    meta_doc = json.loads(SIDECAR.read_text())
    h = meta_doc["headline_result"]
    markets = v.load_corpus_from_json(str(CORPUS), wf)
    report = v.evaluate(markets, wf, cal, seed=h["seed"], decision_lead_days=7.0)
    alpha = report["calibration_alpha_b4a"]

    assert alpha["trades"] == h["trades"]
    assert alpha["total_pnl_usd"] == pytest.approx(h["net_pnl_usd"], abs=0.005)
    assert alpha["seed_hash"] == h["seed_hash"], (
        "the sidecar's published seed_hash does not reproduce from the committed corpus"
    )
    sig = report["significance_alpha_f11"]
    assert sig["verdict"] == h["f11_verdict"]
    assert sig["hit_rate"] == pytest.approx(h["hit_rate"], abs=1e-6)
    assert [sig["total_ci_low"], sig["total_ci_high"]] == pytest.approx(
        h["f11_total_ci"], abs=0.005
    )
