#!/usr/bin/env python3
"""Poptávkový backend webu skeleta.cz.

Přijme JSON z formuláře (POST /api/poptavka, proxované Caddym) a doručí
poptávku do info@skeleta.cz:
  1. přihlášeně přes odesílací server vas-hostingu (ser10, port 587) — běžná cesta,
     projde i přeposílacími pravidly schránky;
  2. když je SMTP nedostupné (ban/výpadek), vloží ji přes IMAP rovnou do schránky.
Přihlašovací údaje čte služba z /etc/poptavka.env (SMTP_USER, SMTP_PASS).

Pojistky (incident 10/2026: změněné heslo → server ho dál zkoušel → poštovní
server zabanoval domácí IP pro odesílání a poptávky měsíce ležely ve frontě):
- neplatné heslo se zkusí JEN JEDNOU; pak se odesílání zastaví, dokud se
  /etc/poptavka.env nezmění (nové heslo + systemctl restart poptavka),
- co nejde doručit hned, se uloží do fronty, ALE zákazník dostane „nepodařilo se"
  → formulář mu nabídne telefon. Žádná poptávka se už neztratí potichu,
- roboti s náhodnými řetězci se zahodí (tváříme se spokojeně),
- všechno jde do journalu: journalctl -u poptavka.

Odpověď drží kontrakt formulářového JS: {"success":"true"} / {"success":"false"}.
"""
import imaplib
import json
import os
import re
import smtplib
import socket
import ssl
import sys
import threading
import time
import uuid
from email.message import EmailMessage
from email.utils import formatdate, make_msgid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

STATE_DIR = os.environ.get("STATE_DIRECTORY", "/var/lib/poptavka")
ENV_FILE = "/etc/poptavka.env"
AUTH_BAD_FLAG = os.path.join(STATE_DIR, ".heslo-neplatne")
RETRY_BASE, RETRY_MAX = 1800, 6 * 3600   # fronta: à 30 min, při chybách až à 6 h


def _ipv4(host):
    """Kontejner nemá IPv6 konektivitu — vynutit A záznam, ať se neplýtvá pokusy."""
    try:
        return socket.getaddrinfo(host, None, socket.AF_INET)[0][4][0]
    except Exception:
        return host


def _log(msg):
    print(msg, file=sys.stderr, flush=True)


TO = "info@skeleta.cz"
MAIL_HOST = "ser10.vas-server.cz"
SMTP_USER = os.environ.get("SMTP_USER")
SMTP_PASS = os.environ.get("SMTP_PASS")
SMTP_HOST = os.environ.get("SMTP_HOST", MAIL_HOST)
SMTP_PORT = int(os.environ.get("SMTP_PORT", "587"))
MAX_BODY = 64 * 1024
WINDOW, LIMIT = 3600, 6          # ochrana: max 6 poptávek za hodinu z jedné IP
_hits = {}

FIELD_ORDER = ["jmeno", "telefon", "email", "zajem", "naradi", "termin", "zprava"]
FIELD_LABELS = {"jmeno": "Jméno a příjmení", "telefon": "Telefon", "email": "E-mail",
                "zajem": "Co poptává", "naradi": "Nářadí", "termin": "Termín",
                "zprava": "Zpráva"}


def _allowed(ip):
    now = time.time()
    recent = [t for t in _hits.get(ip, []) if now - t < WINDOW]
    if len(recent) >= LIMIT:
        _hits[ip] = recent
        return False
    recent.append(now)
    _hits[ip] = recent
    return True


def _random_token(s):
    """Řetězec bota: jedno 'slovo' z >= 10 písmen s náhodně přeskakující velikostí."""
    s = str(s or "").strip()
    if len(s) < 10 or not s.isalpha():
        return False
    return sum(1 for a, b in zip(s, s[1:]) if a.islower() and b.isupper()) >= 2


def _is_bot(data):
    return _random_token(data.get("jmeno")) and (
        _random_token(data.get("zprava")) or _random_token(data.get("termin")))


def _can_send():
    """Odesílat jen s heslem, které jsme ještě neviděli selhat."""
    if not (SMTP_USER and SMTP_PASS):
        return False
    try:
        if os.path.getmtime(AUTH_BAD_FLAG) >= os.path.getmtime(ENV_FILE):
            return False      # heslo už jednou neprošlo a od té doby se nezměnilo
    except OSError:
        pass                  # příznak neexistuje → heslo zatím nikdo nezpochybnil
    return True


def _auth_failed():
    with open(AUTH_BAD_FLAG, "w") as f:
        f.write(time.strftime("%Y-%m-%d %H:%M"))
    _log("HESLO NEPLATNÉ — odesílání zastaveno, dokud se nezmění /etc/poptavka.env")


def _build(data, client_ip):
    import html as h
    subject = str(data.get("_subject") or "Poptávka z webu skeleta.cz").strip()[:150]
    reply = str(data.get("_replyto") or data.get("email") or "").strip()

    # Známá pole v pevném pořadí, pak případná neznámá — nic se neztratí
    items = []
    for key in FIELD_ORDER:
        val = data.get(key)
        if val not in (None, ""):
            items.append((FIELD_LABELS[key], str(val)))
    for key, val in data.items():
        if key.startswith("_") or key in FIELD_ORDER or key == "web" or val in (None, ""):
            continue
        items.append((key, str(val)))
    meta = [("Odesláno ze stránky", str(data.get("web") or "skeleta.cz")),
            ("Datum", time.strftime("%d.%m.%Y %H:%M")),
            ("IP návštěvníka", client_ip)]

    text = "\n".join(f"{lbl}: {val}" for lbl, val in items) \
        + "\n\n———\n" + "\n".join(f"{lbl}: {val}" for lbl, val in meta)

    rows = "".join(
        f'<tr><td style="padding:11px 0 11px 26px;color:#6a6259;font-size:13px;'
        f'vertical-align:top;width:140px;border-bottom:1px solid #f1ece4">{h.escape(lbl)}</td>'
        f'<td style="padding:11px 26px 11px 14px;color:#1b1714;font-size:14px;'
        f'border-bottom:1px solid #f1ece4">{h.escape(val).replace(chr(10), "<br>")}</td></tr>'
        for lbl, val in items)
    footer = "<br>".join(f"{h.escape(lbl)}: {h.escape(val)}" for lbl, val in meta)
    html_body = (
        '<!DOCTYPE html><html><body style="margin:0;padding:24px;background:#faf8f5;'
        'font-family:Arial,Helvetica,sans-serif">'
        '<div style="max-width:560px;margin:0 auto;background:#ffffff;'
        'border:1px solid #e9e2d7;border-radius:8px;overflow:hidden">'
        '<div style="padding:18px 26px;background:#732559;color:#ffffff;'
        f'font-size:17px;font-weight:bold">{h.escape(subject)}</div>'
        f'<table style="width:100%;border-collapse:collapse">{rows}</table>'
        '<div style="padding:13px 26px;background:#f1ece4;color:#6a6259;'
        f'font-size:12px;line-height:1.7">{footer}</div>'
        '</div></body></html>')

    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = f"Web skeleta.cz <{SMTP_USER}>"
    msg["To"] = TO
    msg["Date"] = formatdate(localtime=True)
    msg["Message-ID"] = make_msgid(domain="skeleta.cz")
    if re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", reply):
        msg["Reply-To"] = reply
    msg.set_content(text)
    msg.add_alternative(html_body, subtype="html")
    return msg


def _send_smtp(msg):
    smtp = smtplib.SMTP(_ipv4(SMTP_HOST), SMTP_PORT, timeout=10)
    try:
        smtp.ehlo()
        smtp.starttls(context=ssl.create_default_context()
                      if SMTP_HOST == MAIL_HOST else None)
        smtp.ehlo()
        try:
            smtp.login(SMTP_USER, SMTP_PASS)
        except smtplib.SMTPAuthenticationError:
            _auth_failed()
            raise
        smtp.send_message(msg, from_addr=SMTP_USER, to_addrs=[TO])
    finally:
        try:
            smtp.quit()
        except Exception:
            pass


def _send_imap(msg):
    """Záloha: vložit poptávku rovnou do schránky (IMAP ban ani blacklist nemá)."""
    imap = imaplib.IMAP4_SSL(MAIL_HOST, 993, ssl_context=ssl.create_default_context(),
                             timeout=15)
    try:
        try:
            imap.login(SMTP_USER, SMTP_PASS)
        except imaplib.IMAP4.error:
            _auth_failed()
            raise
        typ, _ = imap.append("INBOX", "", imaplib.Time2Internaldate(time.time()),
                             msg.as_bytes())
        if typ != "OK":
            raise RuntimeError(f"IMAP APPEND: {typ}")
    finally:
        try:
            imap.logout()
        except Exception:
            pass


def _send(data, client_ip):
    """Doručit, nebo vyhodit výjimku. Neplatné heslo zastaví další pokusy."""
    if not _can_send():
        raise RuntimeError("odesílání zastaveno (chybí nebo neplatné heslo)")
    msg = _build(data, client_ip)
    try:
        _send_smtp(msg)
        return "SMTP"
    except smtplib.SMTPAuthenticationError:
        raise
    except Exception as e:
        _log(f"SMTP nedostupné ({type(e).__name__}) — zkouším IMAP do schránky")
    _send_imap(msg)
    return "IMAP"


class Handler(BaseHTTPRequestHandler):
    server_version = "skeleta-poptavka"

    def _json(self, code, ok):
        body = json.dumps({"success": "true" if ok else "false"}).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self):
        if self.path != "/api/poptavka":
            return self._json(404, False)
        try:
            length = int(self.headers.get("Content-Length") or 0)
            if not 0 < length <= MAX_BODY:
                return self._json(400, False)
            data = json.loads(self.rfile.read(length).decode("utf-8"))
            if not isinstance(data, dict):
                return self._json(400, False)
            ip = (self.headers.get("X-Forwarded-For")
                  or self.client_address[0]).split(",")[0].strip()
            if data.get("_honey") or _is_bot(data):
                _log(f"bot zahozen ({ip})")
                return self._json(200, True)   # bot — tváříme se spokojeně
            if not _allowed(ip):
                return self._json(429, False)
            try:
                how = _send(data, ip)
                _log(f"poptávka doručena přes {how} ({ip})")
                return self._json(200, True)
            except Exception as e:
                _log(f"poptávku nešlo doručit ({type(e).__name__}: {str(e)[:100]}) — "
                     f"uložena do fronty, zákazníkovi nabídnut telefon ({ip})")
            _enqueue(data, ip)
            # Zákazník se dozví, že to neprošlo, a formulář mu nabídne telefon;
            # kopie ve frontě se doručí, až odesílání zase půjde.
            return self._json(200, False)
        except Exception:
            return self._json(200, False)

    def log_message(self, *args):
        pass


def _enqueue(data, ip):
    os.makedirs(STATE_DIR, exist_ok=True)
    path = os.path.join(STATE_DIR, f"{int(time.time())}-{uuid.uuid4().hex[:8]}.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump({"ip": ip, "data": data}, f, ensure_ascii=False)


def _retry_loop():
    delay = 60                       # první pokus brzy po startu (třeba po změně hesla)
    while True:
        time.sleep(delay)
        ok = True
        try:
            names = sorted(n for n in os.listdir(STATE_DIR) if n.endswith(".json"))
            if names and not _can_send():
                _log(f"fronta: čeká {len(names)} poptávek, odesílání zastaveno (heslo)")
                names = []
            for name in names:
                path = os.path.join(STATE_DIR, name)
                with open(path, encoding="utf-8") as f:
                    item = json.load(f)
                how = _send(item["data"], item.get("ip", "?"))
                os.remove(path)
                _log(f"fronta: doručeno přes {how}: {name}")
        except Exception as e:
            _log(f"fronta: doručení selhalo ({type(e).__name__}) — zkusím později")
            ok = False
        delay = RETRY_BASE if ok else min(max(delay * 2, RETRY_BASE), RETRY_MAX)


if __name__ == "__main__":
    if not (SMTP_USER and SMTP_PASS):
        _log("START: chybí SMTP_USER/SMTP_PASS v /etc/poptavka.env — poptávky jen do fronty")
    elif not _can_send():
        _log("START: heslo už jednou neprošlo — čekám na nové v /etc/poptavka.env")
    else:
        _log(f"START: odesílám přihlášeně jako {SMTP_USER} (SMTP {SMTP_HOST}, záloha IMAP)")
    threading.Thread(target=_retry_loop, daemon=True).start()
    ThreadingHTTPServer(("127.0.0.1", 8090), Handler).serve_forever()
