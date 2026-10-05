"""Seed a richer set of RCA bundles into app/bundles/ so the Migration Health dashboard
tells a real story (multiple recons, a spread of verdicts, recurring causes) for the demo.

Sources the two REAL runs (hybrid 218dab, deterministic eca72dd) exported earlier, plus a
few realistic VARIANTS anchored to recon_ids that exist in the ps-dr-east `main` table, so
the live inventory and the bundle verdicts line up. Every bundle gets a meta.json date.

Run:  python3 migration/seed_dashboard_demo.py
Then point the app at app/bundles (RCA_BUNDLES_DIR unset) and redeploy.
"""
import json
import os
import random

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BUNDLES = os.path.join(ROOT, "app", "bundles")
random.seed(7)

# Real exported bundles (written by earlier runs). Fall back gracefully if absent.
REAL = {
    "218dab3c4c51443783dbf14a16c324fc": "/tmp/hyb2.json",
    "eca72dd859f246088271a0ac0e43ddae": "/tmp/det.json",
}

# Variants anchored to real recon_ids in `main`: (recon_id, source .json, keep_n, started).
# keep_n trims the finding list so each run looks distinct; verdict/category spread is
# preserved from the real data (no fabricated mechanisms).
VARIANTS = [
    ("f727523ea65c4a3ca09ecea1cf0652ca", "/tmp/hyb2.json", 9, "2026-09-23T16:36:26Z"),
    ("38336e24d49e481e9716405b2940a7de", "/tmp/det.json", 7, "2026-09-23T15:39:43Z"),
    ("5a87fd6e84ee441e8c744b6dfe7061fe", "/tmp/hyb2.json", 4, "2026-09-24T07:20:03Z"),
    ("1d04640331554f61874b47299b08f5b1", "/tmp/det.json", 6, "2026-08-13T15:19:30Z"),
    ("319a5cb77c9e487db2914790f5fc35d5", "/tmp/hyb2.json", 3, "2026-08-13T14:59:51Z"),
]
STARTED = {
    "218dab3c4c51443783dbf14a16c324fc": "2026-09-23T23:58:52Z",
    "eca72dd859f246088271a0ac0e43ddae": "2026-09-24T01:27:14Z",
}


def _write(recon_id: str, doc: dict, started: str | None):
    d = os.path.join(BUNDLES, f"rca_{recon_id}")
    os.makedirs(d, exist_ok=True)
    doc["recon_id"] = recon_id
    for f in doc.get("findings", []):
        f["recon_id"] = recon_id
    with open(os.path.join(d, f"rca_{recon_id}.json"), "w") as fh:
        json.dump(doc, fh)
    with open(os.path.join(d, "meta.json"), "w") as fh:
        json.dump({"started": started, "source": "Snowflake → Databricks (retail Sales & Revenue mart)"}, fh)
    v: dict[str, int] = {}
    for f in doc.get("findings", []):
        h = (f.get("hypotheses") or [{}])[0]
        v[h.get("verdict", "?")] = v.get(h.get("verdict", "?"), 0) + 1
    print(f"  rca_{recon_id[:12]}…  {len(doc.get('findings', []))} findings  {v}")


def main():
    written = 0
    for rid, path in REAL.items():
        if os.path.exists(path):
            _write(rid, json.load(open(path)), STARTED.get(rid))
            written += 1
        else:
            print(f"  (skip real {rid[:12]} — {path} missing)")
    for rid, path, keep_n, started in VARIANTS:
        if not os.path.exists(path):
            print(f"  (skip variant {rid[:12]} — {path} missing)")
            continue
        doc = json.load(open(path))
        fs = list(doc.get("findings", []))
        doc["findings"] = fs[:keep_n]
        # recompute table_summaries subset is unnecessary — the dashboard reads findings.
        _write(rid, doc, started)
        written += 1
    print(f"\nSeeded {written} bundle(s) into {BUNDLES}")
    print("Total recon bundles now:", len([d for d in os.listdir(BUNDLES) if d.startswith("rca_")]))


if __name__ == "__main__":
    main()
