/**
 * Uzbek UI copy — single source, mirrors `backend/bot/locales/uz.py`'s
 * convention. No i18n framework: the project supports only Uzbek (Master
 * TZ header), so a plain constants module is all that's needed.
 */
export const uz = {
  loading: "Yuklanmoqda...",
  retry: "Qaytadan urinib ko'rish",
  emptyCatalog: "Hozircha mahsulotlar yo'q.",
  emptySearch: "Hech narsa topilmadi.",
  emptyCart: "Savatingiz bo'sh.",
  errorUnauthorized: "Sessiya tugagan. Ilovani qaytadan oching.",
  errorForbidden: "Bu amalni bajarish uchun ruxsatingiz yo'q.",
  errorNotFound: "Topilmadi.",
  errorConflict: "Ma'lumot yangilandi, iltimos qaytadan tekshiring.",
  errorValidation: "Ma'lumotlar noto'g'ri kiritilgan.",
  errorServer: "Serverda vaqtinchalik xatolik. Birozdan so'ng urinib ko'ring.",
  errorNetwork: "Internet aloqasi yo'q. Qaytadan urinib ko'ring.",
  priceMismatch: "Narx yangilandi. Yangi narx bilan davom eting.",
  insufficientStock: "Afsuski, bu mahsulotdan yetarli miqdorda qolmagan.",
  addToCart: "Savatga qo'shish",
  checkout: "Buyurtma berish",
  payNow: "To'lovni yuborish",
  uploadReceipt: "Chekni yuklash",
  cancelOrder: "Buyurtmani bekor qilish",
  outOfStock: "Sotuvda yo'q",
  orderCreated: "Buyurtmangiz qabul qilindi",
  requestCancellation: "Bekor qilishni so'rash",
  cancellationRequestSent: "So'rovingiz yuborildi. Administrator tez orada ko'rib chiqadi.",
  cancellationReasonPrompt: "Bekor qilish sababini yozing (kamida 10 belgi):",
  cancellationStatusPending: "Bekor qilish so'rovi ko'rib chiqilmoqda",
  cancellationStatusApproved: "Bekor qilish so'rovi tasdiqlandi",
  cancellationStatusDenied: "Bekor qilish so'rovi rad etildi",
  refundStatusPending: "Qaytarish kutilmoqda",
  refundStatusCompleted: "Qaytarildi",
  refundStatusFailed: "Qaytarish amalga oshmadi",
} as const;
