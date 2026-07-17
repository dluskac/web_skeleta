# SKELETA — web

Statický web **Stavební společnosti SKELETA s.r.o.** (Kyjov) pro doménu **skeleta.cz**.

- `index.html` — hlavní one-page (služby, reference, postup, o nás, kontakt)
- `pujcovna.html` — Půjčovna nářadí a lešení
- `img/` — obrázky (logo, hero, reference)
- `robots.txt`, `sitemap.xml` — SEO
- `deploy/` — konfigurace pro server (Caddy) + postup nasazení
- `EDITACE.md` — průvodce úpravami webu (pro editaci obsahu)

Vanilla HTML/CSS/JS, **žádný build** — každá stránka je jeden self-contained soubor
s inline `<style>` a `<script>`. Editace = úprava souboru + push do `main`;
server si změny automaticky stáhne (viz `deploy/SETUP.md`).

Poptávkový formulář jde přes vlastní backend `/api/poptavka` (deploy/poptavka.py)
přímo do `info@skeleta.cz` — bez třetích stran.

Historicky web vznikl v repu BlackTalon-Investment (složka `skeleta/`, dočasně
hostováno na blacktalon.cz/skeleta) — tam je i historie úprav do 07/2026.
