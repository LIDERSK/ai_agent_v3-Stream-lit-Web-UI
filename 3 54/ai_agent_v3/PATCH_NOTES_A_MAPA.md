# AI Agent v3.54 – patch notes a mapa aplikácie

Tento súbor je určený aj agentovi: všetko o aplikácii (čo sa menilo, kde čo leží, ako sa model rozhoduje) nájde tu.
Agent ho číta nástrojom `app_info` (bez argumentov = obsah, `topic="mapa"` = jedna časť, `query="text"` = hľadanie).
Platí pre verziu **3.54** (`VERSION` v `config.py`). Pri každej novej verzii dopíš sekciu „Zmeny“ a prípadne mapu.

## Ako to čítať

- Slovník: **PC / uzol** = počítač s Ollamou (`NODES` v `config.py`). **Skill** = zapínateľná schopnosť s nástrojmi (Python,
  `core/skills/*.py`). **Balík skillov** = inštrukčný skill vo formáte `SKILL.md` (`skill_packs/`). **Nástroj** = to, čo agent volá
  (`read_file`, `run_code` …). **Workspace** = `workspace/`, jediný priečinok, v ktorom agent smie pracovať.
- Aplikácia je Streamlit rozhranie (`ui/`) nad jadrom bez Streamlitu (`core/`). Jadro sa testuje bez Ollamy aj bez Streamlitu.
- Jazyk textov pre model a používateľa je slovenčina; názvy v kóde sú anglicky.

## Zmeny

Zdroj: README, komentáre v kóde a záznamy z druhého chatu (vetva v3_44 – v3_49, pozri nižšie). Pre niektoré verzie záznam stále neexistuje
(3.4, 3.8 – 3.10, 3.14, 3.16, 3.18, 3.20, 3.22, 3.26, 3.29 – 3.34) – nič som k nim nedomýšľal; čo sa v nich menilo, hľadaj cez `git`/staré zipy.
**Pozor:** záznamy 3.44 – 3.48 a 3.18 – 3.28 pochádzajú z paralelného chatu (osobitná sekcia „Zmeny z paralelného chatu“), kde sa číslovalo inak (tam bola „3.49“ drag & drop, tu je to 3.51).
Nie je overené, že ich kód je v 3.53 – pri väčšine záznamov je „Ako overiť“ (hľadaný názov v kóde).

### 3.54 (táto verzia)
- **Jeden zbalený box „🧰 Postup agenta“** namiesto desiatok rozbalených boxov (myslenie + každé volanie nástroja): počas behu aj v uloženej správe je celý postup v jednom
  rozbaľovacom bloku (`Flat`, `Step` v `ui/live.py`, `proc` v `ui/runs/agent.py`, `_render_flat` / `_render_trace` v `ui/chat_view.py`). Streamlit nepovoľuje vnorené expandery, preto vnútri sú obyčajné kontajnery.
- **Plytké premýšľanie gpt-oss v agentovi:** `AGENT_GPTOSS_THINK = "low"` (`config.py`) – aj pri tlačidle Medium agent používa low (High sa rešpektuje). Dlhé úvahy pred každým malým volaním nástroja končili prázdnou odpoveďou a zaseknutím.
- **Odolnejšie nástroje:** `read_file` s URL vráti pokyn použiť `fetch_url` (`core/skills/fs_read.py`); `write_file` prijme obsah aj z argumentu `content` / `text`, nielen z tela značky (`core/skills/fs_write.py`);
  `TOOL_GUIDE` (`core/prompts.py`) dostal vetu „rob len to, čo zadanie žiada (presný názov súboru, žiadne ďalšie)“.
- Do tohto súboru pribudli záznamy z paralelného chatu (3.44 – 3.48, 3.18 – 3.28, Prevádzkové poznatky).

### 3.53
- **Úloha „otestuj“ pri vypnutom Sandboxe:** agent nikdy nespustil kód a napísal „Hotovo“, hoci nič neotestoval. Teraz: (1) UI hneď ukáže upozornenie, že
  Sandbox je vypnutý (`asks_to_run` v `core/prompts.py`, `ui/runs/agent.py`); (2) prompt dostane pravidlo `SANDBOX_OFF_ASKED` – napísať kód aj testy, nespúšťať
  a v odpovedi výslovne povedať „Kód som nespúšťal“ s príkazom na spustenie; (3) záverečné zhrnutie dostane vo `[FAKTY]` riadok, že Sandbox je vypnutý (`_facts` v `core/agent.py`).
- Počet testov 103.

### 3.52
- **Návod k nástrojom pred úlohou:** agent dostane v systémovom prompte ešte pred workspace a zadaním krátke vysvetlenie, ako nástroje fungujú
  (jedno volanie = jeden nástroj, skutočný výsledok, relatívne cesty, poradie zisti → čítaj → zmeň → over, `[BEZ ZMENY]`) a tipy len pre zapnuté
  skills (`TOOL_GUIDE`, `tool_guide` v `core/prompts.py`). Drží sa krátky, lebo prompt sa musí zmestiť do okna 8192.
- **Oprava: agent čítal ZIP po jednom súbore (~45× `zip_read`) a nikdy ho nerozbalil.** Popis `zip_extract` odporúčal nerozbaľovať, čo sa
  hádalo s pravidlom pre nahraté súbory. Teraz `zip_extract` odporúča rozbaliť hneď pri testovaní / úprave a `zip_read` po 6 prečítaných súboroch
  z jedného archívu vráti chybu s pokynom `zip_extract` (`READ_LIMIT` v `core/skills/zip_tools.py`).

### 3.51
- **Drag & drop do chatu:** súbor (obrázok, ZIP, PDF, Office, textový) stačí pretiahnuť na vstupné pole chatu, ＋ netreba. Funguje
  aj viac súborov naraz; súbor bez textu dostane predvolenú úlohu („Pozri sa na priložené súbory…“). Menu ＋ ostáva. Logika:
  `core/intake.py`, zapojenie `ui/composer.py` (`st.chat_input(accept_file="multiple")`, vyžaduje Streamlit ≥ 1.43).
- **Balíky skillov (SKILL.md)** – modulárne inštrukčné skills ako u komerčných asistentov: v prompte len názov + popis, celý postup
  sa načíta na požiadanie (`skill_use`), priložené súbory cez `skill_file`, skripty sa pripravia pre `run_code`. 6 vstavaných
  balíkov v `skill_packs/`. Kód: `core/skillpacks.py`, nástroje `core/skills/skillpacks.py`, UI `ui/views/skillpacks.py`.
- **Import a preklad z internetu:** ZIP (aj celý repozitár s viacerými skillmi), `.skill`, `SKILL.md`, `.md`, Cursor `.mdc`,
  Claude Code príkaz / agent (`.md`), vložený text alebo odkaz (GitHub blob → raw, repozitár → ZIP). Chýbajúci popis sa odvodí, názvy
  cudzích nástrojov (Bash, Read, Edit, Grep …) sa pri načítaní preložia na naše. Podozrivý obsah sa uloží VYPNUTÝ s upozornením.
- **Nový skill 📚 Znalosť o aplikácii:** nástroj `app_info` číta tento súbor po častiach.
- Nové testy `tests/test_v351.py` (vrátane kontroly, že tento dokument spomína každý modul, skill a nástroj).

### 3.50 – programátorské návyky agenta
- `write_file` na existujúci súbor sa odmietne, ak ho agent nečítal, alebo ak mení menej než 40 % riadkov súboru so 30+ riadkami
  (musí použiť `edit_file`; výnimka `overwrite="true"`). Zmena, ktorá by rozbila Python alebo JSON syntax, sa neuloží.
- Nové nástroje `undo_file`, `code_map`, `run_tests`. Pamäť projektu `AGENTS.md` sa vkladá do promptu. Pravidlá práce:
  pochopiť → jeden malý krok → overiť → pri chybe `undo_file`.

### 3.49
- `read_file` nájde súbor aj keď leží len v nahratom ZIPe (gpt-oss volá `repo_browser.open_file …`).
- Ak model napíše namiesto odpovede len vlastnú anglickú úvahu („We need to…“), agent ho dvakrát vyzve pokračovať po slovensky.

### 3.43
- Nahratý ZIP sa pripája k celému chatu (agent cestu vie aj v ďalších správach). Nový `zip_search`; `zip_read` číta viac súborov naraz.
- `zip_extract` nezaplaví „Vytvorené súbory“. Agent pozná názvy nástrojov gpt-oss (`repo_browser.open_file`, `print_tree`, `search`).

### 3.42
- Vypnutie: „Vypnúť“ (model + Ollama) alebo „⏻ Vypnúť úplne všetko“ (vyloží modely, zastaví Ollamu, zavrie web UI aj agenta).
- Jedno tlačidlo „▶ Spustiť Ollamu“ (skryto, čaká na odpoveď). Deep Research ukazuje tokeny a rýchlosť.

### 3.41
- ZIP a dokumenty: `zip_list`, `zip_read`, `zip_extract`, `zip_create`, `read_document` (.docx .xlsx .pptx .pdf). Nahrávanie cez ＋ do
  `workspace/nahrate/`. Nové nástroje `fetch_url`, `delete_file` (so zálohou). Deep Research aj v agent chate.
- Oprava Deep Research: dlhý vložený text sa zredukuje na tému; vyhľadávací dotaz sa čistí; zrušený neplatný región `wt-wt`.

### 3.40
- 🔬 Deep Research v normálnom chate (plán → hľadanie + čítanie stránok → poznámky → správa s citáciami). Tlačidlá Low / Medium / High pre gpt-oss.

### 3.39
- `edit_file` (SEARCH/REPLACE bloky, všetko alebo nič, diff), `read_file start end`, `search_files`. Poistka proti prepísaniu veľkého súboru úryvkom.

### 3.38 – 3.35
- 3.38: agent spustí test sám, ak ho model nezavolá (max 2×); záverečné zhrnutie dostáva `[FAKTY]`; GUI program sa zastaví po 8 s.
- 3.37: „Počkám na testovanie…“ nie je ohlásený zámer; chýbajúci `.bat` sa pripomína skôr; stub-odpoveď → vypýta sa zhrnutie.
- 3.36: záverečné zhrnutie nie je „ohlásený zámer“; zápis `.bat/.txt/.md/.json` nevyžaduje overenie spustením.
- 3.35: odpoveď „Cieľ: Vytvorím súbor X“ + jeden blok kódu sa vykoná ako `write_file`; chýbajúci `.bat` agent zostaví sám.

### 3.17 – 3.15
- 3.17: Sandbox `run_code` / `sandbox_info` (Python, C, C++, JS, HTML; `SANDBOX_MODE="docker"` pre skutočnú izoláciu).
- 3.15: univerzálny prekladač volania nástrojov `core/toolcalling.py` (protokoly `native` a `text`, prekladač cudzích formátov, samoliečenie).

### 3.13 – 3.11
- 3.13: Ollama chyba „error parsing tool call“ neruší správu. 3.12: gpt-oss sa nezasekáva v „We need to wait.“, detektor cyklenia chytí krátke frázy.
- 3.11: výber modelu na každom PC (detekcia cez `/api/tags`, `/api/show`), `MODEL_PREFERENCE`; gpt-oss Low/Medium/High; skill 📋 Plán úlohy
  (`plan_set`, `plan_done`).

### 3.7 – 3.1
- 3.7: odstránené nastavenia, ktoré spomaľovali (`REPEAT_PENALTY=None`, klaster používa rovnaké okno ako chat); 🧪 Test rýchlosti v bočnom paneli.
- 3.6: diagnostika pamäte (koľko % modelu beží na GPU), 🧹 Uvoľniť pamäť. 3.5: pri nedostatku VRAM sa okno kontextu samo zníži na polovicu a zapamätá (`ctx_limits`).
- 3.3: ochrana pred cyklením (`LOOP_GUARD`, `MAX_NEW_TOKENS`, `MAX_THINK_CHARS`, limity etáp klastra, malé živé okno kódu).
- 3.2: klaster v agent chate, zvuk po dokončení (`NOTIFY_DONE`).
- 3.1: agent bez malého limitu krokov (zastaví sa len keď sa zasekne: `AGENT_STALL_LIMIT`), názvy súborov podľa témy, doručenie súborov (⬇, ZIP, 📂).

## Zmeny z paralelného chatu (3.44 – 3.48, 3.18 – 3.28)

Tieto záznamy sú z druhého chatu (iné číslovanie, pozri „Známe medzery“). Pri väčšine je „Ako overiť“ = názov, ktorý treba nájsť v kóde.

### 3.48 (vetva z iného chatu)
- **Pokazené natívne volanie nástroja → textový protokol.** Model Qwen3.8-27B (`hf.co/unsloth/Qwen3.8-27B-GGUF`) poslal `write_file` s pokazeným JSON;
  Ollama vrátila `llama-server returned invalid tool call arguments … unexpected end of JSON input` a celý beh sa skončil po jednej akcii.
  `_is_toolparse_error` (`core/ollama_client.py`) teraz chytí aj túto chybu; `run_agent` (`core/agent.py`) pri `stopped == "toolparse"` s natívnym protokolom
  zavolá `remember_protocol(url, model, "text")`, `switch_protocol`, pošle udalosť `protocol` a pokračuje textovými značkami `<tool …>`. Pre daný model si to zapamätá.
- Testy: `BrokenNativeToolCallTests` (detekcia chyby, prepnutie protokolu s falošným modelom). *Ako overiť:* hľadaj „Model poslal pokazené natívne volanie“ v `core/agent.py`.

### 3.47 (vetva z iného chatu)
- **FORCE_GPU:** ak je po odpovedi na CPU len malá časť modelu (`FORCE_GPU_MAX_SPILL` = 30 %), `fit_check` raz model vyloží a nabudúce pošle `num_gpu=999`
  (`gpu_force` v `settings.json`: `999` = vynútené, `-1` = nepodarilo sa, nikdy viac). Pri páde / OOM s vynúteným `num_gpu` sa nastavenie zruší (`shrink`, `_CRASH_MARKERS`)
  a okno sa nezmenší hneď. Vypnutie: `FORCE_GPU = False`. README má sekciu „Model pretečie do RAM“. Test `ForceGpuTests`.
- **Poznatok z logov (Ollama 0.40.6, Vulkan, RX 6800 XT):** „pretečenie“ jednej vrstvy (`offloaded 65/66`) pri okne 8192 nespôsobil odhad Ollamy, ale rezerva
  `llama-server` 1936 MiB voľnej VRAM (fit target). Skutočná oprava je premenná prostredia `LLAMA_ARG_FIT_TARGET=512` (Windows: `setx LLAMA_ARG_FIT_TARGET 512`
  a úplný reštart Ollamy) alebo menšie okno; `num_gpu=999` v tejto verzii Ollamy nemusí zaberať (neoverené). *Ako overiť:* `FORCE_GPU` v `config.py`.

### 3.46 (vetva z iného chatu)
- **Čakanie na model sa dá prerušiť a ukazuje stav.** Dovtedy `stream_chat` blokoval na `requests.post`, kým Ollama nevrátila prvý bajt (načítanie modelu + spracovanie zadania,
  pri 27B aj minúty): časovač stál na „0 s“, ⏹ Zastaviť sa spracoval až po návrate a spojenie sa nikdy nezatvorilo, takže GPU pracovalo ďalej.
  Teraz `_post_waiting` (`core/ollama_client.py`) posiela POST na `/api/chat` cez `http.client` vo vlákne a každých HEARTBEAT (0,5 s) vydá udalosť
  `{"type": "wait", "seconds", "loaded"}` (`loaded` = model je v `/api/ps`); zatvorenie generátora (Stop, rerun) zahodí socket (`_abort`) a Ollama prestane počítať.
  `_Resp` je malý objekt s `status_code`, `text`, `json`, `iter_lines`. Ostatné volania (`/api/tags`, `/api/ps`, `/api/show`) zostali na `requests`.
- UI: `wait_text` + `LiveTurn.feed` (`ui/live.py`) píšu „⏳ N s – model sa načítava / model je načítaný, spracúva sa zadanie“; `ui/runs/agent.py` a `ui/runs/cluster.py`
  udalosť `wait` spracujú, `core/cluster.py` a `_wrapup` v `core/agent.py` ju prepúšťajú. Udalosti `run_agent` majú nový typ `wait`.
- Testy: `StreamAbortTests` (falošný Ollama server: heartbeat potom stream; zatvorenie generátora počas čakania zahodí spojenie). *Ako overiť:* `_post_waiting`.

### 3.45 (vetva z iného chatu)
- **Sandbox vidí celý projekt.** `_stage` (`core/sandbox.py`) pri súbore v podpriečinku projektu (`workspace/projekt/tests/x.py`) skopíruje celý najvyšší priečinok projektu
  (bez `.git`, `venv`, `__pycache__`, `node_modules`, súborov nad MAX_COPY_FILE; limity MAX_STAGE_FILES = 3000, MAX_STAGE_BYTES = 80 MB) a `_env(cwd)` nastaví PYTHONPATH
  na dočasný koreň, takže `import core` funguje aj z `tests/`. Súbor priamo vo `workspace/` ostáva ako predtým (len súbory vedľa neho).
- **Vlastný modul nie je pip balík.** `is_local_module` (`core/agent.py`): `env_problem` a `missing_module` ignorujú `No module named 'core'`, ak `core.py` / priečinok `core` existuje vo workspace —
  predtým agent poradil „pip install core“ a skončil.
- **Pád `UnboundLocalError: same_error`:** `same_error` a `sig` sa v `run_agent` nastavia hneď na začiatku (prázdna odpoveď modelu ich čítala pred prvým nástrojom).
- **`UPLOAD_RULE`** (`core/prompts.py`): pri úlohe „zmeň / vylepši kód a pošli ako zip“ agent ZIP hneď rozbalí (`zip_extract`), súbory upraví, overí `run_code` a zabalí `zip_create`;
  čítanie po jednom cez `zip_read` sa neodporúča; pri „použi internet“ použiť `web_search`. *(V 3.52 sa to rieši aj v popise `zip_extract` a `READ_LIMIT` – skontroluj, že text pravidla nie je v rozpore.)*
- Test `SandboxProjectTests`. *Ako overiť:* `is_local_module`, MAX_STAGE_FILES.

### 3.44 (vetva z iného chatu)
- **Agent nevidel zadanie, keď bol priložený ZIP** (prílohy zaplnili okno a Ollama odrezala začiatok promptu): v agent režime sú prílohy krátke (`AGENT_FILE_ATTACH_CHARS` = 2000,
  `AGENT_TEXT_ATTACH_CHARS` = 6000, `_with_attachments(m, agent=True)`), `fit_task` skráti zadanie do okna, `stream_chat` vracia `stats["ctx"]` a `stats["truncated"]`
  (prompt zaplnil ≥ 97 % okna) a agent pri tom zmenší históriu (`_compact`) a ukáže upozornenie.
- Vynútený klaster (`wants_cluster`) sa rozhoduje len podľa slov používateľa (`task_text`), nikdy z textu príloh; po neúspešnom klastri sa falošný auto-plán zmaže.
- `zipwork.list_zip` zbalí šum (zálohy, cache) – NOISE_RE; `preview()` je kratšie. Testy v `tests/test_core.py` (zip noise, `fit_task`, prompt sa zmestí do okna).

### 3.28 – 3.18 (vetva z iného chatu; presné čísla len tam, kde ich poznám)
- 3.19: brány „hotovo“ sa znova zbrania a pri nedokončenom pláne agent poctivo upozorní (`finish_gate`).
- 3.21 / 3.24: voľnejšie parsovanie volania nástrojov; 3.21 / 3.23: pri úlohe „napíš súbor X“ sa uloží len požadovaný súbor (`wanted_files`) a bloky kódu s názvom súboru v ohrade (`save_generated_code`).
- 3.25: `strip_name_line` odstráni samostatný riadok s názvom súboru na začiatku kódu (zapísal sa ako `` `server.py` `` → SyntaxError); po zápise sa kód automaticky spustí a pri chybe sa až 3× opraví (`auto_fix`).
- 3.27: žiadne nežiadané pip balíky (napr. `flask_cors`) – pravidlo v prompte a automatické vypustenie importu; chyba prostredia (ENV_ERR, `env_problem`) agenta zastaví s návodom pre používateľa.
- 3.28: po 3 neúspešných automatických opravách agent nezačne blúdiť, ale ukáže poslednú chybu.
- Ďalšie zmeny z tohto obdobia (bez presného čísla verzie): výber PC + modelu pre každú rolu klastra (architekt / programátor / recenzent, `core/models.cluster_team`, `ui/cluster_team.py`),
  verzia aplikácie v bočnom paneli, checklist plánu viditeľný hneď na začiatku, klaster sa v agent chate použije automaticky pri úlohách o kóde, README: „Testy“ a „Ollama: rýchlosť a VRAM“.

## Mapa súborov

Koreň projektu: `app.py` (vstupný bod), `config.py` (všetky nastavenia), `settings.json` (zapamätané voľby, vzniká za behu),
`PATCH_NOTES_A_MAPA.md` (tento súbor), `README.md`, `AGENTS.md`-štýl pamäť projektu žije až vo `workspace/`.
Priečinky: `core/` jadro, `core/skills/` skills, `ui/` Streamlit, `skill_packs/` balíky skillov, `workspace/` súbory agenta,
`saved_chats/` chaty (JSON), `uploads/` obrázky z chatov, `tests/` testy, `.streamlit/config.toml` vzhľad a limit nahrávania (20 MB).

### core/ – jadro (bez Streamlitu)
| Súbor | Úloha | Dôležité funkcie |
|---|---|---|
| `core/agent.py` | slučka autonómneho agenta, ochrany, automatické opravy | `run_agent`, `run_tool`, `ProgressTracker`, `finish_gate`, `fit_task`, `auto_fix` |
| `core/toolcalling.py` | univerzálna vrstva volania nástrojov (native / text) | `choose_protocol`, `parse_tool_call`, `tool_schemas`, `TextProtocol`, `NativeProtocol` |
| `core/prompts.py` | skladá správy pre model (systémový prompt, história, prílohy) | `build_messages`, `workspace_state`, `project_rule` |
| `core/ollama_client.py` | všetko okolo Ollamy: streamovanie, okno kontextu, OOM, GPU | `stream_chat`, `chat_once`, `effective_ctx`, `fit_check`, `get_capabilities` |
| `core/thinking.py` | hĺbka myslenia, delenie `<think>`, gpt-oss úrovne | `plan_thinking`, `ThinkSplitter`, `tier_for_model` |
| `core/router.py` | výber PC + modelu so záložným riešením | `resolve_target` |
| `core/models.py` | ktorý model beží na ktorom PC, Auto výber, tím klastra | `get_model`, `choices`, `set_model`, `cluster_team` |
| `core/cluster.py` | spolupráca dvoch PC (plán → návrh → recenzia) | `run_cluster` |
| `core/research.py` | Deep Research (plán, hľadanie, poznámky, správa) | `make_plan`, `run_research`, `fetch_page` |
| `core/web_search.py` | DuckDuckGo vyhľadávanie | `search`, `should_search`, `build_query` |
| `core/workspace.py` | klietka ciest, zápis a čítanie súborov, názvy, ZIP | `safe_path`, `write_text`, `save_generated_code`, `make_zip` |
| `core/editing.py` | bezpečné úpravy časti súboru, kontrola syntaxe | `parse_blocks`, `apply_blocks`, `syntax_error` |
| `core/project.py` | pamäť projektu `AGENTS.md`, mapa kódu | `project_notes`, `code_map` |
| `core/sandbox.py` | spúšťanie kódu (Python, C, C++, JS, HTML) | `run`, `run_tests`, `toolchains` |
| `core/zipwork.py` | ZIP v workspace (bezpečné rozbaľovanie) | `list_zip`, `read_member`, `extract`, `create` |
| `core/documents.py` | text z .docx .xlsx .pptx .pdf | `read_document` |
| `core/plan.py` | plán úlohy (checklist) uložený mimo kontextu | `parse_steps`, `render`, `pending` |
| `core/loopguard.py` | detekcia cyklenia modelu | `find_loop`, `trim_repetition` |
| `core/chat_store.py` | ukladanie chatov (1 JSON na chat) | `save_chat`, `load_chat_full`, `normalize` |
| `core/settings_store.py` | `settings.json` (get / put) | `get`, `put` |
| `core/media.py`, `core/vision.py` | obrázky: zmenšenie, kódovanie, popis vision modelom | `prepare_image`, `describe_bytes` |
| `core/power.py` | vypnutie / spustenie Ollamy | `stop_ollama_local`, `start_ollama_local` |
| `core/notify.py` | zvuk po dokončení | `task_done` |
| `core/fileio.py`, `core/utils.py` | atomický zápis, `ttl_cache` | `atomic_write_text` |
| `core/intake.py` | (3.51) čo vráti vstupné pole chatu: text + pretiahnuté súbory | `split_value`, `kind_of`, `default_prompt` |
| `core/skillpacks.py` | (3.51) balíky skillov: čítanie, import, preklad, výber | `list_packs`, `import_file`, `import_url`, `prompt_section`, `translate` |
| `core/appdocs.py` | (3.51) čítanie tohto dokumentu po častiach | `sections`, `find`, `search`, `toc` |

### core/skills/ – skills a ich nástroje
Každý súbor definuje `SKILL = Skill(...)`; nájde sa automaticky (`core/skills/__init__.py`, `_discover`).

| Skill (id) | Súbor | Nástroje | Poznámka |
|---|---|---|---|
| `app_docs` 📚 | `appdocs.py` | `app_info` | číta tento dokument |
| `planning` 📋 | `planning.py` | `plan_set`, `plan_done` | checklist, agent neskončí kým nie je hotový |
| `fs_read` 📖 | `fs_read.py` | `list_files`, `read_file`, `code_map`, `search_files` | číta len vo `workspace/` (a z nahratého ZIPu) |
| `skillpacks` 🧰 | `skillpacks.py` | `skill_list`, `skill_use`, `skill_file` | balíky SKILL.md |
| `zip_tools` 🗜️ | `zip_tools.py` | `zip_list`, `zip_read`, `zip_search`, `zip_extract`, `zip_create`, `read_document` | |
| `fs_write` ✍️ | `fs_write.py` | `write_file`, `edit_file`, `undo_file`, `delete_file`, `rename_file` | poistky proti veľkému prepísaniu a rozbitej syntaxi |
| `run_code` ▶️ | `run_code.py` | `run_code`, `run_tests`, `sandbox_info` | predvolene VYPNUTÝ |
| `web_search` 🌐 | `web.py` | `web_search`, `fetch_url` | v normálnom chate automaticky pri „aktuálnych“ otázkach |
| `vision` 👁 | `vision.py` | `describe_image` | obrázky v chate a v agentovi |
| `cluster` 🤝 | `cluster_collab.py` | `cluster_solve` | režim (čip); predvolene vypnutý |
| `research` 🔬 | `research.py` | – | režim Deep Research; predvolene vypnutý |

`Skill.scope`: `both` | `agent` | `chat`. `Skill.mode=True` znamená, že mení spracovanie KAŽDEJ správy (čip pod vstupom).
Zapnutie / vypnutie sa ukladá do `settings.json` kľúč `skills`.

### ui/ – Streamlit
| Súbor | Úloha |
|---|---|
| `ui/state.py` | stav relácie, životný cyklus chatov, `Settings` (jediné miesto, ktoré mení `messages`) |
| `ui/composer.py` | spodná lišta (＋ menu, PC, model, hĺbka myslenia, čipy) a vstup; `handle_input` spracuje text + pretiahnuté súbory |
| `ui/chat_view.py`, `ui/live.py` | zobrazenie rozhovoru, krokov agenta, živého streamu |
| `ui/generation.py` | rozhodne, ktorý beh spustiť (výskum / agent / klaster / chat) |
| `ui/runs/chat.py`, `agent.py`, `cluster.py`, `research.py`, `common.py` | jednotlivé behy |
| `ui/sidebar.py` | bočný panel: nový chat, história, stav PC, pamäť GPU, vypnutie |
| `ui/views/chat.py`, `workspace.py`, `skills.py`, `skillpacks.py` | stránky (Chat, Workspace, Prispôsobiť, záložka Balíky skillov) |
| `ui/skill_widgets.py`, `ui/delivery.py`, `ui/research_card.py`, `ui/research_options.py`, `ui/cluster_team.py`, `ui/styles.py` | pomocné widgety, doručenie súborov, karta výskumu, CSS |

## Architektúra

Vrstvy: **ui** (Streamlit, len zobrazenie a stav) → **core** (logika, žiadne `import streamlit`) → **Ollama** na PC z `NODES` (HTTP).
Tok jednej správy:
1. `ui/composer.handle_input` prečíta text + súbory (vstupné pole aj ＋), uloží prílohy a pridá správu cez `state.add_message`
   (každá zmena sa hneď ukladá do `saved_chats/`).
2. `ui/generation.run_generation` vyberie beh: zapnutý 🔬 Research → `runs/research`; inak agent chat → `runs/agent`; inak zapnutý 🤝
   klaster → `runs/cluster`; inak `runs/chat`.
3. Beh zavolá `router.resolve_target` (PC + model + či vie obrázky; ak PC nebeží, použije druhý), `thinking.plan_thinking`
   (parameter myslenia + pokyn), `prompts.build_messages` (systémový prompt + história) a `ollama_client.stream_chat`.
4. Udalosti (`thinking`, `content`, `done`, `tool_call`, `tool_result` …) sa streamujú do `ui/live.LiveTurn`; hotová odpoveď sa uloží.
5. Prerušená generácia (Stop / klik) sa zachová cez `state.recover_partial`.

Režimy chatu: **Normálny chat** (model odpovedá, kód označený názvom súboru sa uloží do workspace) a **Agent chat** (nástroje).
Nastavenia, ktoré sa dajú meniť pred KAŽDOU správou: PC, model, hĺbka myslenia, skills (＋), kreativita.

## Myslenie modelu

- **Hĺbky** (`THINKING_TIERS` v `config.py`): Vypnuté (⚡), Ľahké (💡 low), Štandardné (🧠 medium), Hlboké (🔬 high), každá s pokynom pre model.
- `thinking.plan_thinking(tier, model, capabilities)` vráti `(think_param, hint)`:
  - model s natívnym myslením (`thinking` v schopnostiach: qwen3, deepseek-r1, gpt-oss): parameter `think` ide do Ollamy; Ollama vráti
    myslenie v osobitnom poli;
  - **gpt-oss** sa nedá vypnúť, preto tlačidlá Low / Medium / High (`GPTOSS_TIERS`), „Vypnuté“ sa mení na low;
  - model bez natívneho myslenia (napr. qwen2.5-coder): „prompted“ myslenie – model dostane `PROMPTED_COT` a píše úvahu medzi
    `<think>` a `</think>`; `ThinkSplitter` stream rozdelí na myslenie a odpoveď (zvláda značky rozdelené medzi kúskami).
- **Agent** nikdy nemyslí hlbšie než `AGENT_TIER_CAP` („Štandardné“; nevzťahuje sa na gpt-oss) – hlboké myslenie pri každom malom kroku
  len spomaľuje. Ak model nemá natívne myslenie, agent dostane `AGENT_THINK_STEP`: pred každým nástrojom 2 – 4 vety v `<think>`.
- **Ochrany:** myslenie dlhšie ako `MAX_THINK_CHARS` sa preruší a odpoveď sa vyžiada bez neho; odpoveď má strop `MAX_NEW_TOKENS`;
  `loopguard` zastaví model, ktorý donekonečna opakuje ten istý blok.
- Čo model „rozmýšľa“ vidno v rozbaľovacom boxe „🧠 Myšlienkový proces“ a pri agentovi pri každom kroku.

## Jadro agenta

`core/agent.run_agent` je generátor udalostí. Jedna otáčka = jedno volanie modelu + najviac JEDEN nástroj.
1. Pred štartom: `fit_task` skráti prílohy tak, aby sa prompt zmestil do okna (`prompt_budget` = skutočné okno × `CHARS_PER_TOKEN` ×
   `AGENT_PROMPT_SHARE`); inak by Ollama potichu odrezala začiatok promptu (= pokyny).
2. Ak je zapnutý klaster a úloha je o kóde, `cluster_solve` sa zavolá ako prvý krok automaticky (malý model sa nerozhoduje sám),
   potom sa výsledok automaticky spustí a pri chybe opraví (`auto_fix`, najviac 3×).
3. Slučka: `_compact` skracuje starý priebeh → `stream_chat` → `protocol` rozparsuje volanie nástroja → `run_tool` ho vykoná
   (`ToolError` = čitateľná chyba pre model) → výsledok sa vráti modelu → `ProgressTracker.record`.
4. **Pokrok:** krok je pokrok, ak uspel a nie je opakovaním (rovnaký nástroj + argumenty + výsledok viac ako `AGENT_REPEAT_LIMIT`-krát).
   Po `AGENT_NUDGE_AT` krokoch bez pokroku agent dostane `NUDGE` (zmeň prístup); po `AGENT_STALL_LIMIT` sa zastaví (`stopped: stuck`) a
   z hotovej práce sa napíše poctivé zhrnutie (`_wrapup`, so `[FAKTY]`). Bezpečnostné stropy: `AGENT_MAX_STEPS`, `AGENT_MAX_SECONDS`.
5. **Brány pred „hotovo“** (`finish_gate`): nedokončený plán (max 3×), neoverený zapísaný súbor (max 2×), chýbajúci požadovaný typ súboru
   (`.bat`, `.txt`, `.html`), tvrdenie o neexistujúcom súbore, model, ktorý len ohlásil zámer („Cieľ: Vytvorím…“) alebo napísal len anglickú úvahu.
6. **Zámer bez nástroja:** odpoveď „Cieľ: …“ + jeden blok kódu sa vykoná ako `write_file` (`parse_implicit_write`); test, ktorý model nikdy
   nezavolal, spustí agent sám (max 2×); chýbajúci `.bat` agent zostaví sám.
7. Cudzie názvy nástrojov (`repo_browser.open_file`, `tool.run_code`, `functions.x`) sa mapujú na naše (`FOREIGN_TOOLS`, `run_tool`).
8. Poistky zápisu (`fs_write`): nečítaný existujúci súbor sa neprepíše; malá zmena veľkého súboru musí ísť cez `edit_file`; rozbitá syntax
   Pythonu / JSON sa neuloží; `undo_file` vráti stav spred úlohy; všetky prepísané súbory majú zálohu v `workspace/.history/`.

Udalosti generátora: `protocol`, `turn_start`, `thinking`/`content`, `done`, `turn_end`, `tool_call`, `tool_result`, `nudge`, `plan`, `final`, `stopped`.

## Volanie nástrojov

Nástroj sa definuje raz (`Tool(name, usage, example, run, params=(Param…), body=…)`). `core/toolcalling.py` ho preloží:
- **`native`** (priorita 20) – model hlási `tools`: pole `tools` v Ollame, odpoveď `tool_calls`, výsledok rola `tool`;
- **`text`** (priorita 0) – značky `<tool name="x" arg="…"/>` alebo `<tool name="x">telo</tool>`; funguje s každým modelom.
Výber je automatický (`choose_protocol`), vynútiť sa dá `TOOL_PROTOCOL` / `TEXT_ONLY_MODELS`. Ak model natívne nástroje odmietne, zapamätá sa to
(`settings.json` → `tool_protocol`, `protocol_limits`) a nabudúce ide text; po 2 prázdnych odpovediach agent v danom behu prejde na text.
Prekladač cudzích formátov chytí `<tool_call>{json}</tool_call>`, JSON `{"name":…,"arguments":…}` na konci odpovede a gpt-oss „harmony“.
Parameter nástroja sa NESMIE volať `name` (koliduje s atribútom značky) – preto `skill_use skill="…"`.
Nový protokol: podtrieda `ToolProtocol` s `@register_protocol`.

## Prompt a história

`prompts.build_messages(history, mode, hint, web_data, include_images, enabled, custom, protocol)`:
- normálny chat: `SYSTEM_PROMPT` + dátum + vlastné inštrukcie + pokyn k hĺbke myslenia + výsledky webu;
- agent: `AGENT_PROMPT` (s časťou o protokole) + `TOOL_GUIDE` (návod k nástrojom) + `workspace_state` (skutočný zoznam súborov) + `UPLOAD_RULE` (nahraté súbory) + `PLAN_RULE`
  + `EDIT_RULE` a `project_rule` + pamäť projektu `AGENTS.md` + (3.51) zoznam balíkov skillov a `APPDOCS_RULE` + `RUN_RULE`/`NO_RUN_RULE` + `CLUSTER_RULE`;
- posledných `HISTORY_MESSAGES` správ; staršie dlhé sa skracujú (`MAX_OLD_CHARS`); v agent režime sú prílohy krátke
  (`AGENT_FILE_ATTACH_CHARS`, `AGENT_TEXT_ATTACH_CHARS`) – zvyšok číta agent nástrojmi;
- obrázky: najnovšie, najviac `MAX_IMAGES`, len ak cieľový model vie obrázky.

## Pamäť a okno modelu

`ollama_client.effective_ctx` je okno, ktoré sa naozaj použije pre PC + model (`NUM_CTX`, zmenšené podľa `ctx_limits`). Pri „out of memory“ sa okno
zníži na polovicu (min `FIT_MIN_CTX`), požiadavka sa zopakuje a výsledok sa zapamätá. `AUTO_FIT` po odpovedi skontroluje, či model neutiekol do RAM
(`FIT_MIN_GPU`), `FORCE_GPU` skúsi `num_gpu=999` keď je na CPU najviac `FORCE_GPU_MAX_SPILL` % modelu. `KEEP_ALIVE` drží model v pamäti.
Bočný panel ukazuje % na GPU, 🧹 vyloží modely, 🧪 porovná nastavenia rýchlosti.

## Normálny chat, klaster, Deep Research

- **Normálny chat** (`ui/runs/chat.py`): voliteľne webové vyhľadávanie (`web_search.should_search` alebo „Vždy hľadať na webe“), vision model ak sú obrázky,
  kód označený názvom súboru sa uloží do workspace (`workspace.save_generated_code`).
- **Klaster** (`core/cluster.py`): architekt plánuje (`STAGE_MAX_TOKENS["plan"]`), programátor píše návrh, recenzent dokončí; kto je kto určuje
  `cluster_roles` / `cluster_team` (`core/models.py`). Prenášaný text sa orezáva (`CARRY_CHARS`) podľa reálneho okna.
- **Deep Research** (`core/research.py`): plán 2 – 8 krokov (editovateľný) → pre každý krok hľadanie + čítanie `RESEARCH_PAGES` stránok (len verejné adresy)
  → poznámky so značkami `[n]` → správa; zoznam zdrojov dopĺňa kód zo skutočných URL. Ak vyhľadávanie nefunguje, správa sa nevymýšľa z pamäte.

## Skills a balíky skillov

Dva druhy rozšírení – nezamieňať:
1. **Skill (Python)** – `core/skills/*.py`, dáva agentovi NÁSTROJE (kód). Pridanie: nový súbor s `SKILL = Skill(...)`, po reštarte sa objaví v ＋ aj v Prispôsobiť.
2. **Balík skillov (SKILL.md)** – priečinok v `skill_packs/<id>/`, dáva agentovi POSTUP (text + voliteľné skripty a podklady). Pridáva sa za behu bez reštartu.

Balík: `SKILL.md` (frontmatter `name`, `description` + Markdown), voliteľne `scripts/`, `references/`, `assets/`, vlastné metadáta `skillpack.json`
(zdroj, pôvodný formát, poznámky o preklade, upozornenia, `triggers`, `default_enabled`).
Načítanie je „progressive disclosure“: prompt obsahuje len `id: popis` zapnutých balíkov (max `SKILLPACK_PROMPT_CHARS`) a tip, ktorý balík sedí
k úlohe (`skillpacks.suggest`, zhoda slov v názve, popise a `triggers`). Celý postup dá `skill_use skill="id"`; `skill_file` číta priložené súbory
alebo ďalšiu časť dlhého `SKILL.md`; `skill_list` vypíše zapnuté balíky.
**Skripty balíka:** `skill_use` ich skopíruje do `workspace/skills/<id>/…`. `run_code` beží v dočasnej kópii najvyššieho priečinka skriptu (`skills/`) a `nahrate/` nevidí, preto dáta, ktoré skript číta,
treba skopírovať vedľa neho parametrom `copy="nahrate/data.csv"` (v skripte sa potom uvádza len názov súboru).
Vstavané balíky: `code-review`, `debug-postup`, `napis-testy`, `readme-dokumentacia`, `refaktor-bezpecne`, `csv-analyza` (so skriptom).

### Import a preklad (core/skillpacks.py)
| Vstup | Čo sa stane |
|---|---|
| ZIP / `.skill` s jedným skillom | priečinok so `SKILL.md` sa nainštaluje aj s ostatnými súbormi |
| ZIP s viacerými skillami (repozitár) | nainštaluje sa každý priečinok so `SKILL.md` |
| `SKILL.md`, `.md`, `.txt` | nainštaluje sa; bez hlavičky sa názov berie z `# nadpisu`, popis z prvého odseku |
| Cursor `.mdc` (`globs`, `alwaysApply`) | prevedie sa na skill, `globs` a „vždy“ sa pridajú do textu |
| Claude Code príkaz / agent (`allowed-tools`, `model`) | prevedie sa; zoznam povolených nástrojov sa nepoužíva |
| odkaz | GitHub blob → raw, repozitár → ZIP, gist → raw; len verejné adresy, limit `SKILLPACK_DOWNLOAD_MAX` |
| `.py` | NEINŠTALUJE sa (spustilo by sa pri štarte) – skopíruj ručne do `core/skills/` |
Preklad nástrojov pri načítaní (`tool_notes`): Bash → `run_code`, Read → `read_file`, Write → `write_file`, Edit → `edit_file`, Grep → `search_files`,
Glob → `list_files`, WebFetch → `fetch_url`, WebSearch → `web_search`, TodoWrite → `plan_set`/`plan_done`; podagenti nie sú k dispozícii.
Bezpečnosť: ZIP sa kontroluje (zip-slip, absolútne cesty, limity `SKILLPACK_MAX_FILES`, `SKILLPACK_MAX_BYTES`, `SKILLPACK_FILE_MAX`), spustiteľné
binárky sa vynechajú, rizikové príkazy (`curl | sh`, `rm -rf /`, `sudo`) a text typu „ignoruj predchádzajúce pokyny“ vyvolajú upozornenie
a balík sa uloží VYPNUTÝ. Balík z internetu je cudzí text, ktorým sa agent riadi – importuj len dôveryhodné zdroje.
Export: ⬇ ZIP pri balíku (štandardný formát použiteľný aj inde).

## Prevádzkové poznatky (Windows, Ollama 0.40.x, Vulkan)

- Novšia Ollama spúšťa modely cez `llama-server.exe` (v logu `using llama-server for model`); na AMD s „AMD driver is too old“ ide cez **Vulkan** (RX 6800 XT), nie ROCm.
- **RAM ~1 GB v `llama-server.exe` nie je pretečenie:** je to vstupná embedding tabuľka a mapované súbory (`CPU_Mapped model buffer`). Pretečenie ukáže `ollama ps` (PROCESSOR) a v logu `offloaded N/M layers`.
- Flash attention beží sám (`--flash-attn auto`), takže `OLLAMA_FLASH_ATTENTION=1` nič nemení; kvantizovaná KV cache (`OLLAMA_KV_CACHE_TYPE=q8_0`) na Vulkane nie je odporúčaná bez merania.
- Rezervu voľnej VRAM drží `llama-server` (fit target, predvolene ~1936 MiB); znížiť ju: `setx LLAMA_ARG_FIT_TARGET 512` + úplný reštart Ollamy.
- Premenné prostredia na Windowse: `setx NAZOV hodnota` (nie `NAZOV=hodnota` v cmd) a potom reštart procesu.
- Dense 27B (Qwen3.8-27B IQ4_XS / IQ3_XXS) dáva ~30 tok/s a pri 5 000 tokenoch zadania sa spracovanie vstupu spomalí zo ~170 na ~26 tok/s (4096 tokenov trvalo 154 s):
  na agenta (desiatky krokov, dlhý prompt) je vhodnejší MoE ako `gpt-oss:20b` (~94 tok/s); 27B dať do klastra ako architekta / recenzenta.

## Ukladanie dát

- `saved_chats/<id>.json` – chat (správy, kroky agenta, meta); `uploads/` – obrázky z chatov; `workspace/` – súbory agenta, `workspace/nahrate/` nahraté ZIP/PDF/Office,
  `workspace/.history/` zálohy, `workspace/.plan/` plány, `workspace/skills/` pripravené skripty balíkov.
- `settings.json` kľúče: `skills`, `skillpacks`, `node`, `tier`, `temperature`, `force_web`, `custom_instructions`, `models`, `cluster_team`, `cluster_roles`,
  `ctx_limits`, `gpu_force`, `tool_protocol`, `protocol_limits`, `research_steps`, `research_pages`, `research_confirm`.
- Zápisy idú cez `core/fileio.atomic_write_text` (funguje aj na Windowse).

## Konfigurácia

Všetko v `config.py`: `NODES`, `MODEL_PREFERENCE`, `THINKING_TIERS`, okno a limity (`NUM_CTX`, `MAX_NEW_TOKENS`, `HISTORY_MESSAGES`), agent (`AGENT_*`),
sandbox (`SANDBOX_MODE`, `RUN_TIMEOUT`), výskum (`RESEARCH_*`), skill balíky (`SKILLPACK_*`), typy súborov (`IMAGE_TYPES`, `TEXT_TYPES`, `BINARY_TYPES`),
`COMPOSER_MENU` (`popover` alebo `panel`). `.streamlit/config.toml`: `maxUploadSize = 20` (MB, platí aj pre pretiahnuté súbory).

## Testy

`python -m unittest discover -s tests` – bez Streamlitu a bez Ollamy. `tests/test_core.py` (cyklenie, parsovanie nástrojov, ciesty, ZIP, okno),
`tests/test_project_guards.py` (poistky úprav), `tests/test_v351.py` (drag & drop logika, balíky skillov, import a preklad, `app_info`, a kontrola, že tento
dokument spomína každý súbor jadra, každý skill aj nástroj). UI (Streamlit) sa automaticky netestuje – po zmene ho treba vyskúšať v prehliadači.

## Ako rozšíriť

- **Nový skill s nástrojmi:** `core/skills/moj_skill.py` s `SKILL = Skill(id, icon, name, short, description, tools=(Tool(...),))`; potom ho dopíš do tabuľky vyššie.
- **Nový balík skillov:** pretiahni ZIP / `SKILL.md` do Prispôsobiť → 🧰 Balíky skillov, alebo vytvor `skill_packs/<id>/SKILL.md`.
- **Nový PC:** pridaj `Node(...)` do `NODES`. **Nový model:** `ollama pull` + „Znova vyhľadať modely“.
- **Nový protokol volania nástrojov:** `ToolProtocol` + `@register_protocol` v `core/toolcalling.py`.
- **Nová verzia:** zvýš `VERSION`, dopíš „Zmeny“ sem aj do `README.md`, spusti testy.

## Známe medzery

- Záznamy 3.44 – 3.48 (a 3.18 – 3.28) pochádzajú z paralelného chatu: kód z nich treba overiť / zlúčiť s 3.53 (pri väčšine je „Ako overiť“). Kolízia čísel: tam bola „3.49“ drag & drop, tu je to 3.51 (použi tunajšiu verziu, `core/intake.py`).
- UI sa neskúša automaticky; drag & drop na vstupné pole vyžaduje Streamlit ≥ 1.43 (staršie verzie spadnú späť na ＋ menu).
- Balíky skillov v normálnom chate (bez nástrojov) sa nepoužívajú – len v agent chate.
- Import z odkazu potrebuje internet na PC, kde aplikácia beží; súkromné repozitáre sa nedajú stiahnuť.
- Záznamy zmien pre niektoré staré verzie chýbajú (pozri začiatok sekcie „Zmeny“).
