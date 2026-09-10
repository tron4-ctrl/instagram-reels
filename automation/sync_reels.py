#!/usr/bin/env python3
"""Incrementally ingest Instagram Reels into the static site.

Free, fail-safe pipeline:
URL -> shortcode dedup -> yt-dlp metadata/thumbnail -> exact image validation
-> deterministic high-accuracy category -> staged update -> full validation.
No paid services are required.
"""
from __future__ import annotations

import base64
import hashlib
import json
import math
import os
import re
import shutil
import subprocess
import sys
import tempfile
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data" / "reels.json"
META = ROOT / "data" / "meta.json"
COVER_INDEX = ROOT / "data" / "cover_index.json"
COVERS = ROOT / "reel_covers"
AUTOMATION = ROOT / "automation"
LOG = AUTOMATION / "ingestion_log.jsonl"
COOKIE_FILE = Path("/tmp/instagram-cookies.txt")

URL_RE = re.compile(
    r"^https?://(?:www\.)?instagram\.com/reel/([A-Za-z0-9_-]+)(?:/)?(?:[?#].*)?$",
    re.I,
)
STOP = set(
    "the a an and or for to of in on at from with by this that is are was were be been as it its i me my you your we our they their these those about into over under after than then not no yes how what when where which who why via more most some any all just only very can could would should will may might has have had do does did if but so too also now".split()
)
GENERAL = "General / Relatable & Miscellaneous Content"
VIRAL = "Viral Clips / Trending Reels"


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def canonical_shortcode(url: str) -> str | None:
    m = URL_RE.match(str(url).strip())
    return m.group(1) if m else None


def canonical_url(sc: str) -> str:
    return f"https://www.instagram.com/reel/{sc}/"


def load_json(path: Path, default):
    if not path.exists():
        return default
    return json.loads(path.read_text("utf-8"))


def write_json_atomic(path: Path, obj) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(prefix=path.name + ".", suffix=".tmp", dir=path.parent)
    os.close(fd)
    tmp = Path(tmp_name)
    try:
        tmp.write_text(json.dumps(obj, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
        os.replace(tmp, path)
    finally:
        if tmp.exists():
            tmp.unlink(missing_ok=True)


def append_log(entry: dict) -> None:
    LOG.parent.mkdir(parents=True, exist_ok=True)
    with LOG.open("a", encoding="utf-8") as f:
        f.write(json.dumps({"timestamp": now(), **entry}, ensure_ascii=False) + "\n")


def tokenize(text: str) -> set[str]:
    text = (text or "").lower()
    text = re.sub(r"https?://\S+", " ", text)
    vals: set[str] = set()
    for token in re.findall(r"[a-z0-9][a-z0-9_+#.-]{1,}", text):
        token = token.strip("._-+#")
        if len(token) >= 3 and token not in STOP:
            vals.add(token)
    return vals


# Strong, explicit topic signals. Generic viral terms intentionally omitted.
HINTS: dict[str, list[str]] = {
    "Java / Programming Interview Prep": ["java", "springboot", "jvm", "oop", "multithreading", "hashmap", "streamapi", "codinginterview"],
    "Python Programming": ["python", "pandas", "numpy", "flask", "django"],
    "Web Development": ["html", "css", "javascript", "react", "frontend", "webdevelopment", "webdeveloper", "nextjs", "nodejs"],
    "DevOps / Software Engineering": ["devops", "docker", "kubernetes", "cicd", "microservices", "backend", "softwareengineering", "awsdevops"],
    "AI Tools & Generative AI": ["chatgpt", "openai", "generativeai", "genai", "promptengineering", "claude", "gemini", "llm", "artificialintelligence", "midjourney", "copilot"],
    "Cybersecurity": ["cybersecurity", "infosec", "ethicalhacking", "penetrationtesting", "bugbounty", "phishing", "malware", "cybersecurityawareness"],
    "Software Testing & QA": ["softwaretesting", "testing", "selenium", "qaautomation", "junit", "testautomation", "qualityassurance"],
    "Networking / IT Infrastructure": ["networking", "ccna", "cisco", "router", "switch", "tcpip", "dns", "linuxserver"],
    "Computer & Tech How-To Tips": ["windows", "android", "iphone", "shortcut", "howto", "computertricks", "techtricks"],
    "MS Office / Excel Tips": ["excel", "msexcel", "spreadsheet", "powerpoint", "msword", "office365"],
    "Career / Jobs & Hiring": ["jobs", "jobsearch", "hiring", "fresher", "internship", "internships", "placement", "recruitment", "vacancy", "walkin"],
    "Resume & Interview Preparation": ["interview", "interviewquestions", "interviewtips", "resume", "behavioural", "cv", "resumetips"],
    "Career Growth & Workplace": ["careergrowth", "workplace", "corporatelife", "officeculture", "promotion", "salarynegotiation", "leadership"],
    "Freelancing & Entrepreneurship": ["freelancing", "freelancer", "entrepreneur", "startup", "sidehustle", "upwork", "fiverr"],
    "Business Tools & CRM Software": ["crm", "salesforce", "hubspot", "zoho", "notion", "slack", "productivitytool"],
    "Personal Finance & Money": ["finance", "investing", "investment", "stocks", "trading", "salary", "tax", "money", "mutualfund", "sip", "creditcard"],
    "Economy & Business News": ["economy", "inflation", "gdp", "businessnews", "marketnews", "economic"],
    "Real Estate / Property": ["realestate", "property", "apartment", "flat", "rent", "mortgage"],
    "Government Schemes & Policy": ["government", "govt", "scheme", "yojana", "policy", "pension", "subsidy", "governmentjob"],
    "Education & Exams": ["education", "exam", "exams", "student", "study", "boardexam", "upsc", "tnpsc", "neet", "jee"],
    "English & Language Learning": ["english", "grammar", "vocabulary", "spokenenglish", "languagelearning", "ielts", "toefl"],
    "General Knowledge & Facts": ["facts", "didyouknow", "generalknowledge", "sciencefacts", "historyfacts"],
    "Health & Wellness": ["health", "wellness", "nutrition", "mentalhealth", "wellbeing", "doctor", "healthtips"],
    "Ayurveda & Traditional Wellness": ["ayurveda", "ayurvedic", "siddha", "herbal", "traditionalmedicine"],
    "Fitness & Workout": ["fitness", "workout", "gym", "bodybuilding", "weightloss", "exercise", "muscle", "homeworkout"],
    "Hair & Grooming": ["hair", "haircare", "hairstyle", "grooming", "barber", "beard"],
    "Fashion & Beauty": ["fashion", "beauty", "makeup", "skincare", "outfit", "styling", "cosmetics"],
    "Traditional Attire & Styling": ["saree", "sari", "kurta", "veshti", "traditionalwear", "ethnicwear"],
    "Food & Recipes": ["food", "recipe", "cooking", "restaurant", "foodie", "cafe", "biryani", "dessert", "streetfood", "foodreview"],
    "Travel & Places": ["travel", "trip", "vacation", "tourism", "travelguide", "wanderlust", "places"],
    "Chennai / Local Tamil Nadu Information": ["chennai", "tamilnadu", "tamilnadufood", "chennaifood", "perungudi", "tambaram", "coimbatore", "madurai"],
    "Automobile / Vehicle Review": ["car", "cars", "bike", "bikes", "automobile", "vehicle", "review", "suv", "sedan", "ev"],
    "Vehicle Maintenance & Car Care": ["carcare", "maintenance", "servicing", "tyre", "engine", "oilchange", "mechanic"],
    "Road Safety / Driving Tips": ["roadsafety", "driving", "drivingtips", "traffic", "seatbelt", "helmet", "road"],
    "Gaming": ["gaming", "gamer", "gamers", "playstation", "ps5", "xbox", "steam", "gta", "minecraft", "valorant", "pubg"],
    "Sports": ["sports", "cricket", "football", "soccer", "ipl", "tennis", "badminton", "fifa"],
    "Animals & Pets": ["animals", "pets", "dog", "dogs", "cat", "cats", "puppy", "kitten", "wildlife"],
    "Art & Creativity": ["art", "drawing", "painting", "sketch", "illustration", "creative", "diyart"],
    "Music & Songs": ["music", "song", "songs", "lyrics", "singer", "cover", "bgm", "musical", "musicvideo"],
    "Movies & Entertainment": ["movie", "movies", "film", "cinema", "actor", "actress", "series", "netflix", "ott", "scene"],
    "Kollywood / Tamil Movie Fan Edits": ["kollywood", "thalapathy", "vijay", "ajith", "dhanush", "suriya", "rajini", "kamal", "tamilcinema"],
    "Tamil Comedy & Memes": ["tamilmemes", "tamilmeme", "tamilcomedy", "tamilcomedymemes", "vadivelu", "trolltamil", "tamilfunny"],
    "Comedy & Entertainment (General)": ["comedy", "funny", "memes", "meme", "joke", "humour", "humor", "satire", "standup"],
    "Relationships & Friendship": ["relationship", "friendship", "friends", "couple", "love", "breakup", "boyfriend", "girlfriend"],
    "Attraction & Dating Psychology": ["dating", "attraction", "datingtips", "psychology", "crush", "flirting", "seduction"],
    "Life Hacks & Productivity Tips": ["lifehack", "lifehacks", "productivity", "timemanagement", "organization", "organizing", "studyhack"],
    "Motivation & Self Improvement": ["motivation", "motivational", "selfimprovement", "mindset", "discipline", "success", "inspiration", "goals"],
    "Astrology / Spirituality": ["astrology", "zodiac", "horoscope", "spiritual", "spirituality", "meditation", "manifestation", "tarot"],
    "Festivals & Greetings": ["diwali", "pongal", "christmas", "eid", "festival", "greetings", "happynewyear", "birthday"],
    "Nostalgia / Cartoons & TV Throwbacks": ["nostalgia", "90skids", "childhood", "cartoon", "cartoons", "oldtv", "throwback"],
}

CATEGORY_PRIORITY = list(HINTS.keys())


def classify(rec: dict, existing: list[dict]) -> tuple[str, float, str]:
    text = " ".join([rec.get("t", ""), rec.get("d", ""), rec.get("a", "")])
    toks = tokenize(text)

    # 1) Strong direct topic signals.
    direct: list[tuple[float, str]] = []
    for category, keys in HINTS.items():
        hits = sum(1 for k in keys if k in toks)
        if hits:
            # More specific categories get a modest bonus; multiple independent hits score strongly.
            score = hits * 5.0
            if category in ("Kollywood / Tamil Movie Fan Edits", "Tamil Comedy & Memes", "Chennai / Local Tamil Nadu Information") and any(k in toks for k in ("tamil", "chennai", "kollywood")):
                score += 2.5
            direct.append((score, category))
    direct.sort(reverse=True)
    if direct:
        top_score, top_cat = direct[0]
        if len(direct) == 1 or top_score - direct[1][0] >= 2.0:
            return top_cat, top_score, "strong-topic-signal"

    # 2) Learn the vocabulary of the existing categories as a consistency aid.
    profiles: dict[str, Counter[str]] = defaultdict(Counter)
    for r in existing:
        c = r.get("c") or GENERAL
        profiles[c].update(tokenize(" ".join([r.get("t", ""), r.get("d", ""), r.get("a", "")])) )

    scored: list[tuple[float, str]] = []
    for cat, prof in profiles.items():
        score = 0.0
        for tok in toks:
            n = prof.get(tok)
            if n:
                score += 1.0 + math.log1p(n)
        if cat == GENERAL and not any(k in toks for k in ("relatable", "meme", "memes", "funny", "comedy", "joke")):
            score *= 0.35
        if cat == VIRAL and not any(k in toks for k in ("viral", "trending", "trend")):
            score *= 0.2
        scored.append((score, cat))
    scored.sort(reverse=True)
    if scored and scored[0][0] > 0:
        return scored[0][1], scored[0][0], "existing-category-vocabulary"

    # 3) Conservative true fallback. User requested no review queue.
    # We choose General rather than inventing a category unsupported by metadata.
    return GENERAL, 0.0, "true-fallback"


def _cookiefile_from_env() -> str | None:
    ck = os.environ.get("INSTAGRAM_COOKIES", "").strip()
    cb = os.environ.get("INSTAGRAM_COOKIES_B64", "").strip()
    if ck:
        COOKIE_FILE.write_text(ck, encoding="utf-8")
        return str(COOKIE_FILE)
    if cb:
        COOKIE_FILE.write_bytes(base64.b64decode(cb))
        return str(COOKIE_FILE)
    return None


def _ytdlp_options() -> dict:
    opts = {
        "quiet": True,
        "no_warnings": True,
        "noplaylist": True,
        "skip_download": True,
        "retries": 2,
        "extractor_retries": 2,
        "socket_timeout": 30,
        "http_headers": {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/131 Safari/537.36",
            "Accept-Language": "en-US,en;q=0.9",
        },
    }
    cookiefile = _cookiefile_from_env()
    if cookiefile:
        opts["cookiefile"] = cookiefile
    return opts


def yt_metadata(url: str) -> dict:
    try:
        from yt_dlp import YoutubeDL
        with YoutubeDL(_ytdlp_options()) as ydl:
            return ydl.extract_info(url, download=False)
    except Exception as exc:
        raise RuntimeError(f"Instagram metadata fetch failed: {exc}") from exc


def fetch_cover_via_ytdlp(item: dict) -> tuple[bytes, str]:
    thumbs = [x for x in (item.get("thumbnails") or []) if isinstance(x, dict) and x.get("url")]
    direct = item.get("thumbnail") or item.get("thumbnail_url")
    if direct:
        thumbs.append({
            "url": direct,
            "width": item.get("thumbnail_width") or 0,
            "height": item.get("thumbnail_height") or 0,
        })
    if not thumbs:
        raise RuntimeError("no usable thumbnail URL returned by yt-dlp")
    thumbs.sort(key=lambda x: (x.get("width") or 0) * (x.get("height") or 0), reverse=True)
    thumb_url = str(thumbs[0]["url"])

    try:
        from io import BytesIO
        from PIL import Image
        from yt_dlp import YoutubeDL

        with YoutubeDL(_ytdlp_options()) as ydl:
            response = ydl.urlopen(thumb_url)
            raw = response.read()
    except Exception as exc:
        raise RuntimeError(f"thumbnail download failed: {exc}") from exc

    if len(raw) < 1000:
        raise RuntimeError(f"cover too small: {len(raw)} bytes")

    # Decode to prove that the response is an image and canonicalize storage to JPEG.
    try:
        with Image.open(BytesIO(raw)) as im:
            im.verify()
        with Image.open(BytesIO(raw)) as im:
            rgb = im.convert("RGB")
            out = BytesIO()
            rgb.save(out, format="JPEG", quality=92, optimize=True)
            data = out.getvalue()
    except Exception as exc:
        raise RuntimeError(f"cover is not a valid decodable image: {exc}") from exc

    return data, hashlib.sha256(data).hexdigest()

def _is_generic_instagram_title(title: str, author: str = "") -> bool:
    """Return True for generic Instagram placeholder titles."""
    t = " ".join(str(title or "").split()).strip()
    if not t:
        return True

    generic_patterns = (
        r"^video\s+by\s+.+$",
        r"^reel\s+by\s+.+$",
        r"^instagram\s+reel(?:\s+by\s+.+)?$",
        r"^video(?:\s+reel)?\s+by\s+.+$",
        r"^reels?$",
    )
    if any(re.fullmatch(p, t, flags=re.I) for p in generic_patterns):
        return True

    if author:
        a = re.sub(r"^@", "", str(author).strip())
        nt = re.sub(r"[^a-z0-9]+", "", t.lower())
        na = re.sub(r"[^a-z0-9]+", "", a.lower())
        if na and nt in {f"videoby{na}", f"reelby{na}"}:
            return True

    return False


def _derive_display_title(title: str, description: str, author: str = "") -> str:
    """
    Keep a meaningful supplied title. When Instagram supplies a generic
    placeholder such as 'Video by username', derive a concise title from
    the actual caption/context without changing the stored caption.
    """
    supplied = " ".join(str(title or "").split()).strip()
    if supplied and not _is_generic_instagram_title(supplied, author):
        return supplied[:1000]

    candidates = []
    text = str(description or "").replace("\r", "\n")

    for raw in re.split(r"\n+|\s*\|\s*", text):
        s = " ".join(raw.split()).strip(" -\t")
        if not s:
            continue

        clean = re.sub(r"https?://\S+", "", s)
        clean = re.sub(r"(?:^|\s)#[A-Za-z0-9_]+", " ", clean)
        clean = " ".join(clean.split()).strip()
        low = clean.lower()

        if not clean:
            continue
        if low.startswith((
            "follow for", "comment ", "dm me", "link in bio",
            "save this", "like and share", "subscribe"
        )):
            continue
        if re.match(r"^(?:[\d,.]+\s+likes?|[\d,.]+\s+comments?)\b", low):
            continue

        candidates.append(clean)

    if not candidates:
        return supplied[:1000] if supplied else "Instagram Reel"

    candidate = candidates[0]

    m = re.search(r"^(.{1,180}?[.!?])(?:\s|$)", candidate)
    if m:
        candidate = m.group(1).strip()

    candidate = candidate.strip(" \"'")
    if len(candidate) > 160:
        candidate = candidate[:157].rsplit(" ", 1)[0].rstrip(" ,;:-") + "..."

    return candidate or (supplied[:1000] if supplied else "Instagram Reel")


def make_record(item: dict, url: str, existing: list[dict]) -> tuple[dict, dict]:
    sc = canonical_shortcode(url)
    if not sc:
        raise RuntimeError("invalid Instagram Reel URL")

    supplied_title = item.get("title") or item.get("fulltitle") or item.get("raw_title") or ""
    desc = item.get("description") or item.get("caption") or item.get("text") or ""
    author = (
        item.get("uploader")
        or item.get("uploader_id")
        or item.get("author_username")
        or item.get("username")
        or ""
    )
    title = _derive_display_title(supplied_title, desc, author)

    upload = item.get("upload_date") or item.get("timestamp") or ""
    dt = ""
    if isinstance(upload, (int, float)):
        dt = datetime.fromtimestamp(upload, timezone.utc).date().isoformat()
    else:
        s = str(upload)
        if re.fullmatch(r"\d{8}", s):
            dt = f"{s[:4]}-{s[4:6]}-{s[6:]}"
        elif re.match(r"\d{4}-\d{2}-\d{2}", s):
            dt = s[:10]

    rec = {
        "sc": sc,
        "u": canonical_url(sc),
        "t": str(title)[:1000] or (str(desc).split("|")[0].strip() if desc else f"Instagram Reel {sc}"),
        "c": "",
        "d": str(desc)[:10000],
        "a": str(author)[:300],
        "cov": 0,
        "sha": "",
        "dn": 1,
        "dt": dt or None,
        "img": f"{sc}.jpg",
        "ingested_at": now(),
    }

    category, score, method = classify(rec, existing)
    rec["c"] = category
    rec["cat_score"] = round(score, 4)
    rec["cat_method"] = method
    return rec, {"category": category, "score": score, "method": method}


def validate(records: list[dict], expected_base: list[dict] | None = None) -> None:
    shorts = [r.get("sc") for r in records]
    if len(shorts) != len(set(shorts)):
        raise RuntimeError("duplicate shortcodes detected")
    if expected_base is not None:
        new_by_sc = {r["sc"]: r for r in records}
        for old in expected_base:
            n = new_by_sc.get(old.get("sc"))
            if not n:
                raise RuntimeError(f"regression: existing Reel removed: {old.get('sc')}")
            for key in ("u", "t", "d", "a", "c", "img", "sha", "cov"):
                if n.get(key) != old.get(key):
                    raise RuntimeError(f"regression: existing field changed for {old.get('sc')}: {key}")
    for r in records:
        sc = r.get("sc", "")
        if not re.fullmatch(r"[A-Za-z0-9_-]+", sc):
            raise RuntimeError(f"invalid shortcode: {sc}")
        if r.get("u") != canonical_url(sc):
            raise RuntimeError(f"URL mismatch: {sc}")
        if "/p/" in r.get("u", ""):
            raise RuntimeError("non-Reel URL detected")
        if not r.get("c"):
            raise RuntimeError(f"missing category: {sc}")
        if r.get("cov") == 1:
            cover = COVERS / r.get("img", "")
            if not cover.exists():
                raise RuntimeError(f"missing cover file: {sc}")
            sha = hashlib.sha256(cover.read_bytes()).hexdigest()
            if sha != r.get("sha"):
                raise RuntimeError(f"cover hash mismatch: {sc}")


def recalc(records: list[dict]) -> Counter:
    counts = Counter(r.get("sha") for r in records if r.get("cov") == 1 and r.get("sha"))
    for r in records:
        r["dn"] = counts.get(r.get("sha"), 1) if r.get("sha") else 1
    return counts


def publish(records: list[dict], base: list[dict], new_cover: Path | None = None) -> None:
    # Create temporary versions of the data files. Only replace them after all validation passes.
    validate(records, expected_base=base)
    cover_counts = recalc(records)
    meta = {
        "schema_version": 3,
        "generated_at": now(),
        "reel_count": len(records),
        "category_counts": dict(sorted(Counter(r.get("c") for r in records).items())),
        "exact_duplicate_cover_groups": sum(1 for n in cover_counts.values() if n > 1),
    }
    cover_index = [
        {"shortcode": r["sc"], "filename": r["img"], "sha256": r.get("sha", ""), "duplicate_count": r.get("dn", 1)}
        for r in records if r.get("cov") == 1
    ]
    originals = {p: p.read_bytes() if p.exists() else None for p in (DATA, META, COVER_INDEX)}
    try:
        write_json_atomic(DATA, records)
        write_json_atomic(META, meta)
        write_json_atomic(COVER_INDEX, cover_index)
        validate(records, expected_base=base)
    except Exception:
        for path, data in originals.items():
            if data is None:
                path.unlink(missing_ok=True)
            else:
                path.write_bytes(data)
        raise


def process(url: str, dry: bool = False) -> dict:
    records = load_json(DATA, [])
    known = {r.get("sc") for r in records}
    sc = canonical_shortcode(url)
    if not sc:
        return {"status": "ignored", "reason": "not a valid Instagram Reel URL"}
    if sc in known:
        return {"status": "duplicate", "shortcode": sc, "total": len(records)}

    canonical = canonical_url(sc)
    item = yt_metadata(canonical)
    rec, catinfo = make_record(item, canonical, records)
    cover_data, sha = fetch_cover_via_ytdlp(item)

    if dry:
        return {
            "status": "dry_run",
            "shortcode": sc,
            "category": rec["c"],
            "cover_sha256": sha,
            "would_total": len(records) + 1,
        }

    COVERS.mkdir(parents=True, exist_ok=True)
    cover_path = COVERS / f"{sc}.jpg"
    tmp_cover = cover_path.with_suffix(".jpg.tmp")
    tmp_cover.write_bytes(cover_data)

    # Validate the staged cover before it touches production.
    if hashlib.sha256(tmp_cover.read_bytes()).hexdigest() != sha:
        tmp_cover.unlink(missing_ok=True)
        raise RuntimeError("staged cover SHA-256 mismatch")

    rec["cov"] = 1
    rec["sha"] = sha
    rec["dn"] = 1

    # Preserve exact old state. We allow ONLY the new Reel to change here.
    previous_cover = cover_path.read_bytes() if cover_path.exists() else None
    try:
        tmp_cover.replace(cover_path)
        new_records = [rec] + records
        publish(new_records, base=records, new_cover=cover_path)
        append_log({
            "status": "added",
            "shortcode": sc,
            "category": rec["c"],
            "category_method": catinfo["method"],
            "category_score": catinfo["score"],
            "total": len(new_records),
            "cover_sha256": sha,
        })
        return {
            "status": "added",
            "shortcode": sc,
            "category": rec["c"],
            "total": len(new_records),
            "cover_sha256": sha,
        }
    except Exception:
        # Restore the prior cover state if publishing failed.
        if previous_cover is None:
            cover_path.unlink(missing_ok=True)
        else:
            cover_path.write_bytes(previous_cover)
        raise


def main(argv: list[str]) -> None:
    if len(argv) < 2:
        raise SystemExit("usage: sync_reels.py URL [URL ...]")
    results = []
    for url in argv[1:]:
        try:
            results.append(process(url))
        except Exception as exc:
            append_log({"status": "error", "url": url, "reason": str(exc)})
            results.append({"status": "error", "url": url, "reason": str(exc)})
    print(json.dumps(results, ensure_ascii=False))


if __name__ == "__main__":
    main(sys.argv)
