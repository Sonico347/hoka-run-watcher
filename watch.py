#!/usr/bin/env python3
"""Surveille le hub des runs HOKA Paris et envoie une notification ntfy
pour chaque nouveau run publié (et quand des places se libèrent).

Variables d'environnement :
  NTFY_TOPIC     (obligatoire) nom du topic ntfy auquel ton iPhone est abonné
  NTFY_SERVER    (optionnel)   serveur ntfy, par défaut https://ntfy.sh
  WATCH_URL      (optionnel)   page à surveiller
  STATE_FILE     (optionnel)   fichier d'état, par défaut state/state.json
  DEBUG_DIR      (optionnel)   dossier où enregistrer HTML / capture / réponses JSON
  CHROMIUM_PATH  (optionnel)   chemin d'un Chromium/Chrome déjà installé
  BLOCKED_ALERT_AFTER (optionnel) nb d'échecs d'affilée avant alerte, défaut 8
  BLOCKED_FILE   (optionnel)   compteur d'échecs, défaut runtime/blocked_count
"""
from __future__ import annotations

import json
import os
import sys
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

from playwright.sync_api import sync_playwright

WATCH_URL = os.environ.get("WATCH_URL") or "https://eu-events.hoka.com/parisstorehub"
NTFY_SERVER = (os.environ.get("NTFY_SERVER") or "https://ntfy.sh").rstrip("/")
NTFY_TOPIC = (os.environ.get("NTFY_TOPIC") or "").strip()
STATE_FILE = Path(os.environ.get("STATE_FILE") or "state/state.json")
DEBUG_DIR = Path(os.environ.get("DEBUG_DIR") or "debug")
# Compteur d'échecs d'affilée, gardé hors du dépôt pour ne pas créer un commit à chaque essai.
BLOCKED_FILE = Path(os.environ.get("BLOCKED_FILE") or "runtime/blocked_count")

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36"
)
BLOCKED_ALERT_AFTER = int(os.environ.get("BLOCKED_ALERT_AFTER") or 8)
JOURS = ["lun.", "mar.", "mer.", "jeu.", "ven.", "sam.", "dim."]

# Secours si la page change de technologie : liens du même site avec le texte de leur carte.
EXTRACT_LINKS_JS = r"""
() => {
  const hub = location.pathname.replace(/\/+$/, '');
  const seen = new Map();
  for (const a of document.querySelectorAll('a[href]')) {
    let u;
    try { u = new URL(a.getAttribute('href'), location.href); } catch (e) { continue; }
    if (u.host !== location.host) continue;
    const path = u.pathname.replace(/\/+$/, '');
    if (!path || path === hub) continue;
    let el = a, text = (a.innerText || '').trim();
    for (let i = 0; i < 5 && text.length < 20 && el.parentElement; i++) {
      el = el.parentElement; text = (el.innerText || '').trim();
    }
    const url = u.origin + path;
    const clean = text.replace(/\s+/g, ' ').slice(0, 200);
    if (!seen.has(url) || clean.length > seen.get(url).length) seen.set(url, clean);
  }
  return [...seen].map(([url, text]) => ({ url, text }));
}
"""


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def load_state() -> dict:
    if STATE_FILE.exists():
        return json.loads(STATE_FILE.read_text(encoding="utf-8"))
    return {}


def save_state(state: dict) -> None:
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    STATE_FILE.write_text(
        json.dumps(state, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def notify(title: str, message: str, click: str | None = None,
           tags: list[str] | None = None, priority: int = 3) -> None:
    if not NTFY_TOPIC:
        print(f"[NTFY_TOPIC absent, pas d'envoi] {title} — {message}")
        return
    payload = {"topic": NTFY_TOPIC, "title": title, "message": message,
               "priority": priority, "tags": tags or []}
    if click:
        payload["click"] = click
    req = urllib.request.Request(
        NTFY_SERVER, data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"}, method="POST")
    with urllib.request.urlopen(req, timeout=30) as resp:
        print(f"ntfy {resp.status} : {title}")


def format_date(item: dict) -> str:
    """'11/18/2026 18:30:00' -> 'mer. 18/11 à 18h30'."""
    try:
        d = datetime.strptime(item["date"]["start"], "%m/%d/%Y %H:%M:%S")
        return f"{JOURS[d.weekday()]} {d:%d/%m} à {d:%H}h{d:%M}"
    except Exception:
        return "date à confirmer"


def item_to_event(item: dict) -> dict:
    venue = item.get("venue") or {}
    return {
        "title": (item.get("title") or "Run HOKA").strip(),
        "when": format_date(item),
        "start_timestamp": (item.get("date") or {}).get("start_timestamp"),
        "venue": venue.get("name") or venue.get("address") or "",
        "url": item.get("domain") or WATCH_URL,
        "status": item.get("event_status"),   # future / past
        "rsvp": item.get("rsvp_status"),      # open / waitlist / closed…
    }


def rsvp_label(rsvp: str | None) -> str:
    return {"open": "✅ Inscriptions ouvertes",
            "waitlist": "⏳ Complet, liste d'attente",
            "closed": "🔒 Inscriptions fermées"}.get(rsvp or "", f"Inscriptions : {rsvp}")


def fetch_page() -> dict:
    """Ouvre la page dans Chromium ; renvoie le statut, les runs (JSON du hub)
    et, en secours, les liens de la page."""
    DEBUG_DIR.mkdir(parents=True, exist_ok=True)
    captured = []
    with sync_playwright() as p:
        browser = p.chromium.launch(executable_path=os.environ.get("CHROMIUM_PATH") or None)
        ctx = browser.new_context(user_agent=USER_AGENT, locale="fr-FR",
                                  viewport={"width": 1280, "height": 1600})
        page = ctx.new_page()

        def on_response(resp):
            if "json" in resp.headers.get("content-type", ""):
                try:
                    captured.append({"url": resp.url, "body": resp.json()})
                except Exception:
                    pass

        page.on("response", on_response)
        resp = page.goto(WATCH_URL, wait_until="domcontentloaded", timeout=60_000)
        try:
            page.wait_for_load_state("networkidle", timeout=30_000)
        except Exception:
            pass
        page.wait_for_timeout(2_000)

        html = page.content()
        status = resp.status if resp else 0
        blocked = status == 403 or "captcha-delivery.com" in html
        links = [] if blocked else page.evaluate(EXTRACT_LINKS_JS)

        (DEBUG_DIR / "page.html").write_text(html, encoding="utf-8")
        (DEBUG_DIR / "responses.json").write_text(
            json.dumps(captured, ensure_ascii=False, indent=2), encoding="utf-8")
        try:
            page.screenshot(path=str(DEBUG_DIR / "page.png"), full_page=True)
        except Exception:
            pass
        browser.close()

    # Les runs sont chargés par la page via ?action=ohmyhub&method=getItems
    items = None
    for r in captured:
        if "method=getItems" in r["url"] and isinstance(r["body"], dict):
            result = r["body"].get("result")
            if isinstance(result, dict):
                items = (items or {}) | {str(k): v for k, v in result.items()}
            elif isinstance(result, list):
                items = (items or {}) | {str(v.get("event_id")): v for v in result}
    return {"status": status, "blocked": blocked, "items": items, "links": links}


def main() -> int:
    state = load_state()
    state.setdefault("events", {})
    try:
        page = fetch_page()
    except Exception as exc:  # réseau, timeout…
        print(f"Erreur de chargement : {exc}", file=sys.stderr)
        page = {"status": 0, "blocked": True, "items": None, "links": []}

    n_items = len(page["items"]) if page["items"] is not None else "?"
    print(f"HTTP {page['status']} | bloqué={page['blocked']} | runs={n_items} | liens={len(page['links'])}")

    # 1) Accès refusé par l'anti-bot. Ça arrive par intermittence : on ne prévient
    #    qu'après BLOCKED_ALERT_AFTER échecs d'affilée (8 x 15 min = 2 h).
    try:
        blocked_count = int(BLOCKED_FILE.read_text().strip())
    except Exception:
        blocked_count = 0
    BLOCKED_FILE.parent.mkdir(parents=True, exist_ok=True)
    if page["blocked"]:
        blocked_count += 1
        BLOCKED_FILE.write_text(str(blocked_count))
        print(f"Bloqué {blocked_count} fois d'affilée")
        if blocked_count == BLOCKED_ALERT_AFTER:
            notify("⚠️ Surveillance HOKA bloquée",
                   f"Le site refuse l'accès depuis {BLOCKED_ALERT_AFTER} essais "
                   f"(HTTP {page['status']}, anti-bot). Je continue d'essayer "
                   "et te préviens quand ça repasse.",
                   click=WATCH_URL, tags=["warning"], priority=2)
        return 0
    was_blocked = blocked_count >= BLOCKED_ALERT_AFTER
    BLOCKED_FILE.write_text("0")

    first_run = not state.get("initialized")
    known: dict = state["events"]
    alerts = []

    if page["items"] is not None:
        for event_id, item in page["items"].items():
            ev = item_to_event(item)
            old = known.get(event_id)
            if old is None:
                ev["first_seen"] = now()
                if ev["status"] != "past":
                    alerts.append(("new", ev))
            else:
                ev["first_seen"] = old.get("first_seen", now())
                if ev["status"] != "past" and ev["rsvp"] == "open" and old.get("rsvp") != "open":
                    alerts.append(("open", ev))
            known[event_id] = ev
    else:
        # Secours : la page n'a pas chargé le JSON attendu -> on suit les liens.
        for link in page["links"]:
            key = "link:" + link["url"]
            if key not in known:
                known[key] = {"title": link["text"], "url": link["url"], "first_seen": now()}
                alerts.append(("link", known[key]))

    # On oublie les runs passés depuis plus de 60 jours pour garder un fichier léger.
    limit = datetime.now(timezone.utc).timestamp() - 60 * 86400
    for k in [k for k, v in known.items() if (v.get("start_timestamp") or limit + 1) < limit]:
        del known[k]

    if first_run:
        state["initialized"] = True
        upcoming = [e for t, e in alerts if t == "new"]
        lines = [f"• {e['title']} ({e['when']})" for e in upcoming] or ["Aucun run à venir pour l'instant."]
        notify("👟 Surveillance HOKA activée",
               "Runs à venir déjà en ligne :\n" + "\n".join(lines) +
               "\n\nTu seras prévenu à chaque nouveau run.",
               click=WATCH_URL, tags=["running"], priority=2)
    else:
        if was_blocked:
            notify("✅ Surveillance HOKA rétablie", "La page est de nouveau accessible.",
                   click=WATCH_URL, tags=["white_check_mark"], priority=2)
        for kind, ev in alerts:
            if kind == "new":
                notify(f"🏃 Nouveau run : {ev['title']}",
                       f"📅 {ev['when']}\n📍 {ev['venue']}\n{rsvp_label(ev['rsvp'])}",
                       click=ev["url"], tags=["running"], priority=4)
            elif kind == "open":
                notify(f"🎟️ Places dispo : {ev['title']}",
                       f"📅 {ev['when']}\n📍 {ev['venue']}\nLes inscriptions sont ouvertes !",
                       click=ev["url"], tags=["tada"], priority=4)
            else:
                notify("🔔 Nouveau lien sur la page HOKA", ev["title"] or ev["url"],
                       click=ev["url"], tags=["running"], priority=3)

    save_state(state)
    return 0


if __name__ == "__main__":
    sys.exit(main())
