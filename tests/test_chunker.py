from leitor.chunker import normalize, split_text


def test_normalize_collapses_spaces_and_keeps_paragraphs():
    text = "  Primeira   linha\nquebrada.\n\n\n  Segundo\tparágrafo.  "
    assert normalize(text) == "Primeira linha quebrada.\n\nSegundo parágrafo."


def test_normalize_empty():
    assert normalize("   \n\t ") == ""


def test_split_empty_returns_nothing():
    assert split_text("") == []
    assert split_text("  \n ") == []


def test_short_text_is_single_chunk():
    assert split_text("Olá, mundo.") == ["Olá, mundo."]


def test_first_chunk_is_short_for_latency():
    sentences = [f"Esta é a frase número {i} do enunciado clínico." for i in range(30)]
    chunks = split_text(" ".join(sentences), first_max=120, max_len=500)
    assert len(chunks[0]) <= 120
    assert all(len(c) <= 500 for c in chunks)
    # Nothing lost or reordered.
    assert " ".join(chunks) == " ".join(sentences)


def test_paragraphs_start_new_chunks():
    text = "Primeiro parágrafo curto.\n\nSegundo parágrafo curto."
    assert split_text(text) == ["Primeiro parágrafo curto.", "Segundo parágrafo curto."]


def test_long_sentence_without_punctuation_is_split_on_spaces():
    words = ["palavra"] * 300  # ~2400 chars, no sentence punctuation
    text = " ".join(words)
    chunks = split_text(text, first_max=100, max_len=400)
    assert all(len(c) <= 400 for c in chunks)
    assert len(chunks[0]) <= 100
    assert " ".join(chunks) == text


def test_giant_word_is_hard_cut():
    text = "x" * 1000
    chunks = split_text(text, first_max=100, max_len=400)
    assert all(len(c) <= 400 for c in chunks)
    assert "".join(chunks) == text
