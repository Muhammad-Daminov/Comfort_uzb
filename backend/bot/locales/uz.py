"""Uzbek message copy — single source, per Phase-04-Bot.md's
`docs/05_BOT_SPEC.md` deliverable ("Uzbek message copy"). No localization
framework exists elsewhere in the project yet (Master TZ names Uzbek/lotin
as the only supported language, §0 header), so this is a plain constants
module, not a new i18n dependency — scoped to exactly what Phase 04 needs,
not a general-purpose framework for languages nothing else requires yet.
"""
from __future__ import annotations

WELCOME_NEW_USER = (
    "Assalomu alaykum! COMFORT UZB — avto ehtiyot qismlar do'koniga xush kelibsiz.\n\n"
    "Davom etish uchun telefon raqamingizni yuboring."
)
WELCOME_BACK = "Xush kelibsiz! Katalogni ko'rish uchun pastdagi tugmani bosing."
REQUEST_PHONE_BUTTON = "📱 Telefon raqamni yuborish"
OPEN_CATALOG_BUTTON = "🛍 Katalogni ochish"

PHONE_SAVED = "Rahmat! Telefon raqamingiz saqlandi."
PHONE_INVALID = (
    "Telefon raqam formati noto'g'ri. Iltimos, tugma orqali yuboring "
    "yoki +998XX XXX XX XX formatida kiriting."
)

PHONE_ALREADY_USED = (
    "Bu telefon raqam boshqa hisobga bog'langan. Boshqa raqam yuboring "
    "yoki do'kon bilan bog'laning."
)

BLOCKED_USER_WELCOME_BACK = "Botni qayta yoqqaningiz uchun rahmat! Xush kelibsiz."

GENERIC_ERROR = "Kechirasiz, xatolik yuz berdi. Birozdan so'ng qaytadan urinib ko'ring."

NOTIFICATION_PREFIX = "🔔 "

# --- AI admin assistant (v2 rebuild §14-25) -----------------------------------

AI_CONFIRM_BUTTON = "✅ Tasdiqlash"
AI_EDIT_BUTTON = "✏️ Tahrirlash"
AI_CANCEL_BUTTON = "❌ Bekor qilish"

AI_NOT_UNDERSTOOD = "🤖 Tushunmadim. Iltimos, aniqroq yozing yoki masalan \"Mahsulot nomi + 1\" ko'rinishida yuboring."
AI_CLARIFICATION_NEEDED = "🤖 {message}"
AI_STT_NOT_CONFIGURED = (
    "🤖 Ovozli xabarlarni tushunish hozircha ulanmagan (STT_PROVIDER sozlanmagan). "
    "Iltimos, matn ko'rinishida yozing."
)
AI_TRANSCRIPTION_FAILED = "🤖 Ovozli xabarni tushunib bo'lmadi. Iltimos, qaytadan yuboring yoki matn yozing."
AI_VOICE_INVALID = "🤖 Audio faylni o'qib bo'lmadi. Iltimos, qayta yuboring."
AI_PROVIDER_FAILED = "🤖 AI xizmatida vaqtinchalik xatolik. Birozdan so'ng qaytadan urinib ko'ring."
AI_UNAUTHORIZED = "Bu buyruq faqat administrator/egasi uchun."
AI_PERMISSION_REVOKED = "Sizda bu amal uchun ruxsat yo'q."
AI_DRAFT_NOT_FOUND = "Bu so'rov topilmadi yoki muddati o'tgan."
AI_DRAFT_EXPIRED = "⏰ Vaqt tugadi. Iltimos, buyruqni qaytadan yuboring."
AI_ALREADY_HANDLED = "Bu so'rov allaqachon bajarilgan yoki bekor qilingan."
AI_NOT_YOUR_DRAFT = "Bu so'rov sizga tegishli emas."
AI_EXECUTION_FAILED = "🤖 Amalni bajarib bo'lmadi: {error}"
AI_CANCELLED = "❌ Bekor qilindi."
AI_EDIT_PROMPT = "✏️ Yangi buyruqni matn yoki ovozli xabar sifatida qayta yuboring."

AI_PHOTO_AWAITING_DESCRIPTION = (
    "🤖 Rasm qabul qilindi. Endi shu mahsulot haqida matn yoki ovozli xabar yuboring "
    "(2 daqiqa ichida), masalan: \"Malibu 2, [brend], qora, koja, 500 dollar, 1 dona\"."
)
AI_BRAND_REQUIRED = (
    "🤖 Yangi mahsulot uchun brendni ham ko'rsating, masalan: "
    "\"Malibu 2, [brend nomi], 2 ta old sidenasi, qora, koja, 500 dollar, 1 dona\"."
)
AI_PRODUCT_NOT_FOUND = "🤖 \"{query}\" nomli mahsulot topilmadi."
AI_AMBIGUOUS_PRODUCT = "🤖 Bir nechta mos mahsulot topildi, aniqroq yozing:\n{options}"
