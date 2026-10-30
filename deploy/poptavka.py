#!/usr/bin/env python3
"""Poptávkový backend webu skeleta.cz.

Přijme JSON z formuláře (POST /api/poptavka, proxované Caddym) a pošle poptávku
do info@skeleta.cz přes rozesílací službu Brevo — stejně jako BlackTalon (CT103)
a Bystrouška (CT106). Pošta odchází z IP Brevo, takže jí nevadí reputace domácí
IP ani ban na poštovním serveru vas-hostingu, a heslo k info@ není potřeba.

Konfigurace /etc/poptavka.env (převzatá z /opt/blacktalon/.env v CT103):
  SMTP_HOST, SMTP_PORT, SMTP_USER, SMTP_PASS — přístup k Brevo,
  EMAIL_FROM — odesílatel; MUSÍ být u Brevo ověřený (ne SMTP login!),
               jinak Brevo zprávu převezme a potichu nedoručí.

Pojistky (incident 10/2026: neplatné heslo se zkoušelo dokola → ban domácí IP
a poptávky měsíce ležely ve frontě):
- neplatné heslo se zkusí JEN JEDNOU; pak se neposílá, dokud se
  /etc/poptavka.env nezmění (nové údaje + systemctl restart poptavka),
- co nejde poslat hned, se uloží do fronty, ALE zákazník dostane „nepodařilo se"
  → formulář mu nabídne telefon. Žádná poptávka se už neztratí potichu,
- roboti s náhodnými řetězci se zahodí (tváříme se spokojeně),
- všechno jde do journalu: journalctl -u poptavka.

Odpověď drží kontrakt formulářového JS: {"success":"true"} / {"success":"false"}.
"""
import json
import os
import re
import smtplib
import ssl
import sys
import threading
import time
import uuid
from email.message import EmailMessage
from email.utils import formatdate, make_msgid, parseaddr
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

STATE_DIR = os.environ.get("STATE_DIRECTORY", "/var/lib/poptavka")
ENV_FILE = "/etc/poptavka.env"
AUTH_BAD_FLAG = os.path.join(STATE_DIR, ".heslo-neplatne")
RETRY_BASE, RETRY_MAX = 1800, 6 * 3600   # fronta: à 30 min, při chybách až à 6 h

TO = "info@skeleta.cz"
SMTP_HOST = os.environ.get("SMTP_HOST", "")
SMTP_PORT = int(os.environ.get("SMTP_PORT") or 587)
SMTP_USER = os.environ.get("SMTP_USER", "")
SMTP_PASS = os.environ.get("SMTP_PASS", "")
EMAIL_FROM = os.environ.get("EMAIL_FROM", "")
MAX_BODY = 64 * 1024
WINDOW, LIMIT = 3600, 6          # ochrana: max 6 poptávek za hodinu z jedné IP
_hits = {}

FIELD_ORDER = ["jmeno", "telefon", "email", "zajem", "naradi", "termin", "zprava"]
FIELD_LABELS = {"jmeno": "Jméno a příjmení", "telefon": "Telefon", "email": "E-mail",
                "zajem": "Co poptává", "naradi": "Nářadí", "termin": "Termín",
                "zprava": "Zpráva"}


def _log(msg):
    print(msg, file=sys.stderr, flush=True)


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


def _configured():
    return bool(SMTP_HOST and SMTP_USER and SMTP_PASS and "@" in parseaddr(EMAIL_FROM)[1])


def _can_send():
    """Posílat jen s úplnou konfigurací a heslem, které jsme ještě neviděli selhat."""
    if not _configured():
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
    _log("HESLO NEPLATNÉ — posílání zastaveno, dokud se nezmění /etc/poptavka.env")


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
    msg["From"] = EMAIL_FROM
    msg["To"] = TO
    msg["Date"] = formatdate(localtime=True)
    msg["Message-ID"] = make_msgid(domain=parseaddr(EMAIL_FROM)[1].split("@")[-1])
    if re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", reply):
        msg["Reply-To"] = reply
    # Stejné hlavičky jako services/email.py v BlackTalonu: transakční zpráva,
    # žádné autoodpovědi a hlavně VYPNUTÉ sledování Brevo — jinak Brevo vloží
    # sledovací pixel a přepíše odkazy přes svou doménu, což zvedá spamové skóre.
    msg["Auto-Submitted"] = "auto-generated"
    msg["X-Auto-Response-Suppress"] = "All"
    msg["X-Mailin-track-clicks"] = "0"
    msg["X-Mailin-track-opens"] = "0"
    msg["X-Sib-Track-Clicks"] = "0"
    msg["X-Sib-Track-Opens"] = "0"
    msg.set_content(text)
    msg.add_alternative(html_body, subtype="html")
    return msg


def _send(data, client_ip):
    """Poslat přes Brevo, nebo vyhodit výjimku. Neplatné heslo zastaví další pokusy."""
    if not _can_send():
        raise RuntimeError("posílání zastaveno (chybí konfigurace nebo neplatné heslo)")
    msg = _build(data, client_ip)
    ctx = ssl.create_default_context()
    if SMTP_PORT == 465:
        smtp = smtplib.SMTP_SSL(SMTP_HOST, SMTP_PORT, timeout=20, context=ctx)
    else:
        smtp = smtplib.SMTP(SMTP_HOST, SMTP_PORT, timeout=20)
    try:
        smtp.ehlo()
        if SMTP_PORT != 465:
            smtp.starttls(context=ctx)
            smtp.ehlo()
        try:
            smtp.login(SMTP_USER, SMTP_PASS)
        except smtplib.SMTPAuthenticationError:
            _auth_failed()
            raise
        # obálka jako u BlackTalonu (SMTP login), hlavička From = ověřený odesílatel
        smtp.send_message(msg, from_addr=SMTP_USER, to_addrs=[TO])
    finally:
        try:
            smtp.quit()
        except Exception:
            pass


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
                _send(data, ip)
                _log(f"poptávka odeslána ({ip})")
                return self._json(200, True)
            except Exception as e:
                _log(f"poptávku nešlo poslat ({type(e).__name__}: {str(e)[:100]}) — "
                     f"uložena do fronty, zákazníkovi nabídnut telefon ({ip})")
            _enqueue(data, ip)
            # Zákazník se dozví, že to neprošlo, a formulář mu nabídne telefon;
            # kopie ve frontě se pošle, až posílání zase půjde.
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
                _log(f"fronta: čeká {len(names)} poptávek, posílání zastaveno (konfigurace/heslo)")
                names = []
            for name in names:
                path = os.path.join(STATE_DIR, name)
                with open(path, encoding="utf-8") as f:
                    item = json.load(f)
                _send(item["data"], item.get("ip", "?"))
                os.remove(path)
                _log(f"fronta: odesláno {name}")
        except Exception as e:
            _log(f"fronta: posílání selhalo ({type(e).__name__}) — zkusím později")
            ok = False
        delay = RETRY_BASE if ok else min(max(delay * 2, RETRY_BASE), RETRY_MAX)


if __name__ == "__main__":
    if not _configured():
        _log("START: neúplná konfigurace v /etc/poptavka.env — poptávky jen do fronty")
    elif not _can_send():
        _log("START: heslo už jednou neprošlo — čekám na nové v /etc/poptavka.env")
    else:
        _log(f"START: posílám přes {SMTP_HOST}:{SMTP_PORT} jako {EMAIL_FROM}")
    threading.Thread(target=_retry_loop, daemon=True).start()
    ThreadingHTTPServer(("127.0.0.1", 8090), Handler).serve_forever()
