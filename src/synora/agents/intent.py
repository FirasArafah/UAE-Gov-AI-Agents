"""Decide how much work a chat message needs before the agents see it.

A greeting sent to the team used to run four agents, each retrieving eight policy excerpts and
writing a legal assessment, which took over a minute of GPU time to answer 'Hello'. Messages are
now routed in three steps, cheapest first:

1. rules (no model call): greetings, thanks and introductions get a short reply, and
   questions about the assistant itself ('who are you', 'who made you') get a fixed answer
   from the profile file;
2. subject words (no model call): a message about law, privacy, AI, visas and so on is a
   question for the agents;
3. anything else gets one tiny model call (a few output tokens) that tells questions within the
   agents' remit from off-topic ones, which get a short direct reply instead of the team.
"""

import json
import re
from enum import StrEnum
from pathlib import Path

import structlog

from synora.agents.guard import looks_like_injection

logger = structlog.get_logger(__name__)


class MessageKind(StrEnum):
    QUESTION = "question"  # for the agents
    CONVERSATION = "conversation"  # greetings, thanks, acknowledgements
    IDENTITY = "identity"  # who are you, who made you
    OFF_TOPIC = "off_topic"  # outside the agents' remit
    INJECTION = "injection"  # tries to override or extract the instructions


# Arabic punctuation (، ؛ ؟) lies inside the Arabic block, so it is removed separately.
PUNCTUATION_RE = re.compile(r"[^\w\s؀-ۿ]|[،؛؟]")
TATWEEL_AND_MARKS_RE = re.compile(r"[ـً-ْ]")

NAME = r"(mawthuq|mawthuq|mothooq|موثوق)"

IDENTITY_PATTERNS = [
    rf"(who|what) are you( exactly)?|what is {NAME}|who is {NAME}|tell me about (yourself|{NAME})",
    r"who (made|built|created|developed|designed|trained|owns) you",
    r"(who|which team|who is the team) (is |are )?behind (you|this)( project| app| system)?"
    r"|introduce yourself|your name|what is your name",
    rf"(من|ما) (انت|أنت)|ما هو {NAME}|من هو {NAME}|عرف عن نفسك|عرّف عن نفسك|ما اسمك",
    rf"من (صنعك|طورك|أنشأك|انشأك|برمجك|بناك|صممك|يملكك)|من (صنع|طور|أنشأ|برمج|صمم) {NAME}",
    r"(who|which) (is|are) (your|the) (team|developers?|creators?|makers?|authors?)( of this)?",
    r"who (developed|built|made|created) (this|this (app|system|project|assistant))",
    r"(من|ما) (هو|هم)? ?(فريقك|فريق التطوير|المطور|المطورون|المطورين|صانعوك)",
]
CONVERSATION_PATTERNS = [
    # English
    r"(hi|hello|hey|hiya|greetings|good (morning|afternoon|evening|day))( there| team| "
    + NAME + r")?",
    r"(thanks|thank you|thank you very much|thanks a lot|many thanks|cheers)( team| "
    + NAME + r")?",
    r"(ok|okay|great|nice|cool|perfect|got it|understood|sounds good)",
    r"(bye|goodbye|see you|good night)",
    r"how are you( doing)?( today)?",
    r"what can you do|how can you help( me)?|what do you do|help",
    # Arabic
    r"(مرحبا|مرحباً|اهلا|أهلا|أهلاً|اهلا وسهلا|أهلا وسهلا|هلا|السلام عليكم|سلام)( بك| بكم)?",
    r"(صباح الخير|مساء الخير|صباح النور|مساء النور)",
    r"(شكرا|شكراً|شكرا لك|شكرا جزيلا|شكراً جزيلاً|مشكور|يعطيك العافيه|يعطيك العافية)",
    r"(تمام|حسنا|حسناً|ممتاز|رائع|فهمت)",
    r"(مع السلامه|مع السلامة|الى اللقاء|إلى اللقاء)",
    r"(كيف حالك|كيفك|شلونك|كيف الحال)",
    r"(ماذا تفعل|ماذا تستطيع ان تفعل|ماذا تستطيع أن تفعل|كيف تساعدني|كيف يمكنك مساعدتي)",
]


def _sequence_of(patterns: list[str]) -> re.Pattern:
    """One or more of the patterns, e.g. 'hello thanks' or 'hi who are you'."""
    one = "|".join(f"(?:{p})" for p in patterns)
    return re.compile(rf"^(?:{one})(?: (?:{one}))*$")


IDENTITY_RE = re.compile("|".join(f"(?:{p})" for p in IDENTITY_PATTERNS))
LIGHT_RE = _sequence_of(IDENTITY_PATTERNS + CONVERSATION_PATTERNS)

# Any of these makes a message a question for the agents (e.g. "hi, what does the PDPL say?").
SUBJECT_RE = re.compile(
    r"\b(law|laws|legal|article|articles|decree|regulation|regulations|pdpl|icp|ica|policy|"
    r"policies|ai|bias|biased|discrimination|data|privacy|visa|visas|residency|immigration|"
    r"right|rights|gap|gaps|standard|standards|oecd|unesco|itu|eu|charter|strategy|audit|"
    r"auditor|scenario|simulation|consent|authority|government|cyber|cybersecurity|algorithm|"
    r"model|ethics|governance|compliance)\b"
    r"|قانون|مادة|المادة|مرسوم|لائحة|بيانات|خصوصية|سياسة|الذكاء|تأشيرة|إقامة|حق|حقوق|فجوة|"
    r"معيار|ميثاق|استراتيجية|تدقيق|موافقة|هيئة|حكومي|تمييز|تحيز|خوارزمية|أمن سيبراني|حوكمة",
    re.IGNORECASE,
)
MAX_LIGHT_WORDS = 10

# "My name is Firas and I work at ICP" mentions ICP but asks nothing: it is an introduction.
INTRODUCTION_RE = re.compile(
    r"^(?:(?:hi|hello|hey) )?(?:my name is|my name s|i am|i m|this is|call me)\b"
    r"|^(?:(?:مرحبا|اهلا|أهلا|السلام عليكم) )?(?:اسمي|انا اسمي|أنا اسمي|معك|انا|أنا)\b"
)
QUESTION_WORD_RE = re.compile(
    r"\b(what|which|who|whom|whose|when|where|why|how|can|could|should|would|is|are|does|do|"
    r"did|may|must|will|explain|tell|list|give|show)\b"
    r"|(?:^| )(?:ما|ماذا|من|متى|أين|اين|لماذا|كيف|هل|كم|أي|اي|اشرح|وضح|اذكر)(?= |$)"
)
MAX_INTRODUCTION_WORDS = 25


def normalise(text: str) -> str:
    text = TATWEEL_AND_MARKS_RE.sub("", text.strip().lower())
    text = PUNCTUATION_RE.sub(" ", text)
    return re.sub(r"\s+", " ", text).strip()


def classify_by_rules(text: str) -> MessageKind | None:
    """The kind of message when the rules can tell; None when a model must decide."""
    norm = normalise(text)
    if not norm:
        return None
    if looks_like_injection(norm):
        return MessageKind.INJECTION
    intro = INTRODUCTION_RE.search(norm)
    if (
        intro
        and "?" not in text
        and "؟" not in text
        and len(norm.split()) <= MAX_INTRODUCTION_WORDS
        and not QUESTION_WORD_RE.search(norm[intro.end():])
    ):
        return MessageKind.CONVERSATION
    if SUBJECT_RE.search(norm):
        return MessageKind.QUESTION
    if len(norm.split()) <= MAX_LIGHT_WORDS and LIGHT_RE.fullmatch(norm):
        return MessageKind.IDENTITY if IDENTITY_RE.search(norm) else MessageKind.CONVERSATION
    return None


def is_conversational(text: str) -> bool:
    """True for greetings, thanks and questions about the assistant itself."""
    return classify_by_rules(text) in (MessageKind.CONVERSATION, MessageKind.IDENTITY)


SCOPE_PROMPT = (
    "You route messages for mawthuq, an assistant whose agents answer questions about AI "
    "governance in government services: laws and regulations, policies and strategies, "
    "immigration, visas and residency, personal data and privacy, AI ethics, bias and "
    "discrimination, accountability, cybersecurity, digital government, standards (ITU, OECD, "
    "UNESCO, EU AI Act), and the incident simulations these agents run.\n"
    "Answer with one word: IN if the message is about any of those subjects, OUT if it is not "
    "(general knowledge, maths, coding, entertainment, sport, weather, personal advice and so "
    "on). A follow-up to an earlier question on those subjects ('shorten that', 'and for "
    "ICP?') is IN. When unsure, answer IN."
)


async def classify(text: str, llm, previous: str | None = None) -> MessageKind:
    """Rules first; one short model call only for messages the rules cannot place.

    ``previous`` is the user's earlier question, so a follow-up is judged with its topic.
    """
    kind = classify_by_rules(text)
    if kind is not None:
        return kind
    message = text[:1000]
    if previous:
        message = f"Earlier question: {previous[:500]}\nNew message: {message}"
    try:
        verdict = await llm.chat(
            messages=[
                {"role": "system", "content": SCOPE_PROMPT},
                {"role": "user", "content": message},
            ],
            temperature=0.0,
            num_predict=3,
        )
    except Exception as exc:
        # The agents can answer anything; routing must never block a question.
        logger.warning("intent.classify_failed", error=str(exc))
        return MessageKind.QUESTION
    return MessageKind.OFF_TOPIC if verdict.strip().upper().startswith("OUT") else (
        MessageKind.QUESTION
    )


# --- Fixed facts about the assistant -------------------------------------------------------

PROFILE_PATH = Path(__file__).resolve().parents[3] / "data" / "assistant_profile.json"
DEFAULT_PROFILE = {
    "name": {"en": "mawthuq", "ar": "موثوق"},
    "made_by": {
        "en": "the SYNORA team (Firas Arafah, Motaz Abu Amara and Maria Dawaghreh) for the ITU "
        "AI for Good Lab Hackathon in the United Arab Emirates",
        "ar": "فريق SYNORA (فراس عرفة ومعتز ابو عمارة وماريا دواغرة) ضمن هاكاثون مختبر الذكاء "
        "الاصطناعي من أجل الخير التابع للاتحاد الدولي للاتصالات في دولة الإمارات",
    },
    "about": {
        "en": "an assistant for AI governance in government services. A team of agents (the "
        "ICP Representative, an AI Auditor, a Privacy Consultant and a Coordinator) answers "
        "questions from UAE legislation and international references such as the PDPL, the UAE "
        "AI Charter, the EU AI Act, OECD, UNESCO and ITU, and runs incident simulations",
        "ar": "مساعد لحوكمة الذكاء الاصطناعي في الخدمات الحكومية. يجيب فريق من الوكلاء (ممثل "
        "الهيئة الاتحادية للهوية والجنسية، ومدقق الذكاء الاصطناعي، ومستشار الخصوصية، "
        "والمنسّق) عن الأسئلة استناداً إلى التشريعات الإماراتية والمراجع الدولية، ويجري محاكاة "
        "للحوادث",
    },
}


def load_profile() -> dict:
    """The assistant's name, makers and description; data/assistant_profile.json overrides."""
    try:
        custom = json.loads(PROFILE_PATH.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return DEFAULT_PROFILE
    return {key: {**DEFAULT_PROFILE[key], **custom.get(key, {})} for key in DEFAULT_PROFILE}


def identity_reply(language: str) -> str:
    profile = load_profile()
    lang = "ar" if language == "ar" else "en"
    name, made_by, about = (profile[k][lang] for k in ("name", "made_by", "about"))
    if lang == "ar":
        return f"أنا «{name}»، {about}. طوّرني {made_by}. كيف يمكنني مساعدتك؟"
    return f"I'm {name}, {about}. I was built by {made_by}. How can I help you?"


# --- Prompts for short replies ---------------------------------------------------------------

_ABOUT = {
    "en": (
        "You are mawthuq, an assistant for AI governance in UAE government services. A team of "
        "agents answers questions from UAE law and international references (PDPL, UAE AI "
        "Charter, EU AI Act, OECD, UNESCO, ITU) and runs incident simulations.\n"
    ),
    "ar": (
        "أنت «موثوق»، مساعد لحوكمة الذكاء الاصطناعي في الخدمات الحكومية في دولة الإمارات. يجيب "
        "فريق من الوكلاء عن الأسئلة استناداً إلى التشريعات الإماراتية والمراجع الدولية، ويجري "
        "محاكاة للحوادث.\n"
    ),
}

CONVERSATION_PROMPT = {
    "en": _ABOUT["en"]
    + "The user sent a conversational message, not a policy question. Reply in English, "
    "warmly and in one to three short sentences. If it fits, say briefly what you can help "
    "with. Do not cite laws, do not analyse anything, and do not use tags or headings.",
    "ar": _ABOUT["ar"]
    + "أرسل المستخدم رسالة ودّية وليست سؤالاً عن السياسات. ردّ بالعربية الفصحى بلطف وفي جملة "
    "إلى ثلاث جمل قصيرة، واذكر باختصار ما يمكنك المساعدة فيه إن كان ذلك مناسباً. لا تستشهد "
    "بالقوانين ولا تحلّل ولا تستخدم وسوماً أو عناوين.",
}

OFF_TOPIC_PROMPT = {
    "en": _ABOUT["en"]
    + "The user asked something outside that remit. Reply in English in at most three short "
    "sentences: if it is a simple factual question you are sure of, answer it in one sentence; "
    "if it asks you to write, translate, code or plan something, do not do it. Then say that "
    "you specialise in AI governance and public-sector policy and invite such a question. Do "
    "not cite laws and do not use tags or headings.",
    "ar": _ABOUT["ar"]
    + "سأل المستخدم عن أمر خارج هذا الاختصاص. ردّ بالعربية الفصحى في ثلاث جمل قصيرة على الأكثر: "
    "إن كان سؤالاً واقعياً بسيطاً وأنت متأكد من جوابه فأجب في جملة واحدة، وإن طلب كتابة أو "
    "ترجمة أو برمجة أو تخطيطاً فلا تنفّذه، ثم وضّح أنك متخصص في حوكمة "
    "الذكاء الاصطناعي والسياسات الحكومية وادعُ المستخدم إلى سؤال في هذا المجال. لا تستشهد "
    "بالقوانين ولا تستخدم وسوماً أو عناوين.",
}

LIGHT_PROMPTS = {
    MessageKind.CONVERSATION: CONVERSATION_PROMPT,
    MessageKind.OFF_TOPIC: OFF_TOPIC_PROMPT,
}
