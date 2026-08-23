"""
Vector store abstraction with two interchangeable backends:

  - FaissStore   : local, free, zero infra — one .index + .meta.json file
                   per gym on disk. Recommended default for an MVP.
  - QdrantStore  : swap in once you need multi-process writers, hosted
                   persistence, or > a few hundred thousand vectors per gym.
                   Qdrant Cloud's free tier (1GB) is plenty for this.

Both are driven by Google Gemini's free-tier embedding model, so no other
paid service is required to stand this up.

Select via config.VECTOR_BACKEND ("faiss" | "qdrant").
"""
import json
import os
import uuid
import numpy as np
from google import genai
from google.genai import types

from . import config

def _get_client():
    key = config.GEMINI_API_KEY or os.getenv("GEMINI_API_KEY", "")
    if not key:
        return None
    return genai.Client(api_key=key)


GEMINI_EMBED_BATCH_LIMIT = 100  # Gemini's BatchEmbedContentsRequest hard caps at 100 requests/call


def embed_texts(texts: list[str], task_type: str = "RETRIEVAL_DOCUMENT") -> np.ndarray:
    """Embed texts with Gemini's free-tier embedding model, batching internally
    since the API rejects any single call with more than 100 texts — easy to
    hit once a gym has 100+ questions configured, so every caller here can
    just pass however many texts it has without worrying about the limit."""
    if not texts:
        return np.zeros((0, config.EMBED_DIM), dtype="float32")
    
    client = _get_client()
    if not client:
        # Return deterministic dummy vectors if API key is not configured yet
        return np.zeros((len(texts), config.EMBED_DIM), dtype="float32")

    all_vecs = []
    try:
        for i in range(0, len(texts), GEMINI_EMBED_BATCH_LIMIT):
            batch = texts[i:i + GEMINI_EMBED_BATCH_LIMIT]
            result = client.models.embed_content(
                model=config.GEMINI_EMBED_MODEL,
                contents=batch,
                config=types.EmbedContentConfig(
                    task_type=task_type,
                    output_dimensionality=config.EMBED_DIM,
                ),
            )
            all_vecs.extend(e.values for e in result.embeddings)
    except Exception as e:
        print(f"[Embedding Warning] Gemini embed_content failed: {e}. Falling back to offline zero-vectors.")
        return np.zeros((len(texts), config.EMBED_DIM), dtype="float32")

    vecs = np.array(all_vecs, dtype="float32")
    if vecs.shape[0] != len(texts):
        return np.zeros((len(texts), config.EMBED_DIM), dtype="float32")
    norms = np.linalg.norm(vecs, axis=1, keepdims=True)
    norms[norms == 0] = 1
    return vecs / norms



def embed_query(text: str) -> np.ndarray:
    return embed_texts([text], task_type="RETRIEVAL_QUERY")[0]


# ---------------------------------------------------------------- FAISS ----
class FaissStore:
    def __init__(self, gym_id: str):
        import faiss
        self.faiss = faiss
        self.gym_id = gym_id
        self.index_path = os.path.join(config.DATA_DIR, f"{gym_id}.index")
        self.meta_path = os.path.join(config.DATA_DIR, f"{gym_id}.meta.json")
        self.index = faiss.IndexFlatIP(config.EMBED_DIM)
        self.chunks: list[dict] = []
        if os.path.exists(self.index_path) and os.path.exists(self.meta_path):
            self.index = faiss.read_index(self.index_path)
            with open(self.meta_path) as f:
                self.chunks = json.load(f)

    def upsert(self, chunks: list[dict]):
        """Merge-upsert by chunk id: updates/adds the given chunks but keeps
        everything else already indexed. A full wipe-and-replace here would
        mean the wizard's /config save and a PDF /ingest-pdf import destroy
        each other's indexed knowledge depending on which ran last — this
        keeps them additive instead. Re-embeds everything on each call since
        FAISS's flat index has no cheap in-place update; fine at this scale.
        """
        existing = {c["id"]: c for c in self.chunks}
        for c in chunks:
            existing[c["id"]] = c
        merged = list(existing.values())
        self._write_all(merged)

    def replace_ids(self, ids_to_remove: set[str]):
        """Drop chunks whose id is in ids_to_remove (e.g. questions deleted
        from qa_schema.json) without touching anything else. Called after a
        full wizard save, which is the one moment we know the complete
        current canonical schema."""
        if not ids_to_remove:
            return
        kept = [c for c in self.chunks if c["id"] not in ids_to_remove]
        if len(kept) != len(self.chunks):
            self._write_all(kept)

    def _write_all(self, chunks: list[dict]):
        texts = [c["text"] for c in chunks]
        vecs = embed_texts(texts)
        self.index = self.faiss.IndexFlatIP(config.EMBED_DIM)
        if len(chunks):
            self.index.add(vecs)
        self.chunks = chunks
        self.faiss.write_index(self.index, self.index_path)
        with open(self.meta_path, "w") as f:
            json.dump(self.chunks, f)

    def search(self, query: str, top_k: int = config.TOP_K) -> list[dict]:
        if self.index.ntotal == 0:
            return []
        qvec = embed_query(query).reshape(1, -1)
        scores, idxs = self.index.search(qvec, min(top_k, self.index.ntotal))
        results = []
        for score, idx in zip(scores[0], idxs[0]):
            if idx == -1:
                continue
            chunk = dict(self.chunks[idx])
            chunk["score"] = float(score)
            results.append(chunk)
        return results

    def all_ids(self) -> set[str]:
        return {c["id"] for c in self.chunks}


# --------------------------------------------------------------- QDRANT ----
class QdrantStore:
    def __init__(self, gym_id: str):
        from qdrant_client import QdrantClient
        from qdrant_client.models import Distance, VectorParams
        self.gym_id = gym_id
        self.collection = f"gym_{gym_id}"
        self.client = QdrantClient(url=config.QDRANT_URL, api_key=config.QDRANT_API_KEY or None)
        if not self.client.collection_exists(self.collection):
            self.client.create_collection(
                collection_name=self.collection,
                vectors_config=VectorParams(size=config.EMBED_DIM, distance=Distance.COSINE),
            )

    def upsert(self, chunks: list[dict]):
        """Merge-upsert: real point-level upsert by id, no collection wipe —
        so a wizard /config save and a PDF /ingest-pdf import stay additive
        instead of one destroying the other's indexed knowledge. Qdrant point
        ids must be an unsigned int or a UUID, so our own "gym::QID" string
        ids are hashed into a deterministic UUID here and kept as a "chunk_id"
        payload field for lookups/deletes."""
        from qdrant_client.models import PointStruct
        texts = [c["text"] for c in chunks]
        vecs = embed_texts(texts) if texts else []
        points = [
            PointStruct(
                id=str(uuid.uuid5(uuid.NAMESPACE_URL, chunks[i]["id"])),
                vector=vecs[i].tolist(),
                payload={**chunks[i]["metadata"], "text": chunks[i]["text"], "chunk_id": chunks[i]["id"]},
            )
            for i in range(len(chunks))
        ]
        if points:
            self.client.upsert(collection_name=self.collection, points=points)

    def replace_ids(self, ids_to_remove: set[str]):
        """Drop points whose original chunk_id is in ids_to_remove (e.g.
        questions deleted from qa_schema.json) without touching anything else."""
        if not ids_to_remove:
            return
        from qdrant_client.models import Filter, FieldCondition, MatchAny, FilterSelector
        self.client.delete(
            collection_name=self.collection,
            points_selector=FilterSelector(
                filter=Filter(must=[FieldCondition(key="chunk_id", match=MatchAny(any=list(ids_to_remove)))])
            ),
        )

    def search(self, query: str, top_k: int = config.TOP_K) -> list[dict]:
        qvec = embed_query(query)
        hits = self.client.search(collection_name=self.collection, query_vector=qvec.tolist(), limit=top_k)
        return [{"text": h.payload.get("text", ""), "metadata": h.payload, "score": h.score} for h in hits]

    def all_ids(self) -> set[str]:
        ids = set()
        offset = None
        while True:
            points, offset = self.client.scroll(collection_name=self.collection, limit=256, offset=offset, with_payload=True, with_vectors=False)
            for p in points:
                cid = p.payload.get("chunk_id")
                if cid:
                    ids.add(cid)
            if offset is None:
                break
        return ids


def get_store(gym_id: str):
    if config.VECTOR_BACKEND == "qdrant":
        return QdrantStore(gym_id)
    return FaissStore(gym_id)
