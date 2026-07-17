# SKELETA web — kontext pro Clauda

Statický web Stavební společnosti SKELETA s.r.o. (Kyjov) pro doménu **skeleta.cz**.
S uživatelem komunikuj **česky**. Obsah webu řídí Lenka (SKELETA); technický
support David Luskač (@dluskac) — na něj odkazuj věci kolem hostingu/deploye.

## Architektura

- **Žádný framework, žádný build.** `index.html` a `pujcovna.html` jsou
  self-contained (inline `<style>` i `<script>`). Neexistuje package.json a je
  to záměr — nezavádět build ani závislosti.
- Cesty jsou root-relativní (`/img/...`, `/pujcovna.html`) — počítá se
  se servírováním z kořene domény. Lokální náhled: `nahled.bat` (spustí
  server na :8765; přímé otevření souboru cesty rozbije).
- Obrázky do `img/`, názvy **bez diakritiky a mezer**, JPG do ~500 kB.
- Push do `main` = nasazení (produkce si změny stahuje automaticky).
  `deploy/` je serverová konfigurace — neměnit bez domluvy s Davidem.

## Design systém (neměnit bez rozmyslu)

- Barvy = CSS proměnné v `:root` na začátku `<style>` — změny barev dělat TAM,
  ne roztroušeně. Akcent: švestková `#732559` **podle reálného loga firmy**.
  Paleta je záměrně teplá neutrální (písková/kámen), ne studená šeď.
- Typografie: **Space Grotesk** (nadpisy) + **Inter** (text). Neměnit fonty.
- Animace („cinema" vrstva: Ken Burns, zrno, reveal-on-scroll) jsou všechny
  hlídané `prefers-reduced-motion` — každou novou animaci taky ohlídat.
- Číslované kroky mají jednotný vzor: dvouciferně „01" (nikdy „1"),
  border-top nad kontejnerem.
- Na stránce půjčovny záměrně NENÍ běžící pásek (marquee) — nepřidávat.

## ⚠️ Formulář (nejčastější past)

Poptávky jdou přes **FormSubmit AJAX** (`FORM_ENDPOINT` v obou souborech,
cíl info@skeleta.cz). Zásadní: FormSubmit umí vrátit **HTTP 200 a přitom
`success:false`** — odpověď se MUSÍ parsovat (stávající kód to dělá:
`if(!r.ok || String(d.success)!=='true') throw 0;`). Při úpravách formuláře
tuhle kontrolu zachovat, jinak se poptávky tiše ztrácí. Honeypot pole
`_honey` nechat. Hosting musí mít v CSP `connect-src https://formsubmit.co`
(v `deploy/Caddyfile` už je).

## Ověření po úpravách

Po větší změně zkontrolovat: kotvy v menu vedou na existující `id` sekcí,
obrázky se načítají, konzole bez chyb, formulář má všechna pole. Historie
je v gitu — cokoli jde vrátit, při nejistotě commitovat po menších krocích.
