/**
 * Three languages, one of which reads right to left.
 *
 * A small hand-rolled dictionary rather than a library: the surface is a few dozen strings, and
 * the thing that actually matters for Arabic is the document direction, which no library does for
 * you anyway.
 */

export const LOCALES = ["en", "hi", "ar"] as const;
export type Locale = (typeof LOCALES)[number];

export const LOCALE_NAMES: Record<Locale, string> = {
  en: "English",
  hi: "हिन्दी",
  ar: "العربية",
};

export function direction(locale: Locale): "ltr" | "rtl" {
  return locale === "ar" ? "rtl" : "ltr";
}

type Dictionary = Record<string, string>;

const en: Dictionary = {
  "app.name": "YIELDMAP",
  "app.tagline": "Dubai property, from the registry up",
  "notice.title": "Information, not advice",
  "notice.body":
    "Every figure comes from published Dubai Land Department data by way of a recorded query. YIELDMAP explains, compares and simulates. It cannot carry out any transaction.",
  "nav.city": "City",
  "nav.areas": "Areas",
  "nav.compare": "Compare",
  "nav.screener": "Screener",
  "nav.simulate": "Simulate",
  "nav.portfolio": "Portfolio",
  "nav.rent": "Rent",
  "nav.forecast": "Forecast",
  "nav.signals": "Signals",
  "nav.developers": "Developers",
  "nav.ask": "Ask",
  "nav.memos": "Memos",
  "nav.crew": "Crew",
  "nav.models": "Models",
  "nav.evals": "Evals",
  "nav.methodology": "Methodology",
  "nav.data": "Data",
  "nav.security": "Security",
  "nav.report": "Report",
  "kpi.insufficient": "Insufficient data",
  "kpi.sample": "n =",
  "kpi.asof": "as of",
  "kpi.how": "How is this computed?",
  "kpi.sql": "The query behind this number",
  "kpi.copy": "Copy query",
  "kpi.copied": "Copied",
  "kpi.method": "Method",
  "kpi.confidence.high": "High confidence",
  "kpi.confidence.medium": "Medium confidence",
  "kpi.confidence.low": "Low confidence",
  "kpi.confidence.insufficient": "Too few records to report",
  "provenance.synthetic.title": "These figures are generated, not from the registry",
  "provenance.synthetic.body":
    "Dubai Pulse, which publishes the bulk registry files, refuses connections from automated clients. The pipeline is running on a labelled stand-in whose structure is realistic and whose levels are invented. Nothing here is a statement about Dubai.",
  "common.loading": "Loading",
  "common.error": "Something went wrong",
  "common.retry": "Try again",
  "common.none": "Nothing to show yet",
  "common.search": "Search",
  "common.close": "Close",
  "theme.toggle": "Switch theme",
  "role.label": "Role",
};

const hi: Dictionary = {
  ...en,
  "app.tagline": "दुबई की संपत्ति, रजिस्ट्री से सीधे",
  "notice.title": "जानकारी, सलाह नहीं",
  "notice.body":
    "हर आँकड़ा दुबई भूमि विभाग के प्रकाशित आँकड़ों से एक दर्ज क्वेरी के ज़रिए आता है। YIELDMAP समझाता, तुलना और अनुकरण करता है। यह कोई लेनदेन नहीं कर सकता।",
  "nav.city": "शहर",
  "nav.areas": "क्षेत्र",
  "nav.compare": "तुलना",
  "nav.screener": "स्क्रीनर",
  "nav.simulate": "अनुकरण",
  "nav.portfolio": "पोर्टफोलियो",
  "nav.rent": "किराया",
  "nav.forecast": "पूर्वानुमान",
  "nav.signals": "संकेत",
  "nav.developers": "डेवलपर",
  "nav.ask": "पूछें",
  "nav.memos": "मेमो",
  "nav.crew": "टीम",
  "nav.models": "मॉडल",
  "nav.evals": "मूल्यांकन",
  "nav.methodology": "पद्धति",
  "nav.data": "डेटा",
  "nav.security": "सुरक्षा",
  "nav.report": "रिपोर्ट",
  "kpi.insufficient": "पर्याप्त डेटा नहीं",
  "kpi.how": "यह कैसे गणना की गई?",
  "kpi.sql": "इस आँकड़े के पीछे की क्वेरी",
  "kpi.asof": "तिथि",
  "provenance.synthetic.title": "ये आँकड़े उत्पन्न किए गए हैं, रजिस्ट्री से नहीं",
  "provenance.synthetic.body":
    "दुबई पल्स, जो थोक रजिस्ट्री फ़ाइलें प्रकाशित करता है, स्वचालित क्लाइंट से कनेक्शन अस्वीकार करता है। पाइपलाइन एक चिह्नित विकल्प पर चल रही है जिसकी संरचना वास्तविक है पर मान काल्पनिक हैं।",
  "common.loading": "लोड हो रहा है",
  "common.error": "कुछ गड़बड़ हुई",
  "common.retry": "फिर कोशिश करें",
  "common.search": "खोजें",
  "common.close": "बंद करें",
  "theme.toggle": "थीम बदलें",
  "kpi.copy": "क्वेरी कॉपी करें",
  "kpi.copied": "कॉपी हो गया",
  "kpi.method": "विधि",
  "kpi.confidence.high": "उच्च विश्वसनीयता",
  "kpi.confidence.medium": "मध्यम विश्वसनीयता",
  "kpi.confidence.low": "कम विश्वसनीयता",
  "kpi.confidence.insufficient": "रिपोर्ट करने के लिए बहुत कम रिकॉर्ड",
  "common.none": "अभी दिखाने के लिए कुछ नहीं",
  "role.label": "भूमिका",
};

const ar: Dictionary = {
  ...en,
  "app.tagline": "عقارات دبي، من السجل مباشرة",
  "notice.title": "معلومات، وليست نصيحة",
  "notice.body":
    "كل رقم مأخوذ من بيانات دائرة الأراضي والأملاك المنشورة عبر استعلام مسجَّل. يشرح YIELDMAP ويقارن ويحاكي، ولا يمكنه تنفيذ أي معاملة.",
  "nav.city": "المدينة",
  "nav.areas": "المناطق",
  "nav.compare": "مقارنة",
  "nav.screener": "الفارز",
  "nav.simulate": "محاكاة",
  "nav.portfolio": "المحفظة",
  "nav.rent": "الإيجار",
  "nav.forecast": "التوقعات",
  "nav.signals": "الإشارات",
  "nav.developers": "المطوّرون",
  "nav.ask": "اسأل",
  "nav.memos": "المذكرات",
  "nav.crew": "الفريق",
  "nav.models": "النماذج",
  "nav.evals": "التقييمات",
  "nav.methodology": "المنهجية",
  "nav.data": "البيانات",
  "nav.security": "الأمن",
  "nav.report": "التقرير",
  "kpi.insufficient": "بيانات غير كافية",
  "kpi.how": "كيف تم حساب هذا؟",
  "kpi.sql": "الاستعلام وراء هذا الرقم",
  "kpi.asof": "حتى تاريخ",
  "provenance.synthetic.title": "هذه الأرقام مُولَّدة وليست من السجل",
  "provenance.synthetic.body":
    "يرفض دبي بالس، الذي ينشر ملفات السجل الكاملة، الاتصالات من العملاء الآليين. تعمل المنظومة على بديل مُعلَّم بنية واقعية وقيم مُختلَقة.",
  "common.loading": "جارٍ التحميل",
  "common.error": "حدث خطأ ما",
  "common.retry": "أعد المحاولة",
  "common.search": "بحث",
  "common.close": "إغلاق",
  "theme.toggle": "تبديل السمة",
  "kpi.copy": "نسخ الاستعلام",
  "kpi.copied": "تم النسخ",
  "kpi.method": "الطريقة",
  "kpi.confidence.high": "ثقة عالية",
  "kpi.confidence.medium": "ثقة متوسطة",
  "kpi.confidence.low": "ثقة منخفضة",
  "kpi.confidence.insufficient": "السجلات أقل من أن يُبنى عليها رقم",
  "common.none": "لا يوجد ما يُعرض بعد",
  "role.label": "الدور",
};

const DICTIONARIES: Record<Locale, Dictionary> = { en, hi, ar };

/**
 * Keys that are deliberately identical in every language, so English text under a non-English
 * locale is not a gap for them. `app.name` is a brand, and `kpi.sample` is the mathematical "n ="
 * that reads the same in all three.
 */
export const SHARED_ACROSS_LOCALES = ["app.name", "kpi.sample"] as const;

/** Every key the interface can ask for, which is by definition every key English defines. */
export const TRANSLATION_KEYS = Object.keys(en);

/**
 * Keys where a locale still shows the English string.
 *
 * This compares the rendered text rather than asking whether the key is present, because `hi` and
 * `ar` are built by spreading `en` — so every key is always present in every dictionary and a
 * presence check can never report anything. That spread is what let nine strings, including the
 * confidence label on every KPI tile, sit in English behind a right-to-left layout without
 * anything looking wrong.
 *
 * Comparing the text also catches the other way it goes wrong: an English string pasted into a
 * translated dictionary, which a presence check counts as translated.
 */
export function untranslated(locale: Locale): string[] {
  if (locale === "en") return [];
  const dictionary = DICTIONARIES[locale];
  const shared = new Set<string>(SHARED_ACROSS_LOCALES);
  return TRANSLATION_KEYS.filter(
    (key) => !shared.has(key) && dictionary[key] === en[key],
  );
}

export function translator(locale: Locale) {
  const dictionary = DICTIONARIES[locale] ?? en;
  /** Falls back to English, then to the key itself — never to a blank space. */
  return (key: string): string => dictionary[key] ?? en[key] ?? key;
}

export function isLocale(value: string): value is Locale {
  return (LOCALES as readonly string[]).includes(value);
}
