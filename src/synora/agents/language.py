"""Answer language: agents reply in the language the question was asked in."""

import re

ARABIC_LETTER_RE = re.compile(r"[؀-ۿ]")
LATIN_LETTER_RE = re.compile(r"[A-Za-z]")

NOT_COVERED = {
    "ar": "غير مذكور في المصادر الرسمية المتاحة",
    "en": "Not explicitly covered in the official sources provided",
}


def detect_language(text: str) -> str:
    """'ar' when the text is mostly Arabic, otherwise 'en'.

    Arabic questions often contain Latin abbreviations (PDPL, ICP, AI), so the decision
    counts letters rather than looking for any Latin word.
    """
    arabic = len(ARABIC_LETTER_RE.findall(text))
    latin = len(LATIN_LETTER_RE.findall(text))
    return "ar" if arabic > 0 and arabic >= latin * 0.5 else "en"


def output_contract(language: str) -> str:
    """Language, citation and structure rules appended to every agent's system prompt."""
    arabic = language == "ar"
    name = "Modern Standard Arabic" if arabic else "English"
    article = "المادة (18)" if arabic else "Article (18)"
    example = (
        "'... وفقاً للمادة (18) من المرسوم بقانون اتحادي رقم 45 لسنة 2021 [1].'"
        if arabic
        else "'... according to Article (18) of UAE Federal Decree-Law No. 45 of 2021 [1].'"
    )
    return (
        "\n\n[LANGUAGE RULE - HIGHEST PRIORITY]\n"
        f"The question was asked in {name}. Write both <thinking> and <response> entirely in "
        f"{name}. Do not add a translation or a second language version.\n"
        "- Never write Chinese, Cyrillic or any other foreign-script characters.\n"
        "- Keep abbreviations such as ICP, ICA and PDPL exactly as written; do not invent "
        "other meanings for them.\n"
        "- ICP and ICA both mean the UAE Federal Authority for Identity, Citizenship, Customs "
        "and Port Security, a federal governmental entity, not a private company.\n"
        f"- Name articles in the form {article}.\n\n"
        "[CITATION AND COMPLETENESS RULES]\n"
        "1. Use ONLY the RELEVANT POLICY EXCERPTS listed below (or the specialist agent "
        "outputs if you are the Coordinator). Do not use any external knowledge.\n"
        "2. Every sentence that states a legal rule ends with the bracketed number of the "
        "excerpt it comes from, e.g. [1] or [1, 2], together with the law title and article "
        "number. The number is the one printed before that excerpt in the list. "
        f"Example: {example}\n"
        "3. Never mention an article number that does not appear in the excerpts or specialist "
        "agent outputs. Article numbers named in the question or event text are unverified "
        "claims: do not repeat them unless an excerpt contains them.\n"
        "4. Only if no excerpt and no specialist agent output is relevant to the question at "
        f"all, write exactly '{NOT_COVERED[language]}' and stop. If they cover part of it, "
        "answer that part and say plainly which part the sources do not cover.\n"
        "5. When you cite an article, list ALL of its numbered paragraphs, conditions, exceptions "
        "(such as contract necessity, statutory obligations, explicit consent) and procedural "
        "rights (such as the right to human review) that appear in the excerpt. Never stop at "
        "a phrase like 'in the following cases:' without listing the cases.\n\n"
        "Structure your output EXACTLY as follows, replacing the descriptions with your text "
        "(do not wrap your text in brackets):\n"
        "<thinking>\n"
        f"Your reasoning in {name}: which excerpts apply, their articles, every paragraph and "
        "exception.\n"
        "</thinking>\n"
        "<response>\n"
        f"Your complete answer in {name}, with inline citations such as [1].\n"
        "</response>\n"
        "Both closing tags are mandatory."
    )
