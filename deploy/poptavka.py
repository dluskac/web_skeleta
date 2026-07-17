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
import time
from email.message import EmailMessage
from email.utils import formatdate, make_msgid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

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

FIELD_LABELS = {"jmeno": "Jméno", "telefon": "Telefon", "email": "E-mail",
                "zprava": "Zpráva", "typ": "Typ poptávky", "web": "Odesláno z"}


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
    subject = str(data.get("_subject") or "Poptávka z webu skeleta.cz").strip()[:150]
    reply = str(data.get("_replyto") or data.get("email") or "").strip()
    lines = []
    for key, val in data.items():
        if key.startswith("_") or val in (None, ""):
            continue
        lines.append(f"{FIELD_LABELS.get(key, key)}: {val}")
    lines += ["", f"— odesláno formulářem na skeleta.cz (IP {client_ip})"]

    sender = SMTP_USER if (SMTP_USER and SMTP_PASS) else FROM

    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = f"Web skeleta.cz <{sender}>"
    msg["To"] = TO
    msg["Date"] = formatdate(localtime=True)
    msg["Message-ID"] = make_msgid(domain="skeleta.cz")
    if re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", reply):
        msg["Reply-To"] = reply
    msg.set_content("\n".join(lines))

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
            _send(data, ip)
            return self._json(200, True)
        except Exception:
            # JS větev formuláře při success!=true nabídne telefon — správný fallback
            return self._json(200, False)

    def log_message(self, *args):
        pass


if __name__ == "__main__":
    ThreadingHTTPServer(("127.0.0.1", 8090), Handler).serve_forever()
