"""Section- and paragraph-aware chunking for the RAG pipeline.

Turns the cleaned book text (data/feeling_is_the_secret.txt) into overlapping,
token-capped chunks with metadata (chunk index + section/chapter) so retrieval
can later cite *where* an answer came from.

Boundaries: the extraction step already gave us clean paragraphs (blank-line
separated) and section headings. We never split mid-paragraph unless a single
paragraph exceeds the token cap, in which case we fall back to sentence splits.

Token counting: uses Voyage's own tokenizer (the model that will embed these
chunks), run locally — no API call. Sizing by the embedder's tokenizer is what
makes the cap meaningful.
"""

from __future__ import annotations

import json
import os
import re
from dataclasses import asdict, dataclass
from pathlib import Path

# ---- configurable knobs -----------------------------------------------------
MAX_TOKENS = 350        # hard cap on tokens per chunk
OVERLAP_RATIO = 0.15    # fraction of MAX_TOKENS repeated between adjacent chunks
MIN_TOKENS = 80         # a trailing chunk smaller than this is merged into its predecessor
TOKENIZER_MODEL = "voyage-3.5-lite"

SRC = Path("data/feeling_is_the_secret.txt")
OUT = Path("data/chunks.jsonl")
SOURCE_LABEL = "Feeling Is the Secret (1944), Neville Goddard"


# ---- token counting ---------------------------------------------------------
_tokenizer = None


def _count_tokens(text: str) -> int:
    """Count tokens with Voyage's tokenizer. Local only — does not call the API."""
    global _tokenizer
    if _tokenizer is None:
        import voyageai

        # tokenize() runs locally; a real key is only needed for embedding.
        client = voyageai.Client(api_key=os.getenv("VOYAGE_API_KEY", "local-tokenizer-only"))
        _tokenizer = lambda s: len(client.tokenize([s], model=TOKENIZER_MODEL)[0].ids)
    return _tokenizer(text)


# ---- data model -------------------------------------------------------------
@dataclass
class Chunk:
    index: int
    section: str
    text: str
    char_start: int      # offset into data/feeling_is_the_secret.txt
    char_end: int
    n_tokens: int
    n_chars: int
    source: str = SOURCE_LABEL


@dataclass
class _Para:
    text: str
    start: int           # char offset in source file
    end: int


@dataclass
class _Unit:
    text: str
    start: int
    end: int
    para_id: int         # which paragraph this unit came from (for join spacing)
    tokens: int


# ---- parsing: paragraphs + sections ----------------------------------------
_WORD_NUM = {"one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6}


def _split_paragraphs(raw: str) -> list[_Para]:
    paras, pos = [], 0
    for part in raw.split("\n\n"):
        body = part.rstrip("\n")
        if body.strip():
            paras.append(_Para(body, pos, pos + len(body)))
        pos += len(part) + 2  # account for the "\n\n" separator
    return paras


def _assign_sections(paras: list[_Para]) -> list[tuple[_Para, str]]:
    """Attach a section label to each *body* paragraph; drop heading paragraphs.

    Headings seen in this book:
      - "Foreword"
      - "Chapter 1 – Law and Its Operation"      (title inline)
      - "Chapter Two" + "Feeling Is The Secret – Sleep"   (title on next line)
    The two title-block lines ("Neville Goddard – 1944", "Feeling Is The Secret")
    are front matter and are dropped.
    """
    out: list[tuple[_Para, str]] = []
    section = "Front matter"
    i = 0
    while i < len(paras):
        p = paras[i]
        t = p.text.strip()

        if t in {"Neville Goddard – 1944", "Feeling Is The Secret"}:
            i += 1
            continue
        if t == "Foreword":
            section = "Foreword"
            i += 1
            continue

        m = re.match(r"^Chapter\s+(\w+)\b(.*)$", t)
        if m:
            num = m.group(1)
            n = int(num) if num.isdigit() else _WORD_NUM.get(num.lower())
            rest = m.group(2).strip()
            title = ""
            if rest:  # "Chapter 1 – Law and Its Operation"
                title = re.sub(r"^[–—:-]\s*", "", rest)
            elif i + 1 < len(paras) and paras[i + 1].text.startswith("Feeling Is The Secret"):
                sub = paras[i + 1].text
                title = re.sub(r"^Feeling Is The Secret\s*[–—:-]\s*", "", sub).strip()
                i += 1  # consume the subtitle line too
            section = f"Chapter {n} – {title}" if title else f"Chapter {n}"
            i += 1
            continue

        out.append((p, section))
        i += 1
    return out


# ---- units: paragraphs, sub-split only if a paragraph exceeds the cap -------
_SENT = re.compile(r'(?<=[.!?”"])\s+')


def _to_units(body: list[tuple[_Para, str]], max_tokens: int) -> list[tuple[_Unit, str]]:
    units: list[tuple[_Unit, str]] = []
    for pid, (para, section) in enumerate(body):
        if _count_tokens(para.text) <= max_tokens:
            units.append((_Unit(para.text, para.start, para.end, pid, _count_tokens(para.text)), section))
            continue
        # oversized paragraph -> split on sentence boundaries, keep source offsets
        for m in re.finditer(r".+?(?:" + _SENT.pattern + r"|$)", para.text, re.S):
            s = m.group().strip()
            if not s:
                continue
            a = para.start + m.start()
            units.append((_Unit(s, a, a + len(s), pid, _count_tokens(s)), section))
    return units


# ---- windowing: pack units to the cap, with token-based overlap ------------
def _pack_section(units: list[_Unit], max_tokens: int, overlap_tokens: int, min_tokens: int) -> list[tuple[int, int]]:
    """Return [start, end) unit spans for one section. Overlap is applied only
    when a window is cut short by the token cap (i.e. more units remain in the
    section), never at the section's end — so no duplicate tail chunks."""
    spans: list[list[int]] = []
    i, n = 0, len(units)
    while i < n:
        j, toks = i, 0
        while j < n:
            if toks > 0 and toks + units[j].tokens > max_tokens:
                break
            toks += units[j].tokens
            j += 1
        spans.append([i, j])
        if j >= n:
            break
        # repeat ~overlap_tokens of trailing units into the next window
        back, acc, k = 0, 0, j - 1
        while k > i and acc < overlap_tokens:
            acc += units[k].tokens
            k -= 1
            back += 1
        i = max(i + 1, j - back)

    # fold an undersized trailing remainder back into the previous chunk
    if len(spans) >= 2:
        tail = units[spans[-1][0]:spans[-1][1]]
        if sum(u.tokens for u in tail) < min_tokens:
            spans[-2][1] = spans[-1][1]
            spans.pop()
    return [(a, b) for a, b in spans]


def chunk_text(
    raw: str,
    *,
    max_tokens: int = MAX_TOKENS,
    overlap_ratio: float = OVERLAP_RATIO,
    min_tokens: int = MIN_TOKENS,
) -> list[Chunk]:
    body = _assign_sections(_split_paragraphs(raw))
    units = _to_units(body, max_tokens)
    overlap_tokens = round(overlap_ratio * max_tokens)

    chunks: list[Chunk] = []
    k = 0
    while k < len(units):
        section = units[k][1]
        group = []
        while k < len(units) and units[k][1] == section:
            group.append(units[k][0])
            k += 1
        for a, b in _pack_section(group, max_tokens, overlap_tokens, min_tokens):
            window = group[a:b]
            text = _join(window)
            chunks.append(Chunk(
                index=len(chunks),
                section=section,
                text=text,
                char_start=window[0].start,
                char_end=window[-1].end,
                n_tokens=_count_tokens(text),
                n_chars=len(text),
            ))
    return chunks


def _join(units: list[_Unit]) -> str:
    """Join units: space within the same source paragraph, blank line across."""
    out = units[0].text
    for prev, u in zip(units, units[1:]):
        out += (" " if u.para_id == prev.para_id else "\n\n") + u.text
    return out


def main() -> None:
    raw = SRC.read_text(encoding="utf-8")
    chunks = chunk_text(raw)
    with OUT.open("w", encoding="utf-8") as f:
        for c in chunks:
            f.write(json.dumps(asdict(c), ensure_ascii=False) + "\n")

    toks = [c.n_tokens for c in chunks]
    print(f"chunks: {len(chunks)} -> {OUT}")
    print(f"tokens/chunk: min={min(toks)} avg={sum(toks)//len(toks)} max={max(toks)} (cap={MAX_TOKENS})")
    by_sec: dict[str, int] = {}
    for c in chunks:
        by_sec[c.section] = by_sec.get(c.section, 0) + 1
    print("chunks per section:", by_sec)


if __name__ == "__main__":
    main()
