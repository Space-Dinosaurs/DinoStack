# src/nlp/scorer.py (relevant excerpt)
# Caller: bench/score_batch.py iterates 1000 documents, calls
# score_document(doc, reference_corpus) for each.

import math
from collections import Counter
import spacy

_NLP = spacy.load("en_core_web_sm")


def score_document(doc_text: str, reference_corpus: list[str]) -> float:
    vocab = _build_vocab(reference_corpus)
    doc_vec = _tf_idf_vector(doc_text, vocab)
    ref_vec = _tf_idf_vector(" ".join(reference_corpus), vocab)
    return _cosine(doc_vec, ref_vec)


def _build_vocab(reference_corpus: list[str]) -> dict[str, int]:
    # Tokenizes the entire reference corpus and assigns stable IDs.
    # Expensive: spaCy pipeline runs over every token in the corpus.
    tokens: Counter = Counter()
    for doc in reference_corpus:
        parsed = _NLP(doc)
        for tok in parsed:
            if not tok.is_stop and tok.is_alpha:
                tokens[tok.lemma_.lower()] += 1
    return {word: i for i, word in enumerate(tokens)}


def _tf_idf_vector(text: str, vocab: dict[str, int]) -> list[float]:
    parsed = _NLP(text)
    counts = Counter(t.lemma_.lower() for t in parsed if t.is_alpha)
    return [counts.get(w, 0) / max(sum(counts.values()), 1) for w in vocab]


def _cosine(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    return dot / (na * nb) if na and nb else 0.0
