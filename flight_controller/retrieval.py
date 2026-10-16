"""Corpus search for the Flight Controller.

Index choice: Okapi BM25 over ~1k chunks held in memory (numpy, sparse postings).
Why not FAISS / sqlite-vec + sentence-transformers: the corpus is small enough that
exact lexical scoring returns in < 5 ms, flight-rule questions are keyword-heavy
("walkback", "PLSS", "reserve"), and it avoids a ~400 MB torch dependency that has no
wheels for this Python yet. The `search()` interface is the seam to swap in dense
embeddings later (docs/ARCHITECTURE.md).
"""
from __future__ import annotations

import json
import math
import re
from collections import Counter, defaultdict
from functools import lru_cache

from pipeline.geo import ROOT

CHUNKS = ROOT / "corpus" / "chunks" / "chunks.jsonl"
TOKEN = re.compile(r"[a-z0-9]+(?:[-'][a-z0-9]+)*")
STOP = set("the a an of and or to in on for with by is are was were be been at as from that this it its which into than "
           "then there these those not no can may will shall should would could has have had do does did but if".split())


def is_glossary(text: str) -> bool:
    """Abbreviation lists, tables of contents and indexes. Prose is full of function words
    (about 30 % of tokens); lists of terms are not."""
    words = re.findall(r"[A-Za-z]{2,}", text)
    if len(words) < 40:
        return False
    upper = sum(w.isupper() for w in words) / len(words)
    function = sum(w.lower() in STOP for w in words) / len(words)
    return upper > 0.35 or function < 0.08


def tokens(text: str) -> list[str]:
    return [t for t in TOKEN.findall(text.lower()) if t not in STOP and len(t) > 1]


class BM25:
    def __init__(self, docs: list[dict], k1: float = 1.4, b: float = 0.75):
        self.docs, self.k1, self.b = docs, k1, b
        self.post: dict[str, list[tuple[int, int]]] = defaultdict(list)
        self.len = []
        for i, d in enumerate(docs):
            tf = Counter(tokens(d["title"] + " " + d["text"]))
            self.len.append(sum(tf.values()))
            for t, n in tf.items():
                self.post[t].append((i, n))
        self.avg = sum(self.len) / max(len(self.len), 1)
        N = len(docs)
        self.idf = {t: math.log(1 + (N - len(p) + 0.5) / (len(p) + 0.5)) for t, p in self.post.items()}

    def search(self, query: str, k: int = 5) -> list[tuple[float, dict]]:
        scores: dict[int, float] = defaultdict(float)
        for t in set(tokens(query)):
            for i, n in self.post.get(t, ()):
                denom = n + self.k1 * (1 - self.b + self.b * self.len[i] / self.avg)
                scores[i] += self.idf[t] * n * (self.k1 + 1) / denom
        best = sorted(scores.items(), key=lambda x: -x[1])
        out, seen = [], Counter()
        for i, s in best:
            d = self.docs[i]
            if seen[d["source_id"]] >= 2:     # diversity: at most 2 chunks per source
                continue
            seen[d["source_id"]] += 1
            out.append((s, d))
            if len(out) >= k:
                break
        return out


@lru_cache(maxsize=1)
def index() -> BM25:
    docs = [json.loads(line) for line in CHUNKS.read_text(encoding="utf-8").splitlines() if line.strip()] if CHUNKS.exists() else []
    return BM25([d for d in docs if not is_glossary(d["text"])])


def search(query: str, k: int = 5) -> list[dict]:
    return [{"score": round(s, 3), "source_id": d["source_id"], "title": d["title"], "url": d["url"], "page": d["page"],
             "chunk_id": d["id"], "text": d["text"][:1600]} for s, d in index().search(query, k)]
