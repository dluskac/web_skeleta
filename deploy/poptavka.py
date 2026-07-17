#!/usr/bin/env python3
"""Poptávkový backend webu skeleta.cz.

Přijme JSON z formuláře (POST /api/poptavka, proxované Caddym) a doručí
poptávku e-mailem PŘÍMO na poštovní server domény (MX vas-hostingu).
Žádná třetí strana, žádné aktivace, žádná hesla — doručujeme na vlastní
schránku, což SMTP dovoluje bez přihlášení.

Odpověď drží kontrakt formulářového JS: {"success":"true"} / {"success":"false"}.
"""
import json
import os
import re
import smtplib
import threading
import time
import uuid
from email.message import EmailMessage
from email.utils import formatdate, make_msgid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

# Fronta nedoručených poptávek (výpadek/ban SMTP) — zkouší se znovu à 10 min
STATE_DIR = os.environ.get("STATE_DIRECTORY", "/var/lib/poptavka")
RETRY_EVERY = 600

TO = "info@skeleta.cz"
FROM = "web@skeleta.cz"          # SPF domény povoluje IP webu (mechanismus "a")
MX = "ser10.vas-server.cz"

# Přihlášené odesílání (obchází IP blacklisty) — přihlašovací údaje čte služba
# z /etc/poptavka.env (SMTP_USER + SMTP_PASS, volitelně SMTP_HOST/SMTP_PORT).
# Bez nich se zkusí přímé doručení na MX (funguje, jen když IP není na blacklistu).
SMTP_USER = os.environ.get("SMTP_USER")
SMTP_PASS = os.environ.get("SMTP_PASS")
SMTP_HOST = os.environ.get("SMTP_HOST", MX)
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


def _send(data, client_ip):
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

    sender = SMTP_USER if (SMTP_USER and SMTP_PASS) else FROM

    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = f"Web skeleta.cz <{sender}>"
    msg["To"] = TO
    msg["Date"] = formatdate(localtime=True)
    msg["Message-ID"] = make_msgid(domain="skeleta.cz")
    if re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", reply):
        msg["Reply-To"] = reply
    msg.set_content(text)
    msg.add_alternative(html_body, subtype="html")

    if SMTP_USER and SMTP_PASS:
        smtp = smtplib.SMTP(SMTP_HOST, SMTP_PORT, timeout=15)
        try:
            smtp.ehlo()
            smtp.starttls()
            smtp.ehlo()
            smtp.login(SMTP_USER, SMTP_PASS)
            smtp.send_message(msg, from_addr=sender, to_addrs=[TO])
        finally:
            smtp.quit()
    else:
        smtp = smtplib.SMTP(MX, 25, timeout=15)
        try:
            smtp.ehlo()
            if smtp.has_extn("starttls"):
                smtp.starttls()
                smtp.ehlo()
            smtp.send_message(msg, from_addr=sender, to_addrs=[TO])
        finally:
            smtp.quit()


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
            if data.get("_honey"):
                return self._json(200, True)   # bot v pasti — tváříme se spokojeně
            if not _allowed(ip):
                return self._json(429, False)
            try:
                _send(data, ip)
            except Exception:
                _enqueue(data, ip)             # doručíme později, poptávka se neztratí
            return self._json(200, True)
        except Exception:
            # JS větev formuláře při success!=true nabídne telefon — správný fallback
            return self._json(200, False)

    def log_message(self, *args):
        pass


def _enqueue(data, ip):
    os.makedirs(STATE_DIR, exist_ok=True)
    path = os.path.join(STATE_DIR, f"{int(time.time())}-{uuid.uuid4().hex[:8]}.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump({"ip": ip, "data": data}, f, ensure_ascii=False)


def _retry_loop():
    while True:
        time.sleep(RETRY_EVERY)
        try:
            files = sorted(os.listdir(STATE_DIR)) if os.path.isdir(STATE_DIR) else []
            for name in files:
                path = os.path.join(STATE_DIR, name)
                try:
                    with open(path, encoding="utf-8") as f:
                        item = json.load(f)
                    _send(item["data"], item.get("ip", "?"))
                    os.remove(path)
                except Exception:
                    break   # server pořád nedostupný — zkusíme za 10 minut
        except Exception:
            pass


if __name__ == "__main__":
    threading.Thread(target=_retry_loop, daemon=True).start()
    ThreadingHTTPServer(("127.0.0.1", 8090), Handler).serve_forever()
