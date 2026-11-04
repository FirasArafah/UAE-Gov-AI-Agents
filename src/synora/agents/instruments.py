"""The legal instruments of the knowledge base that a question can name.

Similarity search cannot tell "Article 14 of the EU AI Act" from Article (14) of the PDPL, and a
question naming several instruments reaches only the closest one. Recognising the names lets
retrieval fetch the right article from the right law, and at least one passage of each source
the question asks about.
"""

import re
from dataclasses import dataclass

from synora.agents.citations import ARTICLE_MENTION_RE, ARTICLE_NUMBER_RE, SENTENCE_SPLIT_RE

# The words linking an article to the law named after it: "Article 18 of the PDPL".
NAME_FOLLOWS_RE = re.compile(r"\s*(?:of|in|under|from|من|في)\b", re.IGNORECASE)
MAX_NAME_DISTANCE = 40


@dataclass(frozen=True)
class Instrument:
    name: str
    pattern: re.Pattern[str]
    titles: tuple[str, ...]  # Text found in the stored title of each language edition


def _instrument(name: str, pattern: str, *titles: str) -> Instrument:
    return Instrument(name, re.compile(pattern, re.IGNORECASE), titles)


INSTRUMENTS: tuple[Instrument, ...] = (
    _instrument(
        "PDPL",
        r"\bPDPL\b|personal data protection law|\b45\s*(?:of|/)\s*2021\b|\(45\) of 2021"
        r"|قانون حماية البيانات|رقم\s*\(?45\)?",
        "No. 45 of 2021",
        "رقم 45 لسنة 2021",
    ),
    _instrument(
        "Decree-Law 29/2021",
        r"\b29\s*(?:of|/)\s*2021\b|\(29\) of 2021|entry and residence|رقم\s*\(?29\)?"
        r"|دخول وإقامة الأجانب",
        "No. 29 of 2021",
        "رقم 29 لسنة 2021",
    ),
    _instrument(
        "Cabinet Resolution 65/2022",
        r"cabinet resolution|\b65\s*(?:of|/)\s*2022\b|executive regulations?"
        r"|قرار مجلس الوزراء|اللائحة التنفيذية",
        "No. 65 of 2022",
    ),
    _instrument(
        "UAE AI Strategy",
        r"\bAI strategy\b|national strategy for (?:AI|artificial intelligence)|strategy 2031"
        r"|استراتيجية الإمارات للذكاء|الاستراتيجية الوطنية للذكاء",
        "Strategy for Artificial Intelligence 2031",
    ),
    _instrument(
        "UAE AI Charter",
        r"\bAI charter\b|\bUAE charter\b|charter for the development|ميثاق",
        "UAE Charter",
    ),
    _instrument(
        "UAE AI Ethics Guidelines",
        r"ethics guidelines|AI ethics: principles|إرشادات أخلاقيات",
        "UAE AI Ethics Guidelines",
    ),
    _instrument(
        "EU AI Act",
        r"\bAI Act\b|artificial intelligence act|2024/1689|الاتحاد الأوروبي|القانون الأوروبي",
        "2024/1689",
    ),
    _instrument("OECD", r"\bOECD\b|منظمة التعاون الاقتصادي", "OECD"),
    _instrument("UNESCO", r"\bUNESCO\b|اليونسكو", "UNESCO", "اليونسكو"),
    _instrument("ITU-T Y.3172", r"\bY\.?\s?3172\b", "Y.3172"),
    _instrument("ITU AI Readiness", r"\bAI read(?:y|iness)\b", "AI Ready"),
    _instrument(
        "UAE Cybersecurity Strategy",
        r"cyber\s?security strategy|الأمن السيبراني",
        "Cybersecurity Strategy",
    ),
    _instrument(
        "UAE Digital Government Strategy",
        r"digital government|الحكومة الرقمية",
        "Digital Government Strategy",
    ),
)


def named_instruments(text: str) -> list[Instrument]:
    """Instruments the text names, in the order it first mentions them."""
    found = [(m.start(), i) for i in INSTRUMENTS if (m := i.pattern.search(text))]
    return [instrument for _, instrument in sorted(found, key=lambda item: item[0])]


def _instrument_of(
    sentence: str, mention: re.Match[str], names: list[tuple[int, int, Instrument]]
) -> Instrument | None:
    """ "Article 86 of the EU AI Act" names its law after it, "PDPL Article (5)" before it."""
    after = sorted((n for n in names if n[0] >= mention.end()), key=lambda n: n[0])
    for start, _, instrument in after:
        between = sentence[mention.end() : start]
        if len(between) <= MAX_NAME_DISTANCE and NAME_FOLLOWS_RE.match(between):
            return instrument
    before = [n for n in names if n[1] <= mention.start()]
    if before:
        return max(before, key=lambda n: n[0])[2]
    return after[0][2] if after else None


def article_references(text: str) -> list[tuple[str, Instrument | None]]:
    """Article numbers in the text, each with the instrument its sentence ties it to."""
    references: list[tuple[str, Instrument | None]] = []
    for sentence in SENTENCE_SPLIT_RE.split(text):
        names = [(m.start(), m.end(), i) for i in INSTRUMENTS for m in i.pattern.finditer(sentence)]
        for mention in ARTICLE_MENTION_RE.finditer(sentence):
            instrument = _instrument_of(sentence, mention, names)
            for number in ARTICLE_NUMBER_RE.findall(mention.group(1)):
                if (number, instrument) not in references:
                    references.append((number, instrument))
    return references
