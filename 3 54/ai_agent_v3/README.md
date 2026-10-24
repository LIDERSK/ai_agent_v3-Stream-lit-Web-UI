# Lokálny AI Agent

## Spustenie
```
pip install -r requirements.txt
streamlit run app.py        (alebo dvojklik na start_agent.bat)
```
Vision model na PC1 (obrázky):  `ollama pull qwen2.5vl:7b`

## Spustenie bez cmd okna (odporúčané)
1. Dvojklik na `create_desktop_shortcut.vbs` – vytvorí ikonu **AI Agent** na ploche aj v ponuke Start.
2. Ikona spustí aplikáciu skrytú a otvorí prehliadač (ak už beží, len otvorí prehliadač).
3. Zastavenie: `stop_agent.vbs`. Ak sa niečo nespustí, pozri `logs/agent.log`.
(`start_agent.bat` ostáva ako klasické spustenie s oknom.)

## Ovládanie
- **Dole v chate**: `＋` menu (prílohy, schopnosti, režimy, kreativita) · výber PC · hĺbka myslenia · čipy zapnutých režimov (klik na ✕ vypne).
  Hĺbku myslenia aj PC môžeš zmeniť pred KAŽDOU správou.
- **➕ Nový chat** → Normálny chat alebo Agent chat.
- **📁 Workspace** – súbory agenta: náhľad, úprava, stiahnutie, spustenie, auto-oprava.
- **🧩 Prispôsobiť** – skills (zapnúť/vypnúť), vlastné inštrukcie, stav pripojení.

## Novinky v3.1
- **Agent už nemá malý limit krokov.** Beží, kým postupuje. Zastaví sa len keď sa zasekne
  (`AGENT_STALL_LIMIT` krokov po sebe s chybou alebo opakovaním rovnakého volania). Po `AGENT_NUDGE_AT`
  krokoch bez pokroku dostane pokyn zmeniť postup. Dlhé premýšľanie nevadí. Bezpečnostné stropy:
  `AGENT_MAX_STEPS` a `AGENT_MAX_SECONDS` v `config.py`.
- **Názvy súborov podľa témy.** Agent nesmie ukladať `script.py`, `test1.py` a pod. (dostane chybu a zvolí
  lepší názov), súbory ukladá do priečinka podľa témy, má nástroj `rename_file`. Kód z normálneho chatu sa
  pomenuje podľa tvojej otázky (napr. `zalohuje_priecinok_zip_archivu.py`).
- **Doručenie súborov:** pod odpoveďou je blok s tlačidlami ⬇ Stiahnuť pri každom súbore, 📦 Všetko ako ZIP
  a 📂 Otvoriť priečinok (otvorí Prieskumníka na PC, kde beží aplikácia). To isté je na stránke Workspace,
  + ZIP z vybraných súborov a premenovanie.

## Novinky v3.2
- **Klaster v agent chate**: keď je zapnutý, agent ho pri kódovaní používa automaticky, výsledok sa ukladá
  rovno do súborov (názov podľa témy), etapy vidíš naživo a klaster dostane aj históriu chatu (platí aj v normálnom chate).
- **Zvuk po dokončení** úlohy, ktorá trvala aspoň 20 s (`NOTIFY_DONE`, `NOTIFY_MIN_SECONDS` v `config.py`).

## Novinky v3.3 (ochrana pred cyklením)
- Model, ktorý sa zasekne a donekonečna opakuje ten istý blok, sa zastaví (`LOOP_GUARD`), opakovanie sa odstráni
  a zobrazí sa upozornenie. Jedna odpoveď má strop `MAX_NEW_TOKENS`.
- Príliš dlhé premýšľanie (`MAX_THINK_CHARS`) sa preruší a odpoveď sa vyžiada bez neho.
- Klaster: väčšie okno (`CLUSTER_NUM_CTX`), limity dĺžky etáp (`STAGE_MAX_TOKENS`), orezanie textu prenášaného
  medzi etapami (`CARRY_CHARS`) a pokyn „každý súbor presne raz“.
- Živé zobrazenie dlhého kódu je len malé okno s posledným riadkami, stránka už nerastie a neťahá ťa dole.

## Novinky v3.5 (málo VRAM)
- Keď Ollama nahlási nedostatok pamäte (`out of memory`, `failed to allocate ... kv cache`), okno kontextu sa
  samo zníži na polovicu a požiadavka sa zopakuje. Funkčná veľkosť sa zapamätá pre daný PC a model
  (`ctx_limits` v `settings.json`), takže chyba sa nevracia. Klaster podľa nej skracuje prenášaný text.
- Chceš ho vrátiť na plnú veľkosť (napr. po zatvorení hier / výmene modelu)? Zmaž kľúč `ctx_limits` zo `settings.json`.

## Novinky v3.6 (diagnostika pamäte)
- Bočný panel ukazuje pri každom PC, ktoré modely sú v pamäti a koľko % z nich beží na GPU. Pod `GPU_WARN_BELOW` %
  sa zobrazí varovanie (časť modelu je v RAM/na CPU → pomalé).
- Tlačidlo 🧹 Uvoľniť pamäť vyloží všetky modely na oboch PC, nabudúce sa načítajú čisto.

## Novinky v3.7 (rýchlosť)
- Odstránené nastavenia pridané vo v3.3, ktoré mohli spomaľovať: `repeat_penalty` je predvolene vypnutý
  (`REPEAT_PENALTY = None`) a klaster používa rovnaké okno ako bežný chat (iné okno = Ollama načíta model znova).
- Bočný panel → 🧪 Test rýchlosti: tá istá krátka úloha s rôznymi nastaveniami (A predvolené Ollamy, B okno aplikácie,
  C + repeat_penalty, D okno 4096). Podľa tok/s a % na GPU hneď vidno, čo model spomaľuje.

## Novinky v3.13
- Hláška Ollamy „error parsing tool call“ (gpt-oss napíše volanie nástroja vo svojom formáte) už neruší správu:
  odpoveď sa zachová a chyba sa ignoruje.

## Novinky v3.12
- gpt-oss sa zasekával v „We need to wait.“: pokyn už nehovorí „počkaj na výsledok“ (model to bral doslovne), detektor
  cyklenia chytí aj krátke opakované frázy a ak model napíše volanie nástroja len do uvažovania, použije sa aj tak.

## Novinky v3.11
- **Výber modelov na každom PC.** Modely sa zisťujú automaticky z Ollamy (`/api/tags`, schopnosti z `/api/show`:
  🧠 myslenie, 👁 obrázky, 🔧 nástroje). V lište pri správe je vedľa výberu PC aj výber modelu (platí od ďalšej správy);
  „🔎 Auto“ vyberie najlepší nainštalovaný podľa `MODEL_PREFERENCE` v `config.py`. Záložka Prispôsobiť →
  Zariadenia a modely: textový a vision model pre každý PC + úlohy PC v klastri (kto plánuje, kto píše).
  Výber sa ukladá do `settings.json`; `config.py` dáva len predvolené hodnoty.
- **gpt-oss**: hĺbka myslenia sa mapuje na low / medium / high (model sa nedá úplne vypnúť, „Vypnuté“ = low);
  keď myslenie nekončí, odpoveď sa vyžiada s `low`.
- **Agent s plánom:** nový skill 📋 Plán úlohy (plan_set / plan_done). Plán sa ukladá do `workspace/.plan/` a vidí ho po
  každom kroku, takže ho neskracuje kontext. Agent neskončí, kým nie sú kroky hotové a výsledok overený (spustený
  alebo prečítaný späť). Pri chybe najprv napíše príčinu. Pri každom kroku napíše riadok „Cieľ: …“.

## Štruktúra
```
app.py             vstupný bod
config.py          PC, modely, hĺbky myslenia, limity, texty návrhov
core/              logika bez Streamlitu
  skills/          ← každý skill = jeden súbor (nájde sa automaticky)
  agent.py         slučka agenta (textový protokol nástrojov, funguje s každým modelom)
  workspace.py     sandbox: všetky súborové operácie len v workspace/
  cluster.py       spolupráca dvoch PC (streamuje etapy)
  ollama_client / thinking / router / prompts / chat_store / settings_store / vision / media / web_search
ui/
  composer.py      dolná lišta + vstup     sidebar.py   bočný panel
  chat_view.py     správy a kroky agenta   live.py      živé zobrazenie
  delivery.py      stiahnutie súborov, ZIP, otvorenie priečinka
  runs/            chat.py · agent.py · cluster.py     views/  chat · workspace · skills
```

## Pridať vlastný skill
Vytvor `core/skills/moj_skill.py` s `SKILL = Skill(...)` (príklad v `fs_read.py` alebo na stránke Prispôsobiť).

## Volanie nástrojov: univerzálny prekladač (v3.15)

Nástroje sa definujú **raz** (`core/skills/*.py`: názov, popis, `params=(Param(...),)`). Vrstva `core/toolcalling.py`
ich preloží do reči modelu a jeho volanie späť do našej podoby:

| Protokol | Kedy | Ako |
|---|---|---|
| `native` | model hlási `tools` (gpt-oss, qwen, llama3.1, …) | pole `tools` v Ollame, odpoveď `tool_calls`, výsledok rola `tool` |
| `text` | všetky ostatné modely | značky `<tool name="…"/>` v texte |

- **Výber je automatický** (podľa schopností modelu z `/api/show`). Vynútiť sa dá v `config.py`
  (`TOOL_PROTOCOL = "native" | "text"`, `TEXT_ONLY_MODELS = ("qwen2.5-coder:7b",)`).
- **Samoliečenie:** ak model natívne nástroje odmietne, aplikácia to zapíše do `settings.json` a nabudúce
  použije text. Ak model 2× po sebe nevráti nič použiteľné, agent v danom behu prejde na text.
- **Prekladač cudzích formátov:** aj keď model odpovie inak, než sme žiadali, volanie sa vykoná
  (`<tool_call>{json}</tool_call>`, JSON `{"name":…,"arguments":…}`, gpt-oss „harmony“ `to=functions.x`).
  JSON v texte sa berie len na konci odpovede a len pre známy nástroj.
- **Nový protokol pre budúce modely:** v `core/toolcalling.py` podtrieda `ToolProtocol` s dekorátorom
  `@register_protocol` (`supports()`, `priority`, `system_section()`, `assistant_msg()`, `result_msg()`).
  Zvyšok aplikácie sa nemení.
- Vlastný skill bez `params` funguje aj naďalej – parametre sa odvodia z popisu.

## Sandbox pre agenta (v3.17)

Skill **▶️ Sandbox – spúšťanie kódu** (`core/sandbox.py`, nástroje `run_code` a `sandbox_info`) nechá agenta kód
naozaj spustiť a opraviť podľa výstupu:

| Súbor | Čo sa stane |
|---|---|
| `.py` | spustí sa so stdin / argumentmi; chýbajúca knižnica sa nahlási |
| `.c` `.cpp` | skompiluje sa (aj viac súborov v priečinku + hlavičky), chyby kompilátora vidí agent, pád programu sa popíše |
| `.js` | Node.js |
| `.html` | headless Edge/Chrome: chyby konzoly, chýbajúce súbory, text stránky + screenshot `<názov>_nahlad.png` |

- Každý beh prebieha v **dočasnej kópii priečinka** (workspace/ sa nemení), s časovým limitom, limitom výstupu
  a minimálnym prostredím (bez tvojich premenných / kľúčov). Server (Flask…) sa spustením len overí štart.
- `config.py`: `SANDBOX_MODE = "docker"` spustí všetko v kontajneri bez siete (512 MB, 1 CPU) – skutočná izolácia.
- Na Windowse treba pre C/C++ kompilátor a pre JS Node.js; čo chýba, ukáže `sandbox_info` aj stránka Prispôsobiť.

## v3.35 – model oznámi súbor, ale nezavolá nástroj

- Odpoveď typu „Cieľ: Vytvorím súbor start.bat“ + **jeden blok kódu** sa teraz vykoná ako `write_file`
  (názov sa vezme z textu; nepomenovaný `.bat` dostane názov podľa posledného `.py`). Platí len pre odpovede,
  ktoré začínajú zámerom („Cieľ:“, „Teraz vytvorím…“, „Spustím…“) – bežná finálna odpoveď s ukážkou kódu sa nezapisuje.
- Ak zadanie žiada `.bat` a model ho ani po výzve nevytvorí, agent ho **zostaví sám** (`cd /d "%~dp0"`, `python "x.py"`,
  `pause` len pri chybe) a povie to v chate.

## v3.36 – záverečné zhrnutie nie je „ohlásený zámer“

- Prompt káže modelu začať každý krok riadkom „Cieľ: …“, takže aj posledná odpoveď („Cieľ: Kalkulačka je hotová.“)
  vyzerala ako nedokončený zámer, agent ju trikrát vrátil a nakoniec ukázal varovanie. Zámer sa teraz berie len
  vtedy, keď je odpoveď krátka, sľubuje akciu („Vytvorím…“, „Spustím…“) a neobsahuje „hotové / vytvoril som…“.
  Záverečné zhrnutie sa zobrazí bez predpony „Cieľ:“.
- Zápis `.bat`, `.txt`, `.md`, `.json`… už nevyžaduje „overenie spustením“ (nedá sa spustiť v sandboxe).
- Hláška „agent len ohlásil…“ ukazuje aj prvých ~90 znakov toho, čo model napísal (na diagnostiku).
- Kontrola „tvrdil, že vytvoril súbor, ktorý neexistuje“ už nepovažuje `kalk.py` za chýbajúci, ak ho agent zapísal ako `kalk/kalk.py`.

## v3.37 – „Počkám na testovanie…“ nie je dôvod zacykliť sa

- Model po úspešnom spustení písal „Cieľ: Počkám na používateľské testovanie a overím…“. Agent to bral ako sľub akcie.
  Teraz sa zámer vynucuje len kým je ešte čo robiť (nič nezapísané, neoverený kód alebo nedokončený plán).
- Chýbajúci `.bat` sa pripomína **pred** všeobecnou výzvou (a až keď už nejaký súbor vznikol).
- Ak model skončí vetou-stubom, hoci práca existuje, agent od neho vypýta stručné zhrnutie (bez nástrojov)
  namiesto varovania. Varovanie zostáva len vtedy, keď sa nič nevytvorilo.
- Výsledok spustenia GUI aplikácie modelu hovorí, že ďalšie testovanie robí používateľ, a nech napíše zhrnutie.

## v3.38 – agent spustí test sám a zhrnutie vychádza len z faktov

- Ak model ani po výzve nezavolá `run_code` (len opakuje „Cieľ: Spustím…“), agent **spustí posledný súbor sám**
  a výsledok vráti modelu (pri chybe ju má opraviť). Robí to najviac 2×.
- Záverečné zhrnutie dostáva **[FAKTY]**: zoznam súborov a čo naozaj vrátil posledný beh – alebo „kód sa nikdy nespustil“.
  Model tak nemôže napísať, že „test odhalil chybu“, ktorý sa nikdy nekonal.
- GUI program (tkinter, PyQt, pygame…) sa v sandboxe zastaví po 8 s namiesto 30 s; ak okno bežalo bez chyby, štart je OK.

## v3.39 – úpravy po častiach (agent už nemusí prepisovať celý súbor)

Nové nástroje (skill ✍️ Vytváranie súborov a 📖 Čítanie súborov):

| Nástroj | Čo robí |
|---|---|
| `edit_file` | zmení len časť existujúceho súboru – bloky `<<<<<<< SEARCH` / `=======` / `>>>>>>> REPLACE` (aj viac zmien naraz). Všetko alebo nič; text sa musí nájsť jednoznačne; toleruje iné odsadenie. Vráti krátky diff. Jednoriadková zmena ide aj cez `old="…" new="…"`. |
| `read_file … start end` | číta len riadky od–do (očíslované); veľký súbor sa už nerežie na 6000 znakov, ale číta po častiach |
| `search_files` | nájde riadky s textom (alebo `re:regex`) vo všetkých súboroch → `súbor:riadok` |

Poistky: `write_file` odmietne prepísať existujúci súbor (≥ 30 riadkov) kódom s menej než polovicou riadkov
(model zvyčajne napísal len úryvok) – treba `edit_file` alebo `overwrite="true"`. Ak prepíše celý súbor kvôli malej
zmene, dostane tip na `edit_file`. Záchrana „Cieľ + blok kódu“ nikdy neprepíše väčší existujúci súbor úryvkom.
V prompte agenta pribudlo pravidlo ÚPRAVY (najprv search_files → read_file start/end → edit_file).

## v3.40 – 🔬 Deep Research a tlačidlá premýšľania pre gpt-oss

**Deep Research** (＋ → Režimy → 🔬 Deep Research, len v normálnom chate). Pri každej správe:
1. model navrhne **plán** (názov + 2 – 8 krokov) – zobrazí sa karta s krokmi (○ čaká · ◔ beží · ✔ hotovo) a ukazovateľom „Researching…“,
2. pre každý krok sa hľadá na webe (DuckDuckGo), prečítajú sa najlepšie stránky a model zapíše poznámky so značkami zdrojov `[n]`,
3. napíše sa **správa s citáciami**; zoznam zdrojov doplní kód zo skutočných URL (model ho nepíše).

- **⏹ Zastaviť** zachová hotové kroky a poznámky. **✏️ Update** na karte: uprav kroky (jeden riadok = jeden krok), pridaj doplňujúcu
  požiadavku a spusti výskum znova. Voľba „✋ Najprv ukázať plán…“ (popover nad vstupom) zastaví po plánovaní a čaká na tvoj štart.
- Ak webové vyhľadávanie nefunguje, správa sa **nevymýšľa z pamäte** – dostaneš dôvod (internet / `pip install -U ddgs`).
- Stránky sa čítajú len z verejných adries (localhost a domáca sieť sú zablokované). Nastavenia v `config.py` (`RESEARCH_*`).

**gpt-oss: Low / Medium / High.** Keď je vybraný model gpt-oss, tlačidlá v lište sú presne `💡 Low · 🧠 Medium · 🔬 High`
(nedá sa vypnúť, preto „Vypnuté“ chýba). Hodnota ide priamo do modelu v chate, agente (strop „Štandardné“ sa naňho nevzťahuje),
klastri (prvý pokus; opakovanie ide na low) aj vo výskume.


## Novinky vo verzii 3.41
- **ZIP a dokumenty (agent):** nástroje `zip_list`, `zip_read`, `zip_extract`, `zip_create` a `read_document` (.docx, .xlsx, .pptx, .pdf).
  ZIP / PDF / Office súbory sa dajú nahrať cez ＋ (uložia sa do `workspace/nahrate/`; ZIP sa v normálnom chate aj priamo ukáže v texte).
  Rozbaľovanie je chránené pred cestami mimo `workspace/` a ZIP bombami.
- **Nové nástroje agenta:** `fetch_url` (prečíta webovú stránku), `delete_file` (so zálohou v `.history`).
- **Deep Research aj v agent chate:** zapni 🔬 v ＋ menu; správa sa uloží aj ako `vyskum_….md` vo `workspace/`.
- **Oprava Deep Research:** dlhý vložený text (pokyny, zadanie) sa zredukuje na krátku tému, pokyny sa použijú len pri písaní správy;
  vyhľadávací dotaz sa čistí a skracuje; vyhľadávač už nepoužíva neplatný región `wt-wt` (chyba DNS `wt.wikipedia.org`).
- Na čítanie PDF treba `pip install pypdf` (je v `requirements.txt`).

## Novinky vo verzii 3.42
- **Vypnutie:** tlačidlo „🔌 Vypnúť“ v sidebare má dve možnosti – len model + Ollama, alebo „⏻ Vypnúť úplne všetko“
  (vyloží modely, zastaví Ollamu, vyčistí pamäť, zavrie webové rozhranie a ukončí aj agenta).
- **Spustenie Ollamy:** jedno tlačidlo „▶ Spustiť Ollamu“, štartuje skryto (bez blikajúcich cmd okien) a čaká, kým Ollama odpovie.
- **Deep Research:** pod odpoveďou sa teraz ukazujú tokeny a rýchlosť (spolu za plán, poznámky aj správu).

## Novinky vo verzii 3.43
- **ZIP v agent chate:** nahraný ZIP sa pripája k celému chatu (agent vie cestu aj v ďalších správach a nepýta sa na ňu); v zozname súborov je vždy prvý.
  Na čítanie slúžia `zip_list`, `zip_read` (aj viac súborov naraz) a nový `zip_search` – bez rozbaľovania.
- `zip_extract` už nezaplaví „Vytvorené súbory“ desiatkami súborov, nezdvojuje vrchný priečinok archívu a zoznam súborov vo `workspace/` zhrnie po priečinkoch.
- Agent pozná aj názvy nástrojov, ktoré používa gpt-oss (`repo_browser.open_file`, `print_tree`, `search`).


## Testy

`python -m unittest discover -s tests` – rýchle testy jadra (bez Streamlitu a bez Ollamy): detekcia opakovania,
parsovanie volaní nástrojov, bezpečnosť ciest a ZIP archívov, ukladanie kódu a **regresia „prompt sa zmestí do okna“**.

## Ollama: rýchlosť a VRAM (nastavenie na PC, kde Ollama beží)

Keď `ollama ps` ukazuje model nie na „100 % GPU“, časť váh beží na CPU/v RAM a rýchlosť klesne (napr. z 90 na 40 tok/s).
Hlavná príčina je veľkosť kontextového okna – KV cache sa alokuje vopred. Aplikácia okno sama zmenšuje (AUTO_FIT),
ale na strane Ollamy pomáhajú aj tieto premenné prostredia (nastav ich v systéme, nie v termináli, a reštartuj Ollamu):

- `OLLAMA_FLASH_ATTENTION=1` – menej pamäte na KV cache (podľa zdrojov 30 – 50 %), viac vrstiev zostane na GPU.
- `OLLAMA_KV_CACHE_TYPE=q8_0` – KV cache na polovicu veľkosti s minimálnou stratou kvality (vyžaduje flash attention).
  `q4_0` len ak sa model ešte stále „prelieva“ do RAM.
- `NUM_CTX` v `config.py` nechaj 4096 – 8192; väčšie okno zvyšuj len ak `ollama ps` stále ukazuje 100 % GPU.
- `OLLAMA_MAX_LOADED_MODELS=1` – dva veľké modely naraz sa na 16 GB nezmestia a Ollama ich prehadzuje.

Zdroje: popularai.org („How to fix Ollama CPU offloading and slow inference“), runaihome.com („Ollama Slow? How to Get More
Tokens per Second“), docs.ollama.com/context-length.


### Model „pretečie“ do RAM, hoci je VRAM voľná
Ollama odhaduje pamäť opatrne (rezerva na výpočtový buffer a KV cache), takže veľký model nechá pár vrstiev v RAM aj pri 1–2 GB voľnej VRAM
(Správca úloh: GPU 14/16 GB, a `llama-server` v RAM ~1,4 GB). Aplikácia to rieši sama (`FORCE_GPU` v `config.py`): ak je na CPU najviac
30 % modelu, jeden raz model vyloží a znova načíta s `num_gpu=999` (všetky vrstvy na GPU). Ak sa model nenačíta, vráti sa k pôvodnému
nastaveniu a potom zmenšuje okno ako doteraz. Ďalej pomáha `OLLAMA_FLASH_ATTENTION=1`, `OLLAMA_KV_CACHE_TYPE=q8_0` a zatvoriť programy, ktoré
držia GPU (prehliadač, hry).

## Novinky vo verzii 3.49
- `read_file` nájde súbor aj vtedy, keď leží len vo nahratom ZIP-e (gpt-oss volá `repo_browser.open_file ai_agent_v3/core/x.py`) – prečíta ho priamo z archívu; inak chyba ukáže, ktoré archívy sú nahraté.
- Ak model namiesto odpovede napíše len vlastnú anglickú úvahu („We need to…“), agent ho dvakrát vyzve, aby pokračoval nástrojom alebo odpoveďou po slovensky.

## Novinky vo verzii 3.50 – programátorské návyky agenta
Cieľ: agent pridáva malé funkcie bez toho, aby pri každej úlohe zásadne prepisoval kód.
- **Ochrana pred veľkým prepísaním:** `write_file` na existujúci súbor sa odmietne, ak ho agent nečítal (jednorazové upozornenie) alebo ak
  mení menej než 40 % riadkov súboru s 30+ riadkami – vtedy musí použiť `edit_file`. Výnimka: `overwrite="true"`.
- **Syntax:** zmena (`write_file`/`edit_file`), ktorá by rozbila Python alebo JSON, sa vôbec neuloží; nový súbor so syntaktickou chybou sa uloží s varovaním `[SYNTAX]`.
- **`undo_file`:** vráti súbor do stavu spred zmien agenta v tejto úlohe (súbor vytvorený v úlohe zmaže).
- **`code_map`:** prehľad tried a funkcií s číslami riadkov, aby malý model našiel správne miesto bez čítania všetkého.
- **`run_tests`:** spustí `unittest` projektu (tests/test*.py) v dočasnej kópii; počíta sa ako overenie.
- **Pamäť projektu:** súbor `AGENTS.md` (vo `workspace/` alebo v priečinku projektu) sa vkladá do promptu pri každej úlohe;
  agent ho po prvom kroku sám vytvorí a dopĺňa.
- **Pravidlá práce:** pochopiť → jeden malý krok → overiť → v prípade chyby `undo_file`; nová aplikácia po krokoch (najprv spustiteľná kostra).
- Testy: `tests/test_project_guards.py`.

## Novinky vo verzii 3.51
- **Pretiahni súbor rovno do chatu.** Obrázok, ZIP, PDF, Office aj textový súbor stačí pustiť na vstupné pole (aj viac naraz), klikať
  na ＋ netreba. Súbor bez textu dostane predvolenú úlohu („Pozri sa na priložené súbory…“). Menu ＋ ostáva. Vyžaduje Streamlit ≥ 1.43
  (staršia verzia spadne späť na ＋). Limit veľkosti je `maxUploadSize` v `.streamlit/config.toml` (20 MB).
- **🧰 Balíky skillov (SKILL.md)** – modulárne skills ako u komerčných asistentov: v prompte sú len názvy a popisy, celý postup si agent
  načíta, keď ho úloha potrebuje (`skill_use`), priložené súbory cez `skill_file`, skripty spustí cez `run_code`. Vstavané: code-review,
  debug-postup, napis-testy, readme-dokumentacia, refaktor-bezpecne, csv-analyza. Zapínanie: ＋ menu alebo Prispôsobiť → 🧰 Balíky skillov.
- **Import a preklad z internetu:** v Prispôsobiť → 🧰 Balíky skillov pretiahni ZIP (aj celý repozitár s viacerými skillmi), `.skill`,
  `SKILL.md`, `.md` alebo Cursor `.mdc`; alebo vlož odkaz (GitHub súbor / repozitár) či text. Balík sa prevedie na náš formát, chýbajúci popis
  sa odvodí a cudzie názvy nástrojov (Bash, Read, Edit, Grep …) sa pri načítaní preložia na naše. Balík s rizikovým obsahom (`curl | sh`,
  `sudo`, „ignoruj predchádzajúce pokyny“) sa uloží VYPNUTÝ. `.py` súbory sa neinštalujú automaticky. Balík sa dá exportovať ako ZIP (⬇).
- **📚 Znalosť o aplikácii:** nový dokument `PATCH_NOTES_A_MAPA.md` (patch notes, mapa súborov a funkcií, architektúra, myslenie modelu, jadro
  agenta). Agent ho číta nástrojom `app_info` po častiach. Test `tests/test_v351.py` stráži, aby dokument spomínal každý modul, skill a nástroj.
- Pri úprave kódu pridaj do `PATCH_NOTES_A_MAPA.md` sekciu „Zmeny“ a spusti `python -m unittest discover -s tests`.

## Novinky vo verzii 3.52
- **Návod k nástrojom:** pred zadaním agent dostane krátke vysvetlenie, ako nástroje fungujú a v akom poradí ich používať (`TOOL_GUIDE` v `core/prompts.py`).
- **Oprava zaseknutia pri ZIPe:** agent už nečíta archív po jednom súbore (45× `zip_read`). `zip_extract` odporúča rozbaliť hneď pri testovaní a úprave, a `zip_read` po 6 prečítaných súboroch z jedného archívu vyzve na `zip_extract`.

## Novinky vo verzii 3.54

- Celý postup agenta (myslenie + volania nástrojov) je v jednom zbalenom boxe „🧰 Postup agenta“ – rozbalíš ho podľa potreby, chat sa nepredlžuje.
- gpt-oss má v agentovi plytké premýšľanie (`AGENT_GPTOSS_THINK`), `read_file` s URL poradí `fetch_url`, `write_file` prijme aj argument `content`.

## Novinky vo verzii 3.53
- **Úloha „otestuj“ bez zapnutého Sandboxu:** aplikácia hneď upozorní, že agent kód nespustí; agent napíše kód a testy, v odpovedi poctivo povie, že ho nespúšťal, a uvedie príkaz na spustenie. Zapni ▶️ Sandbox v ＋ → Schopnosti, ak chceš, aby kód naozaj spustil a opravil.
