#!/usr/bin/env bash
# COMFORT UZB — lokal dev muhitini bir buyruq bilan ko'tarish.
#
# NEGA BU KERAK: ilova `.env` faylini o'qimaydi — `app/config.py` va
# `bot/config.py` faqat `os.environ` dan o'qiydi (`python-dotenv` yo'q).
# Shuning uchun sirlarni shell darajasida yuklash kerak. Bu skript
# `backend/.env.local` ni yuklaydi va tartibni to'g'ri saqlaydi.
#
# TARTIB MUHIM: Telegram `localhost` ni ko'rmaydi, shuning uchun avval
# HTTPS tunnel ko'tariladi, uning URL i bilan backend ishga tushadi
# (`MINIAPP_URL` — bot Menu Button manzili), va oxirida webhook
# ro'yxatdan o'tkaziladi. Kodda hech narsa `setWebhook` chaqirmaydi —
# webhooksiz `/start` javob bermaydi.
#
#   bash scripts/dev.sh up       — hammasini ko'taradi
#   bash scripts/dev.sh down     — to'xtatadi, webhookni o'chiradi
#   bash scripts/dev.sh status   — nima ishlayotganini ko'rsatadi
#   bash scripts/dev.sh urls     — ochiladigan manzillar
#   bash scripts/dev.sh seed     — demo katalogni to'ldiradi
#
# Token hech qachon terminalga yoki logga chiqarilmaydi.
set -uo pipefail

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BACKEND="$REPO/backend"
MINIAPP="$REPO/miniapp"
ENV_FILE="$BACKEND/.env.local"
STATE="$REPO/.dev-state"
API_PORT="${API_PORT:-8000}"
WEB_PORT="${WEB_PORT:-5173}"
CLOUDFLARED="${CLOUDFLARED:-$HOME/.local/bin/cloudflared}"

mkdir -p "$STATE"

say()  { printf '%s\n' "$*"; }
fail() { printf '\n  XATO: %s\n\n' "$*" >&2; exit 1; }

load_env() {
    [ -f "$ENV_FILE" ] || fail "$ENV_FILE topilmadi. Namuna: backend/.env.example"
    set -a
    # shellcheck disable=SC1090
    source "$ENV_FILE"
    set +a
    [ -n "${BOT_TOKEN:-}" ] || fail "BOT_TOKEN .env.local da yo'q"
    case "$BOT_TOKEN" in
        CHANGE_ME*) fail "BOT_TOKEN hali placeholder. @BotFather dan real token olib, $ENV_FILE ga yozing" ;;
    esac
    [ -n "${DATABASE_URL:-}" ] || fail "DATABASE_URL .env.local da yo'q"
    export UPLOADS_ROOT="${UPLOADS_ROOT:-$HOME/.local/share/comfort-uploads}"
    mkdir -p "$UPLOADS_ROOT"
}

port_busy() { (echo >"/dev/tcp/127.0.0.1/$1") >/dev/null 2>&1; }

wait_for() {  # wait_for <url> <soniya>
    local url="$1" limit="${2:-30}" i=0
    while [ "$i" -lt "$limit" ]; do
        curl -sf -m 2 "$url" >/dev/null 2>&1 && return 0
        sleep 1; i=$((i + 1))
    done
    return 1
}

tg_api() {  # tg_api <method> [curl args...] — token hech qayerda ko'rinmaydi
    local method="$1"; shift
    curl -s -m 20 "https://api.telegram.org/bot${BOT_TOKEN}/${method}" "$@"
}

cmd_up() {
    load_env

    for p in "$API_PORT" "$WEB_PORT"; do
        port_busy "$p" && fail "$p porti band. Avval: bash scripts/dev.sh down (yoki API_PORT=8010 bilan qayta urinib ko'ring)"
    done
    [ -x "$CLOUDFLARED" ] || fail "cloudflared topilmadi: $CLOUDFLARED"

    say "==> [1/5] HTTPS tunnel"
    : > "$STATE/cloudflared.log"
    nohup "$CLOUDFLARED" tunnel --url "http://127.0.0.1:$WEB_PORT" \
        > "$STATE/cloudflared.log" 2>&1 < /dev/null &
    echo $! > "$STATE/cloudflared.pid"
    disown

    local url="" i=0
    while [ "$i" -lt 45 ]; do
        url=$(grep -oE "https://[a-z0-9-]+\.trycloudflare\.com" "$STATE/cloudflared.log" 2>/dev/null | head -1)
        [ -n "$url" ] && break
        sleep 1; i=$((i + 1))
    done
    [ -n "$url" ] || { cmd_down >/dev/null 2>&1; fail "tunnel ko'tarilmadi — $STATE/cloudflared.log ga qarang"; }
    echo "$url" > "$STATE/tunnel_url"
    say "    $url"

    say "==> [2/5] backend (:$API_PORT)"
    cd "$BACKEND"
    MINIAPP_URL="$url/" nohup .venv/bin/uvicorn app.main:app \
        --host 127.0.0.1 --port "$API_PORT" > "$STATE/api.log" 2>&1 < /dev/null &
    echo $! > "$STATE/api.pid"
    disown
    cd "$REPO"
    if ! wait_for "http://127.0.0.1:$API_PORT/health/ready" 40; then
        say "    backend ko'tarilmadi — oxirgi satrlar:"
        tail -5 "$STATE/api.log" | sed 's/^/      /'
        cmd_down >/dev/null 2>&1
        fail "backend tayyor bo'lmadi"
    fi
    say "    $(curl -s "http://127.0.0.1:$API_PORT/health/ready")"

    # configure_bot() Menu Button ni o'rnatadi. Token noto'g'ri bo'lsa
    # ilova bu xatoni yutib yuboradi va jimgina davom etadi — aynan shu
    # "bot ochilyapti, lekin hech narsa yo'q" holatini keltirib chiqaradi.
    if grep -q "configure_bot failed" "$STATE/api.log" 2>/dev/null; then
        say ""
        say "    DIQQAT: Telegram tokenni rad etdi — Menu Button o'rnatilmadi."
        say "    Mini App ham ochilmaydi. $ENV_FILE dagi BOT_TOKEN ni tekshiring."
        say ""
    else
        say "    Menu Button tunnel manziliga o'rnatildi"
    fi

    say "==> [3/5] Mini App (:$WEB_PORT)"
    cd "$MINIAPP"
    COMFORT_UPLOADS_ROOT="$UPLOADS_ROOT" VITE_PROXY_TARGET="http://127.0.0.1:$API_PORT" \
        nohup npx vite --port "$WEB_PORT" --host 127.0.0.1 \
        > "$STATE/vite.log" 2>&1 < /dev/null &
    echo $! > "$STATE/vite.pid"
    disown
    cd "$REPO"
    wait_for "http://127.0.0.1:$WEB_PORT/" 40 || say "    (vite hali javob bermayapti — $STATE/vite.log)"

    say "==> [4/5] Telegram webhook"
    local ok
    ok=$(tg_api setWebhook -d "url=${url}/telegram/webhook" \
                           -d "secret_token=${TELEGRAM_WEBHOOK_SECRET:-}" \
         | python3 -c "import json,sys;d=json.load(sys.stdin);print('ha' if d.get('ok') else 'xato: '+str(d.get('description','')))" 2>/dev/null)
    say "    ro'yxatdan o'tdi: ${ok:-noaniq}"

    say "==> [5/5] tayyor"
    say ""
    cmd_urls
}

cmd_down() {
    [ -f "$ENV_FILE" ] && { set -a; source "$ENV_FILE"; set +a; }
    if [ -n "${BOT_TOKEN:-}" ] && [ "${BOT_TOKEN#CHANGE_ME}" = "$BOT_TOKEN" ]; then
        say "==> webhook o'chirilmoqda"
        tg_api deleteWebhook >/dev/null 2>&1 && say "    o'chirildi"
    fi
    for name in vite api cloudflared; do
        local pidfile="$STATE/$name.pid"
        if [ -f "$pidfile" ]; then
            local pid; pid=$(cat "$pidfile")
            if kill "$pid" 2>/dev/null; then say "    to'xtatildi: $name"; fi
            rm -f "$pidfile"
        fi
    done
    # npx vite o'z bolasini qoldiradi — uni ham to'xtatamiz
    pkill -f "node.*vite --port $WEB_PORT" 2>/dev/null
    pkill -f "uvicorn app.main:app --host 127.0.0.1 --port $API_PORT" 2>/dev/null
    pkill -f "cloudflared tunnel --url http://127.0.0.1:$WEB_PORT" 2>/dev/null
    rm -f "$STATE/tunnel_url"
    say "==> to'xtatildi. Baza va demo ma'lumot tegilmadi."
}

cmd_status() {
    local url; url=$(cat "$STATE/tunnel_url" 2>/dev/null || echo "-")
    say "tunnel   : $url"
    port_busy "$API_PORT" && say "backend  : :$API_PORT ishlayapti — $(curl -s -m 2 "http://127.0.0.1:$API_PORT/health/ready" || echo '?')" \
                          || say "backend  : o'chiq"
    port_busy "$WEB_PORT" && say "mini app : :$WEB_PORT ishlayapti" || say "mini app : o'chiq"
}

cmd_urls() {
    local url; url=$(cat "$STATE/tunnel_url" 2>/dev/null || echo "")
    say "Telegramda ochish:"
    say "  @comfort_uzbBot  →  Menu Button (yoki /start)"
    say ""
    say "Brauzerda:"
    say "  Mini App (lokal)   http://127.0.0.1:$WEB_PORT"
    say "  API hujjatlari     http://127.0.0.1:$API_PORT/docs"
    say "  Katalog JSON       http://127.0.0.1:$API_PORT/catalog/products?limit=6"
    [ -n "$url" ] && say "  Tunnel (public)    $url"
    say ""
    say "To'xtatish: bash scripts/dev.sh down"
}

cmd_seed() {
    load_env
    ( cd "$BACKEND" && .venv/bin/python scripts/seed_demo.py )
}

case "${1:-up}" in
    up)     cmd_up ;;
    down)   cmd_down ;;
    status) cmd_status ;;
    urls)   cmd_urls ;;
    seed)   cmd_seed ;;
    *)      say "ishlatish: bash scripts/dev.sh {up|down|status|urls|seed}"; exit 1 ;;
esac
