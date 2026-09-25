# ForensicAI — Intelligent Data Recovery & Evidence Reconstruction

## Setup (everyone runs this first)

```bash
python -m venv venv
source venv/bin/activate        # Windows: venv\Scripts\activate
pip install -r requirements.txt
python test_data_generator.py   # creates test_data/ with clean + corrupted samples
```

## File map

| File | Owner | Produces | Consumes |
|---|---|---|---|
| `test_data_generator.py` | shared | `test_data/` | — |
| `person1_fragment_recovery.py` | Person 1 | `fragments.json`, `recovered/*` | raw blob or folder |
| `person2_integrity_assessment.py` | Person 2 | `fragments_scored.json` | `fragments.json` |
| `person3_classification_ai.py` | Person 3 | `fragments_final.json` | `fragments_scored.json` |
| `person4_streamlit_app.py` | Person 4 | Streamlit UI | all of the above |

Each module can be run standalone from the command line while building
(`python person1_fragment_recovery.py`, etc.) — you don't need Streamlit
running to test your own piece. Person 4's app just calls the other three
files as Python modules (`import person1_fragment_recovery as p1`), so
**do not rename functions** without telling Person 4.

## Run the full pipeline manually (no UI)

```bash
python test_data_generator.py
python person1_fragment_recovery.py
python person2_integrity_assessment.py
python person3_classification_ai.py
```

Check `fragments_final.json` at the end — that's the full combined record
per fragment that the UI displays.

## Run the app

```bash
streamlit run person4_streamlit_app.py
```

Then in the Upload tab, check "Use the built-in demo dataset" and go
to Recovery → Start Recovery.

## The shared schema (do not break this)

Every fragment record flows through the pipeline gaining fields at each
stage. By the end (`fragments_final.json`) each record looks like:

```json
{
  "fragment_id": "f0001",
  "detected_type": "jpeg",
  "offset_start": 512,
  "offset_end": 3035,
  "size_bytes": 2523,
  "header_found": true,
  "footer_found": true,
  "reassembled": false,
  "reassembly_note": "Complete header+footer match.",
  "file_path": "recovered/f0001.jpg",

  "entropy": 5.452,
  "entropy_verdict": "normal range for structured content",
  "structural_valid": true,
  "structural_note": "Image structure valid (PIL verify passed)",
  "exact_match_to_original": null,
  "integrity_score": 85,
  "status": "intact",
  "scoring_breakdown": ["header present (+15)", "..."],

  "category": "image",
  "ai_label": null,
  "ai_label_confidence": null,
  "priority_score": 67.5
}
```

If you need to add a field, add it — just don't remove or rename
existing keys other modules depend on (`file_path`, `detected_type`,
`integrity_score`, `status`, `category`, `priority_score` are load-bearing
for Person 4's UI).

## Notes / known limitations (mention these on the architecture slide, don't hide them)

- The AI classification layer defaults to a TF-IDF + cosine-similarity
  zero-shot classifier (no internet/GPU needed). If you have time, swap
  in `sentence-transformers` (`all-MiniLM-L6-v2`) for real semantic
  embeddings — the code already supports both and picks automatically
  based on what's installed.
- Reassembly logic in Person 1's module is intentionally simple
  (header/footer carving + truncation flagging), not true fragment
  stitching across non-contiguous clusters — that's a much larger
  research problem. Be upfront about this scope limit when presenting.
- `exact_match_to_original` only works in the demo/test setting where
  `test_data/manifest.json` has original hashes — in a real recovery
  scenario you won't have this, it's there to prove your scoring works.
