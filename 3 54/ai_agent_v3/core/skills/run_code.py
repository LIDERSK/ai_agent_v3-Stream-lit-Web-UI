"""▶️ Sandbox: the agent runs / checks Python, C, C++, JavaScript and HTML (see core/sandbox.py)."""
from core import sandbox
from core.skills import Param, Skill, Tool


def _run(args, body, ctx):
    res = sandbox.run(args.get("path", ""), args.get("stdin", "").replace("\\n", "\n"), args.get("args", ""))
    for rel in res.files:                                  # e.g. the HTML screenshot
        ctx.mark_written(rel)
    return f"Exit code {res.code}\n{res.text}"


def _tests(args, body, ctx):
    res = sandbox.run_tests(args.get("path", ""))
    return f"Exit code {res.code}\n{res.text}"


def _info(args, body, ctx):
    return sandbox.describe()


SKILL = Skill(
    id="run_code", icon="▶️", name="Sandbox – spúšťanie kódu", order=30, default=False, scope="agent",
    short="Agent spúšťa a testuje Python, C, C++, JavaScript, HTML",
    description="Agent spustí kód v izolovanej dočasnej kópii priečinka (workspace/ sa nemení): Python, C a C++ "
                "(s kompiláciou), JavaScript (Node.js) a HTML (headless prehliadač: chyby konzoly, chýbajúce súbory, "
                "text stránky a screenshot). Vidí výstup, chyby kompilátora aj chybové hlásenia, takže kód vie "
                "testovať a opravovať. Čo je na tomto PC dostupné, ukáže `sandbox_info`.",
    warning="⚠️ V režime „local“ beží kód ako tvoj používateľ na tomto počítači (čistá kópia + časový a výstupný "
            "limit, ale nie vzdialený od systému). Pre skutočnú izoláciu nastav v config.py SANDBOX_MODE = \"docker\".",
    tools=(
        Tool("run_code",
             'path="subor.py|.c|.cpp|.js|.html" [stdin="vstupy; nový riadok ako \\n"] [args="argumenty"] – spustí '
             'súbor (C/C++ najprv skompiluje, HTML otvorí v headless prehliadači) a vráti výstup a chyby. Program '
             's input()/scanf/menu SPÚŠŤAJ so stdin (napr. stdin="1\\n5\\n0"); nikdy netvrď, že ho nejde spustiť',
             '<tool name="run_code" path="kalkulacka/main.c"/>', _run,
             params=(Param("path", "súbor vo workspace/ (.py .c .cpp .js .html)"),
                     Param("stdin", "vstupy pre program; nový riadok ako \\n", required=False),
                     Param("args", "argumenty príkazového riadka", required=False))),
        Tool("run_tests", '[path="priecinok_projektu"] – spustí unit testy projektu (tests/test*.py, unittest) v dočasnej kópii a '
                          'vráti, ktoré prešli a ktoré nie. Spusti po KAŽDEJ zmene existujúceho projektu',
             '<tool name="run_tests" path="todo_aplikacia"/>', _tests,
             params=(Param("path", "priečinok projektu (bez parametra celý workspace)", required=False),)),
        Tool("sandbox_info", "bez argumentov – ukáže, ktoré jazyky (kompilátory, Node.js, prehliadač) sú na tomto PC k dispozícii",
             '<tool name="sandbox_info"/>', _info),
    ),
)
