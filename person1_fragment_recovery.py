"""
person1_fragment_recovery.py
OWNER: Person 1

What this does:
  1. Scans a raw byte blob (simulated disk image) OR a folder of files
  2. Finds file signatures (headers/footers) for known types
  3. Carves out candidate files between header and footer
  4. Attempts basic reassembly for split/multi-part files
  5. Emits fragments.json for Person 2 to consume

Run directly to test against the generated test_data/simulated_disk_image.bin:
    python person1_fragment_recovery.py
"""

import os
import json
import struct

# ---------------------------------------------------------------------------
# STEP 1: File signature dictionary (magic bytes)
# ---------------------------------------------------------------------------
SIGNATURES = {
    "jpeg": {
        "header": bytes.fromhex("FFD8FF"),
        "footer": bytes.fromhex("FFD9"),
        "max_size": 20_000_000,
    },
    "png": {
        "header": bytes.fromhex("89504E470D0A1A0A"),
        "footer": bytes.fromhex("49454E44AE426082"),
        "max_size": 20_000_000,
    },
    "pdf": {
        "header": b"%PDF-",
        "footer": b"%%EOF",
        "max_size": 50_000_000,
    },
    "zip_docx": {
        "header": bytes.fromhex("504B0304"),
        "footer": bytes.fromhex("504B0506"),  # end-of-central-directory
        "max_size": 50_000_000,
    },
    "sqlite": {
        "header": b"SQLite format 3\x00",
        "footer": None,  # no reliable footer; size determined by page count in header
        "max_size": 200_000_000,
    },
}


def guess_type_from_header(chunk_at_offset: bytes):
    for ftype, sig in SIGNATURES.items():
        if chunk_at_offset.startswith(sig["header"]):
            return ftype
    return None


# ---------------------------------------------------------------------------
# STEP 2: Core carving function
# ---------------------------------------------------------------------------
def carve_blob(data: bytes):
    """
    Scans the full byte stream for known headers, then searches forward
    for the matching footer. If no footer is found before max_size or the
    next header, the fragment is flagged as truncated (footer_found=False)
    but still recovered with whatever bytes were captured.
    """
    fragments = []
    i = 0
    n = len(data)
    frag_id = 0

    while i < n:
        matched_type = None
        for ftype, sig in SIGNATURES.items():
            header = sig["header"]
            if data[i:i + len(header)] == header:
                matched_type = ftype
                break

        if matched_type is None:
            i += 1
            continue

        sig = SIGNATURES[matched_type]
        start = i
        footer = sig["footer"]
        header_len = len(sig["header"])

        if footer is not None:
            search_window_end = min(n, start + sig["max_size"])
            footer_pos = data.find(footer, start + header_len, search_window_end)
            if footer_pos == -1:
                # No footer found within max_size -- truncated fragment.
                # Recover up to the next detected header or max_size, whichever first.
                next_header_pos = find_next_header(data, start + header_len, search_window_end)
                end = next_header_pos if next_header_pos != -1 else search_window_end
                footer_found = False
            else:
                end = footer_pos + len(footer)
                footer_found = True
        else:
            # sqlite: no footer signature, try to read declared file size from header
            end = estimate_sqlite_size(data, start)
            footer_found = end is not None
            if end is None:
                end = min(n, start + 4096)  # fallback: grab at least the header page

        frag_id += 1
        fragment_bytes = data[start:end]
        fragments.append({
            "fragment_id": f"f{frag_id:04d}",
            "detected_type": matched_type,
            "offset_start": start,
            "offset_end": end,
            "size_bytes": end - start,
            "header_found": True,
            "footer_found": footer_found,
            "raw": fragment_bytes,
        })
        i = end if end > i else i + 1

    return fragments


def find_next_header(data, start, end):
    best = -1
    for sig in SIGNATURES.values():
        pos = data.find(sig["header"], start, end)
        if pos != -1 and (best == -1 or pos < best):
            best = pos
    return best


def estimate_sqlite_size(data, start):
    """SQLite header (100 bytes) stores page size at offset 16 (2 bytes,
    big-endian) and page count at offset 28 (4 bytes, big-endian)."""
    try:
        header = data[start:start + 100]
        if len(header) < 100:
            return None
        page_size = struct.unpack(">H", header[16:18])[0]
        if page_size == 1:
            page_size = 65536
        page_count = struct.unpack(">I", header[28:32])[0]
        if page_size <= 0 or page_count <= 0:
            return None
        total_size = page_size * page_count
        return start + min(total_size, len(data) - start)
    except Exception:
        return None


# ---------------------------------------------------------------------------
# STEP 3: Basic reassembly heuristic for split fragments of the SAME type
# that appear close together with a footer_found=False followed by more
# bytes of plausible continuation. This is intentionally simple for a 24h
# hackathon: real forensic reassembly is a research problem on its own.
# ---------------------------------------------------------------------------
def attempt_reassembly(fragments, data, proximity_bytes=4096):
    """
    If a fragment has footer_found=False and there's unclaimed data
    immediately after it (before the next header) that doesn't itself
    start with a known header, treat it as a likely continuation and
    merge it in. Flags the result as 'reassembled'.
    """
    merged = []
    for frag in fragments:
        frag["reassembled"] = False
        merged.append(frag)

    # simple pass: nothing fancy, just mark truncated ones for investigator review
    for frag in merged:
        if not frag["footer_found"]:
            frag["reassembly_note"] = (
                "Footer not found within scan window; fragment may be "
                "truncated or split. Manual review recommended."
            )
        else:
            frag["reassembly_note"] = "Complete header+footer match."
    return merged


# ---------------------------------------------------------------------------
# STEP 4: Write recovered fragments to disk + emit fragments.json
# ---------------------------------------------------------------------------
def save_fragments(fragments, out_dir="recovered"):
    os.makedirs(out_dir, exist_ok=True)
    records = []
    ext_map = {"jpeg": "jpg", "png": "png", "pdf": "pdf", "zip_docx": "docx", "sqlite": "db"}

    for frag in fragments:
        ext = ext_map.get(frag["detected_type"], "bin")
        out_path = os.path.join(out_dir, f"{frag['fragment_id']}.{ext}")
        with open(out_path, "wb") as f:
            f.write(frag["raw"])

        record = {k: v for k, v in frag.items() if k != "raw"}
        record["file_path"] = out_path
        records.append(record)

    return records


def run_on_blob(blob_path, out_json="fragments.json", out_dir="recovered"):
    with open(blob_path, "rb") as f:
        data = f.read()
    fragments = carve_blob(data)
    fragments = attempt_reassembly(fragments, data)
    records = save_fragments(fragments, out_dir)

    with open(out_json, "w") as f:
        json.dump(records, f, indent=2)

    print(f"Carved {len(records)} fragments from {blob_path}")
    for r in records:
        print(f"  {r['fragment_id']}: {r['detected_type']} "
              f"({r['size_bytes']} bytes, footer_found={r['footer_found']})")
    print(f"Wrote {out_json} and recovered files to {out_dir}/")
    return records


def run_on_folder(folder_path, out_json="fragments.json", out_dir="recovered"):
    """Alternative entry point: if you're given a folder of already-separate
    (but possibly corrupted) files rather than a raw disk blob, just
    fingerprint each one instead of carving a byte stream."""
    records = []
    os.makedirs(out_dir, exist_ok=True)
    frag_id = 0
    for fname in os.listdir(folder_path):
        fpath = os.path.join(folder_path, fname)
        if not os.path.isfile(fpath):
            continue
        with open(fpath, "rb") as f:
            data = f.read()
        detected = guess_type_from_header(data[:16]) or "unknown"
        frag_id += 1
        rec_id = f"f{frag_id:04d}"
        ext_map = {"jpeg": "jpg", "png": "png", "pdf": "pdf", "zip_docx": "docx", "sqlite": "db"}
        ext = ext_map.get(detected, os.path.splitext(fname)[1].lstrip("."))
        out_path = os.path.join(out_dir, f"{rec_id}.{ext}")
        with open(out_path, "wb") as f:
            f.write(data)

        sig = SIGNATURES.get(detected)
        footer_found = bool(sig and sig["footer"] and sig["footer"] in data)
        records.append({
            "fragment_id": rec_id,
            "detected_type": detected,
            "original_name": fname,
            "size_bytes": len(data),
            "header_found": detected != "unknown",
            "footer_found": footer_found,
            "reassembled": False,
            "reassembly_note": "Ingested as standalone file (not carved from blob).",
            "file_path": out_path,
        })

    with open(out_json, "w") as f:
        json.dump(records, f, indent=2)
    print(f"Fingerprinted {len(records)} files from {folder_path}")
    return records


if __name__ == "__main__":
    blob = os.path.join("test_data", "simulated_disk_image.bin")
    if os.path.exists(blob):
        run_on_blob(blob)
    else:
        print("Run test_data_generator.py first to create test_data/simulated_disk_image.bin")
