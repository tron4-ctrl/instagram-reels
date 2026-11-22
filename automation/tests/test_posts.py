import hashlib
import json
import re
from io import BytesIO

from PIL import Image

from automation import sync_posts


def sample_metadata():
    return {
        "post_shortcode": "ABC_123",
        "post_url": "https://www.instagram.com/p/ABC_123/",
        "description": "Learn Java streams and Spring Boot #java",
        "username": "troy_creator",
        "fullname": "TROY Creator",
        "post_date": "2026-11-20T10:30:00",
        "sidecar_shortcode": "ABC_123",
        "display_url": "https://example.invalid/first.jpg",
    }


def test_post_shortcode_rules():
    assert sync_posts.canonical_shortcode("https://www.instagram.com/p/ABC_123/") == "ABC_123"
    assert sync_posts.canonical_shortcode("https://instagram.com/p/ABC_123/?img_index=2") == "ABC_123"
    assert sync_posts.canonical_shortcode("https://instagram.com/reel/ABC_123/") is None
    assert sync_posts.canonical_url("ABC_123") == "https://www.instagram.com/p/ABC_123/"


def test_record_uses_shared_classifier_and_carousel_preview_kind():
    record, info = sync_posts.make_record(
        sample_metadata(),
        "https://www.instagram.com/p/ABC_123/",
        [],
    )
    assert record["sc"] == "ABC_123"
    assert record["u"] == "https://www.instagram.com/p/ABC_123/"
    assert record["kind"] == "carousel"
    assert record["c"] == "Java / Programming Interview Prep"
    assert record["a"] == "troy_creator"
    assert record["dt"] == "2026-11-20"
    assert info["method"]


def test_single_image_kind_and_generic_title():
    item = {
        "username": "photo_user",
        "display_url": "https://example.invalid/image.jpg",
    }
    record, _ = sync_posts.make_record(item, "https://instagram.com/p/SINGLE1/", [])
    assert record["kind"] == "image"
    assert record["t"] == "Instagram Post SINGLE1"


def test_post_validation_rejects_reel_urls():
    record = {
        "sc": "ABC_123",
        "u": "https://www.instagram.com/reel/ABC_123/",
        "c": "General / Relatable & Miscellaneous Content",
        "kind": "image",
        "cov": 1,
        "img": "ABC_123.jpg",
        "sha": "0" * 64,
    }
    try:
        sync_posts.validate([record])
    except RuntimeError as exc:
        assert "URL mismatch" in str(exc)
    else:
        raise AssertionError("Reel URL was incorrectly accepted as a Post")


def test_media_host_allowlist_rejects_non_instagram_urls():
    assert sync_posts._is_instagram_media_host("https://scontent.cdninstagram.com/image.jpg")
    assert sync_posts._is_instagram_media_host("https://scontent-lhr8-1.fna.fbcdn.net/image.jpg")
    assert not sync_posts._is_instagram_media_host("https://example.invalid/image.jpg")
    assert not sync_posts._is_instagram_media_host("http://scontent.cdninstagram.com/image.jpg")


def test_gallery_metadata_merges_post_and_first_media_event(monkeypatch):
    class FakeResult:
        returncode = 0
        stderr = ""
        stdout = json.dumps([
            [2, {
                "post_shortcode": "ABC_123",
                "description": "Parent Post caption",
                "username": "troy_creator",
                "fullname": "TROY Creator",
                "post_date": "2026-11-20",
            }],
            [3, "https://scontent.cdninstagram.com/first.mp4", {
                "sidecar_shortcode": "ABC_123",
                "sidecar_media_id": "991122",
                "display_url": "https://scontent.cdninstagram.com/first-thumbnail.jpg",
                "video_url": "https://scontent.cdninstagram.com/first.mp4",
                "num": 1,
            }],
        ])

    captured = {}

    def fake_run(command, **kwargs):
        captured["command"] = command
        captured["kwargs"] = kwargs
        return FakeResult()

    monkeypatch.setattr(sync_posts.sync_reels, "_cookiefile_from_env", lambda: "/tmp/fake-cookies.txt")
    monkeypatch.setattr(sync_posts.subprocess, "run", fake_run)
    item = sync_posts.gallery_metadata("https://www.instagram.com/p/ABC_123/")
    assert item["_troy_image_url"].endswith("/first-thumbnail.jpg")
    assert item["description"] == "Parent Post caption"
    assert item["username"] == "troy_creator"
    assert item["sidecar_shortcode"] == "ABC_123"
    assert "--range" in captured["command"]
    assert captured["command"][captured["command"].index("--range") + 1] == "1"
    assert "--cookies" in captured["command"]
    assert captured["kwargs"]["timeout"] == 90


def test_gallery_metadata_reports_gallery_dl_error_event(monkeypatch):
    class FakeResult:
        returncode = 0
        stderr = ""
        stdout = json.dumps([[-1, {"error": "LoginRequired", "message": "login required"}]])

    monkeypatch.setattr(sync_posts.sync_reels, "_cookiefile_from_env", lambda: None)
    monkeypatch.setattr(sync_posts.subprocess, "run", lambda *args, **kwargs: FakeResult())
    try:
        sync_posts.gallery_metadata("https://www.instagram.com/p/ABC_123/")
    except RuntimeError as exc:
        assert "login required" in str(exc)
    else:
        raise AssertionError("gallery-dl error event was not reported")


def test_existing_post_is_immutable_except_duplicate_count(tmp_path, monkeypatch):
    image_bytes = b"first-preview-image"
    digest = hashlib.sha256(image_bytes).hexdigest()
    cover_dir = tmp_path / "post_covers"
    cover_dir.mkdir()
    (cover_dir / "EXISTING1.jpg").write_bytes(image_bytes)
    monkeypatch.setattr(sync_posts, "COVERS", cover_dir)

    base = {
        "sc": "EXISTING1",
        "u": "https://www.instagram.com/p/EXISTING1/",
        "t": "Existing title",
        "c": "Technology / Gadgets",
        "d": "Existing caption",
        "a": "Creator",
        "kind": "image",
        "cov": 1,
        "sha": digest,
        "dn": 1,
        "dt": "2026-11-20",
        "img": "EXISTING1.jpg",
        "ingested_at": "2026-11-20T00:00:00+00:00",
    }
    updated = dict(base, dn=2)
    sync_posts.validate([updated], expected_base=[base])

    changed = dict(updated, t="Changed title")
    try:
        sync_posts.validate([changed], expected_base=[base])
    except RuntimeError as exc:
        assert "existing Post changed" in str(exc)
    else:
        raise AssertionError("Existing Post content change was not rejected")

def test_image_normalization_limits_dimensions():
    # Exercise the Pillow behavior used by the processor without network access.
    source = BytesIO()
    Image.new("RGB", (2400, 1200), "navy").save(source, format="PNG")
    image = Image.open(BytesIO(source.getvalue()))
    image.thumbnail((sync_posts.MAX_IMAGE_EDGE, sync_posts.MAX_IMAGE_EDGE), Image.Resampling.LANCZOS)
    assert max(image.size) <= 1600


def test_process_publishes_post_and_first_preview(tmp_path, monkeypatch):
    data_path = tmp_path / "posts.json"
    data_path.write_text("[]", encoding="utf-8")
    cover_dir = tmp_path / "post_covers"
    cover_dir.mkdir()
    monkeypatch.setattr(sync_posts, "DATA", data_path)
    monkeypatch.setattr(sync_posts, "COVERS", cover_dir)
    monkeypatch.setattr(sync_posts, "LOG", tmp_path / "ingestion_log.jsonl")
    monkeypatch.setattr(sync_posts, "gallery_metadata", lambda url: sample_metadata())

    image_buffer = BytesIO()
    Image.new("RGB", (320, 240), "navy").save(image_buffer, format="JPEG")
    image_bytes = image_buffer.getvalue()
    image_sha = hashlib.sha256(image_bytes).hexdigest()
    monkeypatch.setattr(
        sync_posts,
        "download_first_image",
        lambda item: (image_bytes, image_sha),
    )
    monkeypatch.setattr(sync_posts.sync_reels, "append_log", lambda record: None)

    result = sync_posts.process("https://www.instagram.com/p/ABC_123/")
    records = json.loads(data_path.read_text(encoding="utf-8"))

    assert result["status"] == "added"
    assert result["type"] == "post"
    assert len(records) == 1
    assert records[0]["sc"] == "ABC_123"
    assert records[0]["kind"] == "carousel"
    assert records[0]["cov"] == 1
    assert (cover_dir / "ABC_123.jpg").read_bytes() == image_bytes


def test_process_skips_duplicate_without_downloading(tmp_path, monkeypatch):
    data_path = tmp_path / "posts.json"
    data_path.write_text(
        json.dumps([{"sc": "ABC_123"}]),
        encoding="utf-8",
    )
    monkeypatch.setattr(sync_posts, "DATA", data_path)
    monkeypatch.setattr(
        sync_posts,
        "gallery_metadata",
        lambda url: (_ for _ in ()).throw(AssertionError("duplicate should not download")),
    )

    result = sync_posts.process("https://www.instagram.com/p/ABC_123/")
    assert result["status"] == "duplicate"
    assert result["total"] == 1
