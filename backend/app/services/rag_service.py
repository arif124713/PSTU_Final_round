import os
import pickle
import re

import pymupdf
from sklearn.feature_extraction.text import TfidfVectorizer

from app.config import settings
from app.schemas.support import ChatResponse

# We use TF-IDF retrieval instead of ChromaDB's default ONNX embedding
# function: onnxruntime's native extension fails to load on this machine's
# Python 3.14 (DLL init failure — a known class of problem for compiled
# extensions on a brand-new CPython release, the same issue we hit with
# matplotlib/langchain earlier). TF-IDF is pure numpy/scipy, has solid
# wheel support, and is more than adequate for a small PDF knowledge base.

_STORE_PATH = os.path.join(settings.chroma_persist_path, "tfidf_store.pkl")

LOW_CONFIDENCE_PHRASES = [
    "i don't have information",
    "i'm not sure",
    "i cannot find",
    "please contact support",
    "i don't know",
]

SYSTEM_PROMPT = (
    "You are a customer support assistant for the MoneyMove app. "
    "Answer using ONLY the provided context. If the context doesn't answer the question, say: "
    "\"I don't have information on that. Would you like to speak with a human agent?\""
)


class _Store:
    def __init__(self):
        self.ids: list[str] = []
        self.texts: list[str] = []
        self.metadatas: list[dict] = []
        self.vectorizer: TfidfVectorizer | None = None
        self.matrix = None

    def _refit(self):
        if not self.texts:
            self.vectorizer = None
            self.matrix = None
            return
        self.vectorizer = TfidfVectorizer(stop_words="english")
        self.matrix = self.vectorizer.fit_transform(self.texts)

    def add(self, ids: list[str], texts: list[str], metadatas: list[dict]):
        self.ids.extend(ids)
        self.texts.extend(texts)
        self.metadatas.extend(metadatas)
        self._refit()
        self.save()

    def delete_by_source(self, source: str):
        keep = [i for i, m in enumerate(self.metadatas) if m.get("source") != source]
        self.ids = [self.ids[i] for i in keep]
        self.texts = [self.texts[i] for i in keep]
        self.metadatas = [self.metadatas[i] for i in keep]
        self._refit()
        self.save()

    def query(self, text: str, n_results: int) -> tuple[list[str], list[dict]]:
        if not self.texts or self.vectorizer is None:
            return [], []
        query_vec = self.vectorizer.transform([text])
        scores = (self.matrix @ query_vec.T).toarray().ravel()
        top_indices = scores.argsort()[::-1][:n_results]
        top_indices = [i for i in top_indices if scores[i] > 0]
        return [self.texts[i] for i in top_indices], [self.metadatas[i] for i in top_indices]

    def count(self) -> int:
        return len(self.texts)

    def save(self):
        os.makedirs(settings.chroma_persist_path, exist_ok=True)
        with open(_STORE_PATH, "wb") as f:
            pickle.dump({"ids": self.ids, "texts": self.texts, "metadatas": self.metadatas}, f)

    @classmethod
    def load(cls) -> "_Store":
        store = cls()
        if os.path.exists(_STORE_PATH):
            with open(_STORE_PATH, "rb") as f:
                data = pickle.load(f)
            store.ids = data["ids"]
            store.texts = data["texts"]
            store.metadatas = data["metadatas"]
            store._refit()
        return store


_store: _Store | None = None


def get_store() -> _Store:
    global _store
    if _store is None:
        _store = _Store.load()
    return _store


def chunk_text(text: str, chunk_size: int = 500, overlap: int = 50) -> list[str]:
    """Simple sentence-aware sliding-window chunker (stands in for
    LangChain's RecursiveCharacterTextSplitter, which we dropped to avoid
    its heavy/fragile dependency tree on a brand-new Python version)."""
    sentences = re.split(r"(?<=[.?!\n])\s+", text.strip())
    chunks: list[str] = []
    current = ""
    for sentence in sentences:
        if len(current) + len(sentence) + 1 <= chunk_size:
            current = f"{current} {sentence}".strip()
        else:
            if current:
                chunks.append(current)
            current = (current[-overlap:] + " " + sentence).strip() if overlap else sentence
    if current:
        chunks.append(current)
    return [c for c in chunks if c.strip()]


def index_pdf(file_path: str, filename: str) -> int:
    doc = pymupdf.open(file_path)
    store = get_store()
    all_chunks: list[str] = []
    all_ids: list[str] = []
    all_metadatas: list[dict] = []

    for page_num, page in enumerate(doc):
        text = page.get_text()
        if not text.strip():
            continue
        page_chunks = chunk_text(text)
        for i, chunk in enumerate(page_chunks):
            all_chunks.append(chunk)
            all_ids.append(f"{filename}_p{page_num}_{i}")
            all_metadatas.append({"source": filename, "page": page_num})

    if all_chunks:
        store.add(all_ids, all_chunks, all_metadatas)

    return len(all_chunks)


def delete_document(filename: str) -> None:
    get_store().delete_by_source(filename)


def detect_confidence(response_text: str) -> str:
    lower = response_text.lower()
    if any(phrase in lower for phrase in LOW_CONFIDENCE_PHRASES):
        return "low"
    return "high"


async def answer_query(query: str) -> ChatResponse:
    store = get_store()
    if store.count() == 0:
        return ChatResponse(
            answer="I don't have information on that yet. Would you like to speak with a human agent?",
            sources=[],
            confidence="low",
            needs_human=True,
        )

    docs, metadatas = store.query(query, n_results=5)
    if not docs:
        return ChatResponse(
            answer="I don't have information on that. Would you like to speak with a human agent?",
            sources=[],
            confidence="low",
            needs_human=True,
        )

    context = "\n\n".join(docs)
    sources = sorted({m.get("source", "unknown") for m in metadatas})

    from app.services.deepseek_client import chat_completion

    completion = await chat_completion(
        [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": f"Context:\n{context}\n\nQuestion: {query}"},
        ]
    )
    answer = completion["choices"][0]["message"]["content"]
    confidence = detect_confidence(answer)

    return ChatResponse(
        answer=answer,
        sources=sources,
        confidence=confidence,
        needs_human=confidence == "low",
    )
