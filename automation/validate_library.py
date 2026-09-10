#!/usr/bin/env python3
"""Strict production integrity validator for the static Reel library."""
from __future__ import annotations

import hashlib
import json
import re
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data" / "reels.json"
COVERS = ROOT / "reel_covers"
META = ROOT / "data" / "meta.json"
COVER_INDEX = ROOT / "data" / "cover_index.json"

records = json.loads(DATA.read_text("utf-8"))
shorts = [r.get("sc") for r in records]
assert len(shorts) == len(set(shorts)), "duplicate shortcodes"
assert all(re.fullmatch(r"[A-Za-z0-9_-]+", r.get("sc", "")) for r in records)
assert all(r.get("u") == f"https://www.instagram.com/reel/{r.get('sc')}/" for r in records)
assert all("/p/" not in r.get("u", "") for r in records)
assert all(r.get("c") for r in records), "uncategorized Reel"

for r in records:
    if r.get("cov") == 1:
        p = COVERS / r["img"]
        assert p.exists(), f"missing cover: {r['sc']}"
        digest = hashlib.sha256(p.read_bytes()).hexdigest()
        assert digest == r.get("sha"), f"cover hash mismatch: {r['sc']}"
        assert r["img"] == f"{r['sc']}.jpg", f"non-deterministic cover filename: {r['sc']}"

counts = Counter(r.get("c") for r in records)
assert sum(counts.values()) == len(records)

meta = json.loads(META.read_text("utf-8"))
assert meta.get("reel_count") == len(records), "meta count mismatch"
assert meta.get("category_counts") == dict(sorted(counts.items())), "category count mismatch"

idx = json.loads(COVER_INDEX.read_text("utf-8"))
assert len(idx) == sum(1 for r in records if r.get("cov") == 1), "cover index count mismatch"
idx_by_sc = {x.get("shortcode"): x for x in idx}
assert len(idx_by_sc) == len(idx), "duplicate cover index shortcodes"
for r in records:
    if r.get("cov") == 1:
        x = idx_by_sc.get(r["sc"])
        assert x and x.get("filename") == r.get("img") and x.get("sha256") == r.get("sha"), f"cover index mismatch: {r['sc']}"

hash_counts = Counter(r.get("sha") for r in records if r.get("cov") == 1)
for r in records:
    if r.get("cov") == 1:
        assert r.get("dn") == hash_counts[r.get("sha")], f"duplicate-cover count mismatch: {r['sc']}"

print(json.dumps({
    "total": len(records),
    "unique_shortcodes": len(set(shorts)),
    "categories": len(counts),
    "category_counts": dict(sorted(counts.items())),
    "covers": sum(1 for r in records if r.get("cov") == 1),
    "exact_duplicate_cover_groups": sum(1 for n in hash_counts.values() if n > 1),
    "validation": "PASS",
}, ensure_ascii=False))
