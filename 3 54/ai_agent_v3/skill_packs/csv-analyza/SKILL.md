---
name: "Analýza CSV dát"
description: "Rýchly prehľad CSV súboru (stĺpce, typy, prázdne hodnoty, štatistiky) pomocou priloženého skriptu. Použi, keď používateľ nahrá CSV alebo žiada rozbor tabuľky."
---

# Analýza CSV

1. Zavolaj `skill_use skill="csv-analyza" copy="nahrate/data.csv"` (cestu k CSV vezmi z list_files). Skript sa pripraví do
   `workspace/skills/csv-analyza/scripts/` a CSV sa skopíruje vedľa neho (sandbox nevidí priečinok `nahrate/`).
2. Spusti skript cez run_code s NÁZVOM súboru (nie cestou):
   `run_code path="skills/csv-analyza/scripts/profile_csv.py" args="data.csv"`
3. Ak skript hlási chybu kódovania alebo oddeľovača, skús iný súbor / napíš to používateľovi.
4. Z výstupu napíš zhrnutie: počet riadkov a stĺpcov, typy, stĺpce s chýbajúcimi hodnotami, rozsahy čísel, najčastejšie hodnoty.
5. Podrobnejšie pravidlá interpretácie sú v `references/interpretacia.md` (skill_file).
6. Nevymýšľaj čísla: uvádzaj len to, čo skript vypísal.
