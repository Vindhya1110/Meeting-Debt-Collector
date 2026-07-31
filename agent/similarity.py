"""
THREE outcomes from ONE engine:
  new         → insert as fresh commitment
  merge       → duplicate across meetings
  renegotiate → speaker modified existing open commitment
  recommit    → same promise made again after it was missed

Uses real sentence embeddings (all-MiniLM-L6-v2) for task similarity instead of
naive word overlap - more robust to paraphrasing across meetings.
"""
import os
import numpy as np
from models import get_db

EMBEDDING_MODEL_NAME = os.getenv("EMBEDDING_MODEL", "sentence-transformers/all-MiniLM-L6-v2")

_model = None

def _get_model():
    global _model
    if _model is None:
        from sentence_transformers import SentenceTransformer
        _model = SentenceTransformer(EMBEDDING_MODEL_NAME)
    return _model

def get_embedding(text: str) -> np.ndarray:
    if not text:
        text = ""
    return _get_model().encode(text, convert_to_numpy=True, normalize_embeddings=True)

def cosine_similarity(a: np.ndarray, b: np.ndarray) -> float:
    denom = np.linalg.norm(a) * np.linalg.norm(b)
    if denom == 0:
        return 0.0
    return float(np.dot(a, b) / denom)

THRESHOLD = 0.55

RENEG_PHRASES = [
    "push that to", "push this to", "move it to", "delay", "next week",
    "next sprint", "won't make", "can't make", "let's extend", "actually let's",
    "I'll do half", "partial", "not going to make", "can we extend"
]

def classify(new: dict) -> dict:
    conn = get_db()
    rows = conn.execute("""
        SELECT id, owner, normalized_task, status
        FROM commitments
        WHERE status IN ('open','nudged','escalated','missed')
    """).fetchall()
    conn.close()

    if not rows:
        return {"action": "new"}

    task = new.get("normalized_task", "")
    owner = (new.get("owner") or "").lower()
    text = new.get("commitment_text", "").lower()
    new_vec = get_embedding(task)

    best, best_score = None, 0.0
    for r in rows:
        score = cosine_similarity(new_vec, get_embedding(r["normalized_task"]))
        if r["owner"].lower() == owner:
            score = min(1.0, score * 1.15)
        if score > best_score:
            best_score, best = score, r

    if best_score < THRESHOLD or not best:
        return {"action": "new"}

    if any(p in text for p in RENEG_PHRASES):
        return {"action": "renegotiate", "target_id": best["id"],
                "new_deadline": new.get("deadline"), "similarity": best_score}

    if best["status"] == "missed":
        return {"action": "recommit", "target_id": best["id"],
                "warning": "This was committed before and missed. Second promise flagged.",
                "similarity": best_score}

    return {"action": "merge", "target_id": best["id"], "similarity": best_score}
