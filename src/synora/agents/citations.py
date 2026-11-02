"""Deterministic checks on model output: repeated paragraphs and unsupported citations."""

import re

# "Article (18)", "Articles 4 and 6", "Art. 10", "المادة (18)", "المواد 4 و6", "Article (3.1.2.4)"
ARTICLE_MENTION_RE = re.compile(
    r"(?:Articles?|Art\.|المادة|المواد)\s*"
    r"((?:\(?\s*\d+(?:\.\d+)*\s*\)?(?:\s*(?:,|and|&|و)\s*(?=\(?\s*\d))?)+)",
    re.IGNORECASE,
)
ARTICLE_NUMBER_RE = re.compile(r"\d+(?:\.\d+)*")
BRACKET_CITATION_RE = re.compile(r"\[(\d+(?:\s*,\s*\d+)*)\]")
# Keeps "No. 45" and "Art. 10" whole: a sentence never ends right before a digit.
SENTENCE_SPLIT_RE = re.compile(r"(?<=[.؟!])\s+(?=\D)|\n+")

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


def _article_numbers(text: str) -> set[str]:
    numbers: set[str] = set()
    for mention in ARTICLE_MENTION_RE.findall(text):
        numbers.update(ARTICLE_NUMBER_RE.findall(mention))
    return numbers


def _is_supported(number: str, source: str) -> bool:
    if "." in number:  # Section numbers such as 3.1.2.4 appear without the word "Article"
        return re.search(rf"(?<![\d.]){re.escape(number)}(?![\d.]*\d)", source) is not None
    return number in _article_numbers(source)


def find_citation_problems(
    content: str,
    references: list[dict],
    extra_sources: list[str] | None = None,
) -> list[str]:
    """Return one message per article or excerpt citation the sources do not support."""
    sources = [f"{ref.get('section') or ''}\n{ref.get('content') or ''}" for ref in references]
    all_sources = "\n".join([*sources, *(extra_sources or [])])

    problems: list[str] = []
    unsupported = sorted(
        (n for n in _article_numbers(content) if not _is_supported(n, all_sources)),
        key=lambda n: [int(part) for part in n.split(".")],
    )
    problems.extend(f"Article ({n}) is not in the retrieved sources" for n in unsupported)

    cited = {int(n) for group in BRACKET_CITATION_RE.findall(content) for n in group.split(",")}
    if sources:
        problems.extend(
            f"Excerpt [{n}] does not exist" for n in sorted(cited) if not 1 <= n <= len(sources)
        )

    mismatches: list[str] = []
    for sentence in SENTENCE_SPLIT_RE.split(content):
        excerpts = [
            int(n) for group in BRACKET_CITATION_RE.findall(sentence) for n in group.split(",")
        ]
        excerpts = [n for n in excerpts if 1 <= n <= len(sources)]
        if not excerpts:
            continue
        for number in sorted(_article_numbers(sentence) - set(unsupported)):
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
