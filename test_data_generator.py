"""
test_data_generator.py
Run this FIRST. Creates a folder of clean + corrupted sample files
so all 4 people can test their modules against the same data.

Usage:
    python test_data_generator.py
"""

import os
import sqlite3
import struct
import random
import hashlib
import json
from PIL import Image, ImageDraw

OUT_DIR = "test_data"
CLEAN_DIR = os.path.join(OUT_DIR, "clean")
CORRUPT_DIR = os.path.join(OUT_DIR, "corrupted")
MANIFEST_PATH = os.path.join(OUT_DIR, "manifest.json")


def ensure_dirs():
    os.makedirs(CLEAN_DIR, exist_ok=True)
    os.makedirs(CORRUPT_DIR, exist_ok=True)


def make_clean_image(path, text="SAMPLE"):
    img = Image.new("RGB", (300, 300), color=(30, 120, 180))
    draw = ImageDraw.Draw(img)
    draw.text((80, 140), text, fill=(255, 255, 255))
    img.save(path, "JPEG")


def make_clean_png(path, text="SAMPLE PNG"):
    img = Image.new("RGB", (300, 300), color=(180, 60, 60))
    draw = ImageDraw.Draw(img)
    draw.text((60, 140), text, fill=(255, 255, 255))
    img.save(path, "PNG")


def make_clean_pdf(path, content="This is a sample financial record for testing recovery."):
    # Minimal valid PDF written by hand (no external deps needed)
    pdf_bytes = f"""%PDF-1.4
1 0 obj<</Type/Catalog/Pages 2 0 R>>endobj
2 0 obj<</Type/Pages/Kids[3 0 R]/Count 1>>endobj
3 0 obj<</Type/Page/Parent 2 0 R/MediaBox[0 0 200 200]/Contents 4 0 R/Resources<</Font<</F1 5 0 R>>>>>>endobj
4 0 obj<</Length 73>>
stream
BT /F1 12 Tf 10 100 Td ({content}) Tj ET
endstream
endobj
5 0 obj<</Type/Font/Subtype/Type1/BaseFont/Helvetica>>endobj
xref
0 6
trailer<</Size 6/Root 1 0 R>>
%%EOF""".encode("latin-1", errors="ignore")
    with open(path, "wb") as f:
        f.write(pdf_bytes)


def make_clean_sqlite(path):
    conn = sqlite3.connect(path)
    cur = conn.cursor()
    cur.execute("CREATE TABLE logs (id INTEGER PRIMARY KEY, event TEXT, ts TEXT)")
    for i in range(20):
        cur.execute("INSERT INTO logs (event, ts) VALUES (?,?)",
                    (f"login_attempt_{i}", f"2026-09-{(i % 28)+1:02d}T10:00:00"))
    conn.commit()
    conn.close()


def make_clean_docx(path, text="Sample DOCX-like content for testing."):
    # Real docx is a zip; python-docx not guaranteed installed, so make a
    # minimal valid zip with docx-like structure using zipfile stdlib.
    import zipfile
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("word/document.xml",
                    f"<document><body><p>{text}</p></body></document>")
        z.writestr("[Content_Types].xml", "<Types></Types>")


def truncate_file(src, dst, keep_fraction=0.6):
    with open(src, "rb") as f:
        data = f.read()
    cut = int(len(data) * keep_fraction)
    with open(dst, "wb") as f:
        f.write(data[:cut])


def zero_out_middle(src, dst, start_fraction=0.3, end_fraction=0.5):
    with open(src, "rb") as f:
        data = bytearray(f.read())
    n = len(data)
    s, e = int(n * start_fraction), int(n * end_fraction)
    for i in range(s, e):
        data[i] = 0
    with open(dst, "wb") as f:
        f.write(data)


def inject_noise(src, dst, fraction=0.1):
    with open(src, "rb") as f:
        data = bytearray(f.read())
    n_bytes = int(len(data) * fraction)
    random.seed(42)
    for _ in range(n_bytes):
        idx = random.randint(0, len(data) - 1)
        data[idx] = random.randint(0, 255)
    with open(dst, "wb") as f:
        f.write(data)


def concat_into_blob(file_list, blob_path, junk_size=512):
    """Simulate a raw disk image: concatenate files with junk bytes between
    them so Person 1's carver has to find headers/footers inside a blob."""
    random.seed(7)
    with open(blob_path, "wb") as out:
        for fp in file_list:
            junk = bytes(random.randint(0, 255) for _ in range(junk_size))
            out.write(junk)
            with open(fp, "rb") as f:
                out.write(f.read())
        out.write(bytes(random.randint(0, 255) for _ in range(junk_size)))


def sha256_of(path):
    with open(path, "rb") as f:
        return hashlib.sha256(f.read()).hexdigest()


def main():
    ensure_dirs()
    manifest = {"clean_files": [], "corrupted_files": [], "blob": None}

    # 1. Clean originals
    clean_files = {
        "sample1.jpg": lambda p: make_clean_image(p, "PHOTO ONE"),
        "sample2.png": lambda p: make_clean_png(p, "PHOTO TWO"),
        "sample1.pdf": lambda p: make_clean_pdf(p, "Q3 financial summary confidential"),
        "sample1.db": lambda p: make_clean_sqlite(p),
        "sample1.docx": lambda p: make_clean_docx(p, "Meeting notes: project Phoenix"),
    }
    paths = {}
    for name, fn in clean_files.items():
        p = os.path.join(CLEAN_DIR, name)
        fn(p)
        paths[name] = p
        manifest["clean_files"].append({
            "name": name, "path": p, "sha256": sha256_of(p), "size": os.path.getsize(p)
        })

    # 2. Corrupted variants (one corruption type per file, on purpose)
    corrupt_specs = [
        ("sample1.jpg", "sample1_truncated.jpg", truncate_file, {"keep_fraction": 0.5}),
        ("sample2.png", "sample2_noise.png", inject_noise, {"fraction": 0.15}),
        ("sample1.pdf", "sample1_zeroed.pdf", zero_out_middle, {"start_fraction": 0.3, "end_fraction": 0.6}),
        ("sample1.db", "sample1_truncated.db", truncate_file, {"keep_fraction": 0.7}),
        ("sample1.docx", "sample1_noise.docx", inject_noise, {"fraction": 0.05}),
    ]
    for src_name, dst_name, fn, kwargs in corrupt_specs:
        src = paths[src_name]
        dst = os.path.join(CORRUPT_DIR, dst_name)
        fn(src, dst, **kwargs)
        manifest["corrupted_files"].append({
            "name": dst_name, "path": dst,
            "original": src_name,
            "original_sha256": sha256_of(src),
            "size": os.path.getsize(dst)
        })

    # 3. One "disk image" blob mixing clean + corrupted + junk, for Person 1's carver
    blob_inputs = [paths["sample1.jpg"], paths["sample1.pdf"],
                   os.path.join(CORRUPT_DIR, "sample2_noise.png"),
                   paths["sample1.db"]]
    blob_path = os.path.join(OUT_DIR, "simulated_disk_image.bin")
    concat_into_blob(blob_inputs, blob_path)
    manifest["blob"] = {"path": blob_path, "size": os.path.getsize(blob_path),
                         "contains": [os.path.basename(p) for p in blob_inputs]}

    with open(MANIFEST_PATH, "w") as f:
        json.dump(manifest, f, indent=2)

    print(f"Done. Clean files in {CLEAN_DIR}, corrupted in {CORRUPT_DIR}")
    print(f"Simulated disk image blob at {blob_path}")
    print(f"Manifest (with original hashes for scoring) at {MANIFEST_PATH}")


if __name__ == "__main__":
    main()
