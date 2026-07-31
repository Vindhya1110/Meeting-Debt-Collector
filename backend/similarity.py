import os
import numpy as np
from models import get_db

EMBEDDING_MODEL_NAME = os.getenv("EMBEDDING_MODEL", "sentence-transformers/all-MiniLM-L6-v2")

_model = None

def _get_model():
    """Lazy-load the sentence-transformer model — keeps server startup fast
    and avoids paying the ~90MB download cost unless similarity is actually used."""
    global _model
    if _model is None:
        from sentence_transformers import SentenceTransformer
        _model = SentenceTransformer(EMBEDDING_MODEL_NAME)
    return _model

def get_embedding(text: str) -> np.ndarray:
    """Real sentence embedding via all-MiniLM-L6-v2 (384-dim)."""
    if not text:
        text = ""
    model = _get_model()
    return model.encode(text, convert_to_numpy=True, normalize_embeddings=True)

def cosine_similarity(vec_a: np.ndarray, vec_b: np.ndarray) -> float:
    denom = (np.linalg.norm(vec_a) * np.linalg.norm(vec_b))
    if denom == 0:
        return 0.0
    return float(np.dot(vec_a, vec_b) / denom)

RENEGOTIATION_PHRASES = [
    "push that to", "push this to", "move it to", "delay",
    "i'll do half", "partial", "next week", "next sprint",
    "not going to make", "won't be able", "can we extend"
]

MODIFICATION_THRESHOLD = 0.55  # cosine similarity score to consider same task

def classify_against_open(new_commitment: dict) -> dict:
    """
    Compare a new commitment against all open commitments.
    Returns one of:
    - {"action": "new"} — no match, insert as new
    - {"action": "merge", "target_id": "..."} — duplicate, merge
    - {"action": "renegotiate", "target_id": "...", "new_deadline": "..."} — update existing
    - {"action": "recommit", "target_id": "...", "prior_missed": true} — same promise again

    THREE OUTCOMES FROM ONE ENGINE — this is U6, U7, and F9 combined.
    """
    conn = get_db()
    open_items = conn.execute("""
        SELECT id, owner, normalized_task, deadline, status, nudge_count
        FROM commitments
        WHERE status IN ('open', 'nudged', 'escalated', 'missed')
    """).fetchall()
    conn.close()

    if not open_items:
        return {"action": "new"}

    new_vec = get_embedding(new_commitment.get("normalized_task", ""))
    new_owner = (new_commitment.get("owner") or "").lower()
    new_text = new_commitment.get("commitment_text", "").lower()

    best_match = None
    best_score = 0.0

    for item in open_items:
        existing_vec = get_embedding(item["normalized_task"])
        score = cosine_similarity(new_vec, existing_vec)

        # Same owner boosts score — same person, similar task, almost certainly the same thread
        if item["owner"].lower() == new_owner:
            score = min(1.0, score * 1.15)

        if score > best_score:
            best_score = score
            best_match = item

    if best_score < MODIFICATION_THRESHOLD or best_match is None:
        return {"action": "new"}

    # Match found — determine what kind
    is_renegotiation = any(phrase in new_text for phrase in RENEGOTIATION_PHRASES)

    if is_renegotiation:
        return {
            "action": "renegotiate",
            "target_id": best_match["id"],
            "new_deadline": new_commitment.get("deadline"),
            "reason": "speaker modified existing commitment",
            "similarity": best_score
        }

    if best_match["status"] == "missed":
        return {
            "action": "recommit",
            "target_id": best_match["id"],
            "prior_missed": True,
            "warning": "This was committed before and missed. Second time flagged.",
            "similarity": best_score
        }

    # Same task, same person, still open = duplicate
    return {
        "action": "merge",
        "target_id": best_match["id"],
        "note": "Duplicate commitment detected across meetings",
        "similarity": best_score
    }
