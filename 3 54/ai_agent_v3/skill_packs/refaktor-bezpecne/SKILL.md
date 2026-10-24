---
name: "Bezpečný refaktoring"
description: "Prerobí štruktúru kódu bez zmeny správania: po malých krokoch, s overením po každom. Použi pri „vyčisti“, „rozdeľ na moduly“, „zjednoduš“, „refaktoruj“."
---

# Bezpečný refaktoring

Pravidlo číslo 1: **správanie sa nesmie zmeniť**. Ak chce používateľ aj novú funkciu, urob to ako SAMOSTATNÝ krok.

1. Najprv zafixuj správanie: spusti existujúce testy (run_tests). Ak žiadne nie sú, spusti program s typickým vstupom a ulož si výstup.
2. Urob JEDNU malú zmenu (premenovanie, vybratie funkcie, rozdelenie súboru) cez edit_file.
3. Po každej zmene spusti to isté ako v kroku 1 a porovnaj. Rozdiel = chyba → undo_file.
4. Pri presune funkcie do iného modulu: search_files na všetky miesta, kde sa volá, a uprav importy.
5. Nepridávaj funkcie, nemeň názvy verejných funkcií bez dôvodu, nemeň formát výstupu.

## Na konci
Vymenuj, čo si presunul / premenoval, a potvrď, čo si overil (a čo nie).
