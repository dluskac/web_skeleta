#!/usr/bin/env python3
"""Hlídač reputace domácí IP — jednou denně (systemd timer hlidac-reputace).

Proč: 10/2026 se domácí IP dostala na Spamhaus CSS, protože Proxmox posílal
upozornění napřímo jako „proxmox.lan". Poštovní server vas-hostingu pak IP
blokoval a z domu nešla odeslat pošta z @skeleta.cz. Nikdo o tom měsíce nevěděl.

Co dělá: zjistí veřejnou IP, ověří ji na blacklistech (dotazy přes DNS
poskytovatele — Spamhaus veřejná DNS 1.1.1.1/8.8.8.8 ignoruje) a s kontrolním
dotazem 127.0.0.2, který listovaný být MUSÍ (jinak „nelze ověřit", ne „čistá").
Když se IP objeví na blacklistu, pošle e-mail (připomene se nejdřív po 3 dnech);
když zmizí, pošle „vyřešeno". Pošta jde přes Brevo (/etc/poptavka.env).

Volby: --zkouska (jen vypíše, nic neposílá ani neukládá),
       --inicializovat (uloží aktuální stav bez e-mailu).
"""
import json
import os
import random
import smtplib
import socket
import ssl
import struct
import sys
import time
import urllib.request
from email.message import EmailMessage
from email.utils import formatdate, make_msgid, parseaddr

RESOLVERY = ["212.111.1.10", "212.111.0.10", "192.168.1.1"]   # INTERNEXT, router
BLACKLISTY = ["zen.spamhaus.org", "bl.spamcop.net", "b.barracudacentral.org", "psbl.surriel.com"]
ZEN_VYZNAM = {2: "SBL — spam", 3: "CSS — zdroj spamu / špatné HELO",
              4: "XBL — napadené zařízení (malware)", 5: "XBL — napadené zařízení",
              6: "XBL — napadené zařízení", 7: "XBL — napadené zařízení", 9: "DROP",
              10: "PBL — domácí IP", 11: "PBL — domácí IP"}
STAV = os.path.join(os.environ.get("STATE_DIRECTORY", "/var/lib/hlidac-reputace"), "stav.json")
PRIPOMENOUT_PO = 3 * 86400


def _dotaz_a(jmeno, resolver, timeout=4.0):
    """Minimální DNS dotaz na A záznam přes konkrétní resolver. Vrací seznam IP."""
    qid = random.randint(0, 0xFFFF)
    paket = struct.pack(">HHHHHH", qid, 0x0100, 1, 0, 0, 0)
    for cast in jmeno.rstrip(".").split("."):
        paket += bytes([len(cast)]) + cast.encode()
    paket += b"\x00" + struct.pack(">HH", 1, 1)
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    s.settimeout(timeout)
    try:
        s.sendto(paket, (resolver, 53))
        data, _ = s.recvfrom(2048)
    finally:
        s.close()
    rid, flags, qd, an = struct.unpack(">HHHH", data[:8])
    if rid != qid or flags & 0x000F not in (0, 3):     # 0 = OK, 3 = NXDOMAIN
        raise RuntimeError(f"DNS chyba {flags & 0x000F}")
    i = 12
    for _ in range(qd):                                 # přeskočit otázku
        while data[i] != 0:
            i += 1 + data[i]
        i += 5
    vysledky = []
    for _ in range(an):
        if data[i] & 0xC0 == 0xC0:
            i += 2
        else:
            while data[i] != 0:
                i += 1 + data[i]
            i += 1
        typ, _, _, delka = struct.unpack(">HHIH", data[i:i + 10])
        i += 10
        if typ == 1 and delka == 4:
            vysledky.append(".".join(str(b) for b in data[i:i + 4]))
        i += delka
    return vysledky


def _listovani(odpovedi):
    """Skutečné zápisy jsou 127.0.0.x; 127.255.255.x jsou chybové kódy Spamhausu."""
    return [a for a in odpovedi if a.startswith("127.") and not a.startswith("127.255.")]


def verejna_ip():
    try:
        with urllib.request.urlopen("https://api.ipify.org", timeout=10) as r:
            ip = r.read().decode().strip()
            socket.inet_aton(ip)
            return ip
    except Exception:
        for r in RESOLVERY:
            try:
                return _dotaz_a("skeleta.cz", r)[0]
            except Exception:
                continue
        raise


def zkontroluj(ip):
    """Vrací {blacklist: 'čistá' | 'nelze ověřit' | '127.0.0.x …'}.
    Resolver se použije jen ten, přes který projde kontrolní dotaz 127.0.0.2."""
    obracene = ".".join(reversed(ip.split(".")))
    vysledek = {}
    for bl in BLACKLISTY:
        vysledek[bl] = "nelze ověřit"
        for r in RESOLVERY:
            try:
                if not _listovani(_dotaz_a(f"2.0.0.127.{bl}", r)):
                    continue                      # tenhle resolver blacklist neobslouží
                hit = _listovani(_dotaz_a(f"{obracene}.{bl}", r))
            except Exception:
                continue
            if not hit:
                vysledek[bl] = "čistá"
            else:
                kod = int(hit[0].rsplit(".", 1)[1])
                vyznam = ZEN_VYZNAM.get(kod, "") if bl.startswith("zen.") else ""
                vysledek[bl] = f"{hit[0]} {vyznam}".strip()
            break
    return vysledek


def posli(predmet, text):
    host, port = os.environ.get("SMTP_HOST", ""), int(os.environ.get("SMTP_PORT") or 587)
    user, heslo = os.environ.get("SMTP_USER", ""), os.environ.get("SMTP_PASS", "")
    adresa_od = parseaddr(os.environ.get("EMAIL_FROM", ""))[1]
    komu = os.environ.get("HLIDAC_TO", "")
    if not (host and user and heslo and "@" in adresa_od and "@" in komu):
        raise RuntimeError("chybí konfigurace pošty (poptavka.env / hlidac-reputace.env)")
    m = EmailMessage()
    m["Subject"] = predmet
    m["From"] = f"Hlídač domácí sítě <{adresa_od}>"
    m["To"] = komu
    m["Date"] = formatdate(localtime=True)
    m["Message-ID"] = make_msgid(domain=adresa_od.split("@")[1])
    m["Auto-Submitted"] = "auto-generated"
    for h in ("X-Mailin-track-clicks", "X-Mailin-track-opens", "X-Sib-Track-Clicks", "X-Sib-Track-Opens"):
        m[h] = "0"
    m.set_content(text)
    ctx = ssl.create_default_context()
    s = smtplib.SMTP(host, port, timeout=20)
    try:
        s.ehlo(); s.starttls(context=ctx); s.ehlo()
        s.login(user, heslo)
        s.send_message(m, from_addr=user, to_addrs=[komu])
    finally:
        try:
            s.quit()
        except Exception:
            pass


def main():
    zkouska = "--zkouska" in sys.argv
    inicializovat = "--inicializovat" in sys.argv
    ip = verejna_ip()
    stav_bl = zkontroluj(ip)
    listovana = {bl: v for bl, v in stav_bl.items() if v.startswith("127.")}
    print(f"IP {ip}: " + "; ".join(f"{bl}={v}" for bl, v in stav_bl.items()), flush=True)

    try:
        stav = json.load(open(STAV, encoding="utf-8"))
    except Exception:
        stav = {"listovana": {}, "posledni_upozorneni": 0}
    ted = time.time()
    predmet = text = None

    if listovana and (not stav["listovana"] or ted - stav["posledni_upozorneni"] > PRIPOMENOUT_PO):
        predmet = f"⚠ Domácí IP {ip} je na blacklistu"
        text = (
            "Hlídač domácí sítě zjistil, že vaše veřejná IP je na blacklistu:\n\n"
            + "\n".join(f"  • {bl}: {v}" for bl, v in listovana.items())
            + "\n\nCo to znamená: nějaké zařízení doma posílá poštu napřímo (bez poskytovatele,"
              " s neplatným jménem). Pošta z domu se pak může vracet a poštovní server"
              " vas-hostingu může IP zablokovat — pak z domu nejde odeslat pošta z @skeleta.cz.\n\n"
              f"Kdo to je: https://check.spamhaus.org/results/?query={ip}\n"
              "  → „Most recently seen HELO values“ ukazuje jméno zařízení (v 10/2026 to byl proxmox.lan).\n"
              "  → V logu routeru hledejte BLOK-SMTP25 — router odchozí port 25 blokuje a zapíše,"
              " kdo to zkoušel.\n\n"
              "Až bude příčina odstraněná: na stejné stránce Spamhausu „Proceed to verification form“"
              " a potvrdit e-mail.\n")
        stav["posledni_upozorneni"] = ted
    elif not listovana and stav["listovana"]:
        predmet = f"✅ Domácí IP {ip} už není na blacklistu"
        text = ("Hlídač domácí sítě: vaše veřejná IP je znovu čistá na všech kontrolovaných"
                " blacklistech.\n\n" + "\n".join(f"  • {bl}: {v}" for bl, v in stav_bl.items()) + "\n")

    stav["listovana"] = listovana
    if zkouska:
        print(f"[zkouška] e-mail: {predmet or '(žádný)'}")
        return
    if predmet and not inicializovat:
        posli(predmet, text)
        print(f"odeslán e-mail: {predmet}", flush=True)
    os.makedirs(os.path.dirname(STAV), exist_ok=True)
    with open(STAV, "w", encoding="utf-8") as f:
        json.dump(stav, f, ensure_ascii=False)


if __name__ == "__main__":
    main()
