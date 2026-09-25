"""
person3_classification_ai.py
OWNER: Person 3

What this does:
  1. Reads fragments_scored.json (Person 2's output)
  2. Rule-based categorization (document / image / database_log / system_trace)
  3. AI layer: zero-shot text classification for documents using sentence
     embeddings + cosine similarity (no training data needed -- good for 24h)
  4. Priority scoring: combines integrity_score + category value + recency
  5. Writes fragments_final.json for Person 4 (the Streamlit app) to consume

Run directly to test against Person 2's output:
    python person2_integrity_assessment.py  (produces fragments_scored.json)
    python person3_classification_ai.py     (consumes it, produces fragments_final.json)

NOTE ON THE AI COMPONENT:
  sentence-transformers gives a real embedding-based classifier without
  needing labeled training data -- good tradeoff for a 24h hackathon.
  If it's not installed or too slow to download in your environment,
  this file automatically falls back to a TF-IDF + cosine similarity
  classifier (pure scikit-learn, no internet needed), so the pipeline
  never breaks. Tell the judges which one you ended up using.
"""

import os
import json
import zipfile
import re

# ---------------------------------------------------------------------------
# STEP 1: Rule-based categorization (baseline -- always works)
# ---------------------------------------------------------------------------
CATEGORY_MAP = {
    "jpeg": "image",
    "png": "image",
    "pdf": "document",
    "zip_docx": "document",
    "sqlite": "database_log",
}

# Manual value ranking used in prioritization (investigator judgment call --
# tune this for your specific hackathon scenario / judges' expectations)
CATEGORY_VALUE = {
    "document": 30,
    "database_log": 25,
    "image": 15,
    "system_trace": 20,
    "unknown": 5,
}

LABELS = ["financial_record", "personal_correspondence", "system_log",
          "legal_document", "technical_notes", "miscellaneous"]


def rule_based_category(detected_type):
    return CATEGORY_MAP.get(detected_type, "unknown")


# ---------------------------------------------------------------------------
# STEP 2: Extract text content from recoverable documents (best-effort)
# ---------------------------------------------------------------------------
def extract_text(path, detected_type):
    try:
        if detected_type == "pdf":
            try:
                from pypdf import PdfReader
            except ImportError:
                from PyPDF2 import PdfReader
            reader = PdfReader(path)
            text = " ".join(page.extract_text() or "" for page in reader.pages)
            return text.strip()
        elif detected_type == "zip_docx":
            with zipfile.ZipFile(path) as z:
                if "word/document.xml" in z.namelist():
                    xml = z.read("word/document.xml").decode("utf-8", errors="ignore")
                    text = re.sub("<[^<]+?>", " ", xml)
                    return text.strip()
    except Exception:
        pass
    return ""


# ---------------------------------------------------------------------------
# STEP 3: AI classification layer
#   Try sentence-transformers first (semantic embeddings), fall back to
#   TF-IDF if unavailable. Either way this is the visible "AI" component
#   beyond simple rule matching -- make sure to mention it on your
#   architecture slide.
# ---------------------------------------------------------------------------
_embedding_model = None
_backend = None


def _get_backend():
    global _embedding_model, _backend
    if _backend is not None:
        return _backend
    try:
        from sentence_transformers import SentenceTransformer
        _embedding_model = SentenceTransformer("all-MiniLM-L6-v2")
        _backend = "sentence-transformers"
    except Exception:
        _backend = "tfidf"
    return _backend


def classify_text_semantic(text, labels=LABELS):
    """sentence-transformers path: embed text + labels, cosine similarity."""
    from sentence_transformers import util
    label_embeddings = _embedding_model.encode(labels, convert_to_tensor=True)
    text_embedding = _embedding_model.encode(text, convert_to_tensor=True)
    scores = util.cos_sim(text_embedding, label_embeddings)[0]
    best_idx = int(scores.argmax())
    return labels[best_idx], float(scores[best_idx])


def classify_text_tfidf(text, labels=LABELS):
    """Fallback: TF-IDF + cosine similarity against label *descriptions*
    (since we have no training data, we compare the fragment's text against
    a short seed phrase per label -- crude but functional and dependency-light)."""
    from sklearn.feature_extraction.text import TfidfVectorizer
    from sklearn.metrics.pairwise import cosine_similarity

    label_seeds = {
        "financial_record": "invoice payment balance account transaction budget financial money",
        "personal_correspondence": "dear hello meeting email letter regards personal message",
        "system_log": "error warning event login attempt system log timestamp process",
        "legal_document": "agreement contract clause terms legal party signature witness",
        "technical_notes": "code function variable technical architecture design system notes",
        "miscellaneous": "general information document content text file",
    }
    corpus = [text] + [label_seeds[l] for l in labels]
    if not text.strip():
        return "miscellaneous", 0.0
    vectorizer = TfidfVectorizer().fit(corpus)
    vectors = vectorizer.transform(corpus)
    sims = cosine_similarity(vectors[0:1], vectors[1:])[0]
    best_idx = int(sims.argmax())
    return labels[best_idx], float(sims[best_idx])


def classify_text(text):
    if not text or len(text.strip()) < 3:
        return "miscellaneous", 0.0
    backend = _get_backend()
    try:
        if backend == "sentence-transformers":
            return classify_text_semantic(text)
        else:
            return classify_text_tfidf(text)
    except Exception as e:
        print(f"  [warn] classification failed ({e}), defaulting to miscellaneous")
        return "miscellaneous", 0.0


# ---------------------------------------------------------------------------
# STEP 4: Priority scoring
#   priority = 0.5 * integrity_score + 0.35 * category_value (normalized)
#              + 0.15 * recency_bonus
#   Weights are a judgment call -- tune freely, just document your choice
#   on the architecture slide.
# ---------------------------------------------------------------------------
def compute_priority(integrity_score, category, has_ai_label_confidence=None):
    category_value = CATEGORY_VALUE.get(category, CATEGORY_VALUE["unknown"])
    # normalize category_value (max 30) to a 0-100 scale for blending
    category_component = (category_value / 30) * 100

    # recency: not available in our carved-fragment metadata by default,
    # so treat as neutral (50) unless you extend Person 1's output with
    # real timestamps recovered from filesystem metadata.
    recency_component = 50

    priority = (0.5 * integrity_score) + (0.35 * category_component) + (0.15 * recency_component)
    return round(priority, 1)


# ---------------------------------------------------------------------------
# STEP 5: Main pipeline
# ---------------------------------------------------------------------------
def classify_and_prioritize(scored_json="fragments_scored.json", out_json="fragments_final.json"):
    with open(scored_json) as f:
        fragments = json.load(f)

    backend = _get_backend()
    print(f"Using AI classification backend: {backend}")

    final = []
    for frag in fragments:
        category = rule_based_category(frag["detected_type"])
        ai_label, ai_confidence = None, None

        if category == "document":
            text = extract_text(frag["file_path"], frag["detected_type"])
            ai_label, ai_confidence = classify_text(text)

        priority = compute_priority(frag["integrity_score"], category)

        frag_final = dict(frag)
        frag_final.update({
            "category": category,
            "ai_label": ai_label,
            "ai_label_confidence": round(ai_confidence, 3) if ai_confidence is not None else None,
            "priority_score": priority,
        })
        final.append(frag_final)

    # sort by priority descending for convenience
    final.sort(key=lambda x: x["priority_score"], reverse=True)

    with open(out_json, "w") as f:
        json.dump(final, f, indent=2)

    print(f"Classified {len(final)} fragments -> {out_json}")
    for f_ in final:
        label_str = f" ai_label={f_['ai_label']}({f_['ai_label_confidence']})" if f_['ai_label'] else ""
        print(f"  {f_['fragment_id']}: category={f_['category']}{label_str} "
              f"priority={f_['priority_score']}")
    return final


if __name__ == "__main__":
    if not os.path.exists("fragments_scored.json"):
        print("Run person2_integrity_assessment.py first to produce fragments_scored.json")
    else:
        classify_and_prioritize()
