import hashlib
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
recs = json.loads((ROOT / "data" / "reels.json").read_text(encoding="utf-8"))
assert len(recs) == 3646
assert len({r["sc"] for r in recs}) == 3646
assert all(re.fullmatch(r"[A-Za-z0-9_-]+", r["sc"]) for r in recs)
assert all(r["u"] == f"https://www.instagram.com/reel/{r['sc']}/" for r in recs)
assert all("/p/" not in r["u"] for r in recs)
for r in recs:
    assert r.get("c")
    if r.get("cov") == 1:
        p = ROOT / "reel_covers" / r["img"]
        assert p.exists()
        assert hashlib.sha256(p.read_bytes()).hexdigest() == r["sha"]
print("SMOKE PASS")
