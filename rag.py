import glob
import os

import faiss
import numpy as np
from sentence_transformers import SentenceTransformer

from log_utils import log

KB_DIR = os.path.join(os.path.dirname(__file__), "knowledge_base")
SIMILARITY_THRESHOLD = 0.35
TOP_K = 2

_model = None
_index = None
_docs = []  # list of (filename, text)


def _load_documents():
    docs = []
    for path in sorted(glob.glob(os.path.join(KB_DIR, "*.txt"))):
        with open(path, "r", encoding="utf-8") as f:
            docs.append((os.path.basename(path), f.read().strip()))
    return docs


def build_index():
    global _model, _index, _docs
    _docs = _load_documents()
    _model = SentenceTransformer("all-MiniLM-L6-v2")
    embeddings = _model.encode([text for _, text in _docs], normalize_embeddings=True)
    _index = faiss.IndexFlatIP(embeddings.shape[1])
    _index.add(np.array(embeddings, dtype=np.float32))
    log("RAG", f"indexed {len(_docs)} documents from knowledge_base/")


def retrieve(query: str):
    """Returns [(filename, text, score), ...] for chunks above the similarity threshold, best first."""
    if _index is None:
        build_index()

    query_vec = _model.encode([query], normalize_embeddings=True)
    scores, indices = _index.search(np.array(query_vec, dtype=np.float32), TOP_K)

    results = []
    for score, idx in zip(scores[0], indices[0]):
        if idx == -1 or score < SIMILARITY_THRESHOLD:
            continue
        filename, text = _docs[idx]
        results.append((filename, text, float(score)))
    return results
