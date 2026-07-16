# SKELETA — web

Statický web **Stavební společnosti SKELETA s.r.o.** (Kyjov) pro doménu **skeleta.cz**.

- `index.html` — hlavní one-page (služby, reference, kalkulačka, dotace, FAQ, kontakt)
- `pujcovna.html` — Půjčovna nářadí a lešení
- `img/` — obrázky (logo, hero, reference)
- `robots.txt`, `sitemap.xml` — SEO
- `deploy/` — konfigurace pro server (Caddy) + postup nasazení

Vanilla HTML/CSS/JS, **žádný build** — každá stránka je jeden self-contained soubor
s inline `<style>` a `<script>`. Editace = úprava souboru + push do `main`;
server si změny automaticky stáhne (viz `deploy/SETUP.md`).

Poptávkový formulář jde přes FormSubmit na `info@skeleta.cz` (bez backendu).

Historicky web vznikl v repu BlackTalon-Investment (složka `skeleta/`, dočasně
hostováno na blacktalon.cz/skeleta) — tam je i historie úprav do 07/2026.
