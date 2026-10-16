"""Download, extract and chunk the Flight Controller corpus (corpus/sources.yaml).

Run: python -m pipeline.build_corpus
Writes corpus/chunks/chunks.jsonl: {id, source_id, title, url, page, text}
and corpus/chunks/report.json listing every source that failed.
"""
from __future__ import annotations

import html
import json
import re
import sys
import urllib.request
from pathlib import Path

import yaml

from pipeline.geo import RAW, ROOT

CHUNK_CHARS = 2000      # ~500 tokens
OVERLAP_CHARS = 300
MAX_PAGES = 250


def fetch(url: str, dest: Path) -> Path:
    if dest.exists() and dest.stat().st_size > 0:
        return dest
    req = urllib.request.Request(url, headers={"User-Agent": "marswalk-corpus/0.1 (NASA Space Apps)"})
    with urllib.request.urlopen(req, timeout=90) as r:
        data = r.read()
    dest.write_bytes(data)
    return dest


def pdf_pages(path: Path) -> list[tuple[int, str]]:
    from pypdf import PdfReader

    reader = PdfReader(str(path))
    out = []
    for i, page in enumerate(reader.pages[:MAX_PAGES]):
        try:
            out.append((i + 1, page.extract_text() or ""))
        except Exception:
            continue
    return out


def html_text(path: Path) -> list[tuple[int, str]]:
    raw = path.read_text(encoding="utf-8", errors="ignore")
    raw = re.sub(r"(?is)<(script|style).*?</\1>", " ", raw)
    return [(1, html.unescape(re.sub(r"<[^>]+>", " ", raw)))]


def chunk(text: str) -> list[str]:
    text = re.sub(r"\s+", " ", text).strip()
    out, i = [], 0
    while i < len(text):
        piece = text[i:i + CHUNK_CHARS]
        if len(piece) > 200:
            out.append(piece)
        i += CHUNK_CHARS - OVERLAP_CHARS
    return out


def main() -> int:
    sources = yaml.safe_load((ROOT / "corpus" / "sources.yaml").read_text(encoding="utf-8"))["sources"]
    raw = RAW / "corpus"
    raw.mkdir(parents=True, exist_ok=True)
    out_dir = ROOT / "corpus" / "chunks"
    out_dir.mkdir(parents=True, exist_ok=True)
    chunks, failed, ok = [], [], []
    for s in sources:
        try:
            path = fetch(s["url"], raw / s["id"])
            head = path.read_bytes()[:5]
            pages = pdf_pages(path) if head.startswith(b"%PDF") else html_text(path)
            n0 = len(chunks)
            for page, text in pages:
                for k, c in enumerate(chunk(text)):
                    chunks.append({"id": f"{s['id']}:{page}:{k}", "source_id": s["id"], "title": s["title"], "url": s["url"],
                                   "page": page, "topic": s.get("topic", ""), "text": c})
            if len(chunks) == n0:
                raise ValueError("no extractable text")
            ok.append({"id": s["id"], "chunks": len(chunks) - n0})
            print(f"  ok   {s['id']}: {len(chunks) - n0} chunks")
        except Exception as e:
            failed.append({"id": s["id"], "url": s["url"], "error": str(e)[:200]})
            print(f"  FAIL {s['id']}: {e}")
    with open(out_dir / "chunks.jsonl", "w", encoding="utf-8") as f:
        for c in chunks:
            f.write(json.dumps(c, ensure_ascii=False) + "\n")
    (out_dir / "report.json").write_text(json.dumps({"ok": ok, "failed": failed, "chunks": len(chunks)}, indent=1))
    print(f"{len(chunks)} chunks from {len(ok)} sources, {len(failed)} failed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
