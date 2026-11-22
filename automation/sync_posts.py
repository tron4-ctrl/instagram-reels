#!/usr/bin/env python3
"""Incrementally ingest Instagram photo/video Posts into the TROY library.

Post pipeline:
URL -> shortcode dedup -> gallery-dl first-media metadata -> first-image
preview -> shared TROY classifier -> staged update -> independent validation.

Only the first media item is stored. Carousel users open the original Instagram
post to view the remaining slides. Reel data and Reel ingestion are untouched.
"""
from __future__ import annotations

import hashlib
import http.cookiejar
import json
import re
import subprocess
import sys
from collections import Counter
from datetime import datetime, timezone
from io import BytesIO
from pathlib import Path
from urllib.parse import urlparse
from urllib.request import HTTPCookieProcessor, Request, build_opener

from PIL import Image, ImageOps

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from automation import sync_reels

DATA = ROOT / "data" / "posts.json"
COVERS = ROOT / "post_covers"
LOG = ROOT / "automation" / "ingestion_log.jsonl"
COOKIE_FILE = Path("/tmp/instagram-cookies.txt")

URL_RE = re.compile(
    r"^https?://(?:www\.)?instagram\.com/p/([A-Za-z0-9_-]+)(?:/)?(?:[?#].*)?$",
    re.I,
)
MAX_DOWNLOAD_BYTES = 25 * 1024 * 1024
MAX_IMAGE_EDGE = 1600
MIN_IMAGE_BYTES = 1000
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
)


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def canonical_shortcode(url: str) -> str | None:
    match = URL_RE.match(str(url).strip())
    return match.group(1) if match else None


def canonical_url(shortcode: str) -> str:
    return f"https://www.instagram.com/p/{shortcode}/"


def load_posts() -> list[dict]:
    if not DATA.exists():
        return []
    value = json.loads(DATA.read_text(encoding="utf-8"))
    if not isinstance(value, list):
        raise RuntimeError("data/posts.json must contain a JSON array")
    return value


def _gallery_events(stdout: str) -> tuple[dict, list[dict], list[dict]]:
    """Decode gallery-dl's event-array JSON and tolerate JSONL output too."""
    payload = None
    try:
        payload = json.loads(stdout.strip())
    except json.JSONDecodeError:
        payload = []
        for line in stdout.splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                payload.append(json.loads(line))
            except json.JSONDecodeError:
                continue

    if not isinstance(payload, list):
        payload = [payload]

    post_metadata: dict = {}
    file_events: list[dict] = []
    errors: list[dict] = []

    for event in payload:
        if isinstance(event, dict):
            if event.get("error"):
                errors.append(event)
            elif event.get("display_url") or event.get("url"):
                file_events.append(event)
            continue

        if not isinstance(event, list) or not event:
            continue

        # gallery-dl Message.Directory = 2, Message.Url = 3.
        message_type = event[0]
        if message_type == 2:
            # Current DataJob emits [2, metadata]; accept [2, unused, metadata]
            # too, matching the public message protocol documentation.
            metadata = next((v for v in reversed(event[1:]) if isinstance(v, dict)), {})
            post_metadata.update(metadata)
        elif message_type == 3:
            media_url = event[1] if len(event) > 1 and isinstance(event[1], str) else ""
            media_metadata = event[2] if len(event) > 2 and isinstance(event[2], dict) else {}
            merged = {**post_metadata, **media_metadata}
            if media_url or merged.get("display_url") or merged.get("thumbnail_url") or merged.get("url"):
                # Prefer Instagram's image rendition. The gallery-dl file URL can
                # be an MP4 when the first carousel slide is a video.
                merged["_troy_image_url"] = (
                    merged.get("display_url")
                    or merged.get("thumbnail_url")
                    or media_url
                    or merged.get("url")
                )
                file_events.append(merged)
        elif message_type == -1 and len(event) > 1 and isinstance(event[1], dict):
            errors.append(event[1])

    return post_metadata, file_events, errors


def gallery_metadata(url: str) -> dict:
    """Return Post-level metadata merged with only the first media item."""
    cookiefile = sync_reels._cookiefile_from_env()
    command = [
        sys.executable,
        "-m",
        "gallery_dl",
        # Instagram's REST media endpoint can return 401 for public posts
        # when accessed without a logged-in session. GraphQL is a separate
        # supported gallery-dl API mode and is the no-cookie path we test first.
        "--option",
        "api=graphql",
        "--range",
        "1",
        "--dump-json",
        "--no-input",
    ]
    if cookiefile:
        command.extend(["--cookies", cookiefile])
    command.append(url)

    try:
        result = subprocess.run(
            command,
            capture_output=True,
            text=True,
            timeout=90,
            check=False,
        )
    except FileNotFoundError as exc:
        raise RuntimeError(
            "gallery-dl is not installed. Install automation/requirements.txt first."
        ) from exc
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError("Instagram Post metadata request timed out") from exc

    post_metadata, candidates, errors = _gallery_events(result.stdout or "")
    if result.returncode != 0 or not candidates:
        if errors:
            detail = errors[0].get("message") or errors[0].get("error") or str(errors[0])
        else:
            detail = (result.stderr or result.stdout or "No first-media metadata returned").strip()
        raise RuntimeError(f"Instagram Post extraction failed: {str(detail)[-1200:]}")

    # gallery-dl's --range 1 should emit one file event. Preserve the parent
    # post shortcode/caption/creator as well as first-slide metadata.
    item = {**post_metadata, **candidates[0]}
    image_url = item.get("_troy_image_url") or item.get("display_url") or item.get("url")
    if not image_url:
        raise RuntimeError("Instagram returned Post metadata but no first-image URL was available")
    item["_troy_image_url"] = image_url
    return item


def _is_instagram_media_host(url: str) -> bool:
    parsed = urlparse(url)
    host = (parsed.hostname or "").lower().rstrip(".")
    return parsed.scheme == "https" and (
        host.endswith(".cdninstagram.com") or host.endswith(".fbcdn.net")
    )


def _cookie_opener():
    jar = http.cookiejar.MozillaCookieJar()
    if COOKIE_FILE.exists():
        try:
            jar.load(ignore_discard=True, ignore_expires=True)
        except Exception as exc:
            raise RuntimeError(
                "Instagram cookies could not be read as a Netscape cookie file"
            ) from exc
    return build_opener(HTTPCookieProcessor(jar))


def download_first_image(item: dict) -> tuple[bytes, str]:
    image_url = item.get("_troy_image_url") or item.get("display_url") or item.get("url")
    if not isinstance(image_url, str) or not _is_instagram_media_host(image_url):
        raise RuntimeError("Instagram did not return a trusted HTTPS media URL")

    request = Request(
        image_url,
        headers={
            "User-Agent": USER_AGENT,
            "Referer": "https://www.instagram.com/",
            "Accept": "image/avif,image/webp,image/apng,image/*,*/*;q=0.8",
        },
    )
    try:
        with _cookie_opener().open(request, timeout=45) as response:
            if not _is_instagram_media_host(response.geturl()):
                raise RuntimeError("Post preview redirected outside Instagram media domains")
            raw = response.read(MAX_DOWNLOAD_BYTES + 1)
    except Exception as exc:
        raise RuntimeError(f"Post preview image download failed: {exc}") from exc

    if len(raw) > MAX_DOWNLOAD_BYTES:
        raise RuntimeError("Post preview image exceeds the 25 MB safety limit")
    if len(raw) < MIN_IMAGE_BYTES:
        raise RuntimeError(f"Post preview image is too small: {len(raw)} bytes")

    try:
        with Image.open(BytesIO(raw)) as image:
            image.verify()
        with Image.open(BytesIO(raw)) as image:
            image = ImageOps.exif_transpose(image)
            if image.mode in ("RGBA", "LA") or "transparency" in image.info:
                rgba = image.convert("RGBA")
                background = Image.new("RGB", rgba.size, "white")
                background.paste(rgba, mask=rgba.getchannel("A"))
                image = background
            else:
                image = image.convert("RGB")

            image.thumbnail(
                (MAX_IMAGE_EDGE, MAX_IMAGE_EDGE),
                Image.Resampling.LANCZOS,
            )
            output = BytesIO()
            image.save(output, format="JPEG", quality=90, optimize=True, progressive=True)
            data = output.getvalue()
    except Exception as exc:
        raise RuntimeError(f"Post preview is not a valid decodable image: {exc}") from exc

    return data, hashlib.sha256(data).hexdigest()


def _post_date(item: dict) -> str | None:
    value = item.get("post_date") or item.get("date") or item.get("timestamp")
    if isinstance(value, (int, float)):
        return datetime.fromtimestamp(value, timezone.utc).date().isoformat()
    if not value:
        return None
    text = str(value).strip()
    match = re.match(r"^(\d{4}-\d{2}-\d{2})", text)
    if match:
        return match.group(1)
    if re.fullmatch(r"\d{8}", text):
        return f"{text[:4]}-{text[4:6]}-{text[6:8]}"
    return None


def make_record(item: dict, url: str, existing: list[dict]) -> tuple[dict, dict]:
    shortcode = canonical_shortcode(url)
    if not shortcode:
        raise RuntimeError("invalid Instagram Post URL")

    description = str(item.get("description") or item.get("caption") or "")
    # The frontend prefixes this field with @, so prefer the actual handle.
    author = str(
        item.get("username")
        or item.get("author_username")
        or item.get("uploader_id")
        or item.get("fullname")
        or item.get("full_name")
        or item.get("author")
        or ""
    )
    supplied_title = item.get("title") or item.get("post_title") or ""
    title = sync_reels._derive_display_title(supplied_title, description, author)
    if not title or title == "Instagram Reel":
        title = f"Instagram Post {shortcode}"

    is_carousel = bool(item.get("sidecar_shortcode") or item.get("sidecar_media_id"))
    kind = "carousel" if is_carousel else ("video" if item.get("video_url") else "image")

    record = {
        "sc": shortcode,
        "u": canonical_url(shortcode),
        "t": str(title)[:1000],
        "c": "",
        "d": description[:10000],
        "a": author[:300],
        "kind": kind,
        "cov": 0,
        "sha": "",
        "dn": 1,
        "dt": _post_date(item),
        "img": f"{shortcode}.jpg",
        "ingested_at": now(),
    }

    category, score, method = sync_reels.classify(
        record,
        existing + sync_reels.load_json(sync_reels.DATA, []),
    )
    record["c"] = category
    record["cat_score"] = round(score, 4)
    record["cat_method"] = method
    return record, {"category": category, "score": score, "method": method}


def validate(records: list[dict], expected_base: list[dict] | None = None) -> None:
    shortcodes = [record.get("sc") for record in records]
    if len(shortcodes) != len(set(shortcodes)):
        raise RuntimeError("duplicate Post shortcodes detected")

    if expected_base is not None:
        new_by_shortcode = {record.get("sc"): record for record in records}
        for old in expected_base:
            current = new_by_shortcode.get(old.get("sc"))
            if current is None:
                raise RuntimeError(
                    f"regression: existing Post removed: {old.get('sc')}"
                )
            # dn is recalculated when another Post shares the same preview hash.
            for key, old_value in old.items():
                if key == "dn":
                    continue
                if current.get(key) != old_value:
                    raise RuntimeError(
                        f"regression: existing Post changed: {old.get('sc')} ({key})"
                    )

    for record in records:
        shortcode = record.get("sc", "")
        if not re.fullmatch(r"[A-Za-z0-9_-]+", shortcode):
            raise RuntimeError(f"invalid Post shortcode: {shortcode}")
        if record.get("u") != canonical_url(shortcode):
            raise RuntimeError(f"Post URL mismatch: {shortcode}")
        if not record.get("c"):
            raise RuntimeError(f"missing Post category: {shortcode}")
        if record.get("kind") not in {"image", "carousel", "video"}:
            raise RuntimeError(f"invalid Post kind: {shortcode}")
        if record.get("cov") != 1:
            raise RuntimeError(f"Post preview is not marked available: {shortcode}")
        if record.get("img") != f"{shortcode}.jpg":
            raise RuntimeError(f"non-deterministic Post preview filename: {shortcode}")
        if not re.fullmatch(r"[0-9a-f]{64}", str(record.get("sha", ""))):
            raise RuntimeError(f"invalid Post preview SHA-256: {shortcode}")

        cover_path = COVERS / record["img"]
        if not cover_path.exists():
            raise RuntimeError(f"missing Post preview file: {shortcode}")
        digest = hashlib.sha256(cover_path.read_bytes()).hexdigest()
        if digest != record.get("sha"):
            raise RuntimeError(f"Post preview hash mismatch: {shortcode}")


def _recalculate_duplicate_counts(records: list[dict]) -> Counter:
    counts = Counter(record.get("sha") for record in records if record.get("sha"))
    for record in records:
        record["dn"] = counts.get(record.get("sha"), 1) if record.get("sha") else 1
    return counts


def publish(records: list[dict], base: list[dict]) -> None:
    validate(records, expected_base=base)
    _recalculate_duplicate_counts(records)
    original = DATA.read_bytes() if DATA.exists() else None
    try:
        sync_reels.write_json_atomic(DATA, records)
        validate(records, expected_base=base)
    except Exception:
        if original is None:
            DATA.unlink(missing_ok=True)
        else:
            DATA.write_bytes(original)
        raise


def process(url: str, dry: bool = False) -> dict:
    records = load_posts()
    shortcode = canonical_shortcode(url)
    if not shortcode:
        return {
            "status": "ignored",
            "type": "post",
            "reason": "not a valid Instagram Post URL",
        }

    if any(record.get("sc") == shortcode for record in records):
        return {
            "status": "duplicate",
            "type": "post",
            "shortcode": shortcode,
            "total": len(records),
        }

    canonical = canonical_url(shortcode)
    item = gallery_metadata(canonical)
    record, category_info = make_record(item, canonical, records)
    cover_data, sha = download_first_image(item)

    if dry:
        return {
            "status": "dry_run",
            "type": "post",
            "shortcode": shortcode,
            "category": record["c"],
            "kind": record["kind"],
            "cover_sha256": sha,
            "would_total": len(records) + 1,
        }

    COVERS.mkdir(parents=True, exist_ok=True)
    cover_path = COVERS / f"{shortcode}.jpg"
    staged_cover = cover_path.with_suffix(".jpg.tmp")
    staged_cover.write_bytes(cover_data)

    if hashlib.sha256(staged_cover.read_bytes()).hexdigest() != sha:
        staged_cover.unlink(missing_ok=True)
        raise RuntimeError("staged Post preview SHA-256 mismatch")

    record["cov"] = 1
    record["sha"] = sha
    record["dn"] = 1

    previous_cover = cover_path.read_bytes() if cover_path.exists() else None
    try:
        staged_cover.replace(cover_path)
        new_records = [record] + records
        publish(new_records, base=records)
        try:
            sync_reels.append_log({
                "status": "added",
                "type": "post",
                "shortcode": shortcode,
                "category": record["c"],
                "category_method": category_info["method"],
                "category_score": category_info["score"],
                "kind": record["kind"],
                "total": len(new_records),
                "cover_sha256": sha,
            })
        except OSError:
            # A logging failure must not undo a successfully validated publish.
            pass
        return {
            "status": "added",
            "type": "post",
            "shortcode": shortcode,
            "category": record["c"],
            "kind": record["kind"],
            "total": len(new_records),
            "cover_sha256": sha,
        }
    except Exception:
        if previous_cover is None:
            cover_path.unlink(missing_ok=True)
        else:
            cover_path.write_bytes(previous_cover)
        raise


def main(argv: list[str]) -> None:
    if len(argv) < 2:
        raise SystemExit("usage: sync_posts.py URL [URL ...]")
    results = []
    for url in argv[1:]:
        try:
            results.append(process(url))
        except Exception as exc:
            sync_reels.append_log({
                "status": "error",
                "type": "post",
                "url": url,
                "reason": str(exc),
            })
            results.append({
                "status": "error",
                "type": "post",
                "url": url,
                "reason": str(exc),
            })
    print(json.dumps(results, ensure_ascii=False))


if __name__ == "__main__":
    main(sys.argv)
