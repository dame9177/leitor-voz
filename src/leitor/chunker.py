"""Split text into chunks small enough for low-latency TTS requests.

The first chunk is kept short so audio starts quickly; later chunks are
synthesized while earlier ones play, so they can be longer.
"""

import re

_SENTENCE_END = re.compile(r"(?<=[.!?…;:])\s+")
_PARAGRAPH_BREAK = re.compile(r"\n\s*\n")


def normalize(text: str) -> str:
    """Collapse whitespace inside paragraphs, keep blank-line paragraph breaks."""
    paragraphs = _PARAGRAPH_BREAK.split(text)
    cleaned = (" ".join(p.split()) for p in paragraphs)
    return "\n\n".join(p for p in cleaned if p)


def _split_long(piece: str, limit: int) -> list[str]:
    """Split a piece with no sentence boundary: on spaces, else hard cut."""
    parts = []
    while len(piece) > limit:
        cut = piece.rfind(" ", 0, limit + 1)
        if cut <= 0:
            parts.append(piece[:limit])
            piece = piece[limit:]
        else:
            parts.append(piece[:cut])
            piece = piece[cut + 1 :]
    if piece:
        parts.append(piece)
    return parts


def split_text(text: str, first_max: int = 220, max_len: int = 900) -> list[str]:
    chunks: list[str] = []
    for paragraph in normalize(text).split("\n\n"):
        if not paragraph:
            continue
        current = ""
        for sentence in _SENTENCE_END.split(paragraph):
            limit = first_max if not chunks else max_len
            candidate = f"{current} {sentence}" if current else sentence
            if len(candidate) <= limit:
                current = candidate
                continue
            if current:
                chunks.append(current)
                current = ""
                limit = max_len
            if len(sentence) <= limit:
                current = sentence
                continue
            pieces = _split_long(sentence, limit)
            # After the first piece the limit relaxes to max_len.
            if len(pieces) > 1 and limit < max_len:
                rest = sentence[len(pieces[0]) :].removeprefix(" ")
                pieces = [pieces[0], *_split_long(rest, max_len)]
            chunks.extend(pieces[:-1])
            current = pieces[-1]
        if current:
            chunks.append(current)
    return chunks
