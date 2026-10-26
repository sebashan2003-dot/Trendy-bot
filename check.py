#!/usr/bin/env python3
"""
Rastreador del Calendario de Adviento Trendy.

Cada ejecución:
  1. Consulta el catálogo público (API VTEX) de la tienda oficial de Trendy y de Novaventa.
  2. Compara con la última revisión guardada en state.json.
  3. Si hay cambios (producto nuevo, stock, precio, descuento, descripción), avisa por Telegram.
  4. Regenera la página docs/index.html con el estado actual y el historial.

Solo usa la librería estándar de Python (no hay que instalar nada).
Variables de entorno:
  TELEGRAM_TOKEN     token del bot (de @BotFather)
  TELEGRAM_CHAT_IDS  uno o varios chat_id separados por comas
  PAGE_URL           (opcional) enlace a la página, se incluye en los avisos
  DRY_RUN=1          (opcional) no envía mensajes, solo los imprime
  MOCK_DIR           (opcional, para pruebas) carpeta con respuestas JSON simuladas
"""

import html
import json
import os
import re
import sys
import time
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone

BOGOTA = timezone(timedelta(hours=-5))
ROOT = os.path.dirname(os.path.abspath(__file__))
STATE_FILE = os.path.join(ROOT, "state.json")
PAGE_FILE = os.path.join(ROOT, "docs", "index.html")
MAX_HISTORY = 200
FAIL_ALERT_AFTER = 4  # avisa si una tienda falla este número de veces seguidas

STORES = [
    {
        "id": "trendy",
        "name": "Trendy (tienda oficial)",
        "base": "https://www.maquillajetrendyshop.com",
        "terms": ["calendario adviento", "calendario", "adviento"],
        "must_match_brand": False,
    },
    {
        "id": "novaventa",
        "name": "Novaventa",
        "base": "https://novaventa.com",
        "terms": ["calendario adviento trendy", "trendy landia", "calendario trendy"],
        "must_match_brand": True,  # Novaventa vende calendarios de otras marcas
    },
]

KEYWORDS = re.compile(r"calendario|adviento", re.I)
UA = ("Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/124.0 Safari/537.36")


# --------------------------------------------------------------------------- red

def http_get_json(url):
    mock = os.environ.get("MOCK_DIR")
    if mock:
        key = re.sub(r"[^a-z0-9]+", "_", url.lower())[-120:]
        path = os.path.join(mock, key + ".json")
        if not os.path.exists(path):
            raise RuntimeError(f"sin mock para {url}")
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "application/json"})
    last = None
    for attempt in range(3):
        try:
            with urllib.request.urlopen(req, timeout=30) as r:
                return json.loads(r.read().decode("utf-8"))
        except Exception as e:  # noqa: BLE001
            last = e
            time.sleep(3 * (attempt + 1))
    raise RuntimeError(f"{url}: {last}")


def search_urls(base, term):
    q = urllib.parse.quote(term)
    return [
        # API clásica de catálogo VTEX
        f"{base}/api/catalog_system/pub/products/search?ft={q}&_from=0&_to=49",
        # Intelligent Search de VTEX (respaldo)
        f"{base}/api/io/_v/api/intelligent-search/product_search/?query={q}&count=50",
    ]


# ------------------------------------------------------------------ normalización

def clean_text(s):
    s = re.sub(r"<[^>]+>", " ", s or "")
    return re.sub(r"\s+", " ", html.unescape(s)).strip()


def to_price(v):
    try:
        v = float(v)
        return int(round(v)) if v > 0 else None
    except (TypeError, ValueError):
        return None


def normalize(raw, store):
    """Convierte un producto VTEX en un dict simple. Devuelve None si no es un calendario."""
    name = raw.get("productName") or raw.get("productTitle") or ""
    brand = raw.get("brand") or ""
    if not KEYWORDS.search(name):
        return None
    if store["must_match_brand"] and not re.search(r"trendy", name + " " + brand, re.I):
        return None

    link = raw.get("link") or ""
    if link.startswith("/"):
        link = store["base"] + link
    if not link and raw.get("linkText"):
        link = f"{store['base']}/{raw['linkText']}/p"

    prices, list_prices, qty, available = [], [], 0, False
    for item in raw.get("items") or []:
        for seller in item.get("sellers") or []:
            offer = seller.get("commertialOffer") or seller.get("commercialOffer") or {}
            p, lp = to_price(offer.get("Price")), to_price(offer.get("ListPrice"))
            q = offer.get("AvailableQuantity") or 0
            if p:
                prices.append(p)
            if lp:
                list_prices.append(lp)
            try:
                qty += int(q)
            except (TypeError, ValueError):
                pass
            if offer.get("IsAvailable") or (q and q > 0):
                available = True

    image = ""
    try:
        image = raw["items"][0]["images"][0]["imageUrl"]
    except (KeyError, IndexError, TypeError):
        pass

    price = min(prices) if prices else None
    list_price = max(list_prices) if list_prices else None
    return {
        "key": f"{store['id']}:{raw.get('productId') or link or name}",
        "store": store["name"],
        "name": name.strip(),
        "link": link,
        "image": image,
        "price": price,
        "list_price": list_price if (list_price and price and list_price > price) else None,
        "available": available,
        "qty": qty if qty < 99999 else None,  # VTEX a veces devuelve 99999 = "mucho"
        "description": clean_text(raw.get("description") or raw.get("metaTagDescription"))[:1500],
        "release": raw.get("releaseDate") or "",
    }


def fetch_store(store):
    found, errors, any_ok = {}, [], False
    for term in store["terms"]:
        for url in search_urls(store["base"], term):
            try:
                data = http_get_json(url)
            except Exception as e:  # noqa: BLE001
                errors.append(str(e))
                continue
            any_ok = True
            products = data.get("products") if isinstance(data, dict) else data
            for raw in products or []:
                p = normalize(raw, store)
                if p:
                    found[p["key"]] = p
            break  # este término ya respondió; no hace falta el respaldo
    if not any_ok:
        raise RuntimeError("; ".join(errors[-2:]) or "sin respuesta")
    return found


# ---------------------------------------------------------------------- formato

def cop(v):
    return "—" if v is None else "$" + f"{v:,}".replace(",", ".")


def now_bogota():
    return datetime.now(BOGOTA)


def stamp(dt=None):
    return (dt or now_bogota()).strftime("%d/%m/%Y %I:%M %p")


def describe(p):
    stock = "✅ DISPONIBLE" if p["available"] else "❌ Agotado / no disponible"
    if p["available"] and p["qty"]:
        stock += f" ({p['qty']} unid.)"
    price = cop(p["price"])
    if p["list_price"]:
        pct = round(100 * (1 - p["price"] / p["list_price"]))
        price += f" (antes {cop(p['list_price'])}, -{pct}%)"
    return f"{p['name']}\n{p['store']}\nPrecio: {price}\nEstado: {stock}\n{p['link']}"


# ---------------------------------------------------------------------- cambios

def diff(old, new):
    """Devuelve lista de (prioridad, texto). Prioridad 0 = urgente."""
    events = []
    for k, p in new.items():
        o = old.get(k)
        changes = []  # (prioridad, línea)
        if o is None:
            changes.append((0 if p["available"] else 1, "🆕 Producto nuevo publicado"))
            if p["available"]:
                changes.append((0, "🚨 ¡YA SE PUEDE COMPRAR!"))
        else:
            if p["available"] and not o.get("available"):
                changes.append((0, "🚨 ¡YA SE PUEDE COMPRAR!"))
            elif o.get("available") and not p["available"]:
                changes.append((1, "⛔ Se agotó"))
            if p["price"] != o.get("price") and p["price"] is not None:
                changes.append((1, f"💲 Cambio de precio: {cop(o.get('price'))} → {cop(p['price'])}"))
            if p["list_price"] and not o.get("list_price"):
                changes.append((1, "🏷️ Nuevo descuento"))
            if p["description"] and p["description"] != o.get("description"):
                changes.append((2, "📝 Se actualizó la descripción (posible contenido revelado):\n"
                                   + p["description"][:600]))
        if changes:
            changes.sort(key=lambda c: c[0])
            text = "\n".join(c[1] for c in changes) + "\n\n" + describe(p)
            events.append((changes[0][0], text))
    for k, o in old.items():
        if k not in new:
            events.append((2, f"👻 Ya no aparece en el catálogo: {o['name']} ({o['store']})"))
    return sorted(events, key=lambda e: e[0])


# --------------------------------------------------------------------- telegram

def send_telegram(text):
    token = os.environ.get("TELEGRAM_TOKEN", "").strip()
    chats = [c.strip() for c in os.environ.get("TELEGRAM_CHAT_IDS", "").split(",") if c.strip()]
    page = os.environ.get("PAGE_URL", "").strip()
    if page:
        text += f"\n\n📄 Estado completo: {page}"
    if os.environ.get("DRY_RUN") == "1" or not token or not chats:
        print("---- MENSAJE (no enviado) ----\n" + text + "\n------------------------------")
        return
    for chat in chats:
        body = urllib.parse.urlencode({
            "chat_id": chat, "text": text[:4000], "disable_web_page_preview": "false",
        }).encode()
        try:
            urllib.request.urlopen(
                f"https://api.telegram.org/bot{token}/sendMessage", data=body, timeout=30
            ).read()
        except Exception as e:  # noqa: BLE001
            print(f"Error enviando a {chat}: {e}", file=sys.stderr)


# ------------------------------------------------------------------------ página

def render_page(state):
    products = sorted(state["products"].values(), key=lambda p: (not p["available"], p["store"], p["name"]))
    any_avail = any(p["available"] for p in products)
    if any_avail:
        banner = ("ok", "Hay calendarios disponibles para comprar")
    elif products:
        banner = ("warn", "Publicado, pero sin stock en este momento")
    else:
        banner = ("idle", "Aún no aparece el calendario 2026 en las tiendas")

    cards = []
    for p in products:
        price = cop(p["price"])
        if p["list_price"]:
            price = f"<s>{cop(p['list_price'])}</s> {price}"
        img = f'<img src="{html.escape(p["image"])}" alt="" loading="lazy">' if p["image"] else ""
        cards.append(f"""
      <article class="card">
        {img}
        <div class="body">
          <span class="pill {'yes' if p['available'] else 'no'}">{'Disponible' if p['available'] else 'Agotado'}</span>
          <h3>{html.escape(p['name'])}</h3>
          <p class="store">{html.escape(p['store'])}</p>
          <p class="price">{price}</p>
          <a href="{html.escape(p['link'])}" target="_blank" rel="noopener">Ver en la tienda →</a>
        </div>
      </article>""")
    if not cards:
        cards.append('<p class="empty">Nada todavía. En cuanto Trendy publique la ficha, aparecerá aquí '
                     'y llegará un aviso por Telegram.</p>')

    hist = "".join(
        f"<li><time>{html.escape(h['t'])}</time><pre>{html.escape(h['msg'])}</pre></li>"
        for h in state["history"][:60]
    ) or "<li class='empty'>Sin cambios registrados aún.</li>"

    errs = "".join(
        f"<li>{html.escape(s)}: {html.escape(v['error'])} ({v['count']} intentos seguidos)</li>"
        for s, v in state.get("failures", {}).items() if v.get("count")
    )
    errs_html = f'<section class="errors"><h2>Problemas de conexión</h2><ul>{errs}</ul></section>' if errs else ""

    return f"""<!doctype html>
<html lang="es">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta http-equiv="refresh" content="900">
<title>Calendario Trendy 2026</title>
<style>
  :root {{ --bg:#fff7fa; --fg:#2b1d24; --muted:#7a6470; --card:#fff; --line:#f0d9e3;
          --accent:#c2185b; --ok:#1b7f4b; --okbg:#e3f5ea; --no:#9a3412; --nobg:#fdeee4; }}
  @media (prefers-color-scheme: dark) {{
    :root {{ --bg:#1a1216; --fg:#f5e9ee; --muted:#b89dab; --card:#241a1f; --line:#3a2a32;
            --accent:#f06292; --ok:#7bd8a2; --okbg:#173326; --no:#f4a77a; --nobg:#3a2216; }} }}
  * {{ box-sizing:border-box }}
  body {{ margin:0; background:var(--bg); color:var(--fg);
         font:16px/1.5 system-ui,-apple-system,"Segoe UI",Roboto,sans-serif; }}
  main {{ max-width:880px; margin:0 auto; padding:28px 16px 60px; }}
  h1 {{ font-size:1.7rem; margin:0 0 4px; }}
  .sub {{ color:var(--muted); margin:0 0 20px; }}
  .banner {{ padding:14px 16px; border-radius:12px; font-weight:600; margin-bottom:24px; }}
  .banner.ok {{ background:var(--okbg); color:var(--ok); }}
  .banner.warn {{ background:var(--nobg); color:var(--no); }}
  .banner.idle {{ background:var(--card); border:1px solid var(--line); }}
  .grid {{ display:grid; gap:14px; grid-template-columns:repeat(auto-fill,minmax(240px,1fr)); }}
  .card {{ background:var(--card); border:1px solid var(--line); border-radius:14px; overflow:hidden; }}
  .card img {{ width:100%; aspect-ratio:1; object-fit:cover; display:block; background:var(--line); }}
  .body {{ padding:12px 14px 16px; }}
  .card h3 {{ margin:8px 0 2px; font-size:1rem; }}
  .store {{ margin:0; color:var(--muted); font-size:.85rem; }}
  .price {{ font-weight:700; font-size:1.15rem; margin:8px 0; }}
  .price s {{ color:var(--muted); font-weight:400; font-size:.9rem; }}
  .pill {{ font-size:.75rem; font-weight:700; padding:2px 8px; border-radius:99px; }}
  .pill.yes {{ background:var(--okbg); color:var(--ok); }}
  .pill.no {{ background:var(--nobg); color:var(--no); }}
  a {{ color:var(--accent); }}
  h2 {{ font-size:1.1rem; margin:32px 0 10px; }}
  ol {{ list-style:none; padding:0; margin:0; }}
  ol li {{ border-left:3px solid var(--line); padding:4px 0 10px 12px; }}
  time {{ color:var(--muted); font-size:.8rem; }}
  pre {{ white-space:pre-wrap; font:inherit; margin:2px 0 0; overflow-wrap:anywhere; }}
  .empty {{ color:var(--muted); }}
  .errors {{ color:var(--no); font-size:.9rem; }}
  footer {{ margin-top:36px; color:var(--muted); font-size:.8rem; }}
</style>
</head>
<body>
<main>
  <h1>🎄 Calendario de Adviento Trendy 2026</h1>
  <p class="sub">Última revisión: {html.escape(state['last_check'])} (hora Colombia) · se revisa automáticamente cada 2 horas</p>
  <div class="banner {banner[0]}">{banner[1]}</div>
  <section class="grid">{''.join(cards)}</section>
  {errs_html}
  <h2>Historial de cambios</h2>
  <ol>{hist}</ol>
  <footer>Fuentes: catálogo público de maquillajetrendyshop.com y novaventa.com.
  El único canal oficial de venta de Trendy es su web; desconfía de preventas por otros medios.
  Esta página no está afiliada a Trendy.</footer>
</main>
</body>
</html>
"""


# -------------------------------------------------------------------------- main

def load_state():
    if os.path.exists(STATE_FILE):
        with open(STATE_FILE, encoding="utf-8") as f:
            return json.load(f)
    return {"products": {}, "history": [], "failures": {}, "initialized": False, "last_check": ""}


def main():
    state = load_state()
    state.setdefault("failures", {})
    old = state["products"]
    new = {}
    ok_stores = set()

    for store in STORES:
        try:
            new.update(fetch_store(store))
            ok_stores.add(store["name"])
            state["failures"].pop(store["name"], None)
        except Exception as e:  # noqa: BLE001
            f = state["failures"].setdefault(store["name"], {"count": 0, "error": ""})
            f["count"] += 1
            f["error"] = str(e)[:300]
            print(f"[{store['name']}] error: {e}", file=sys.stderr)
            if f["count"] == FAIL_ALERT_AFTER:
                send_telegram(f"⚠️ El bot lleva {FAIL_ALERT_AFTER} revisiones sin poder leer {store['name']}. "
                              f"Puede que el sitio haya cambiado. Detalle: {f['error'][:200]}")
            # conserva los productos conocidos de la tienda que falló, para no inventar "desapariciones"
            new.update({k: v for k, v in old.items() if v["store"] == store["name"]})

    # solo compara tiendas que respondieron
    comparable_old = {k: v for k, v in old.items() if v["store"] in ok_stores}
    comparable_new = {k: v for k, v in new.items() if v["store"] in ok_stores}

    state["last_check"] = stamp()

    if not state.get("initialized"):
        if ok_stores:
            lines = [describe(p) for p in comparable_new.values()] or ["Aún no aparece el calendario 2026 en las tiendas."]
            msg = "🤖 Bot del Calendario Trendy activado.\nEstado actual:\n\n" + "\n\n".join(lines)
            send_telegram(msg)
            state["history"].insert(0, {"t": state["last_check"], "msg": "Bot activado.\n" + "\n\n".join(lines)})
            state["initialized"] = True
    else:
        events = diff(comparable_old, comparable_new)
        if events:
            msg = "🎄 NOVEDAD Calendario Trendy\n\n" + "\n\n".join(t for _, t in events)
            send_telegram(msg)
            for _, t in events:
                state["history"].insert(0, {"t": state["last_check"], "msg": t})
        print(f"{len(events)} cambio(s) detectado(s).")

    state["products"] = new
    state["history"] = state["history"][:MAX_HISTORY]

    with open(STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)
    os.makedirs(os.path.dirname(PAGE_FILE), exist_ok=True)
    with open(PAGE_FILE, "w", encoding="utf-8") as f:
        f.write(render_page(state))
    print(f"Revisión completa: {state['last_check']} · {len(new)} producto(s) · tiendas OK: {sorted(ok_stores)}")


if __name__ == "__main__":
    main()
