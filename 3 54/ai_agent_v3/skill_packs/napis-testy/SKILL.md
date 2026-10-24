---
name: "Písanie testov"
description: "Navrhne a napíše unittest / pytest testy pre existujúci kód: bežné prípady, okrajové prípady a chyby. Použi pri žiadosti o testy alebo pokrytie kódu."
---

# Písanie testov

1. Prečítaj testovaný kód (code_map, potom read_file len potrebných funkcií). Zisti, či projekt už má tests/ a aký štýl používa
   (unittest alebo pytest) – drž sa ho.
2. Pre každú verejnú funkciu napíš testy v troch skupinách:
   - bežný prípad (typický vstup → očakávaný výstup),
   - okrajové (prázdny vstup, nula, jeden prvok, veľmi veľká hodnota, diakritika),
   - chybové (neplatný vstup → očakávaná výnimka).
3. Test = jedna vec. Názov vyjadruje, čo sa overuje (`test_delenie_nulou_vyhodi_chybu`).
4. Žiadne spoliehanie na sieť, aktuálny čas ani poradie testov; súbory len v dočasnom priečinku.
5. Spusti testy (run_tests alebo run_code). Padajúci test: najprv rozhodni, či je chyba v teste alebo v kóde, a povedz to.
   Kód meň len ak o to používateľ žiadal.

## Výstup
Súbor `tests/test_<modul>.py`. V odpovedi: koľko testov, čo pokrývajú a čo sa nepokrylo.
