---
name: "Hľadanie chýb (debugging)"
description: "Systematický postup, ako nájsť a opraviť chybu: reprodukcia, príčina, najmenšia oprava, overenie. Použi pri „nefunguje to“, traceback, výnimka alebo pád programu."
---

# Hľadanie chýb

1. **Reprodukuj**: spusti kód (run_code), zachyť presnú chybovú hlášku a riadok. Bez reprodukcie nič neopravuj.
2. **Zaraď príčinu** podľa hlášky: syntax / import / typ / hodnota / logika / prostredie (chýbajúca knižnica, zlá cesta).
3. **Zúž miesto**: read_file len okolie riadku z chyby (start/end), search_files na názov funkcie alebo premennej.
4. **Napíš príčinu jednou vetou** („funkcia delí nulou, keď je zoznam prázdny“) ešte pred opravou.
5. **Najmenšia oprava**: edit_file jednej funkcie. Nepíš celý súbor odznova, nič netreba „pri tom“ prerábať.
6. **Over**: spusti znova ten istý scenár. Ak chyba trvá alebo vznikla nová, vráť zmenu (undo_file) a skús inú hypotézu.
7. Po dvoch neúspešných hypotézach zmeň prístup: pridaj výpisy (print) na hranice podozrivej časti a spusti znova.

## Pravidlá
- Jedna hypotéza naraz. Nikdy nemeň viac vecí naraz.
- Ak chyba zmizla, ale nevieš prečo, nepovažuj to za vyriešené.
- Na konci povedz: príčinu, zmenený súbor a funkciu, čo si overil.
