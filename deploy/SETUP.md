# Nasazení skeleta.cz na Proxmox

## Zadání (TL;DR pro IT)

Tento repozitář je **statický web** (čisté HTML + obrázky, žádná databáze,
žádný backend — poptávkový formulář jde přes externí službu FormSubmit).
**Repo na GitHubu = jediný zdroj obsahu webu**; úpravy se dělají commitem sem.

**DNS a e-maily domény skeleta.cz spravujete vy** — my dodáváme jen web.
Pro hosting jsou dvě cesty, výběr je na vás:

**A) Náš Proxmox** — postavíme malý LXC kontejner podle kroků 1–3 níže
(Caddy + automatický git pull, údržba nulová) a dodáme vám veřejnou IP;
vy na ni pak přesměrujete DNS (apex A záznam + www).

**B) Vaše řešení** — web umí servírovat cokoliv, co zvládne statické soubory
přes HTTPS. Doporučujeme nastavit automatické stahování změn z GitHubu
(git pull timer, krok 3), ať úpravy webu doputují na doménu bez ručního
nasazování. Repo je veřejné, klonování nevyžaduje přihlášení.

ℹ️ K DNS jen naměřená fakta (kdyby se hodila): web dnes míří na mrtvý Webnode
(apex A 3.73.27.108 + 3.125.172.46, www = CNAME na skeleta.webnode.cz),
TTL 600 s. Na doméně běží firemní pošta — MX ser10.vas-server.cz, TXT
SPF/DMARC, subdomény mail + autoconfig.

---

Cíl: malý samostatný LXC kontejner, který servíruje tento repozitář přes Caddy
a sám si stahuje změny z GitHubu.

## Předpoklad (ověřit PŘED vším ostatním)

Server musí být dosažitelný z internetu na portech **80 a 443** (Let's Encrypt
+ provoz webu). Ověření z jiné sítě (mobilní data): `curl -m5 http://<verejna-IP>/`.
Pokud veřejná IP není / porty nejde otevřít (CGNAT), použít variantu
Cloudflare Tunnel (viz konec souboru).

## 1) Kontejner

Debian/Ubuntu LXC, 1 CPU / 512 MB RAM / 4 GB disk bohatě stačí.
Na Proxmox firewallu/routeru přesměrovat porty 80 a 443 na tento kontejner.

## 2) Instalace (v kontejneru)

```bash
apt update && apt install -y caddy git
git clone https://github.com/dluskac/web_skeleta.git /srv/skeleta-web
cp /srv/skeleta-web/deploy/Caddyfile /etc/caddy/Caddyfile
caddy validate --config /etc/caddy/Caddyfile && systemctl reload caddy
```

(Repo je veřejné, klonování funguje bez přihlášení. Kdyby se později přepnulo
na soukromé, použít deploy key: `ssh-keygen -t ed25519`, veřejný klíč vložit
na GitHubu do Settings → Deploy keys, klonovat přes SSH URL.)

## 3) Auto-aktualizace z GitHubu (pull každou minutu)

```bash
cat >/etc/systemd/system/skeleta-pull.service <<'EOF'
[Unit]
Description=Pull skeleta-web z GitHubu
[Service]
Type=oneshot
ExecStart=/usr/bin/git -C /srv/skeleta-web pull --ff-only
EOF

cat >/etc/systemd/system/skeleta-pull.timer <<'EOF'
[Unit]
Description=Pravidelný pull skeleta-web
[Timer]
OnBootSec=30
OnUnitActiveSec=60
[Install]
WantedBy=timers.target
EOF

systemctl daemon-reload && systemctl enable --now skeleta-pull.timer
```

Statické soubory čte Caddy přímo z disku — po pullu není potřeba nic restartovat.

## 3b) Poptávkový formulář (vlastní backend)

Formulář webu posílá na `/api/poptavka` — obsluhuje ho `deploy/poptavka.py`
(systemd služba, port 8090 jen na localhost; Caddy na něj proxuje).
E-mail se doručuje přímo na MX domény, bez třetích stran a bez hesel.

```bash
cp /srv/skeleta-web/deploy/poptavka.service /etc/systemd/system/poptavka.service
systemctl daemon-reload && systemctl enable --now poptavka
```

Po změně `poptavka.py`: `systemctl restart poptavka` (git pull službu nerestartuje).

## 4) Ověření po přepnutí DNS

```bash
curl -sSI https://skeleta.cz/ | head -5        # 200 + platný cert
curl -sSI https://www.skeleta.cz/ | head -3    # 301 → https://skeleta.cz/
journalctl -u caddy | grep -i acme | tail -5   # vydání certifikátů bez chyb
```

Pokud ACME selhává: NErestartovat Caddy opakovaně (rate limit Let's Encrypt,
5 pokusů/hod) — nejdřív ověřit, že DNS už míří sem a port 80 je dostupný zvenku,
pak jeden `systemctl reload caddy`.

## Varianta B: Cloudflare Tunnel (když není veřejná IP)

skeleta.cz se přidá jako zóna do Cloudflare účtu (změna nameserverů — POZOR,
pak je nutné v CF DNS znovu vytvořit VŠECHNY záznamy vč. MX/TXT pro e-mail!),
v kontejneru běží `cloudflared` s ingress `skeleta.cz -> http://localhost:80`
a Caddyfile se zjednoduší na `:80` bez TLS. Tuto variantu rozpracovat, až
pokud varianta A nebude možná.
