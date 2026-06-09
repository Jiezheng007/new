"""Acceptance tests for Phase 4 / Issue 6: analysis + risk scoring.

Covers:
  - KeywordNlpProvider sentiment + confidence for sample Chinese text
  - compute_risk factor math + level mapping (using seeded DB)
  - analyze_opinion persists AnalysisResult and never raises on failure
  - analyze_batch runs against ingestion sample_ids
  - POST /api/opinions/{id}/analyze happy path + RBAC + audit
  - POST /api/opinions/analyze-pending re-runs missing items
  - List filters: sentiment, risk_level, analysis_status
  - Re-analysis replaces the prior result (one-to-one)
  - Web UI page renders without errors for risk_control
"""
from __future__ import annotations

import json

import pytest
from sqlalchemy.orm import Session

from app.db import session as session_module
from app.models.analysis import (
    ANALYSIS_STATUS_FAILED,
    ANALYSIS_STATUS_SUCCESS,
    AnalysisResult,
)
from app.models.audit import AuditLog
from app.models.datasource import DataSource, OpinionItem
from app.models.rule import (
    RiskThreshold,
    SensitiveKeyword,
    SubjectKeyword,
)
from app.services.analysis import (
    analyze_batch,
    analyze_opinion,
    pending_opinions,
)
from app.services.nlp import (
    BaseNlpProvider,
    NlpResult,
    SENTIMENT_NEGATIVE,
    SENTIMENT_POSITIVE,
    get_nlp_provider,
    reset_nlp_provider_cache,
)
from app.services.nlp.keyword import KeywordNlpProvider
from app.services.scoring import (
    SENSITIVE_SEVERITY_CONTRIB,
    TOTAL_CAP,
    compute_risk,
)


def _engine():
    return session_module.engine


def _session():
    return Session(_engine())


def _latest_audit(action: str, target_id: str = ""):
    db = _session()
    try:
        q = db.query(AuditLog).filter(AuditLog.action == action)
        if target_id:
            q = q.filter(AuditLog.target_id == target_id)
        return q.order_by(AuditLog.id.desc()).first()
    finally:
        db.close()


def _seed_static_demo(client):
    client.post("/api/auth/login", json={"username": "admin", "password": "admin123"})
    db = _session()
    try:
        src = db.query(DataSource).filter(DataSource.code == "demo_static").one()
        source_id = src.id
    finally:
        db.close()
    res = client.post(f"/api/datasources/{source_id}/fetch")
    assert res.status_code == 200, res.text
    client.post("/api/auth/logout")
    return source_id


# ---------- NLP provider ----------

def test_get_nlp_provider_default_is_keyword():
    reset_nlp_provider_cache()
    provider = get_nlp_provider()
    assert isinstance(provider, KeywordNlpProvider)
    assert provider.name == "keyword_nlp"


def test_keyword_provider_positive():
    result = KeywordNlpProvider().analyze("营收同比增长,新业务取得突破,获得客户好评", language="zh")
    assert result.sentiment == SENTIMENT_POSITIVE
    assert result.error_message is None
    assert 0.5 <= result.confidence <= 0.95


def test_keyword_provider_negative():
    result = KeywordNlpProvider().analyze("产品出现严重质量问题,涉及安全事故,被监管部门查处", language="zh")
    assert result.sentiment == SENTIMENT_NEGATIVE
    assert result.error_message is None


def test_keyword_provider_neutral_for_empty_text():
    result = KeywordNlpProvider().analyze("", language="zh")
    assert result.sentiment == "neutral"


def test_keyword_provider_unsupported_language_records_error():
    result = KeywordNlpProvider().analyze("anything", language="fr")
    assert result.sentiment == "neutral"
    assert result.error_message is not None
    assert "unsupported_language" in result.error_message


# ---------- scoring ----------

def test_compute_risk_for_negative_demo_item_persists_high(client):
    """Static demo item 003 has both sensitive (重大 / 安全 / 严重) and
    subject (监管部门 / 某品牌) hits, plus negative sentiment, so the
    score should land in the high or severe band."""
    _seed_static_demo(client)
    db = _session()
    try:
        item = (
            db.query(OpinionItem)
            .filter(OpinionItem.external_id == "demo-003")
            .one()
        )
        text = f"{item.title}\n{item.content}"
        nlp = KeywordNlpProvider().analyze(text, language="zh")
        assert nlp.sentiment == SENTIMENT_NEGATIVE
        result = compute_risk(db, item, nlp)
        score = result.score
        level = result.level
        explanation = list(result.explanation)
        sensitive_breakdown = result.factors["sensitive_keywords"]["hits"]
    finally:
        db.close()
    assert score >= 60
    assert level in {"high", "severe"}
    assert any("重大" in line or "严重" in line for line in explanation)
    assert any(h["keyword"] == "重大" for h in sensitive_breakdown)


def test_compute_risk_handles_missing_published_at():
    db = _session()
    try:
        opinion = OpinionItem(
            source_id=1,
            source_code="x",
            source_type="x",
            title="x",
            content="重大 严重 安全 事故 违规 投诉",  # 6 distinct keywords
            content_hash="x" * 32,
            published_at=None,
        )
        nlp = NlpResult(sentiment=SENTIMENT_NEGATIVE, confidence=0.7)
        result = compute_risk(db, opinion, nlp)
        score = result.score
        heat = result.factors["heat"]["contribution"]
    finally:
        db.close()
    assert heat == 0
    # sentiment 25 + sensitive 40 (capped) + source 4 + heat 0 = 69
    assert score == 69


def test_compute_risk_total_is_capped_at_100():
    db = _session()
    try:
        # Multiple distinct keywords, negative sentiment, but no published_at
        # so heat is 0. Total must be capped at TOTAL_CAP.
        opinion = OpinionItem(
            source_id=1,
            source_code="x",
            source_type="x",
            title="x",
            content="重大 严重 安全 事故 违规 投诉 召回 泄露",
            content_hash="x" * 32,
        )
        nlp = NlpResult(sentiment=SENTIMENT_NEGATIVE, confidence=1.0)
        result = compute_risk(db, opinion, nlp)
        score = result.score
        level = result.level
    finally:
        db.close()
    assert score <= TOTAL_CAP
    # sentiment 25 + sens 40 (capped) + source 4 + heat 0 = 69 → "high"
    assert score == 69
    assert level == "high"


def test_compute_risk_uses_severity_weight_table():
    """Severe hits must score more than high hits, and high more than medium."""
    db = _session()
    try:
        # 1 severe hit
        severe_op = OpinionItem(
            source_id=1, source_code="x", source_type="x", title="x",
            content="安全", content_hash="a" * 32,
        )
        # 1 high hit
        high_op = OpinionItem(
            source_id=1, source_code="x", source_type="x", title="x",
            content="重大", content_hash="b" * 32,
        )
        # 1 medium hit
        med_op = OpinionItem(
            source_id=1, source_code="x", source_type="x", title="x",
            content="违规", content_hash="c" * 32,
        )
        nlp = NlpResult(sentiment=SENTIMENT_POSITIVE, confidence=0.5)
        severe_score = compute_risk(db, severe_op, nlp).score
        high_score = compute_risk(db, high_op, nlp).score
        med_score = compute_risk(db, med_op, nlp).score
    finally:
        db.close()
    assert severe_score > high_score > med_score
    assert severe_score - med_score == (
        SENSITIVE_SEVERITY_CONTRIB["severe"] - SENSITIVE_SEVERITY_CONTRIB["medium"]
    )


def test_compute_risk_factor_breakdown_persists_caps():
    db = _session()
    try:
        opinion = OpinionItem(
            source_id=1, source_code="x", source_type="x", title="x",
            content="重大 严重 安全 事故 违规 投诉",  # 6 distinct → cap kicks in
            content_hash="x" * 32,
        )
        nlp = NlpResult(sentiment=SENTIMENT_POSITIVE, confidence=0.5)
        result = compute_risk(db, opinion, nlp)
        factors = result.factors
        sens = factors["sensitive_keywords"]
    finally:
        db.close()
    assert sens["contribution"] == 40
    # raw is the sum of severity weights for the 6 distinct hits
    expected_raw = (
        SENSITIVE_SEVERITY_CONTRIB["high"]   # 重大
        + SENSITIVE_SEVERITY_CONTRIB["high"]  # 严重
        + SENSITIVE_SEVERITY_CONTRIB["severe"]  # 安全
        + SENSITIVE_SEVERITY_CONTRIB["severe"]  # 事故
        + SENSITIVE_SEVERITY_CONTRIB["medium"]  # 违规
        + SENSITIVE_SEVERITY_CONTRIB["low"]   # 投诉
    )
    assert sens["raw_contribution"] == expected_raw


# ---------- analyze_opinion / analyze_batch ----------

def test_analyze_opinion_persists_success_row(client):
    _seed_static_demo(client)
    db = _session()
    try:
        item = db.query(OpinionItem).order_by(OpinionItem.id.asc()).first()
        result = analyze_opinion(db, item)
        db.commit()
        status = result.status
        sentiment = result.sentiment
        score = result.score
        level = result.level

        stored = (
            db.query(AnalysisResult)
            .filter(AnalysisResult.opinion_item_id == item.id)
            .one()
        )
        stored_status = stored.status
    finally:
        db.close()
    assert status == ANALYSIS_STATUS_SUCCESS
    assert sentiment in {"positive", "neutral", "negative"}
    assert score is not None
    assert level in {"low", "medium", "high", "severe"}
    assert stored_status == ANALYSIS_STATUS_SUCCESS


def test_analyze_opinion_records_failed_status_for_unsupported_language(client):
    """A 'fr' opinion should produce a failed analysis row, never raise."""
    _seed_static_demo(client)
    db = _session()
    try:
        item = db.query(OpinionItem).order_by(OpinionItem.id.asc()).first()
        item.language = "fr"
        db.commit()
        result = analyze_opinion(db, item)
        db.commit()
        status = result.status
        err = result.error_message
    finally:
        db.close()
    assert status == ANALYSIS_STATUS_FAILED
    assert err is not None
    assert "unsupported_language" in err


def test_analyze_batch_runs_on_multiple_items(client):
    """Auto-analysis runs against the freshly inserted items, so the demo
    seed + the analysis side-effect should leave every opinion with a
    successful analysis result."""
    _seed_static_demo(client)
    db = _session()
    try:
        statuses = [
            row.status
            for row in db.query(AnalysisResult.status).all()
        ]
    finally:
        db.close()
    assert len(statuses) >= 3
    assert all(s == ANALYSIS_STATUS_SUCCESS for s in statuses)


def test_analyze_opinion_replaces_existing_row(client):
    """Re-analyzing the same opinion must not create a second row."""
    _seed_static_demo(client)
    client.post("/api/auth/login", json={"username": "risk", "password": "risk123"})
    res1 = client.post("/api/opinions/1/analyze")
    res2 = client.post("/api/opinions/1/analyze")
    assert res1.status_code == 200
    assert res2.status_code == 200
    client.post("/api/auth/logout")

    db = _session()
    try:
        count = (
            db.query(AnalysisResult)
            .filter(AnalysisResult.opinion_item_id == 1)
            .count()
        )
    finally:
        db.close()
    assert count == 1


def test_pending_opinions_returns_items_with_failed_analysis(client):
    """An item whose analysis row is failed must show up in pending_opinions."""
    _seed_static_demo(client)
    db = _session()
    try:
        target_id = db.query(OpinionItem).order_by(OpinionItem.id.asc()).first().id
        row = (
            db.query(AnalysisResult)
            .filter(AnalysisResult.opinion_item_id == target_id)
            .one()
        )
        row.status = ANALYSIS_STATUS_FAILED
        row.error_message = "synthetic"
        db.commit()
        pending_ids = {o.id for o in pending_opinions(db, limit=10)}
    finally:
        db.close()
    assert target_id in pending_ids


# ---------- API: /api/opinions/{id}/analyze ----------

def test_analyze_endpoint_requires_auth(client):
    res = client.post("/api/opinions/1/analyze")
    assert res.status_code == 401


def test_analyze_endpoint_blocks_handler_and_viewer(client):
    _seed_static_demo(client)
    for user, pwd in [("handler", "handler123"), ("viewer", "viewer123"), ("auditor", "auditor123")]:
        client.post("/api/auth/login", json={"username": user, "password": pwd})
        res = client.post("/api/opinions/1/analyze")
        assert res.status_code == 403, user
        client.post("/api/auth/logout")


def test_analyze_endpoint_happy_path_writes_audit(client):
    _seed_static_demo(client)
    client.post("/api/auth/login", json={"username": "risk", "password": "risk123"})
    res = client.post("/api/opinions/1/analyze")
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["status"] == "success"
    assert body["risk_level"] in {"low", "medium", "high", "severe"}
    assert body["risk_score"] is not None

    entry = _latest_audit("opinion.analyze", "1")
    assert entry is not None
    detail = json.loads(entry.detail)
    assert detail["status"] == "success"
    assert detail["risk_level"] == body["risk_level"]


def test_analyze_endpoint_404_for_missing_opinion(client):
    client.post("/api/auth/login", json={"username": "admin", "password": "admin123"})
    res = client.post("/api/opinions/99999/analyze")
    assert res.status_code == 404


# ---------- API: /api/opinions/analyze-pending ----------

def test_analyze_pending_runs_on_missing_items(client):
    _seed_static_demo(client)
    db = _session()
    try:
        db.query(AnalysisResult).delete()
        db.commit()
    finally:
        db.close()
    client.post("/api/auth/login", json={"username": "admin", "password": "admin123"})
    res = client.post("/api/opinions/analyze-pending?limit=20")
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["requested"] >= 6
    assert body["succeeded"] >= 6
    assert body["failed"] == 0


def test_analyze_pending_blocked_for_handler(client):
    client.post("/api/auth/login", json={"username": "handler", "password": "handler123"})
    res = client.post("/api/opinions/analyze-pending")
    assert res.status_code == 403


# ---------- API: list filters ----------

def test_list_opinions_sentiment_filter(client):
    _seed_static_demo(client)
    client.post("/api/auth/login", json={"username": "risk", "password": "risk123"})
    res = client.get("/api/opinions?sentiment=negative")
    assert res.status_code == 200
    for it in res.json()["items"]:
        assert it["analysis"]["sentiment"] == "negative"


def test_list_opinions_risk_level_filter(client):
    _seed_static_demo(client)
    client.post("/api/auth/login", json={"username": "risk", "password": "risk123"})
    res = client.get("/api/opinions?risk_level=high")
    assert res.status_code == 200
    items = res.json()["items"]
    assert items  # at least one high-risk item should be present
    for it in items:
        assert it["analysis"]["level"] == "high"


def test_list_opinions_analysis_status_filter(client):
    _seed_static_demo(client)
    client.post("/api/auth/login", json={"username": "risk", "password": "risk123"})
    res = client.get("/api/opinions?analysis_status=success")
    assert res.status_code == 200
    for it in res.json()["items"]:
        assert it["analysis"]["status"] == "success"


def test_list_opinions_filter_validation(client):
    _seed_static_demo(client)
    client.post("/api/auth/login", json={"username": "risk", "password": "risk123"})
    for bad in ["sentiment=banana", "risk_level=extreme", "analysis_status=oops"]:
        res = client.get(f"/api/opinions?{bad}")
        assert res.status_code == 400, bad


# ---------- threshold re-mapping ----------

def test_threshold_change_re_maps_level_on_reanalysis(client):
    """Re-analysis after a threshold change must use the new mapping."""
    _seed_static_demo(client)

    # Find an opinion that scores high (demo-003 or demo-004 should).
    client.post("/api/auth/login", json={"username": "risk", "password": "risk123"})
    res = client.get("/api/opinions?risk_level=high&limit=1")
    assert res.status_code == 200
    items = res.json()["items"]
    assert items, "expected at least one high-risk opinion from the seeded demo"
    target_id = items[0]["id"]
    first_score = items[0]["analysis"]["score"]
    first_level = items[0]["analysis"]["level"]
    client.post("/api/auth/logout")

    # Make the "high" band harder to reach (score must be >= 95) and
    # "severe" effectively only fires on a perfect 100, so the same
    # numeric score re-maps downward.
    client.post("/api/auth/login", json={"username": "admin", "password": "admin123"})
    res = client.put(
        "/api/rules/thresholds",
        json={
            "thresholds": [
                {"level": "low", "min_score": 0},
                {"level": "medium", "min_score": 30},
                {"level": "high", "min_score": 95},
                {"level": "severe", "min_score": 100},
            ]
        },
    )
    assert res.status_code == 200, res.text
    client.post("/api/auth/logout")

    client.post("/api/auth/login", json={"username": "risk", "password": "risk123"})
    res = client.post(f"/api/opinions/{target_id}/analyze")
    assert res.status_code == 200
    new_level = res.json()["risk_level"]
    new_score = res.json()["risk_score"]
    client.post("/api/auth/logout")
    assert new_score == first_score
    assert new_level != first_level  # threshold change must remap
    assert new_level in {"medium", "high"}  # the score can only be in these bands now


# ---------- web UI ----------

def test_opinions_page_renders_with_analysis_columns(client):
    _seed_static_demo(client)
    client.post("/api/auth/login", json={"username": "risk", "password": "risk123"})
    res = client.get("/web/opinions")
    assert res.status_code == 200, res.text
    body = res.text
    assert "情感" in body
    assert "风险等级" in body
    assert "分析状态" in body
    assert "重新分析" in body
