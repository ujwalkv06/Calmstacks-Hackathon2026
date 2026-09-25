"""
person2_integrity_assessment.py
OWNER: Person 2

What this does:
  1. Reads fragments.json (Person 1's output)
  2. For each fragment, runs type-specific structural validation
  3. Computes Shannon entropy of the raw bytes
  4. Optionally compares against a known-good hash manifest (for demo/testing)
  5. Aggregates everything into a 0-100 integrity_score + status bucket
  6. Writes fragments_scored.json for Person 3 to consume

Run directly to test against Person 1's output:
    python person1_fragment_recovery.py     (produces fragments.json)
    python person2_integrity_assessment.py  (consumes it, produces fragments_scored.json)
"""

import os
import json
import math
import hashlib
import sqlite3
import zipfile
from collections import Counter

try:
    from PIL import Image
    PIL_AVAILABLE = True
except ImportError:
    PIL_AVAILABLE = False

try:
    from pypdf import PdfReader
    PYPDF_AVAILABLE = True
except ImportError:
    try:
        from PyPDF2 import PdfReader
        PYPDF_AVAILABLE = True
    except ImportError:
        PYPDF_AVAILABLE = False


# ---------------------------------------------------------------------------
# STEP 1: Shannon entropy (type-agnostic corruption signal)
# ---------------------------------------------------------------------------
def shannon_entropy(data: bytes) -> float:
    if not data:
        return 0.0
    counts = Counter(data)
    length = len(data)
    entropy = 0.0
    for count in counts.values():
        p = count / length
        entropy -= p * math.log2(p)
    return round(entropy, 3)  # max ~8.0 for random bytes


def entropy_verdict(entropy: float) -> str:
    # Rough heuristic bands -- structured file formats with real content
    # usually sit in the 3-7 range; near-8 suggests encryption/randomness/
    # heavy corruption; very low suggests mostly-zeroed/empty data.
    if entropy >= 7.5:
        return "high (possibly encrypted, overwritten, or random garbage)"
    elif entropy <= 1.0:
        return "very low (mostly zeroed or empty)"
    else:
        return "normal range for structured content"


# ---------------------------------------------------------------------------
# STEP 2: Type-specific structural validators
# ---------------------------------------------------------------------------
def validate_image(path):
    if not PIL_AVAILABLE:
        return None, "PIL not installed, skipped structural check"
    try:
        with Image.open(path) as img:
            img.verify()
        return True, "Image structure valid (PIL verify passed)"
    except Exception as e:
        return False, f"Image validation failed: {e}"


def validate_pdf(path):
    if not PYPDF_AVAILABLE:
        return None, "pypdf not installed, skipped structural check"
    try:
        reader = PdfReader(path)
        n_pages = len(reader.pages)
        if n_pages == 0:
            return False, "PDF opened but contains 0 pages"
        return True, f"PDF structure valid, {n_pages} page(s) readable"
    except Exception as e:
        return False, f"PDF validation failed: {e}"


def validate_sqlite(path):
    try:
        conn = sqlite3.connect(path)
        cur = conn.cursor()
        cur.execute("PRAGMA integrity_check")
        result = cur.fetchone()
        conn.close()
        ok = result is not None and result[0] == "ok"
        return ok, f"SQLite integrity_check: {result[0] if result else 'no result'}"
    except Exception as e:
        return False, f"SQLite validation failed: {e}"


def validate_zip_docx(path):
    try:
        with zipfile.ZipFile(path) as z:
            bad_file = z.testzip()
            if bad_file is None:
                return True, "ZIP/DOCX structure valid (testzip passed)"
            else:
                return False, f"ZIP/DOCX corrupted at member: {bad_file}"
    except Exception as e:
        return False, f"ZIP/DOCX validation failed: {e}"


VALIDATORS = {
    "jpeg": validate_image,
    "png": validate_image,
    "pdf": validate_pdf,
    "sqlite": validate_sqlite,
    "zip_docx": validate_zip_docx,
}


# ---------------------------------------------------------------------------
# STEP 3: Optional hash comparison against a known-good manifest
# (only useful in the demo/test setting where you kept originals)
# ---------------------------------------------------------------------------
def load_manifest(manifest_path="test_data/manifest.json"):
    if not os.path.exists(manifest_path):
        return {}
    with open(manifest_path) as f:
        manifest = json.load(f)
    lookup = {}
    for entry in manifest.get("clean_files", []):
        lookup[entry["name"]] = entry["sha256"]
    for entry in manifest.get("corrupted_files", []):
        lookup[entry["name"]] = entry.get("original_sha256")
    return lookup


def sha256_of(path):
    with open(path, "rb") as f:
        return hashlib.sha256(f.read()).hexdigest()


def byte_similarity(path, original_hash, hash_lookup_reverse=None):
    """We don't have the original bytes at recovery time in a real scenario,
    only its hash if a manifest existed. This returns whether the recovered
    file is a full byte-for-byte match to a known original -- useful signal,
    not available in every real case."""
    if not original_hash:
        return None
    recovered_hash = sha256_of(path)
    return recovered_hash == original_hash


# ---------------------------------------------------------------------------
# STEP 4: Score aggregation
# ---------------------------------------------------------------------------
def compute_integrity_score(fragment, structural_valid, entropy, exact_match):
    score = 0
    notes = []

    # Header/footer presence (from Person 1) -- up to 30 pts
    if fragment.get("header_found"):
        score += 15
        notes.append("header present (+15)")
    if fragment.get("footer_found"):
        score += 15
        notes.append("footer present (+15)")

    # Structural validation -- up to 40 pts
    if structural_valid is True:
        score += 40
        notes.append("structural validation passed (+40)")
    elif structural_valid is False:
        notes.append("structural validation FAILED (+0)")
    else:
        score += 20  # validator unavailable, don't penalize fully
        notes.append("structural validation unavailable, partial credit (+20)")

    # Entropy sanity -- up to 15 pts
    if 2.0 <= entropy <= 7.4:
        score += 15
        notes.append("entropy in normal range (+15)")
    elif entropy > 7.4:
        notes.append("entropy abnormally high, possible corruption/encryption (+0)")
    else:
        score += 5
        notes.append("entropy very low, likely sparse/empty content (+5)")

    # Exact match bonus (only when ground truth is available) -- up to 15 pts
    if exact_match is True:
        score += 15
        notes.append("byte-exact match to known original (+15)")
    elif exact_match is False:
        notes.append("differs from known original (+0)")
    # exact_match is None -> no ground truth available, skip silently

    score = min(score, 100)

    if score >= 80:
        status = "intact"
    elif score >= 40:
        status = "partial"
    else:
        status = "corrupted"

    return score, status, notes


# ---------------------------------------------------------------------------
# STEP 5: Main pipeline
# ---------------------------------------------------------------------------
def assess_fragments(fragments_json="fragments.json", out_json="fragments_scored.json",
                      manifest_path="test_data/manifest.json"):
    with open(fragments_json) as f:
        fragments = json.load(f)

    hash_lookup = load_manifest(manifest_path)
    scored = []

    for frag in fragments:
        path = frag["file_path"]
        ftype = frag["detected_type"]
        data = open(path, "rb").read()

        entropy = shannon_entropy(data)

        validator = VALIDATORS.get(ftype)
        structural_valid, structural_note = (None, "No validator for this type")
        if validator:
            structural_valid, structural_note = validator(path)

        # exact match check only works if this fragment corresponds to a
        # known test file name -- in real forensics you usually won't have
        # this, it's here for demo scoring / self-evaluation.
        original_name = frag.get("original_name")
        exact_match = None
        if original_name and original_name in hash_lookup:
            exact_match = byte_similarity(path, hash_lookup[original_name])

        score, status, notes = compute_integrity_score(frag, structural_valid, entropy, exact_match)

        frag_scored = dict(frag)
        frag_scored.update({
            "entropy": entropy,
            "entropy_verdict": entropy_verdict(entropy),
            "structural_valid": structural_valid,
            "structural_note": structural_note,
            "exact_match_to_original": exact_match,
            "integrity_score": score,
            "status": status,
            "scoring_breakdown": notes,
        })
        scored.append(frag_scored)

    with open(out_json, "w") as f:
        json.dump(scored, f, indent=2)

    print(f"Scored {len(scored)} fragments -> {out_json}")
    for f_ in scored:
        print(f"  {f_['fragment_id']} ({f_['detected_type']}): "
              f"score={f_['integrity_score']} status={f_['status']} "
              f"entropy={f_['entropy']}")
    return scored


if __name__ == "__main__":
    if not os.path.exists("fragments.json"):
        print("Run person1_fragment_recovery.py first to produce fragments.json")
    else:
        assess_fragments()
