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

## ⚠️ Formulář

Poptávky jdou na **vlastní backend** `/api/poptavka` (`FORM_ENDPOINT` v obou
souborech) — malá systemd služba `poptavka` na serveru (`deploy/poptavka.py`),
která poptávku pošle do `info@skeleta.cz` přes rozesílací službu **Brevo**
(stejně jako BlackTalon a Bystrouška; odesílatel = ověřená adresa Brevo).
Kontrakt odpovědi: JSON `{"success":"true"}` — JS kontrolu
`if(!r.ok || String(d.success)!=='true') throw 0;` zachovat: když poptávka
nejde doručit hned, backend vrátí `false` a formulář zákazníkovi nabídne
**telefon** (kopie čeká ve frontě). Honeypot `_honey` nechat; roboty
s náhodnými řetězci backend zahazuje sám.

Přístup k Brevo je v `/etc/poptavka.env` (kontejner 104), převzatý ze stejného
souboru BlackTalonu (`/opt/blacktalon/.env` v CT103). **Když se změní heslo
k Brevo u BlackTalonu, převést ho znovu** a `systemctl restart poptavka` —
jinak se posílání zastaví (backend zkusí špatné heslo jen jednou; dřív ho
zkoušel dokola a poštovní server pak zabanoval celou domácí IP).
`EMAIL_FROM` musí být u Brevo **ověřená** adresa — nikdy SMTP login, jinak
Brevo zprávu převezme a potichu nedoručí. Stav a chyby: `journalctl -u poptavka`.
Po změně `deploy/poptavka.py` je potřeba `systemctl restart poptavka`
(git pull službu nerestartuje).

## Ověření po úpravách

Po větší změně zkontrolovat: kotvy v menu vedou na existující `id` sekcí,
obrázky se načítají, konzole bez chyb, formulář má všechna pole. Historie
je v gitu — cokoli jde vrátit, při nejistotě commitovat po menších krocích.
