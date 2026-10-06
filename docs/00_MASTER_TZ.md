COMFORT UZB — Texnik Topshiriq (TZ) v1.0

Loyiha: Avto sidena do'koni uchun Telegram Mini Web App + Bot Bozor: Toshkent, O'zbekiston · Til: O'zbek (lotin) Infratuzilma: O'zi boshqaradigan (self-hosted) Contabo VPS Versiya: 3.0 — v2.0 ni to'liq almashtiradi

0. v3.0 DA NIMA O'ZGARDI
0.1 Asosiy o'zgarish: Supabase → Contabo VPS
	v2.0 (Supabase)	v3.0 (Contabo)
Database	Supabase managed Postgres	O'z serveringizdagi PostgreSQL 16
Fayl ombori	Supabase Storage	Server diski + Nginx
Signed URL	Supabase beradi	O'zingiz qilasiz (Nginx secure_link)
RLS	Majburiy edi	Talabdan chiqarildi (§12.2 — sabab bor)
Backend↔DB masofa	Tarmoq (20–100ms)	Unix socket (~0.1ms)
Backup	Supabase (free da PITR yo'q)	O'zingiz — lekin PITR mumkin bo'ldi
Migration	Supabase CLI	Alembic
Connection pool	Supavisor	asyncpg pool + PgBouncer
Cron/worker	Yo'q edi	systemd timer (§15)
Server xavfsizligi	Supabase zimmasida	Sizning zimmangizda (§12.5)
Narx	Bepul, lekin 500MB DB / 1GB storage	~€6/oy, 100GB
0.2 Yaxshilanishlar
PITR mumkin bo'ldi. WAL arxivlash bilan RPO 24 soatdan 5 daqiqaga tushdi. Supabase free tier da bu imkonsiz edi
Storage limiti yo'q. 1 GB → 100 GB
RLS olib tashlandi → kod ancha sodda (sabab: §12.2)
Barcha loyihalar bir serverda — har biriga alohida to'lov yo'q
0.3 Olib tashlangan talablar
Nima	Nega
Promo kodlar	Chegirma tizimi (§7) allaqachon yetarli. Do'kon hozir ham shunday ishlaydi
RLS policy lar	Faqat backend DB ga ulanadi. Postgres role/GRANT yetarli (§12.2)
Supabase-ga xos hamma narsa	Auth, Realtime, Edge Functions, auto REST API — ishlatilmagan edi
Multiple warehouses	Bitta do'kon. Kerak emas
0.4 v1.0 dagi qarama-qarshiliklar

v1.0 da uch jiddiy ziddiyat bor edi — hammasi hal qilindi:

Arxitektura: "frontend RLS orqali DB ga kirsin" ⟷ "server haqiqat manbai" → ADR-1 (frontend faqat backend API bilan gaplashadi)
Auth: "SMS asosiy auth bo'lmaydi" ⟷ kodda SMS OTP bor → ADR-2 (SMS butunlay olib tashlandi)
Narx: product da ham, variant da ham price → ADR-4 (faqat variantda)
1. ARXITEKTURA QARORLARI (ADR)

Bu qarorlar majburiy.

ADR-1 — Yagona backend
Telegram Mini App ──HTTPS──▶ Nginx ──▶ FastAPI ──unix socket──▶ PostgreSQL
Telegram Bot ─────webhook──▶ Nginx ──▶ FastAPI ──▶ (bir xil Service qatlami)

Butun tizim bitta VPS da. Frontend DB ga hech qachon tegmaydi.

Sabab: narxni qayta tekshirish, stok atomikligi, permission — bularni DB qatlami o'zi bajara olmaydi. Biznes logika bitta joyda.

Bonus: backend va DB bir mashinada → tarmoq kechikishi yo'q. 5 marta DB ga tegadigan endpoint Supabase da 300ms yo'qotardi, endi ~1ms.

ADR-2 — Auth: Telegram initData. SMS YO'Q.

SMS OTP butunlay olib tashlanadi. Sabab: Eskiz.uz pullik, OTP saqlash/eskirish/brute-force himoyasi keraksiz kod, Telegram allaqachon foydalanuvchini tasdiqlagan.

Mexanizm:

Mini App window.Telegram.WebApp.initData ni yuboradi
Backend tekshiradi:
secret_key = HMAC_SHA256(key="WebAppData", msg=bot_token)
computed_hash = HMAC_SHA256(key=secret_key, msg=data_check_string)
computed_hash == received_hash bo'lishi shart
auth_date 24 soatdan oshmagan
Tekshirilgandan keyin telegram_id ishonchli
Telefon kerak bo'lsa — bot da KeyboardButton(request_contact=True), bepul

Frontenddan kelgan user_id hech qachon auth sifatida qabul qilinmaydi.

ADR-3 — Pul: BIGINT so'm
sql
price BIGINT NOT NULL CHECK (price >= 0)   -- so'm, butun son

FLOAT, REAL, DOUBLE PRECISION — taqiqlanadi. Tiyin ishlatilmaydi.

ADR-4 — Variant asosiy

Har product da kamida 1 ta variant. Rang yo'q bo'lsa — DEFAULT variant.

Maydon	Product	Variant
Nom, tavsif, brend	✅	—
Compatibility	✅	—
Narx	❌	✅
Stok	❌	✅
Boshlang'ich to'lov	❌	✅
Rang	❌	✅

Katalogda: MIN(variant.price) → "850 000 so'mdan".

ADR-5 — Order = snapshot

order_items snapshot saqlaydi:

product_name_snapshot, variant_label_snapshot, sku_snapshot,
unit_price, discount_amount, quantity,
required_initial_payment, line_total
order.total_amount            = SUM(line_total)
order.required_initial_amount = SUM(required_initial_payment × quantity)
order.paid_amount             = tasdiqlangan to'lovlar
order.remaining_amount        = total − paid

Product narxi keyin o'zgarsa eski order buzilmaydi.

ADR-6 — Stok rezervatsiyasi + TTL

Variantda uchta son:

stock_on_hand    -- omborda jismonan bor
stock_reserved   -- buyurtmalarga band
available        -- on_hand − reserved
Hodisa	Ta'sir
Order yaratildi	reserved += qty, expires_at = now() + 24h
To'lov tasdiqlandi	on_hand −= qty, reserved −= qty
Bekor qilindi	reserved −= qty
TTL o'tdi (worker)	reserved −= qty, order → EXPIRED

CHECK (stock_on_hand >= 0), CHECK (stock_reserved >= 0), CHECK (stock_reserved <= stock_on_hand).

ADR-7 — Idempotency
Idempotency-Key: 9f2b1c4e-...   (UUID v4)
sql
CREATE TABLE idempotency_keys (
  key           uuid PRIMARY KEY,
  endpoint      text NOT NULL,
  user_id       bigint NOT NULL,
  request_hash  text NOT NULL,
  response_body jsonb,
  status_code   int,
  created_at    timestamptz NOT NULL DEFAULT now()
);

Kalit mavjud bo'lsa — saqlangan javob qaytariladi, amal qayta bajarilmaydi. 24 soatdan keyin worker tozalaydi.

Majburiy: order yaratish, to'lov, chek yuklash, stok tuzatish, confirm/cancel, broadcast.

ADR-8 — Qidiruv: kirill/lotin normalizatsiya

O'zbekiston bozorida kritik. Odam yozadi: Nexia, Neksiya, Нексия, nexiya, Lasetti, Ласетти.

1) Normalizatsiya (yozishda va qidirishda bir xil funksiya):

kirill → lotin:  н→n  х→x  ш→sh  ч→ch  ў→o  қ→q  ғ→g  ҳ→h  ц→ts  я→ya ...
oʻ o' o` ў  →  o
gʻ g' g`    →  g
kichik harf, ortiqcha bo'shliq va tinish belgilari olib tashlanadi

2) Trigram index:

sql
CREATE EXTENSION IF NOT EXISTS pg_trgm;
ALTER TABLE products ADD COLUMN search_text text;
CREATE INDEX idx_products_search_trgm
  ON products USING gin (search_text gin_trgm_ops);

3) Alias jadvali:

sql
CREATE TABLE search_aliases (
  id          bigserial PRIMARY KEY,
  alias       text NOT NULL,      -- 'neksiya'
  canonical   text NOT NULL,      -- 'nexia'
  entity_type text NOT NULL       -- 'car_model' | 'brand'
);
CREATE UNIQUE INDEX ON search_aliases (alias, entity_type);

Tartib: alias → exact → trigram similarity (0.3+).

ADR-9 — Chek retention (30 kun)

DB yozuvi hech qachon o'chirilmaydi. Faqat fayl o'chiriladi.

sql
payment_receipts (
  storage_path      text NOT NULL,
  visibility_status text NOT NULL,   -- VISIBLE | HIDDEN_BY_USER | HIDDEN_BY_ADMIN
  hidden_at         timestamptz,
  hidden_by         bigint,
  retention_until   timestamptz NOT NULL,   -- uploaded_at + 30 kun
  file_purged_at    timestamptz,
  reviewed_at       timestamptz,
  review_result     text            -- APPROVED | REJECTED
)

"Chek tasdiqlashdan oldin o'chirildimi?" javobi:

hidden_at < reviewed_at   → tasdiqlashdan OLDIN yashirilgan  ⚠️
hidden_at > reviewed_at   → tasdiqlashdan KEYIN yashirilgan  ✅
reviewed_at IS NULL       → hali ko'rilmagan

OWNER panelida ogohlantirish belgisi bilan ko'rsatiladi.

Worker: retention_until < now() → faylni diskdan o'chiradi, file_purged_at yozadi. Metadata abadiy qoladi.

ADR-10 — Sell-request → Product
PENDING → UNDER_REVIEW → APPROVED → CONVERTED  (product yaratildi)
                       ↘ REJECTED  (sabab majburiy)
                       ↘ SOLD      (do'kondan tashqari sotildi)

APPROVED bo'lgach admin "Mahsulotga aylantirish" bosadi:

Draft product yaratiladi
products.source = 'CONSIGNMENT'
products.source_sell_request_id = <id>
Rasmlar sell-requests/ dan products/ katalogiga ko'chiriladi
Admin narx/stok to'ldiradi → publish
ADR-11 — OWNER bootstrap
sql
-- migration 001
INSERT INTO users (telegram_id, role, status)
VALUES (:OWNER_TELEGRAM_ID, 'OWNER', 'ACTIVE')
ON CONFLICT (telegram_id) DO NOTHING;

CREATE UNIQUE INDEX idx_single_owner ON users ((role))
  WHERE role = 'OWNER' AND deleted_at IS NULL;

OWNER_TELEGRAM_ID — env variable. UI orqali OWNER yaratish imkonsiz.

ADR-12 — Bot bloklangan foydalanuvchi

Telegram 403 Forbidden: bot was blocked qaytarsa:

sql
UPDATE users SET bot_blocked_at = now() WHERE telegram_id = ?;
Broadcast dan chiqariladi
Notification notifications jadvaliga yoziladi, Mini App ichida ko'rinadi
Qayta /start bosganda bot_blocked_at = NULL
ADR-13 — Signed URL: Nginx secure_link ⭐ YANGI

Supabase Storage signed URL ni o'zi berardi. Endi o'zimiz qilamiz.

Prinsip: backend imzo yaratadi, Nginx faylni beradi (Python fayl uzatmaydi — tez).

Backend (imzo yaratish):

python
def signed_url(path: str, ttl_seconds: int = 3600) -> str:
    expires = int(time.time()) + ttl_seconds
    raw = f"{expires}/files/{path} {SECRET}"
    digest = hashlib.md5(raw.encode()).digest()
    sig = base64.urlsafe_b64encode(digest).decode().rstrip("=")
    return f"/files/{path}?s={sig}&e={expires}"

Nginx (tekshirish va berish):

nginx
location /files/ {
    secure_link         $arg_s,$arg_e;
    secure_link_md5     "$secure_link_expires$uri SECRET";

    if ($secure_link = "")  { return 403; }   # imzo noto'g'ri
    if ($secure_link = "0") { return 410; }   # muddat o'tgan

    alias /var/comfort/uploads/;
    add_header Cache-Control "private, max-age=3600";
}

Muhim tafsilotlar:

$remote_addr imzoga qo'shilmaydi — mobil internetda IP o'zgaradi, link buziladi
Modul kerak: apt install nginx-extras, tekshirish: nginx -V 2>&1 | grep secure_link
TTL: cheklar 15 daqiqa, product rasmlari 24 soat
SECRET env dan, kodda emas
ADR-14 — Fayl tuzilishi ⭐ YANGI
/var/comfort/uploads/
├── products/{product_id}/{uuid}.webp
├── products/{product_id}/thumbs/{uuid}.webp
├── receipts/{yyyy}/{mm}/{uuid}.webp
├── sell-requests/{request_id}/{uuid}.webp
└── chat/{conversation_id}/{uuid}.webp
Fayl nomi — server generatsiya qiladi (uuid4), user nomi ishlatilmaydi
Cheklar yil/oy bo'yicha — purge worker uchun qulay
Egalik: chown comfort:www-data, ruxsat 640 (fayl), 750 (katalog)
Bu katalog to'g'ridan Nginx root bo'lmaydi — faqat /files/ orqali, imzo bilan
2. SCOPE VA USTUVORLIK
MVP (P0) — ~9 hafta

Auth (initData) · Rollar (OWNER/ADMIN/USER) · Katalog (product+variant+rasm+compatibility+qidiruv/filter) · Savat · Buyurtma (snapshot+rezervatsiya+TTL) · To'lov (karta→chek→review) · Stok (on_hand/reserved, atomic) · Admin panel · Bot notification · Audit log

v1.1 (P1) — +3 hafta

Favorites · Stok xabarnomasi · Sell-request · User↔Admin chat · Broadcast · Buyurtma tarixi · Dark/light mode

v1.2 (P2) — +2 hafta

OWNER moliyaviy hisobot · Top mahsulotlar · Admin faoliyati · Adminlarni boshqarish · Audit paneli

v2.0 (P3) — keyinroq

Refund lifecycle · Analytics events · Online to'lov · Yetkazib berish · Loyalty

Qoida: P1 ni P0 ga qo'shmaslik.

3. ROLLAR VA PERMISSION
Rol	Kim	Soni
OWNER	Do'kon egasi	Aniq 1 ta
ADMIN	Sotuvchi / ishchi	Ko'p
USER	Xaridor	Ko'p
Permission	OWNER	ADMIN	USER
catalog.view	✅	✅	✅
products.create / update / archive	✅	✅	—
inventory.manage	✅	✅	—
orders.view.all	✅	✅	—
orders.view.own	✅	✅	✅
orders.confirm / cancel	✅	✅	—
payments.review	✅	✅	—
receipts.view	✅	✅	faqat o'zi
sell_requests.review	✅	✅	—
chat.reply	✅	✅	—
broadcast.send	✅	✅	—
finance.view	✅	❌	—
analytics.view	✅	❌	—
admins.manage	✅	❌	—
audit.view	✅	❌	—
settings.manage	✅	❌	—

Majburiy: permission har API chaqiruvida serverda tekshiriladi. Frontendda tugmani yashirish — himoya emas.

Rollar roles + permissions + role_permissions jadvallari orqali — kodda hardcode qilinmaydi. Kelajakda SENIOR_ADMIN, OPERATOR qo'shish mumkin.

4. DOMAIN MODEL
IDENTITY      users, roles, permissions, role_permissions
CATALOG       products, product_variants, product_images, brands, colors
VEHICLE       car_brands, car_models, car_generations, product_compatibilities
PRICING       discounts, discount_targets
INVENTORY     inventory_movements
COMMERCE      carts, cart_items, orders, order_items, stock_reservations
PAYMENTS      payments, payment_receipts, refunds
ENGAGEMENT    favorites, stock_notifications
COMMUNICATION conversations, messages, notifications, broadcasts, broadcast_targets
MARKETPLACE   sell_requests, sell_request_images
SEARCH        search_aliases
SECURITY      audit_logs, idempotency_keys

~30 jadval. MVP da ~20 tasi (COMMUNICATION va MARKETPLACE keyinroq).

5. MA'LUMOT TIPLARI (majburiy standart)
5.1 Pul
sql
price BIGINT NOT NULL CHECK (price >= 0)   -- so'm
5.2 Vaqt
sql
created_at timestamptz NOT NULL DEFAULT now()   -- UTC

Server vaqt zonasi UTC (timedatectl set-timezone UTC). Ko'rsatishda va hisobotlarda Asia/Tashkent (UTC+5, DST yo'q).

5.3 Telefon
sql
phone text CHECK (phone ~ '^\+998[0-9]{9}$')
CREATE UNIQUE INDEX ON users (phone)
  WHERE phone IS NOT NULL AND deleted_at IS NULL;

Yozishdan oldin normalizatsiya: bo'shliq, -, (, ) olib tashlanadi.

5.4 Soft delete + UNIQUE
sql
-- ❌ soft-delete qilingan SKU yangi mahsulotni bloklaydi
CREATE UNIQUE INDEX ON product_variants (sku);

-- ✅
CREATE UNIQUE INDEX ON product_variants (sku) WHERE deleted_at IS NULL;
5.5 ID
users.telegram_id → BIGINT (32-bit dan oshadi)
Ichki PK → BIGSERIAL
Tashqi ko'rinadigan order raqami → qisqa random kod (CU-7F3K92), ketma-ket son emas
5.6 Status

text + CHECK (status IN (...)). Kodda va DB da bir xil ro'yxat.

6. KATALOG
6.1 Product

Nom, tavsif, brend, holat (DRAFT/ACTIVE/ARCHIVED), manba (OWN/CONSIGNMENT), search_text, timestamps.

6.2 Variant

SKU (unique, soft-delete hisobga olingan), rang, narx, boshlang'ich to'lov, stock_on_hand, stock_reserved, holat.

6.3 Rasmlar
Har product ga 1–5 ta
Diskda fayl, DB da metadata: storage_path, sort_order, is_primary, width, height, bytes
Har product da aniq 1 ta primary:
sql
CREATE UNIQUE INDEX ON product_images (product_id)
  WHERE is_primary AND deleted_at IS NULL;
6.4 Compatibility
car_brands → car_models → car_generations → product_compatibilities
sql
product_compatibilities (
  product_id    bigint NOT NULL,
  generation_id bigint NOT NULL,
  year_from     smallint,     -- NULL = generatsiya boshidan
  year_to       smallint,     -- NULL = oxirigacha
  note          text,         -- 'faqat sedan', 'lyuks komplektatsiya'
  CHECK (year_to IS NULL OR year_from IS NULL OR year_to >= year_from)
)
6.5 Qidiruv va filter

Qidiruv: product nomi, brend, mashina brend/model/generatsiya, SKU — ADR-8 bilan. Filter: mashina brend/model, product brend, narx oralig'i, mavjudlik, chegirma, rang. Sort: narx ↑↓, yangi, mashhur.

7. NARX VA CHEGIRMA
7.1 Model
sql
discounts (
  id, name,
  kind,          -- PERCENT | FIXED
  value,         -- 20 (%) yoki 100000 (so'm)
  starts_at, ends_at, is_active,
  priority smallint
)
discount_targets (discount_id, target_type, target_id)
  -- target_type: VARIANT | PRODUCT | BRAND | CAR_MODEL | ALL
7.2 Ustuvorlik
Aniqlik: VARIANT > PRODUCT > BRAND > CAR_MODEL > ALL
Bir darajada bir nechta bo'lsa — priority kattasi
Teng bo'lsa — foydalanuvchiga foydali (arzon)
Stacking yo'q — faqat bittasi qo'llanadi
Natija manfiy bo'lmaydi
7.3 Checkout da qayta tekshirish

Frontenddan kelgan narxga ishonilmaydi. Backend:

Variant ACTIVE mi?
available >= qty mi?
Amaldagi narxni qayta hisoblaydi
Chegirmani qayta qo'llaydi
Boshlang'ich to'lov talabini oladi
Snapshot yozadi

Narx farq qilsa → 409 Conflict + yangi narx, user tasdiqlaydi.

8. BUYURTMA VA TO'LOV
8.1 Lifecycle
CREATED
   ├─▶ AWAITING_PAYMENT ─▶ PAYMENT_SUBMITTED ─▶ UNDER_REVIEW
   │                                              ├─▶ CONFIRMED
   │                                              └─▶ REJECTED
   ├─▶ CANCELLED   (user yoki admin)
   └─▶ EXPIRED     (TTL, worker)

CONFIRMED ─▶ REFUND_PENDING ─▶ REFUNDED    (v2.0)

Ruxsat etilgan o'tishlar kodda aniq jadval. Boshqasi → 422.

8.2 Concurrency

Ikki admin bir vaqtda confirm bossa:

sql
BEGIN;
  SELECT status FROM orders WHERE id = :id FOR UPDATE;
  IF status <> 'UNDER_REVIEW' THEN
    RAISE EXCEPTION 'invalid_transition';
  END IF;
  UPDATE orders SET status = 'CONFIRMED', confirmed_at = now(), confirmed_by = :actor;
  UPDATE product_variants
     SET stock_on_hand = stock_on_hand - :qty,
         stock_reserved = stock_reserved - :qty
   WHERE id = :variant_id;
  INSERT INTO inventory_movements (...);
  INSERT INTO audit_logs (...);
COMMIT;

Ikkinchi admin xato oladi, UI da: "boshqa admin allaqachon tasdiqlagan".

8.3 To'lov (MVP)

Bank kartasiga qo'lda o'tkazma → chek rasmi → admin tekshiradi.

sql
payments (
  order_id, amount, method,   -- CARD_TRANSFER
  status,                      -- PENDING | APPROVED | REJECTED
  submitted_at, reviewed_at, reviewed_by, rejection_reason
)

APPROVED to'lov qayta PENDING ga qaytmaydi.

8.4 Bekor qilish

Admin bekor qilsa cancellation_reason majburiy (min 10 belgi).

9. STOK
sql
inventory_movements (
  variant_id, movement_type,   -- IN | OUT | RESERVE | RELEASE | ADJUST
  quantity_change,
  quantity_before, quantity_after,
  reason, reference_type, reference_id,
  actor_id, created_at
)

Append-only. Har o'zgarish yoziladi.

Qoidalar: stok faqat backend orqali · manfiy bo'lmaydi (CHECK) · parallel operatsiya FOR UPDATE bilan · qo'lda ADJUST sabab talab qiladi va audit ga tushadi.

10. QOLGAN MODULLAR

Favorites — UNIQUE (user_id, variant_id)

Stok xabarnomasi — UNIQUE (user_id, variant_id). Stok > 0 bo'lganda yuboriladi, keyin notified_at yoziladi.

Sell request — ADR-10. Rad etishda sabab majburiy.

Chat — conversations (user, tayinlangan admin, holat) + messages (sender, matn, attachment, o'qilgan holat). Admin o'zgarsa tarix saqlanadi.

Notification — ikki kanal: Telegram xabari + notifications jadvali (Mini App ichida). Bot bloklangan bo'lsa faqat ikkinchisi (ADR-12).

Broadcast — Telegram rate limit:

Maksimum 25 xabar/sekund (Telegram ~30, zaxira qoldiriladi)
429 → retry_after kutish, keyin exponential backoff (2s, 4s, 8s, max 60s)
403 → ADR-12, qayta urinilmaydi
broadcast_targets jadvali: har user uchun SENT/FAILED/BLOCKED
Qayta ishga tushsa faqat FAILED larga (idempotent)
11. FAYL OMBORI (Contabo diskda)
11.1 Kataloglar va TTL
Katalog	Signed URL TTL	Retention
products/	24 soat	Product arxivlanmaguncha
receipts/	15 daqiqa	Min 30 kun (ADR-9)
sell-requests/	1 soat	Ariza yopilgandan 90 kun
chat/	1 soat	180 kun

Hech qanday fayl imzosiz ochilmaydi (ADR-13).

11.2 Upload validatsiyasi
MIME:        image/jpeg, image/png, image/webp
Maksimum:    5 MB (kelgan), 1 MB (siqilgandan keyin)
Magic bytes: tekshiriladi (kengaytmaga ishonilmaydi)
Fayl nomi:   server uuid4 generatsiya qiladi
Executable:  bloklanadi

Nginx da ham cheklov: client_max_body_size 6M;

11.3 Rasm qayta ishlash (Pillow)
WebP ga o'girish, quality 85
Maksimum uzun tomon 1600px
Thumbnail 400px generatsiya qilinadi
EXIF metadata o'chiriladi (GPS koordinatalari sizib chiqmasin)
Katalogda thumbnail, detalda to'liq rasm (lazy load)
11.4 Disk budjeti (100 GB)
Element	Hisob	Hajm
OS + paketlar		~10 GB
PostgreSQL data (1 yil)		~2 GB
WAL arxiv (7 kun)		~3 GB
Product rasmlari	300 × 4 × 150 KB	~180 MB
Thumbnail lar	1200 × 25 KB	~30 MB
Cheklar (30 kun)	300/oy × 200 KB	~60 MB
Sell-request rasmlari	100 × 3 × 150 KB	~45 MB
Local backup (7 kun)		~2 GB
Loglar		~1 GB
Comfort UZB jami		~19 GB
Bo'sh		~81 GB

Boshqa loyihalar ham shu serverda bo'lsa (§16.4) — joy yetadi. Faqat video/media saqlaydigan loyiha bo'lsa ehtiyot bo'ling.

Monitoring: disk 80% dan oshsa bot OWNER ga xabar yuboradi.

12. XAVFSIZLIK
12.1 Ilova darajasi
Nazorat	Qanday
initData verification	HMAC-SHA256, auth_date < 24h (ADR-2)
Authorization	Har endpointda server-side permission
Input validation	Pydantic — barcha input
SQL injection	Faqat parametrlangan query (asyncpg / SQLAlchemy)
XSS	Frontendda textContent, innerHTML ishlatilmaydi
Fayl xavfsizligi	§11.2 + signed URL (ADR-13)
Rate limiting	§12.4
Secret management	.env (chmod 600), git da emas
12.2 RLS o'rniga Postgres role/GRANT ⭐ O'ZGARDI

RLS talabdan chiqarildi. Sabab: Supabase da RLS kerak edi, chunki Supabase internetga ochiq REST API beradi. Contabo da PostgreSQL faqat localhost da tinglaydi va faqat backend ulanadi — RLS ikki marta ish bo'ladi.

O'rniga least privilege role lar:

sql
-- Ilova roli — DDL yo'q, DROP yo'q
CREATE ROLE comfort_app LOGIN PASSWORD '...';
GRANT SELECT, INSERT, UPDATE ON ALL TABLES IN SCHEMA public TO comfort_app;
REVOKE DELETE ON ALL TABLES IN SCHEMA public FROM comfort_app;   -- soft delete ishlatiladi

-- Audit: faqat yozish va o'qish
REVOKE UPDATE, DELETE ON audit_logs FROM comfort_app;
GRANT INSERT, SELECT ON audit_logs TO comfort_app;

-- Migration roli — faqat Alembic ishlatadi
CREATE ROLE comfort_migrate LOGIN PASSWORD '...';
GRANT ALL ON SCHEMA public TO comfort_migrate;

-- Backup roli — faqat o'qish
CREATE ROLE comfort_backup LOGIN PASSWORD '...';
GRANT SELECT ON ALL TABLES IN SCHEMA public TO comfort_backup;

Ilova superuser yoki DB egasi bilan ulanmaydi. postgresql.conf:

listen_addresses = 'localhost'

pg_hba.conf — faqat local scram-sha-256, tashqi ulanish yo'q.

12.3 Audit log immutability
sql
CREATE FUNCTION prevent_audit_mutation() RETURNS trigger AS $$
BEGIN
  RAISE EXCEPTION 'audit_logs is append-only';
END $$ LANGUAGE plpgsql;

CREATE TRIGGER audit_no_mutation
  BEFORE UPDATE OR DELETE ON audit_logs
  FOR EACH ROW EXECUTE FUNCTION prevent_audit_mutation();

Yozuv: actor_id, actor_role, action, entity_type, entity_id, old_data (jsonb), new_data (jsonb), ip, created_at, metadata.

Kritik hodisalar: auth, admin qo'shish/o'chirish, product create/update, narx o'zgarishi, stok o'zgarishi, order confirm/cancel, payment approve/reject, chek yashirish, sell-request qarori, broadcast, permission o'zgarishi.

12.4 Rate limiting
Endpoint	Limit
Umumiy	60 so'rov/min / user
POST /orders	5/min
POST /payments	5/min
Fayl upload	10/min
Qidiruv	30/min
Admin confirm/cancel	60/min

Nginx darajasida ham: limit_req_zone $binary_remote_addr zone=api:10m rate=10r/s; Oshsa → 429 + Retry-After.

12.5 Server xavfsizligi ⭐ YANGI (avval Supabase zimmasida edi)
SSH:        faqat kalit (PasswordAuthentication no), root login yo'q
            port 22 → nostandart port (masalan 2222)
Firewall:   ufw — faqat SSH port, 80, 443. Boshqa hamma yopiq
            PostgreSQL 5432 tashqariga OCHILMAYDI
fail2ban:   SSH va Nginx uchun
Updates:    unattended-upgrades (security patch avtomatik)
User:       ilova `comfort` nomli non-root user ostida ishlaydi
HTTPS:      Certbot + auto-renew (Telegram Mini App uchun MAJBURIY)
Nginx:      server_tokens off; TLS 1.2+; HSTS header
Loglar:     logrotate, 14 kun

Boshlang'ich checklist:

[ ] root SSH o'chirilgan
[ ] SSH kalit o'rnatilgan, parol auth o'chirilgan
[ ] ufw yoqilgan va tekshirilgan
[ ] fail2ban ishlayapti
[ ] unattended-upgrades yoqilgan
[ ] Postgres localhost only
[ ] .env chmod 600, egasi comfort
[ ] HTTPS ishlayapti, auto-renew test qilingan
12.6 Test qilinishi shart bo'lgan holatlar
Parallel oxirgi stok xaridi (2 user, 1 dona) → faqat bittasi
Ikki admin bir vaqtda confirm → faqat bitta o'tish
User boshqa user orderini so'raydi → 403
ADMIN finance.view ga uradi → 403
Imzosiz /files/receipts/... → 403
Muddati o'tgan imzo → 410
Boshqa odamning chek imzosini so'rash → 403
Frontendda narx o'zgartirilgan → backend rad etadi
Manfiy miqdor / manfiy narx → 422
Dublikat Idempotency-Key → bir marta bajariladi
Deaktivlangan admin amal qiladi → 403
Buzilgan / eskirgan initData → 401
.php yoki executable upload → rad etiladi
Tashqaridan psql -h <server_ip> → ulanmaydi
13. BACKEND ARXITEKTURASI
13.1 Qatlamlar
Router (FastAPI)   — HTTP, validatsiya, auth
   ↓
Service            — biznes logika (YAGONA manba)
   ↓
Repository         — DB murojaatlari
   ↓
PostgreSQL (asyncpg pool, unix socket)

Bot ham, Mini App ham bir xil Service ni chaqiradi. Bot da biznes logika yozilmaydi.

13.2 Texnologiyalar
Python 3.12
FastAPI + uvicorn        — API
aiogram 3.x              — bot
asyncpg                  — DB (SQLAlchemy Core ixtiyoriy)
Alembic                  — migration
Pydantic v2              — validatsiya
Pillow                   — rasm
python-jose / hmac       — initData + signed URL
13.3 Connection pool ⭐ YANGI
python
pool = await asyncpg.create_pool(
    dsn="postgresql:///comfort_uzb?host=/var/run/postgresql",  # unix socket
    min_size=2, max_size=10,
    command_timeout=30,
)
Unix socket — TCP dan tez, tarmoq stack yo'q
postgresql.conf: max_connections = 100
Bir necha loyiha bir Postgres da bo'lsa — har biriga max 10, jami 100 dan oshmasin
PgBouncer faqat kerak bo'lsa (100+ parallel ulanish) — hozir kerak emas
13.4 API endpointlari
POST   /auth/session                initData → session

GET    /catalog/products            filter, sort, pagination
GET    /catalog/products/{id}
GET    /catalog/search              ?q=
GET    /catalog/filters
GET    /vehicles/brands|models|generations

GET    /cart
POST   /cart/items
PATCH  /cart/items/{id}
DELETE /cart/items/{id}

POST   /orders                      [Idempotency-Key]
GET    /orders
GET    /orders/{id}
POST   /orders/{id}/cancel

POST   /payments                    [Idempotency-Key]
POST   /payments/{id}/receipt       multipart
GET    /files/{path}?s=&e=          → Nginx (backend tegmaydi)

GET    /favorites
POST   /favorites/{variant_id}
DELETE /favorites/{variant_id}
POST   /stock-notifications/{variant_id}

POST   /sell-requests
GET    /sell-requests

GET    /conversations/me
POST   /conversations/me/messages
GET    /notifications

--- ADMIN ---
GET    /admin/orders
POST   /admin/orders/{id}/confirm   [Idempotency-Key]
POST   /admin/orders/{id}/cancel    [Idempotency-Key] + reason
POST   /admin/payments/{id}/review  approve|reject + reason
GET    /admin/payments/{id}/receipt → signed URL qaytaradi
CRUD   /admin/products, /admin/variants, /admin/images
POST   /admin/inventory/adjust      + reason
GET    /admin/sell-requests
POST   /admin/sell-requests/{id}/review
POST   /admin/sell-requests/{id}/convert
GET    /admin/conversations
POST   /admin/conversations/{id}/messages
POST   /admin/broadcasts            [Idempotency-Key]

--- OWNER ---
GET    /owner/dashboard
GET    /owner/finance               ?from=&to=
GET    /owner/analytics
CRUD   /owner/admins
GET    /owner/audit-logs
GET/PUT /owner/settings

--- OPS ---
GET    /health                      DB + disk + worker holati
13.5 Xato formati
json
{
  "error": {
    "code": "INSUFFICIENT_STOCK",
    "message": "Bu mahsulotdan 2 ta qoldi",
    "details": { "available": 2, "requested": 5 }
  }
}

Userga o'zbek tilida tushunarli matn. Texnik detal server logida.

14. FRONTEND
14.1 Ekranlar

USER: Home · Katalog · Qidiruv · Filter · Product detali · Yoqtirilganlar · Savat · Checkout · To'lov · Chek yuklash · Buyurtmalar tarixi · Buyurtma detali · Sidena sotish · Chat · Profil · Bildirishnomalar · Sozlamalar

ADMIN: Dashboard · Buyurtmalar · Buyurtma detali · To'lovlar · Mahsulotlar · Product yaratish/tahrirlash · Stok · Sotish arizalari · Chatlar · Broadcast

OWNER: yuqoridagi + Moliya · Analytics · Adminlar · Audit loglar · Sozlamalar

14.2 Talablar
Mobile-first, 375px dan
Telegram themeParams va colorScheme ga moslashish
safe-area-inset hisobga olinadi
localStorage ishlatilmaydi — Telegram WebView da ishonchsiz. CloudStorage API yoki server
Rasm lazy loading + skeleton
Rasm URL lari signed — muddati o'tsa qayta so'raladi (ADR-13 TTL ni hisobga olib)
14.3 Rasm yuklash (galereyadan)
html
<input type="file" accept="image/*" multiple>

Telegram WebView da galereya ochiladi. Yuborishdan oldin frontendda siqiladi (canvas, max 1600px, WebP, quality 0.85) — serverga kichik fayl boradi, mobil internetda tez.

14.4 Joylashuv

Static fayllar Nginx dan beriladi (/var/comfort/web/), oldida Cloudflare proxy (bepul CDN + cache). Alohida deploy joyi kerak emas.

nginx
location / {
    root /var/comfort/web;
    try_files $uri $uri/ /index.html;
    add_header Cache-Control "public, max-age=31536000, immutable";   # hashed assets
}
15. WORKER LAR (systemd timer) ⭐ YANGI

Supabase da bu qism yo'q edi. Endi kerak:

Worker	Davriylik	Vazifa
comfort-reservation-expiry	5 daqiqada	TTL o'tgan rezervatsiyani bo'shatish, order → EXPIRED
comfort-receipt-purge	Kunda 04:00	retention_until o'tgan chek faylini o'chirish, metadata qoladi
comfort-broadcast	Doimiy (queue)	§10 rate limit bilan yuborish
comfort-idempotency-cleanup	Kunda 04:30	24 soatdan oshgan kalitlarni o'chirish
comfort-backup	Kunda 03:00	pg_dump + tashqi joyga (§17.3)
comfort-health	10 daqiqada	Disk/RAM/DB tekshiruvi, 80% dan oshsa OWNER ga Telegram xabari

Har biri alohida systemd service + timer. Restart=on-failure.

Muhim: bitta worker ikki nusxada ishlamasligi kerak → flock yoki Postgres advisory lock.

16. SERVER KONFIGURATSIYASI (Contabo)
16.1 Server
4 vCPU · 8 GB RAM · 100 GB SSD/NVMe
Ubuntu 24.04 LTS
1 snapshot (Contabo panelida)

Lokatsiya: checkout paytida Contabo real latency ko'rsatadi — EU Hub, Hindiston, Singapur uchtasini solishtirib, eng kichigini tanlang. O'zbekistondan trafik ko'pincha Yevropa orqali o'tadi, shuning uchun EU Hub ehtimol eng tez (ustiga qo'shimcha to'lov ham yo'q).

Disk: imkon bo'lsa NVMe — Postgres uchun sezilarli tezroq.

16.2 Resurs taqsimoti
Xizmat	RAM
OS	~0.5 GB
PostgreSQL	~2.5 GB
FastAPI (2 worker)	~0.7 GB
Bot	~0.3 GB
Worker lar	~0.3 GB
Nginx	~0.1 GB
Comfort UZB jami	~4.4 GB
Bo'sh (boshqa loyihalar uchun)	~3.6 GB
16.3 PostgreSQL tuning (8 GB RAM)
conf
shared_buffers = 2GB
effective_cache_size = 5GB
work_mem = 16MB
maintenance_work_mem = 512MB
max_connections = 100
random_page_cost = 1.1              # SSD/NVMe
effective_io_concurrency = 200      # NVMe
wal_level = replica
archive_mode = on                   # PITR uchun
archive_command = '...'             # §17.3
listen_addresses = 'localhost'
16.4 Bir necha loyiha bir serverda

Boshqa loyihalaringiz ham shu serverda bo'lsa:

PostgreSQL (bitta instansiya)
├── comfort_uzb        role: comfort_app
├── loyiha_2           role: loyiha2_app      ← har biri o'z DB va role
└── loyiha_3           role: loyiha3_app         boshqa DB ni ko'rmaydi

Nginx — subdomain bo'yicha
├── comfort.domen.uz  → 127.0.0.1:8001
├── loyiha2.domen.uz  → 127.0.0.1:8002
└── loyiha3.domen.uz  → 127.0.0.1:8003

systemd — har loyiha alohida service

Muhim: har loyihaga alohida DB va alohida role. REVOKE CONNECT ON DATABASE comfort_uzb FROM PUBLIC; — boshqa loyiha buzilsa Comfort UZB ma'lumoti tegilmaydi.

Connection budjeti: max_connections = 100, har loyiha max_size=10 → 10 loyihaga yetadi.

17. DEPLOYMENT
17.1 Muhitlar
Muhit	Qanday
Development	Local kompyuter, alohida DB, test bot (alohida token)
Production	Contabo, real bot, real DB

Ikkisi hech qachon bir DB ni ishlatmaydi. Dev da products jadvalini o'chirish production ga ta'sir qilmasligi kerak.

17.2 Stack
Cloudflare (DNS + proxy + CDN, bepul)
      ↓
Contabo VPS
├── Nginx          — HTTPS, static, /files/ signed, reverse proxy
├── FastAPI        — 127.0.0.1:8001 (uvicorn, systemd)
├── aiogram bot    — webhook, systemd
├── Worker lar     — systemd timer (§15)
├── PostgreSQL 16  — localhost only
└── /var/comfort/  — uploads, web, backup

Domen kerak. Telegram Mini App yaroqli HTTPS sertifikat talab qiladi — self-signed ishlamaydi.

17.3 Backup ⭐ ENG MUHIM O'ZGARISH

Supabase o'zi qilardi. Endi sizning zimmangizda. Bu tanlov emas — majburiyat.

Uch qatlam:

Qatlam	Nima	Davriylik	Nima uchun
1. pg_dump	Mantiqiy backup, gzip	Kunda 03:00	Jadval/ma'lumot tiklash
2. WAL arxiv	Continuous archiving	Doimiy (5 daq)	PITR — istalgan daqiqaga qaytish
3. Snapshot	Butun server	Qo'lda, xavfli ishdan oldin	OS/paket buzilsa
bash
# /etc/comfort/backup.sh  — kunda 03:00
set -euo pipefail
DATE=$(date +%F)
pg_dump -U comfort_backup comfort_uzb | gzip > /var/comfort/backup/db-$DATE.sql.gz
tar czf /var/comfort/backup/files-$DATE.tar.gz /var/comfort/uploads
rclone copy /var/comfort/backup/ r2:comfort-backup/   # Cloudflare R2 (10 GB bepul)
find /var/comfort/backup -mtime +7 -delete            # local 7 kun

Maqsadlar:

	v2.0 (Supabase free)	v3.0 (Contabo)
RPO (yo'qolish)	24 soat	5 daqiqa (WAL bilan)
RTO (tiklash)	4 soat	2 soat

⚠️ Sinovdan o'tmagan backup — backup emas. Har oyda bir marta boshqa joyga tiklab, ishlashini tekshirish majburiy. Kalendarga qo'ying.

⚠️ Snapshot backup emas: faqat 1 ta (yangi olganda eskisi o'chadi), bir xil infratuzilmada turadi, va 2 hafta oldin buzilgan ma'lumotni tutmaydi.

17.4 Migration

Barcha DB o'zgarishi Alembic orqali, versiyalangan. Serverga psql bilan qo'lda kirib ALTER TABLE qilish taqiqlanadi — dev va prod bir-biridan uzoqlashadi.

bash
alembic revision -m "add stock_reserved"
alembic upgrade head      # deploy paytida
17.5 Deploy oqimi
git push  →  serverda git pull
          →  pip install -r requirements.txt
          →  alembic upgrade head
          →  systemctl restart comfort-api comfort-bot
          →  /health tekshirish

Deploy dan oldin: pg_dump va (katta o'zgarish bo'lsa) snapshot.

17.6 Monitoring
Nima	Qanday
Service o'chsa	systemd Restart=on-failure
Server o'chsa	Tashqi ping (healthchecks.io — bepul), 10 daqiqada
Disk 80%+	comfort-health worker → OWNER ga Telegram
Xatolar	Sentry (bepul tier) yoki ERROR log → Telegram
Loglar	journald + logrotate, 14 kun
17.7 Ishga tushirish checklisti
[ ] Domen + Cloudflare DNS
[ ] §12.5 server xavfsizlik checklisti to'liq
[ ] HTTPS (Certbot) + auto-renew test qilingan
[ ] PostgreSQL localhost only, role lar yaratilgan
[ ] Alembic migration lar bajarildi
[ ] OWNER seed qilindi (OWNER_TELEGRAM_ID)
[ ] /var/comfort/uploads ruxsatlari to'g'ri
[ ] Nginx secure_link ishlayapti (imzosiz → 403)
[ ] Telegram webhook o'rnatildi
[ ] Menu button URL
[ ] Barcha systemd service va timer yoqilgan
[ ] Backup cron ishlayapti VA tiklash sinovdan o'tdi
[ ] WAL arxivlash ishlayapti
[ ] Tashqi uptime monitoring
[ ] Rate limiting yoqilgan
[ ] §12.6 dagi 14 ta xavfsizlik testi o'tdi
18. PERFORMANCE MAQSADLARI
Metrika	Maqsad
Mini App birinchi ko'rinish (4G)	< 2.0 s
Katalog (20 mahsulot) API p95	< 150 ms (bir serverda — Supabase da 300ms edi)
Qidiruv p95	< 200 ms
Product detali p95	< 120 ms
Order yaratish p95	< 300 ms
Signed fayl berish	< 50 ms (Nginx to'g'ridan)
Thumbnail	< 30 KB
Birinchi yuklash jami	< 400 KB
18.1 Pagination

Products · Orders · Messages · Notifications · Users · Audit · Sell requests — majburiy. Default limit=20, max 100. Cursor-based (keyset) — OFFSET katta sahifalarda sekin.

18.2 Index lar
sql
-- Identity
CREATE UNIQUE INDEX ON users (telegram_id);
CREATE INDEX ON users (role) WHERE deleted_at IS NULL;

-- Catalog
CREATE INDEX ON products (status) WHERE deleted_at IS NULL;
CREATE INDEX ON products USING gin (search_text gin_trgm_ops);
CREATE UNIQUE INDEX ON product_variants (sku) WHERE deleted_at IS NULL;
CREATE INDEX ON product_variants (product_id, status);
CREATE INDEX ON product_variants (price);
CREATE UNIQUE INDEX ON product_images (product_id) WHERE is_primary AND deleted_at IS NULL;

-- Vehicle
CREATE INDEX ON product_compatibilities (generation_id);
CREATE INDEX ON product_compatibilities (product_id);

-- Commerce
CREATE INDEX ON orders (user_id, created_at DESC);
CREATE INDEX ON orders (status, created_at DESC);
CREATE INDEX ON order_items (order_id);
CREATE INDEX ON stock_reservations (expires_at) WHERE released_at IS NULL;

-- Payments
CREATE INDEX ON payments (order_id);
CREATE INDEX ON payments (status, submitted_at DESC);
CREATE INDEX ON payment_receipts (retention_until) WHERE file_purged_at IS NULL;

-- Communication
CREATE INDEX ON messages (conversation_id, created_at DESC);
CREATE INDEX ON notifications (user_id, read_at, created_at DESC);
CREATE INDEX ON broadcast_targets (broadcast_id, status);

-- Security
CREATE INDEX ON audit_logs (actor_id, created_at DESC);
CREATE INDEX ON audit_logs (entity_type, entity_id, created_at DESC);
19. TESTING
Tur	Nima
Unit	Narx hisobi, chegirma ustuvorligi, status o'tishlari, normalizatsiya, signed URL imzosi
Integration	Order flow, to'lov flow, stok harakati, transaction
Security	§12.6 dagi 14 holat
E2E	User → savat → order → to'lov → admin → tasdiq → stok kamaydi
Load	50 parallel user katalog + 10 parallel checkout
Restore	Backup dan boshqa joyga tiklash — oyda 1 marta

Minimal talab: §12.6 dagi 14 holat, E2E flow va restore testi avtomatlashtirilgan yoki hujjatlashtirilgan bo'lishi kerak.

20. BIZNES QOIDALARI
Stok manfiy bo'lmaydi
available = on_hand − reserved, manfiy emas
CONFIRMED order oddiy UPDATE bilan o'zgartirilmaydi
APPROVED to'lov qayta PENDING ga qaytmaydi
Chek metadata hech qachon o'chirilmaydi (fayl o'chirilishi mumkin)
ADMIN moliyaviy ma'lumotni ko'rmaydi
USER boshqa USER buyurtmasini ko'rmaydi
OWNER aniq bitta
Bekor qilishda sabab majburiy
Narx/stok/chegirma faqat serverda hisoblanadi
Audit log append-only
Rezervatsiya 24 soatdan ko'p turmaydi
Bir user bir variantni bir marta favorite qiladi
Har product da aniq bitta primary rasm
Hech qanday fayl imzosiz ochilmaydi
21. SOFT DELETE VA RETENTION
Ma'lumot	Siyosat
Products	ARCHIVED holat, hard delete yo'q
Users / Admins	deleted_at, hard delete yo'q
Orders / Payments	Hech qachon o'chirilmaydi
Audit logs	Hech qachon o'chirilmaydi (12 oydan keyin arxiv jadvaliga)
Chek metadata	Hech qachon o'chirilmaydi
Chek fayli	Min 30 kun, keyin purge
Messages	180 kun
Idempotency keys	24 soat
WAL arxiv	7 kun
Local backup	7 kun (tashqi joyda 30 kun)
22. RIVOJLANISH BOSQICHLARI
#	Ish	Muddat
0	Server setup (§12.5 + §16 + §17)	3 kun
1	TZ (bu hujjat) + to'liq DB sxemasi	✅
2	Alembic migration lar + seed + role lar	1 hafta
3	Backend: auth, catalog, cart	1.5 hafta
4	Backend: order, payment, stock, signed URL	1.5 hafta
5	Worker lar + backup	0.5 hafta
6	Mini App: user ekranlari	2 hafta
7	Admin panel	1 hafta
8	Bot: notification lar	0.5 hafta
9	Xavfsizlik + test	1 hafta
10	Production deploy	0.5 hafta
MVP jami		~10 hafta
11	v1.1	+3 hafta
12	v1.2	+2 hafta
23. YAKUNIY PRINSIPLAR
Server — haqiqat manbai. Frontend hech narsani hal qilmaydi
Xavfsizlik birinchi — permission har chaqiruvda serverda
DB integrity majburiy — constraint lar kodga ishonmaydi
Kritik amallar audit qilinadi, audit o'zgartirilmaydi
Tarixiy buyurtmalar buzilmaydi — snapshot
Stok izchil — transaction va lock
Pul hech qachon float emas
Telegram identity serverda tasdiqlanadi
Hech qanday fayl imzosiz ochilmaydi
Backup — infratuzilmaning bir qismi, keyingi ish emas
Modulli va o'sishga tayyor — rollar hardcode emas
MVP birinchi. Ishlamayotgan mukammal arxitektura — nol qiymat
24. TUGALLANGANLIK MEZONI

MVP production-ready, agar:

 initData verification ishlaydi, user_id ga ishonilmaydi
 Uch rol server-side ajratilgan, ADMIN moliyaga kirmaydi
 Katalog, qidiruv (kirill/lotin), filter ishlaydi
 Savat → order → snapshot to'g'ri
 Rezervatsiya + TTL ishlaydi, stok qotib qolmaydi
 Chek yuklanadi, faqat imzolangan URL bilan ochiladi
 Admin tasdiqlaydi → stok atomik kamayadi
 Parallel confirm testi o'tadi
 Audit log yoziladi va o'zgartirilmaydi
 Bot notification lari boradi, bloklangan user crash qilmaydi
 §12.6 dagi 14 ta xavfsizlik testi o'tadi
 Backup ishlaydi VA boshqa joyga tiklash sinovidan o'tdi
 Barcha worker lar ishlayapti
 Tashqi uptime monitoring xabar beradi
 Mobil UX real telefonda tekshirilgan
25. KEYINGI HUJJATLAR
Server Setup Runbook — Contabo dan boshlab: user, SSH, ufw, fail2ban, Postgres, Nginx, Certbot, systemd, backup (skript bilan)
Complete PostgreSQL Schema — to'liq DDL, constraint, index, role/GRANT
Backend API Specification — har endpoint: request/response/xato
Bot Specification — handler lar, FSM, xabar matnlari
Mini App UI/UX Spec — ekran-ekran
Deployment & Backup Runbook — deploy, rollback, restore protsedurasi

Bu hujjat COMFORT UZB loyihasining Single Source of Truth. v3.0: Supabase → self-hosted Contabo VPS. RLS talabi olib tashlandi (§12.2), signed URL o'z qo'limizga o'tdi (ADR-13), worker lar qo'shildi (§15), server xavfsizligi qo'shildi (§12.5), backup to'liq bizning zimmamizga o'tdi (§17.3). Promo kodlar olib tashlandi. Kod bilan TZ farq qilsa — TZ yangilanadi, keyin kod.