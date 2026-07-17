# Jak upravovat web — průvodce pro editaci

Web jsou dva soubory: `index.html` (hlavní stránka) a `pujcovna.html` (půjčovna).
Všechno — texty, vzhled i funkce — je uvnitř těchto souborů. Obrázky jsou ve složce `img/`.

## Úprava textu (nejčastější případ)

1. Na GitHubu otevři soubor (např. `index.html`) a klikni na **tužku** (Edit) vpravo nahoře
2. **Ctrl+F** → najdi text, který chceš změnit
3. Přepiš ho a klikni na zelené **Commit changes** (do popisku stručně co jsi změnila)

Hotovo — změna je uložená i s historií, takže nejde nic nenávratně zkazit.
Cokoliv jde vrátit zpět.

## Jak se v souboru vyznat

- **Nahoře** mezi `<style>` a `</style>` je **vzhled** (barvy, písma, rozměry) —
  needituj, pokud přesně nevíš; radši napiš Davidovi
- **Texty stránky** jsou v druhé půlce souboru, od `<body>` dál — tady se edituje bezpečně
- **Úplně dole** mezi `<script>` a `</script>` je **funkčnost** (formulář, animace) — nesahat

Zlaté pravidlo: **měň text mezi značkami, ne značky samotné.**
Např. v `<h2>Naše služby</h2>` přepiš jen slova „Naše služby".

## Obrázky

1. Ve složce `img/` klikni **Add file → Upload files** a nahraj obrázek
   (JPG, ideálně do ~500 kB — velké fotky web zpomalují)
2. V HTML se na něj odkazuje cestou `/img/nazev-souboru.jpg`
   — v názvech **bez diakritiky a bez mezer** (place `zamecek-milotice.jpg`, ne `zámeček Milotice.jpg`)

## Náhled změn

- Až web pojede na skeleta.cz, každá změna se tam projeví **do minuty** sama
- Do té doby: commitni a napiš Davidovi — projedeme to a pošleme náhled

## Když si nejsi jistá

Napiš Davidovi, co potřebuješ (klidně lidsky: „chci přidat sekci s cenami"),
a uděláme to za tebe — větší zásahy (nové sekce, změny vzhledu, úpravy formuláře)
je stejně lepší nechat na nás, ať web zůstane rychlý a funkční.
