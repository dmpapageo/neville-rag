"""Offline tests: chunker behaviour and the source-offset invariant that
citation mapping depends on. No API keys, no network — the Voyage tokenizer is
swapped for a word count so these run anywhere.

Run from the repo root:  PYTHONPATH=backend uv run --with pytest pytest tests/ -q
"""

import json
from pathlib import Path

import pytest

from app.ingestion import chunk as chunking

ROOT = Path(__file__).resolve().parent.parent
RAW = (ROOT / "data" / "feeling_is_the_secret.txt").read_text(encoding="utf-8")
CHUNKS = [json.loads(l) for l in (ROOT / "data" / "chunks.jsonl").read_text(encoding="utf-8").splitlines() if l.strip()]


@pytest.fixture(autouse=True)
def word_tokenizer(monkeypatch):
    monkeypatch.setattr(chunking, "_count_tokens", lambda s: len(s.split()))


SAMPLE = (
    "Neville Goddard – 1944\n\nFeeling Is The Secret\n\nForeword\n\n"
    "Alpha one two three four five.\n\n"
    "Chapter 1 – Law and Its Operation\n\n"
    "Beta one two three four five six seven.\n\nGamma one two three four five six.\n\n"
    "Delta one two three four five six seven eight.\n\n"
    "Chapter Two\n\nFeeling Is The Secret – Sleep\n\n"
    "Epsilon one two three four five six seven eight nine ten.\n\nZeta one two three.\n"
)


def _chunks(**kw):
    return chunking.chunk_text(SAMPLE, **kw)


# --- sections -----------------------------------------------------------------------

def test_headings_become_section_labels_and_are_not_chunk_text():
    sections = {c.section for c in _chunks(max_tokens=100)}
    assert sections == {"Foreword", "Chapter 1 – Law and Its Operation", "Chapter 2 – Sleep"}
    for c in _chunks(max_tokens=100):
        assert "Chapter" not in c.text
        assert "Feeling Is The Secret" not in c.text
        assert "Neville Goddard – 1944" not in c.text


def test_chunks_never_cross_a_section_boundary():
    for c in _chunks(max_tokens=100):
        assert not ("Delta" in c.text and "Epsilon" in c.text)
        assert not ("Alpha" in c.text and "Beta" in c.text)


# --- token cap and overlap ---------------------------------------------------------------

def test_token_cap_is_respected():
    # min_tokens=1 so the tail-merge (which may fold a small last chunk past the cap) is off
    for c in _chunks(max_tokens=12, min_tokens=1):
        assert c.n_tokens <= 12


def test_oversized_paragraph_is_split_on_sentences_with_offsets_kept():
    long_para = "One two three four five six. Seven eight nine ten eleven twelve. Thirteen fourteen.\n"
    text = "Foreword\n\n" + long_para
    cs = chunking.chunk_text(text, max_tokens=8, min_tokens=1)
    assert len(cs) >= 2
    for c in cs:
        assert c.n_tokens <= 8
        assert text[c.char_start:c.char_end] == c.text


def test_adjacent_chunks_in_a_section_overlap():
    # Chapter 1 paragraphs are 8, 7, 9 words; a 16-token window holds two at a time,
    # so consecutive windows must repeat the trailing paragraph.
    cs = [c for c in _chunks(max_tokens=16, overlap_ratio=0.5, min_tokens=1)
          if c.section == "Chapter 1 – Law and Its Operation"]
    assert len(cs) == 2
    assert "Gamma" in cs[0].text and "Gamma" in cs[1].text
    assert cs[1].char_start < cs[0].char_end


def test_undersized_tail_is_merged_into_previous_chunk():
    cs = [c for c in _chunks(max_tokens=14, overlap_ratio=0.0, min_tokens=6) if c.section == "Chapter 2 – Sleep"]
    # Epsilon (10 tokens) then Zeta (3 tokens): Zeta alone is under min_tokens, so it is folded in.
    assert len(cs) == 1
    assert "Zeta" in cs[0].text


def test_indices_are_sequential():
    assert [c.index for c in _chunks(max_tokens=12)] == list(range(len(_chunks(max_tokens=12))))


# --- the offset invariant citation mapping relies on --------------------------------

def test_char_offsets_point_at_the_chunk_text_in_the_source():
    for c in _chunks(max_tokens=12):
        head = c.text.split("\n\n")[0].split(" ")[0]
        assert SAMPLE[c.char_start:].startswith(head)
        assert SAMPLE[:c.char_end].endswith(c.text.split()[-1])


def test_committed_chunks_still_match_the_committed_source():
    """data/chunks.jsonl is what got embedded; its offsets must index into
    data/feeling_is_the_secret.txt, or citation highlighting is wrong."""
    assert len(CHUNKS) == 30
    for c in CHUNKS:
        first_unit = c["text"].split("\n\n")[0]
        assert RAW[c["char_start"]:c["char_start"] + len(first_unit)] == first_unit, c["index"]
        last_word = c["text"].split()[-1]
        assert RAW[:c["char_end"]].endswith(last_word), c["index"]
        assert c["char_start"] < c["char_end"]
        assert c["n_tokens"] <= chunking.MAX_TOKENS


def test_committed_chunks_are_ordered_and_section_contiguous():
    starts = [c["char_start"] for c in CHUNKS]
    assert starts == sorted(starts)
    seen, last = [], None
    for c in CHUNKS:
        if c["section"] != last:
            assert c["section"] not in seen, "section appears twice non-contiguously"
            seen.append(c["section"])
            last = c["section"]
    assert seen == ["Foreword", "Chapter 1 – Law and Its Operation", "Chapter 2 – Sleep",
                    "Chapter 3 – Prayer", "Chapter 4 – Spirit – Feeling"]


# --- eval set sanity: every gold phrase is real ----------------------------------------

def test_every_gold_phrase_exists_in_source_and_in_a_chunk():
    cases = json.loads((ROOT / "eval" / "questions.json").read_text(encoding="utf-8"))
    assert sum(c["expect"] == "answer" for c in cases) >= 15
    assert sum(c["expect"] == "refuse" for c in cases) >= 3
    for case in cases:
        for phrase in case.get("gold_phrases", []):
            i = RAW.find(phrase)
            assert i >= 0, f"{case['id']}: {phrase!r}"
            assert any(c["char_start"] <= i and i + len(phrase) <= c["char_end"] for c in CHUNKS), case["id"]
