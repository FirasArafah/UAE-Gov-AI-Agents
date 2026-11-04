"""Deterministic checks on model output: repeated paragraphs and unsupported citations."""

import re

# "Article (18)", "Articles 4 and 6", "Art. 10", "المادة (18)", "المواد 4 و6", "Article (3.1.2.4)"
# In "Article 3(4)" the (4) is a paragraph of Article 3, not an article of its own.
ARTICLE_MENTION_RE = re.compile(
    r"(?:Articles?|Art\.|(?:ال|لل|بال|ل)?(?:مادة|مواد))\s*"
    r"(\(?\s*\d+(?:\.\d+)*\s*\)?(?:\s*(?:,|and|&|و)\s*\(?\s*\d+(?:\.\d+)*\s*\)?)*)",
    re.IGNORECASE,
)
ARTICLE_NUMBER_RE = re.compile(r"\d+(?:\.\d+)*")
BRACKET_CITATION_RE = re.compile(r"\[(\d+(?:\s*,\s*\d+)*)\]")
# Keeps "No. 45" and "Art. 10" whole: a sentence never ends right before a digit.
SENTENCE_SPLIT_RE = re.compile(r"(?<=[.؟!])\s+(?=\D)|\n+")
ARABIC_LETTER_RE = re.compile(r"[\u0600-\u06FF]")
# Cyrillic, Japanese kana and Chinese: the model sometimes slips into them mid-sentence.
WRONG_SCRIPT_RE = re.compile(r"[\u0400-\u04FF\u3040-\u30FF\u4E00-\u9FFF]")

MIN_REPEATED_PARAGRAPH_CHARS = 40


def _paragraphs(text: str) -> list[str]:
    return [line.strip() for line in text.split("\n") if line.strip()]


def has_repeated_paragraph(text: str) -> bool:
    """True when a substantial finished paragraph appears twice (the model is looping)."""
    seen: set[str] = set()
    for paragraph in _paragraphs(text.rpartition("\n")[0]):
        if len(paragraph) < MIN_REPEATED_PARAGRAPH_CHARS:
            continue
        if paragraph in seen:
            return True
        seen.add(paragraph)
    return False


def drop_repeated_paragraphs(text: str) -> str:
    """Remove later copies of substantial paragraphs, keeping the first of each."""
    seen: set[str] = set()
    kept: list[str] = []
    for line in text.split("\n"):
        paragraph = line.strip()
        if len(paragraph) >= MIN_REPEATED_PARAGRAPH_CHARS:
            if paragraph in seen:
                continue
            seen.add(paragraph)
        kept.append(line)
    return "\n".join(kept)


def article_numbers(text: str) -> set[str]:
    numbers: set[str] = set()
    for mention in ARTICLE_MENTION_RE.findall(text):
        numbers.update(ARTICLE_NUMBER_RE.findall(mention))
    return numbers


def _is_supported(number: str, source: str) -> bool:
    if "." in number:  # Section numbers such as 3.1.2.4 appear without the word "Article"
        return re.search(rf"(?<![\d.]){re.escape(number)}(?![\d.]*\d)", source) is not None
    return number in article_numbers(source)


def has_wrong_script(text: str) -> bool:
    return WRONG_SCRIPT_RE.search(text) is not None


def _source_texts(references: list[dict]) -> list[str]:
    return [f"{ref.get('section') or ''}\n{ref.get('content') or ''}" for ref in references]


def _best_excerpt(number: str, sentence: str, references: list[dict]) -> int | None:
    """Pick the excerpt holding an article, preferring the sentence's language."""
    holders = [
        idx
        for idx, source in enumerate(_source_texts(references), start=1)
        if _is_supported(number, source)
    ]
    language = "ar" if ARABIC_LETTER_RE.search(sentence) else "en"
    same_language = [idx for idx in holders if references[idx - 1].get("language") == language]
    return next(iter(same_language or holders), None)


def _repair_sentence(sentence: str, references: list[dict]) -> str:
    sources = _source_texts(references)
    cited = [int(n) for group in BRACKET_CITATION_RE.findall(sentence) for n in group.split(",")]
    cited = [n for n in cited if 1 <= n <= len(sources)]
    numbers = article_numbers(sentence)
    if not cited or not numbers:
        return sentence

    missing = [n for n in numbers if not any(_is_supported(n, sources[c - 1]) for c in cited)]
    fixes = {_best_excerpt(n, sentence, references) for n in missing} - {None}
    if not fixes:
        return sentence

    # An excerpt holding a different article is what the fix replaces; a non-legal one may stay.
    kept = {
        c
        for c in cited
        if not article_numbers(references[c - 1].get("section") or "")
        or any(_is_supported(n, sources[c - 1]) for n in numbers)
    }
    merged = ", ".join(str(n) for n in sorted(kept | fixes))
    start = BRACKET_CITATION_RE.search(sentence).start()
    head, tail = sentence[:start], sentence[start:]
    tail = re.sub(r"\s*" + BRACKET_CITATION_RE.pattern, "", tail)
    return f"{head.rstrip()} [{merged}]{tail}"


def repair_citations(content: str, references: list[dict]) -> str:
    """Point a citation at the excerpt that holds the article the sentence names."""
    parts = re.split(f"({SENTENCE_SPLIT_RE.pattern})", content)
    return "".join(
        part if idx % 2 else _repair_sentence(part, references) for idx, part in enumerate(parts)
    )


def merge_references(groups: list[list[dict]]) -> tuple[list[dict], list[dict[int, int]]]:
    """Combine several agents' excerpt lists into one, with each list's old-to-new numbers."""
    merged: list[dict] = []
    positions: dict[tuple, int] = {}
    mappings: list[dict[int, int]] = []
    for references in groups:
        mapping: dict[int, int] = {}
        for old, ref in enumerate(references, start=1):
            key = (ref.get("title"), ref.get("section"))
            if key not in positions:
                merged.append(ref)
                positions[key] = len(merged)
            mapping[old] = positions[key]
        mappings.append(mapping)
    return merged, mappings


def renumber_citations(text: str, mapping: dict[int, int]) -> str:
    """Rewrite [n] markers through a mapping, dropping any number it does not hold."""

    def replace(match: re.Match[str]) -> str:
        cited = (int(n) for n in match.group(1).split(","))
        numbers = sorted({mapping[n] for n in cited if n in mapping})
        return f"[{', '.join(str(n) for n in numbers)}]" if numbers else ""

    return BRACKET_CITATION_RE.sub(replace, text)


def find_citation_problems(
    content: str,
    references: list[dict],
    extra_sources: list[str] | None = None,
    check_excerpts: bool = True,
) -> list[str]:
    """Return one message per article or excerpt citation the sources do not support.

    ``check_excerpts`` also compares each sentence's article with the excerpt it cites. A
    synthesis has only the titles of its sources, so it cannot make that comparison.
    """
    sources = _source_texts(references)
    all_sources = "\n".join([*sources, *(extra_sources or [])])

    problems: list[str] = []
    unsupported = sorted(
        (n for n in article_numbers(content) if not _is_supported(n, all_sources)),
        key=lambda n: [int(part) for part in n.split(".")],
    )
    problems.extend(f"Article ({n}) is not in the retrieved sources" for n in unsupported)

    cited = {int(n) for group in BRACKET_CITATION_RE.findall(content) for n in group.split(",")}
    if sources:
        problems.extend(
            f"Excerpt [{n}] does not exist" for n in sorted(cited) if not 1 <= n <= len(sources)
        )

    mismatches: list[str] = []
    for sentence in SENTENCE_SPLIT_RE.split(content) if check_excerpts else []:
        excerpts = [
            int(n) for group in BRACKET_CITATION_RE.findall(sentence) for n in group.split(",")
        ]
        excerpts = [n for n in excerpts if 1 <= n <= len(sources)]
        if not excerpts:
            continue
        for number in sorted(article_numbers(sentence) - set(unsupported)):
            if not any(_is_supported(number, sources[n - 1]) for n in excerpts):
                labels = ", ".join(str(n) for n in excerpts)
                message = f"Article ({number}) is cited to excerpt [{labels}], which lacks it"
                if message not in mismatches:
                    mismatches.append(message)
    problems.extend(mismatches)
    return problems


def format_citation_warning(problems: list[str]) -> str:
    """Build the warning block shown with an answer that failed the checks."""
    if not problems:
        return ""
    lines = ["\n\n---\nتنبيه: فشل التحقق من هذا الجواب / Warning: this answer failed verification:"]
    lines.extend(f"- {problem}" for problem in problems)
    return "\n".join(lines)
