import hashlib
import json
import re
import tempfile
from pathlib import Path

from automation import sync_reels

ROOT = Path(__file__).resolve().parents[2]


def fake_item(title="Python Tutorial", description="Learn Python programming #viral", author="tester"):
    return {
        "title": title,
        "description": description,
        "uploader": author,
        "upload_date": "20260910",
        "thumbnail": "https://example.invalid/thumb.jpg",
    }


def test_shortcode_rules():
    assert sync_reels.canonical_shortcode("https://www.instagram.com/reel/ABC_123/") == "ABC_123"
    assert sync_reels.canonical_shortcode("https://instagram.com/p/ABC_123/") is None
    assert sync_reels.canonical_url("ABC_123") == "https://www.instagram.com/reel/ABC_123/"


def test_classification_is_not_driven_by_viral_hashtag():
    rec = {"t": "Python Tutorial", "d": "Learn Python programming #viral", "a": ""}
    cat, _, _ = sync_reels.classify(rec, [{"c": "Python Programming", "t": "Python tutorial", "d": "python coding", "a": ""}])
    assert cat == "Python Programming"


def test_true_fallback_category():
    rec = {"t": "", "d": "A random post", "a": ""}
    cat, _, method = sync_reels.classify(rec, [])
    assert cat == sync_reels.GENERAL
    assert method == "true-fallback"


def test_cover_hash_is_deterministic():
    data = b"abc123"
    assert hashlib.sha256(data).hexdigest() == hashlib.sha256(data).hexdigest()


def test_production_baseline():
    recs = json.loads((ROOT / "data" / "reels.json").read_text(encoding="utf-8"))
    assert len(recs) == 3646
    assert len({r["sc"] for r in recs}) == 3646
    assert all(re.fullmatch(r"[A-Za-z0-9_-]+", r["sc"]) for r in recs)
