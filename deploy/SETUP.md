# Nasazení skeleta.cz na Proxmox

Cíl: malý samostatný LXC kontejner, který servíruje tento repozitář přes Caddy
a sám si stahuje změny z GitHubu. Úplně oddělené od BlackTalonu.

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
git clone https://github.com/<UCET>/<REPO>.git /srv/skeleta-web
cp /srv/skeleta-web/deploy/Caddyfile /etc/caddy/Caddyfile
caddy validate --config /etc/caddy/Caddyfile && systemctl reload caddy
```

(U soukromého repa použít deploy key: `ssh-keygen -t ed25519`, veřejný klíč
vložit na GitHubu do Settings → Deploy keys, klonovat přes SSH URL.)

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
