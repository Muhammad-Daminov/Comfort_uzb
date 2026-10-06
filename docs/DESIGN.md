# Comfort UZB — Dizayn tizimi

Yo'nalish (2026-09-29 dan): **Premium sidena/seat-cover do'kon** — teri va
usta ishi kayfiyati (leather/upholstery/craftsmanship), Uzum/Wildberries
emas. Minimal, iliq, "expensive-looking", lekin bachkana emas: ko'p rang,
gradient, neon, glassmorphism yo'q. Faqat SIDENA va SIDENA CHEXOLLARI
sotiladi — UI boshqa avtomobil aksessuarlari kategoriyasi ko'rsatmaydi.

Bu qiymatlardan tashqari qiymat ishlatilmaydi. Oraliq son yo'q.

## Rang

Fon va matn Telegram themeParams dan olinadi, lekin fallback (Telegram
tashqarisida — lokal brauzer) endi iliq/premium, Telegram default ko'k
emas. Brend ranglari OLINMAYDI — dark/light da ham o'zgarmaydi.

    --pri        #4A3221   espresso jigarrang — asosiy harakat, brend
    --pri-dark   #C8955F   (dark rejimda --pri o'rniga — iliq tan)
    --pri-bg     #F1E7DA / #2E2115
    --acc        #A9824F   muted gold — chegirma, urg'u
    --ok         #5B7355   sage yashil — mavjud, tasdiqlangan
    --warn       #A9824F   gold — kam qoldi (--acc bilan bir xil)
    --danger     #9A4433   rust qizil — tugagan, bekor, xato

Neytral (themeParams bo'lmasa fallback — iliq krem/qahva, Telegram ko'ki
emas):

    light  bg #FAF6F0  surface #FFFFFF  line #E7DDD0
           text #2A211A  text2 #6B5D4F  text3 #A69783
    dark   bg #1C1712  surface #241D17  line #3A2E24
           text #F2E9DD  text2 #B7A793  text3 #7A6C5C

## Shrift

Ikkita shrift, aniq vazifa bilan:

    Sarlavha (serif)   "Fraunces" — screen-title, section-title, h1/h2,
                        brend wordmark ("COMFORT UZB"), mahsulot nomi
                        (detal sahifasida). Nafas oladigan, elegant.
    UI (sans-serif)     Inter — tugma, yorliq, narx, navigatsiya, meta,
                        kartadagi mahsulot nomi (kichik joy — serif
                        o'qilmaydi shu o'lchamda).

Boshqa shrift yo'q.

    display  32 / 600 / -0.01em / serif    ekran sarlavhasi
    title    19 / 600 / -0.01em / serif    bo'lim nomi
    body     15 / 400  / sans              asosiy matn
    card     12.5 / 700 / sans             karta nomi
    label    13 / 600 / sans               tugma, yorliq
    caption  11 / 500 / sans               meta, izoh
    brand    9.5 / 700 / 0.07em / sans     UPPERCASE, karta brendi

    narx     14.5 / 800  (kartada)
             19 / 900    (detal va pastki panel)
             font-variant-numeric: tabular-nums   ← MAJBURIY

Narx har doim tabular-nums. Aks holda ro'yxatda raqamlar qalqib turadi.
Narx sans-serif — raqam serifda emas.

## Ikonka

Emoji YO'Q (🏠🔍📦 va h.k.) — professional ko'rinish uchun `src/components/
icons.ts` dagi minimal chiziqli SVG ikonkalar ishlatiladi (stroke=currentColor,
1.5-2px, 20-24px). Yurak (♡/♥, sevimlilar) ham shu to'plamda SVG sifatida.

    4  8  10  12  14  16  24  32

Boshqa qiymat yo'q. Ekran cheti = 14. Kartalar orasi = 10.

## Radius

    3    belgi, chip ichidagi mayda
    10   tugma, input
    14   karta, modal, promo
    20   chip, badge, yumaloq tugma
    50%  avatar, yurak tugmasi

## Soya — ikkitasi

    karta   0 1px 3px rgba(20,24,33,.07)
    modal   0 8px 32px rgba(20,24,33,.16)

Dark rejimda soya o'rniga `line` chegara ishlatiladi.

## Mahsulot kartasi — do'konning yuzi

Tuzilishi (o'zgarmaydi):

    ┌──────────────────┐
    │ [−30%]      [♡] │  rasm 1:1, fon = bg
    │       🪑         │  chap tepa: chegirma yoki "Tugagan"
    │                  │  o'ng tepa: yurak
    ├──────────────────┤
    │ NEXIA            │  brand — 9.5/700, uppercase, --pri
    │ Nexia 3 teri     │  nom — 12.5/700, 2 qator, kesiladi
    │ Nexia 3 2016–24  │  moslik — 10.5, --text3
    │ 455 000      [+] │  narx — 14.5/800 tabular
    │ 650 000          │  eski narx — 10.5, ustidan chizilgan
    └──────────────────┘

Moslik qatorida **yil oralig'i majburiy**. Xaridorning birinchi savoli
"mening mashinamga tushadimi" — javob kartada bo'lsin, detalga
kirmasdan. DB da year_from/year_to bor, ishlatilsin.

Bosilganda: `transform: scale(.97)`, 120ms.

## Holatlar — har ro'yxatda uchtasi ham

    Yuklanmoqda   skeleton, kartaning aynan shakli. Spinner YO'Q
    Bo'sh         belgi + bir jumla tushuntirish + harakat tugmasi
    Xato          nima bo'ldi + "Qayta urinish" tugmasi

Bo'sh ekran matni harakatga chorlaydi, kechirim so'ramaydi.
❌ "Hech narsa topilmadi"
✅ "Bu mashinaga sidena hozircha yo'q. Boshqa modelni ko'ring"

## Tugmalar

    asosiy      --pri fon, oq matn, radius 10, padding 12/20, 13.5/700
    ikkilamchi  --pri-bg fon, --pri matn
    tashqi      shaffof, --line chegara, --text matn
    xavfli      --danger fon, oq matn

Bosilganda opacity .85 + scale .98.

## Matn qoidalari

- O'zbek (lotin). Ingliz so'z yo'q
- Tugma nima qilishini aytadi: "Savatga qo'shish", "Yuborish" emas
- Bir amal — bir nom. "Sotib olish" bosilsa, keyingi ekran ham
  "Sotib olish" desin
- Xato aybdorni ko'rsatmaydi, yechimni aytadi

## Telegram

- Fon, matn, tugma ranglari `themeParams` dan
- `colorScheme` o'zgarsa darhol moslashadi
- Pastki panel `safe-area-inset-bottom` hisobga oladi
- `BackButton` va `MainButton` — Telegram niki ishlatiladi,
  o'z tugmangizni chizmang