"""Tell conversational messages (greetings, thanks, 'who are you') from real questions.

A greeting sent to the team used to run four agents, each retrieving eight policy excerpts and
writing a legal assessment, which took over a minute of GPU time to answer 'Hello'. Messages
recognised here get a short direct reply instead. The check is rule-based so that classifying a
message costs nothing, and it is conservative: anything that mentions a legal or policy subject
is treated as a question.
"""

import re

# Arabic punctuation (، ؛ ؟) lies inside the Arabic block, so it is removed separately.
PUNCTUATION_RE = re.compile(r"[^\w\s؀-ۿ]|[،؛؟]")
TATWEEL_AND_MARKS_RE = re.compile(r"[ـً-ْ]")

# Whole messages, after normalisation, that are only conversation.
CONVERSATIONAL_PATTERNS = [
    # English
    r"(hi|hello|hey|hiya|greetings|good (morning|afternoon|evening|day))( there| team| mathuq)?",
    r"(thanks|thank you|thank you very much|thanks a lot|many thanks|cheers)( team| mathuq)?",
    r"(ok|okay|great|nice|cool|perfect|got it|understood|sounds good)",
    r"(bye|goodbye|see you|good night)",
    r"how are you( doing)?( today)?",
    r"who are you|what are you|what is mathuq|who made you",
    r"what can you do|how can you help( me)?|what do you do|help",
    # Arabic
    r"(مرحبا|مرحباً|اهلا|أهلا|أهلاً|اهلا وسهلا|أهلا وسهلا|هلا|السلام عليكم|سلام)( بك| بكم)?",
    r"(صباح الخير|مساء الخير|صباح النور|مساء النور)",
    r"(شكرا|شكراً|شكرا لك|شكرا جزيلا|شكراً جزيلاً|مشكور|يعطيك العافيه|يعطيك العافية)",
    r"(تمام|حسنا|حسناً|ممتاز|رائع|فهمت)",
    r"(مع السلامه|مع السلامة|الى اللقاء|إلى اللقاء)",
    r"(كيف حالك|كيفك|شلونك|كيف الحال)",
    r"(من انت|من أنت|ما هو موثوق|ماذا تفعل|ماذا تستطيع ان تفعل|ماذا تستطيع أن تفعل|كيف تساعدني)",
]
CONVERSATIONAL_RE = re.compile(
    r"^(" + "|".join(f"(?:{p})" for p in CONVERSATIONAL_PATTERNS) + r")( (?:" +
    "|".join(f"(?:{p})" for p in CONVERSATIONAL_PATTERNS) + r"))*$"
)

# Any of these makes a short message a real question (e.g. "hi, what does the PDPL say?").
SUBJECT_RE = re.compile(
    r"\b(law|laws|article|articles|decree|regulation|pdpl|icp|ica|policy|policies|ai|bias|data|"
    r"privacy|visa|residency|right|rights|gap|gaps|standard|oecd|unesco|itu|eu|charter|"
    r"strategy|audit|scenario|consent|authority|government)\b"
    r"|قانون|مادة|المادة|مرسوم|لائحة|بيانات|خصوصية|سياسة|الذكاء|تأشيرة|إقامة|حق|حقوق|فجوة|"
    r"معيار|ميثاق|استراتيجية|تدقيق|موافقة|هيئة|حكومي",
    re.IGNORECASE,
)


def normalise(text: str) -> str:
    text = TATWEEL_AND_MARKS_RE.sub("", text.strip().lower())
    text = PUNCTUATION_RE.sub(" ", text)
    return re.sub(r"\s+", " ", text).strip()


def is_conversational(text: str) -> bool:
    """True for greetings, thanks and questions about the assistant itself."""
    norm = normalise(text)
    if not norm or len(norm.split()) > 8 or SUBJECT_RE.search(norm):
        return False
    return CONVERSATIONAL_RE.fullmatch(norm) is not None


CONVERSATION_PROMPT = {
    "en": (
        "You are Mathuq, an assistant for AI governance in UAE government services. A team of "
        "agents (the ICP Representative, an AI Auditor, a Privacy Consultant and a Coordinator) "
        "answers questions from UAE law and international references such as the PDPL, the UAE "
        "AI Charter, the EU AI Act, OECD, UNESCO and ITU, and runs incident simulations.\n"
        "The user sent a conversational message, not a policy question. Reply in English, "
        "warmly and in one to three short sentences. If it fits, say briefly what you can help "
        "with. Do not cite laws, do not analyse anything, and do not use tags or headings."
    ),
    "ar": (
        "أنت «موثوق»، مساعد لحوكمة الذكاء الاصطناعي في الخدمات الحكومية في دولة الإمارات. يجيب "
        "فريق من الوكلاء (ممثل الهيئة الاتحادية للهوية والجنسية، ومدقق الذكاء الاصطناعي، "
        "ومستشار الخصوصية، والمنسّق) عن الأسئلة استناداً إلى التشريعات الإماراتية والمراجع "
        "الدولية، ويجري محاكاة للحوادث.\n"
        "أرسل المستخدم رسالة ودّية وليست سؤالاً عن السياسات. ردّ بالعربية الفصحى بلطف وفي جملة "
        "إلى ثلاث جمل قصيرة، واذكر باختصار ما يمكنك المساعدة فيه إن كان ذلك مناسباً. لا تستشهد "
        "بالقوانين ولا تحلّل ولا تستخدم وسوماً أو عناوين."
    ),
}
