---
name: "Code review"
description: "Skontroluje kód alebo zmenu: chyby, bezpečnosť, čitateľnosť a testy. Použi, keď používateľ žiada review, kontrolu kódu alebo „pozri sa na tento kód“."
---

# Code review

1. Prečítaj kód, ktorý sa kontroluje (read_file; veľký súbor po častiach). Ak ide o projekt, najprv code_map.
2. Prejdi ho v tomto poradí a poznamenaj len skutočné nálezy (nič nevymýšľaj):
   - **Chyby**: zlé podmienky, off-by-one, neošetrené None / prázdny vstup, zabudnuté zatvorenie súboru, zlé poradie operácií.
   - **Bezpečnosť**: vstup od používateľa v ceste k súboru / príkaze / SQL, pevne zapísané heslá a kľúče, nebezpečné eval / exec.
   - **Čitateľnosť**: nejasné názvy, príliš dlhé funkcie (50+ riadkov), duplicitný kód.
   - **Testy**: čo nie je pokryté a kde by test zachytil chybu.
3. Ak je to možné, nálezy over (run_code / run_tests) skôr, než ich tvrdíš.
4. Kód NEUPRAVUJ, kým o to používateľ nepožiada. Review je len správa.

## Formát odpovede
Zoznam nálezov, každý: **súbor:riadok – závažnosť (vysoká / stredná / nízka) – problém – odporúčaná oprava (1 veta)**.
Na konci jedna veta „Celkovo: …“. Ak je kód v poriadku, povedz to a nevymýšľaj výhrady.
