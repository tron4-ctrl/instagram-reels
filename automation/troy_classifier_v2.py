#!/usr/bin/env python3
"""TROY classifier v2 baseline.

Standalone development classifier for the approved 38-category taxonomy.
It deliberately does NOT read or learn from existing category labels.

This is a deterministic prototype for benchmark work, not yet the production
sync_reels.py integration. Historical Sorti evidence is accepted only through
explicit optional arguments; future classification should use caption/hashtags,
OCR, then tightly-capped account metadata.
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Iterable

ROOT = Path(__file__).resolve().parents[1]
TAXONOMY_PATH = ROOT / "automation" / "troy_taxonomy.json"

GENERAL = "General / Relatable & Miscellaneous Content"
UNCATEGORIZED = "Uncategorized / No Content Available"
SPORTS = "Sports"
VIRAL = "Viral Clips / Trending Reels"


def _load_taxonomy() -> dict:
    data = json.loads(TAXONOMY_PATH.read_text("utf-8"))
    if data.get("canonical_category_count") != 38:
        raise RuntimeError("Unexpected canonical category count")
    cats = data.get("canonical_categories") or []
    if len(cats) != 38:
        raise RuntimeError("Taxonomy must contain exactly 38 categories")
    if set(data.get("retired_categories", [])) != {SPORTS, VIRAL}:
        raise RuntimeError("Unexpected retired-category set")
    return data


TAXONOMY = _load_taxonomy()
CATEGORIES = tuple(TAXONOMY["canonical_categories"])
CATEGORY_SET = set(CATEGORIES)

# Seed signals for the benchmark prototype. These are intentionally explicit,
# conservative, and independent of existing TROY category labels.
SIGNALS: dict[str, tuple[str, ...]] = {
    "Programming / Coding General": (
        "programming", "coding", "python", "c++", "javascript", "java",
        "variable", "function", "class", "syntax", "algorithm",
    ),
    "Java / Programming Interview Prep": (
        "coding interview", "technical interview", "interview questions", "dsa",
        "placement coding", "coding round", "leetcode", "datastructures",
    ),
    "Web Development": (
        "web development", "website", "web design", "frontend", "backend web",
        "react", "nextjs", "html", "css", "javascript", "portfolio website",
    ),
    "DevOps / Software Engineering": (
        "devops", "docker", "kubernetes", "microservices", "ci/cd", "cicd",
        "deployment", "pipeline", "system design", "software testing",
        "test automation", "selenium", "junit",
    ),
    "Data Science / Analytics": (
        "data science", "data analyst", "data analytics", "sql", "primary key",
        "foreign key", "etl", "power bi", "tableau", "pandas", "numpy",
    ),
    "AI Tools & Generative AI": (
        "chatgpt", "claude", "gemini", "copilot", "midjourney", "generative ai",
        "genai", "prompt engineering", "ai tool", "ai image", "ai video",
    ),
    "Cybersecurity": (
        "cybersecurity", "cyber security", "infosec", "ethical hacking", "phishing",
        "malware", "ransomware", "bug bounty", "cyber awareness", "cybercrime",
    ),
    "Technology / Gadgets": (
        "iphone", "ipad", "android", "windows", "laptop", "computer", "gadget",
        "tech tip", "computer trick", "cctv camera", "excel", "outlook",
        "powerpoint", "ms word", "office 365",
    ),
    "Career / Jobs & Hiring": (
        "job opening", "job openings", "hiring", "vacancy", "internship",
        "internships", "placement", "recruitment", "get hired", "career switch",
    ),
    "Career Growth & Workplace": (
        "promotion", "salary negotiation", "workplace", "work culture", "office culture",
        "professional communication", "ooo email", "out of office", "offer call",
        "workplace rights", "employee rights",
    ),
    "Resume & Interview Preparation": (
        "resume", "cv", "ats", "interview tips", "self introduction", "notice period",
        "behavioural interview", "behavioral interview", "interview preparation",
    ),
    "Freelancing & Entrepreneurship": (
        "freelancing", "freelancer", "entrepreneur", "startup", "side hustle",
        "small business", "client work", "upwork", "fiverr",
    ),
    "Personal Finance & Money": (
        "personal finance", "mutual fund", "mutual funds", "sip", "emi", "loan",
        "interest rate", "tax", "pf", "epf", "epfo", "investment", "investing",
        "credit card", "rent vs", "rent or buy", "government scheme",
    ),
    "Education & Exams": (
        "exam", "exams", "upsc", "tnpsc", "neet", "jee", "student", "study",
        "did you know", "general knowledge", "history fact", "science fact",
    ),
    "English & Language Learning": (
        "spoken english", "learn english", "english grammar", "vocabulary",
        "pronunciation", "english speaking", "language learning", "conversation starter",
    ),
    "Fitness & Workout": (
        "workout", "work out", "gym", "fitness", "exercise", "cardio", "bodybuilding",
        "muscle", "squat", "push up", "pull up", "deadlift", "bench press",
    ),
    "Health & Wellness": (
        "health", "wellness", "nutrition", "skincare", "skin care", "sleep",
        "doctor", "hydration", "diet", "mental health", "recovery", "health tips",
    ),
    "Fashion & Beauty": (
        "fashion", "beauty", "makeup", "cosmetics", "outfit", "styling", "streetwear",
        "mens fashion", "men's fashion", "women's fashion",
    ),
    "Hair & Grooming": (
        "hair", "haircare", "hair care", "hairstyle", "haircut", "barber", "beard",
        "grooming",
    ),
    "Astrology / Spirituality": (
        "astrology", "zodiac", "horoscope", "spirituality", "spiritual", "meditation",
        "manifestation", "tarot", "prayer",
    ),
    "Life Hacks & Productivity Tips": (
        "life hack", "lifehack", "productivity", "time management", "organization",
        "organizing", "shortcut", "tips and tricks",
    ),
    "Art & Creativity": (
        "art", "drawing", "painting", "sketch", "illustration", "procreate", "creative",
        "digital art", "diy art",
    ),
    "Food & Recipes": (
        "recipe", "recipes", "cooking", "food", "biryani", "dessert", "street food",
        "restaurant", "cafe", "food review", "chutney", "sambar",
    ),
    "Travel & Places": (
        "travel", "trip", "vacation", "tourism", "travel guide", "tourist", "landmark",
        "trek", "beach", "temple visit", "waterfall", "places to visit",
    ),
    "Chennai / Local Tamil Nadu Information": (
        "chennai", "tamil nadu", "tamilnadu", "tambaram", "perungudi", "coimbatore",
        "madurai", "trichy", "local service", "shop", "store", "civic", "tn police",
    ),
    "Automobile / Vehicle Review": (
        "car review", "bike review", "automobile", "vehicle review", "suv", "sedan",
        "electric vehicle", "ev car", "ev bike", "new car", "new bike",
    ),
    "Road Safety / Driving Tips": (
        "driving", "driving tips", "road safety", "traffic", "seatbelt", "helmet",
        "parking", "safe driving", "road rules",
    ),
    "Movies & Entertainment": (
        "movie", "movies", "film", "cinema", "actor", "actress", "series", "netflix",
        "ott", "movie scene", "trailer",
    ),
    "Kollywood / Tamil Movie Fan Edits": (
        "kollywood", "tamil cinema", "tamilcinema", "thalapathy", "vijay", "ajith",
        "dhanush", "suriya", "rajini", "kamal", "fan edit",
    ),
    "Tamil Comedy & Memes": (
        "tamil comedy", "tamil meme", "tamil memes", "vadivelu", "tamil funny", "troll tamil",
    ),
    "Comedy & Entertainment (General)": (
        "comedy", "funny", "meme", "memes", "joke", "humor", "humour", "satire",
        "funny reel",
    ),
    "Music & Songs": (
        "music", "song", "songs", "lyrics", "singer", "cover song", "bgm", "music video",
    ),
    "Gaming": (
        "gaming", "gamer", "playstation", "ps5", "xbox", "steam", "gta", "minecraft",
        "valorant", "pubg",
    ),
    "Motivation & Self Improvement": (
        "motivation", "motivational", "self improvement", "self-improvement", "mindset",
        "discipline", "success", "inspiration", "goals", "hardships", "dreams",
    ),
    "Relationships & Friendship": (
        "relationship", "friendship", "friends", "couple", "love", "breakup", "boyfriend",
        "girlfriend", "family", "father", "mother",
    ),
    "Animals & Pets": (
        "animal", "animals", "pet", "pets", "dog", "dogs", "cat", "cats", "puppy",
        "kitten", "wildlife",
    ),
}

# These are dangerous when seen alone. They are never sufficient evidence.
WEAK_ONLY = {
    "review", "technology", "career", "ai", "actor", "road", "safety", "office",
    "engineering", "developer", "viral", "trending", "tamil", "music", "entertainment",
    "guide", "guides", "tips", "coding", "code", "tech",
}

SPORTS_TERMS = (
    "sports", "cricket", "football", "soccer", "ipl", "tennis", "badminton", "fifa",
    "goalkeeper", "wicket", "bowler", "batsman", "run out", "six", "four",
)
GENERAL_ENGINEERING_TERMS = (
    "mechanical engineering", "electrical engineering", "civil engineering", "structural engineering",
    "mechanical design", "phase selector", "circuit", "cad design", "engineering drawing",
)
DANCE_TERMS = (
    "dance", "choreography", "choreographer", "dance workshop", "dance class", "dancer",
)
NOVELTY_TERMS = (
    "toy", "toys", "doll", "dolls", "action figure", "collectible figure", "figurine",
)

METADATA_ONLY_RE = re.compile(
    r"^\s*[\d,.]+\s*(?:k|m|b)?\s+likes?\s*,\s*[\d,.]+\s*(?:k|m|b)?\s+comments?\s*-\s*@?[A-Za-z0-9_.-]+\s+on\s+\d{1,4}[/.-]\d{1,4}[/.-]\d{2,4}\s*$",
    re.I,
)
PLACEHOLDER_RE = re.compile(r"^\(No caption text available for this Reel\.\)$", re.I)


def _norm(s: str) -> str:
    s = str(s or "").lower()
    s = s.replace("’", "'")
    s = re.sub(r"https?://\S+", " ", s)
    s = re.sub(r"\s+", " ", s).strip()
    return s


def _present(text: str, signal: str) -> bool:
    if " " in signal or "-" in signal or "+" in signal or "/" in signal:
        return signal in text
    return re.search(rf"(?<![a-z0-9_]){re.escape(signal)}(?![a-z0-9_])", text) is not None


def _matches(text: str, signals: Iterable[str]) -> list[str]:
    return [s for s in signals if _present(text, s)]


def _metadata_only(caption: str) -> bool:
    return bool(METADATA_ONLY_RE.fullmatch(caption.strip()))


def _strong_enough(matches: list[str]) -> bool:
    # One multi-word/domain-specific signal is enough; a single weak token is not.
    if not matches:
        return False
    return any((" " in m) or ("-" in m) or (len(m) >= 6 and m not in WEAK_ONLY) for m in matches)


def _confidence(candidate_count: int, strong: bool, conflict: bool = False) -> str:
    if conflict:
        return "LOW"
    if candidate_count == 1 and strong:
        return "HIGH"
    if candidate_count >= 1:
        return "MEDIUM"
    return "LOW"


def classify_record(
    rec: dict,
    *,
    ocr_text: str = "",
    sorti_description: str = "",
    sorti_tags: Iterable[str] = (),
    sorti_category: str = "",
) -> dict:
    """Return one canonical category plus routing/audit metadata.

    Existing `rec['c']` is NEVER read and cannot influence the result.
    Sorti category is used only as a sanity-check signal, not as primary truth.
    """
    caption = _norm(rec.get("d") or "")
    title = _norm(rec.get("t") or "")
    account = _norm(rec.get("a") or "")
    ocr = _norm(ocr_text)
    sdesc = _norm(sorti_description)
    tags_text = _norm(" ".join(str(x) for x in sorti_tags))

    combined_primary = " ".join(x for x in (caption, title) if x).strip()
    evidence_text = " ".join(x for x in (caption, title, ocr, sdesc, tags_text) if x).strip()

    suspected_extraction_defect = False
    if not caption or PLACEHOLDER_RE.fullmatch(caption):
        suspected_extraction_defect = True
    elif _metadata_only(caption) and not ocr:
        suspected_extraction_defect = True

    # Evidence-state classification comes before any topic scoring.
    if (not caption or PLACEHOLDER_RE.fullmatch(caption)) and not ocr and not sdesc and not tags_text:
        return {
            "category": UNCATEGORIZED,
            "routing_reason": "evidence_absent",
            "gap_type": None,
            "confidence": "LOW",
            "needs_review": bool(suspected_extraction_defect),
            "suspected_extraction_defect": suspected_extraction_defect,
            "score": 0.0,
            "method": "evidence-absent",
            "evidence": [],
        }

    if _metadata_only(caption) and not ocr and not sdesc and not tags_text:
        return {
            "category": UNCATEGORIZED,
            "routing_reason": "evidence_absent",
            "gap_type": None,
            "confidence": "LOW",
            "needs_review": True,
            "suspected_extraction_defect": True,
            "score": 0.0,
            "method": "metadata-only-caption",
            "evidence": [],
        }

    scores: dict[str, float] = {}
    evidence: dict[str, list[str]] = {}
    for cat, signals in SIGNALS.items():
        m = _matches(combined_primary, signals)
        om = _matches(ocr, signals)
        sm = _matches(sdesc, signals)
        tm = _matches(tags_text, signals)
        # Caption/hashtags are strongest. OCR is escalation evidence. Sorti
        # description is allowed historically but only as corroborated evidence
        # in this baseline. Tags are weaker.
        score = len(m) * 5.0 + len(om) * 4.0 + len(sm) * 3.0 + len(tm) * 1.5
        if score:
            scores[cat] = score
            evidence[cat] = list(dict.fromkeys(m + om + sm + tm))

    # Remove weak-only matches from consideration unless corroborated by a
    # stronger signal in the same category.
    for cat in list(scores):
        useful = [x for x in evidence[cat] if x not in WEAK_ONLY]
        if not useful:
            del scores[cat]
            evidence.pop(cat, None)

    # Explicit multi-topic routing overrides.
    sports = _matches(evidence_text, SPORTS_TERMS)
    comedy = _matches(evidence_text, SIGNALS["Comedy & Entertainment (General)"] + SIGNALS["Tamil Comedy & Memes"])
    training = _matches(evidence_text, SIGNALS["Fitness & Workout"])
    movie = _matches(evidence_text, SIGNALS["Movies & Entertainment"] + SIGNALS["Kollywood / Tamil Movie Fan Edits"])

    # Sports: retired category. Resolve real domain where possible; only a
    # genuine standalone sports item becomes taxonomy_gap/sports.
    if sports:
        if comedy:
            cat = "Tamil Comedy & Memes" if re.search(r"\btamil\b|tamilmeme|tamil comedy|vadivelu", evidence_text) else "Comedy & Entertainment (General)"
            return _result(cat, "canonical_match", None, "HIGH", False, suspected_extraction_defect, 9.0, "sports-comedy", sports + comedy)
        if training:
            return _result("Fitness & Workout", "canonical_match", None, "HIGH", False, suspected_extraction_defect, 9.0, "sports-training", sports + training)
        if movie:
            cat = "Kollywood / Tamil Movie Fan Edits" if re.search(r"kollywood|tamil cinema|thalapathy|vijay|ajith|dhanush|suriya|rajini|kamal", evidence_text) else "Movies & Entertainment"
            return _result(cat, "canonical_match", None, "HIGH", False, suspected_extraction_defect, 9.0, "sports-movie", sports + movie)
        return _result(GENERAL, "taxonomy_gap", "sports", "MEDIUM", True, suspected_extraction_defect, 0.0, "sports-gap", sports)

    # Other approved taxonomy gaps.
    general_eng = _matches(evidence_text, GENERAL_ENGINEERING_TERMS)
    if general_eng:
        return _result(GENERAL, "taxonomy_gap", "general_engineering", "MEDIUM", True, suspected_extraction_defect, 0.0, "engineering-gap", general_eng)
    dance = _matches(evidence_text, DANCE_TERMS)
    if dance and not re.search(r"dance music|music video", evidence_text):
        return _result(GENERAL, "taxonomy_gap", "dance", "MEDIUM", True, suspected_extraction_defect, 0.0, "dance-gap", dance)
    novelty = _matches(evidence_text, NOVELTY_TERMS)
    if novelty and not re.search(r"toy store|doll making|art doll", evidence_text):
        return _result(GENERAL, "taxonomy_gap", "novelty_product", "MEDIUM", True, suspected_extraction_defect, 0.0, "novelty-product-gap", novelty)

    if scores:
        ordered = sorted(scores.items(), key=lambda kv: (-kv[1], kv[0]))
        top_cat, top_score = ordered[0]
        second_score = ordered[1][1] if len(ordered) > 1 else 0.0
        conflict = len(ordered) > 1 and (top_score - second_score) < 2.0

        # Deterministic pairwise boundaries.
        if conflict:
            pair = {top_cat, ordered[1][0]}
            if pair == {"Hair & Grooming", "Fashion & Beauty"}:
                hair_words = _matches(evidence_text, SIGNALS["Hair & Grooming"])
                top_cat = "Hair & Grooming" if hair_words else "Fashion & Beauty"
                conflict = False
            elif pair == {"Fitness & Workout", "Health & Wellness"}:
                top_cat = "Fitness & Workout" if training else "Health & Wellness"
                conflict = False
            elif pair == {"Web Development", "Programming / Coding General"}:
                web_words = _matches(evidence_text, SIGNALS["Web Development"])
                top_cat = "Web Development" if web_words else "Programming / Coding General"
                conflict = False
            elif pair == {"Career / Jobs & Hiring", "Career Growth & Workplace"}:
                job_words = _matches(evidence_text, SIGNALS["Career / Jobs & Hiring"])
                top_cat = "Career / Jobs & Hiring" if job_words else "Career Growth & Workplace"
                conflict = False
            elif pair == {"Movies & Entertainment", "Kollywood / Tamil Movie Fan Edits"}:
                kol = _matches(evidence_text, SIGNALS["Kollywood / Tamil Movie Fan Edits"])
                top_cat = "Kollywood / Tamil Movie Fan Edits" if kol else "Movies & Entertainment"
                conflict = False
            elif pair == {"Tamil Comedy & Memes", "Comedy & Entertainment (General)"}:
                tamil = bool(re.search(r"\btamil\b|tamilmeme|tamil comedy|vadivelu|troll tamil", evidence_text))
                top_cat = "Tamil Comedy & Memes" if tamil else "Comedy & Entertainment (General)"
                conflict = False

        if top_cat not in CATEGORY_SET:
            raise RuntimeError(f"Classifier emitted non-canonical category: {top_cat}")
        strong = _strong_enough(evidence.get(top_cat, []))
        conf = _confidence(len(ordered), strong, conflict)
        return _result(
            top_cat,
            "canonical_match",
            None,
            conf,
            conf == "LOW" or suspected_extraction_defect,
            suspected_extraction_defect,
            round(top_score, 4),
            "signal-baseline",
            evidence.get(top_cat, []),
        )

    # General is earned only after evidence exhaustion.
    return _result(
        GENERAL,
        "true_general",
        None,
        "HIGH" if caption and not suspected_extraction_defect else "MEDIUM",
        suspected_extraction_defect,
        suspected_extraction_defect,
        0.0,
        "true-general-exhaustion",
        [],
    )


def _result(category: str, routing_reason: str, gap_type: str | None, confidence: str,
            needs_review: bool, suspected_extraction_defect: bool, score: float,
            method: str, evidence: list[str]) -> dict:
    if category not in CATEGORY_SET:
        raise RuntimeError(f"Invalid canonical category: {category}")
    if category in {SPORTS, VIRAL}:
        raise RuntimeError("Retired category emitted")
    if routing_reason == "taxonomy_gap" and gap_type not in TAXONOMY["taxonomy_gap_registry"]:
        raise RuntimeError("taxonomy_gap requires a registered gap_type")
    if routing_reason != "taxonomy_gap" and gap_type is not None:
        raise RuntimeError("gap_type must be null outside taxonomy_gap")
    if routing_reason == "taxonomy_gap" and confidence == "HIGH":
        raise RuntimeError("taxonomy_gap cannot be HIGH confidence")
    if routing_reason == "taxonomy_gap" and not needs_review:
        raise RuntimeError("taxonomy_gap must require review")
    return {
        "category": category,
        "routing_reason": routing_reason,
        "gap_type": gap_type,
        "confidence": confidence,
        "needs_review": bool(needs_review),
        "suspected_extraction_defect": bool(suspected_extraction_defect),
        "score": float(score),
        "method": method,
        "evidence": list(dict.fromkeys(evidence)),
    }


def assert_contract(result: dict) -> None:
    """Raise if the result violates the implementation contract."""
    if result["category"] not in CATEGORY_SET:
        raise AssertionError("non-canonical category")
    if result["category"] in {SPORTS, VIRAL}:
        raise AssertionError("retired category emitted")
    if result["routing_reason"] not in {"canonical_match", "true_general", "taxonomy_gap", "evidence_absent"}:
        raise AssertionError("invalid routing_reason")
    if result["routing_reason"] == "taxonomy_gap":
        if not result.get("gap_type") or not result.get("needs_review"):
            raise AssertionError("invalid taxonomy_gap metadata")
        if result.get("confidence") == "HIGH":
            raise AssertionError("taxonomy_gap cannot be HIGH")
    else:
        if result.get("gap_type") is not None:
            raise AssertionError("gap_type must be null")


if __name__ == "__main__":
    # Lightweight contract smoke-test; does not touch TROY data files.
    examples = [
        {"d": "Just a relatable day 😊", "t": "Just a relatable day", "a": "user"},
        {"d": "Java interview questions and DSA roadmap", "t": "", "a": "user"},
        {"d": "97K likes, 127 comments - someuser on 20/09/2026", "t": "", "a": "someuser"},
        {"d": "Cricket match highlights", "t": "", "a": "user"},
        {"d": "Laptop price at our Chennai store", "t": "", "a": "user"},
    ]
    for ex in examples:
        out = classify_record(ex)
        assert_contract(out)
        print(json.dumps(out, ensure_ascii=False))
