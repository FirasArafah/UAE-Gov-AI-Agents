/**
 * Interface language (English / Arabic). The choice is kept in localStorage; a first visit
 * follows the browser language. Arabic switches the document to right-to-left.
 */

const STORAGE_KEY = "lang";
const LANGUAGES = ["en", "ar"];

const DICT = {
  en: {
    "app.title": "Mawthuq",
    brand: "Mawthuq",
    "nav.main": "Main",
    "nav.skip": "Skip to content",
    "nav.menu": "Menu",
    "nav.newChat": "New chat",
    "nav.chat": "Chat",
    "nav.simulations": "Simulations",
    "nav.agents": "Agents",
    "nav.kb": "Knowledge base",
    "nav.recent": "Recent",
    "nav.recentAria": "Recent chats",
    "recents.empty": "No chats yet",
    "recents.error": "Could not load chats",
    "recents.options": "Options for {title}",
    "recents.rename": "Rename",
    "recents.delete": "Delete",
    "recents.renameLabel": "New name for the chat",
    "recents.confirmDelete":
      "Delete the chat “{title}”? Its messages and audit entries are removed for good.",
    "recents.failed": "The chat could not be changed: {error}",
    "health.ok": "Model online",
    "health.degraded": "Degraded",
    "health.down": "Server offline",
    "health.checking": "Checking",
    "health.title": "Database: {db} · Model: {llm} · Agents: {agents}",
    "theme.toggle": "Switch between light and dark",
    "lang.switchTo": "العربية",
    "lang.toggle": "Switch interface language",
    "page.notFound": "This page does not exist.",
    "page.back": "Back to chat",
    "common.loading": "Loading…",
    "common.loadFailed": "Could not load: {error}",
    "time.seconds": "{s}s",
    "time.minutes": "{m}m {s}s",
  },
  ar: {
    "app.title": "موثوق",
    brand: "موثوق",
    "nav.main": "القائمة الرئيسية",
    "nav.skip": "تخطَّ إلى المحتوى",
    "nav.menu": "القائمة",
    "nav.newChat": "محادثة جديدة",
    "nav.chat": "المحادثة",
    "nav.simulations": "المحاكاة",
    "nav.agents": "الوكلاء",
    "nav.kb": "قاعدة المعرفة",
    "nav.recent": "الأحدث",
    "nav.recentAria": "المحادثات الأخيرة",
    "recents.empty": "لا توجد محادثات بعد",
    "recents.error": "تعذّر تحميل المحادثات",
    "recents.options": "خيارات {title}",
    "recents.rename": "إعادة التسمية",
    "recents.delete": "حذف",
    "recents.renameLabel": "اسم جديد للمحادثة",
    "recents.confirmDelete":
      "حذف المحادثة «{title}»؟ ستُحذف رسائلها وسجلات التدقيق الخاصة بها نهائياً.",
    "recents.failed": "تعذّر تعديل المحادثة: {error}",
    "health.ok": "النموذج متصل",
    "health.degraded": "أداء منخفض",
    "health.down": "الخادم غير متاح",
    "health.checking": "جارٍ التحقق",
    "health.title": "قاعدة البيانات: {db} · النموذج: {llm} · الوكلاء: {agents}",
    "theme.toggle": "التبديل بين الوضع الفاتح والداكن",
    "lang.switchTo": "English",
    "lang.toggle": "تغيير لغة الواجهة",
    "page.notFound": "هذه الصفحة غير موجودة.",
    "page.back": "العودة إلى المحادثة",
    "common.loading": "جارٍ التحميل…",
    "common.loadFailed": "تعذّر التحميل: {error}",
    "time.seconds": "{s} ث",
    "time.minutes": "{m} د {s} ث",
  },
};

function initialLanguage() {
  try {
    const saved = localStorage.getItem(STORAGE_KEY);
    if (LANGUAGES.includes(saved)) return saved;
  } catch {
    /* storage unavailable */
  }
  return (navigator.language || "").toLowerCase().startsWith("ar")
    ? "ar"
    : "en";
}

let current = initialLanguage();

export const language = () => current;
export const isRtl = () => current === "ar";

/** Add strings for a page; each page keeps its own text next to its code. */
export function addStrings(strings) {
  for (const lang of LANGUAGES) Object.assign(DICT[lang], strings[lang] || {});
}

/** Translate a key, filling {placeholders} from vars. Unknown keys fall back to English. */
export function t(key, vars = {}) {
  const text = DICT[current][key] ?? DICT.en[key] ?? key;
  return text.replace(/\{(\w+)\}/g, (_, name) => vars[name] ?? `{${name}}`);
}

/** Format a number with Western digits, as UAE government sites do in both languages. */
export const num = (n) => Number(n).toLocaleString("en-US");

export function duration(ms) {
  const total = Math.max(1, Math.round(ms / 1000));
  if (total < 60) return t("time.seconds", { s: total });
  return t("time.minutes", {
    m: Math.floor(total / 60),
    s: String(total % 60).padStart(2, "0"),
  });
}

/** Apply the language to <html> and to static markup: data-i18n and data-i18n-<attr>. */
export function applyLanguage(root = document) {
  const html = document.documentElement;
  html.lang = current;
  html.dir = isRtl() ? "rtl" : "ltr";
  document.title = `${t("app.title")} · ${current === "ar" ? "Mawthuq" : "موثوق"}`;
  for (const el of root.querySelectorAll("[data-i18n]"))
    el.textContent = t(el.dataset.i18n);
  for (const attr of ["aria-label", "title", "placeholder"]) {
    for (const el of root.querySelectorAll(`[data-i18n-${attr}]`)) {
      el.setAttribute(attr, t(el.getAttribute(`data-i18n-${attr}`)));
    }
  }
}

export function setLanguage(lang) {
  if (!LANGUAGES.includes(lang) || lang === current) return;
  current = lang;
  try {
    localStorage.setItem(STORAGE_KEY, lang);
  } catch {
    /* storage unavailable */
  }
  applyLanguage();
  window.dispatchEvent(new Event("language-changed"));
}
