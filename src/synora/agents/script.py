"""Keep model output in the scripts Mathuq answers in: Latin and Arabic.

Qwen models sometimes slip a Chinese word or punctuation mark into an English or Arabic
answer. The prompt forbids it, but a 7B model does not always obey, so every token the model
produces passes through this filter before anyone sees it: Chinese, Japanese, Korean and
Cyrillic characters are dropped and full-width punctuation becomes its ASCII form.
"""

import re

# CJK ideographs and radicals, kana, bopomofo, hangul, compatibility ideographs and Cyrillic.
FOREIGN_SCRIPT_RE = re.compile(
    "["
    "Ѐ-ӿ"
    "ᄀ-ᇿ"
    "⺀-⿟"
    "぀-ヿ"
    "㄀-ㇿ"
    "㐀-䶿"
    "一-鿿"
    "가-힯"
    "豈-﫿"
    "�"  # the replacement character left by a broken multi-byte token
    "]+"
)

FULL_WIDTH_PUNCTUATION = str.maketrans(
    {
        "　": " ",
        "、": ", ",
        "。": ". ",
        "，": ", ",
        "．": ". ",
        "：": ": ",
        "；": "; ",
        "！": "! ",
        "？": "? ",
        "（": " (",
        "）": ") ",
        "「": '"',
        "」": '"',
        "《": '"',
        "》": '"',
        "【": "[",
        "】": "]",
    }
)

SPACE_BEFORE_PUNCTUATION_RE = re.compile(r" +(?=[.,;:!?)\]،؛؟])")
REPEATED_SPACES_RE = re.compile(r" {2,}")
CLOSING_PUNCTUATION = set(".,;:!?)]،؛؟")


def has_foreign_script(text: str) -> bool:
    return FOREIGN_SCRIPT_RE.search(text) is not None


class ScriptFilter:
    """Cleans a token stream and repairs the spacing a dropped word leaves behind.

    Trailing spaces are held back by one token, so "shows 偏见 against" becomes "shows against"
    and "the 模型." becomes "the." even when the foreign word arrives as a token of its own.
    """

    def __init__(self) -> None:
        self.removed = 0  # characters dropped so far
        self._held = ""  # trailing spaces not yet emitted
        self._gap = False  # something was dropped since the last emitted text
        self._last = ""  # last character emitted

    def feed(self, token: str) -> str:
        text = token.translate(FULL_WIDTH_PUNCTUATION)
        cleaned = FOREIGN_SCRIPT_RE.sub("", text)
        if cleaned != token:
            self.removed += len(text) - len(cleaned)
            self._gap = True
            cleaned = REPEATED_SPACES_RE.sub(" ", cleaned)
            cleaned = SPACE_BEFORE_PUNCTUATION_RE.sub("", cleaned)
        if not cleaned:
            return ""
        if self._gap:
            if self._held and (cleaned[0] == " " or cleaned[0] in CLOSING_PUNCTUATION):
                self._held = ""
            if self._last in ("", "\n") and not self._held:
                cleaned = cleaned.lstrip(" ")
        body = cleaned.rstrip(" ")
        out = self._held + body if body else ""
        self._held = cleaned[len(body):] if body else self._held + cleaned
        if body:
            self._gap = False
            self._last = body[-1]
        return out

    def flush(self) -> str:
        held, self._held = self._held, ""
        return held


def clean_text(text: str) -> str:
    """The whole-text form of the filter, for answers that are not streamed."""
    script = ScriptFilter()
    return script.feed(text) + script.flush()
