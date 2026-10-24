"""🤝 Cluster collaboration of both PCs."""
from config import TOOL_RESULT_MAX
from core import workspace
from core.cluster import run_cluster
from core.skills import Param, Skill, Tool, ToolError


def _solve(args, body, ctx):
    goal = body.strip() or args.get("goal", "")
    if not goal:
        raise ToolError("cluster_solve potrebuje zadanie v tele značky.")
    final, error = "", ""
    for ev in run_cluster(goal, ctx.temperature, context=ctx.history):
        if ctx.on_event:
            ctx.on_event(ev)                                   # live stages in the UI
        if ev["type"] == "final":
            final = ev["text"]
        elif ev["type"] == "error":
            error = ev["text"]
    if not final:
        raise ToolError(error or "Klaster nevrátil výsledok.")
    # The result goes straight to files (named after the topic) - the agent never has to copy long code.
    saved = workspace.save_generated_code(final, goal, workspace.wanted_files(goal))
    for rel in saved:
        ctx.mark_written(rel)
    if saved:
        can_run = "run_code" in ctx.enabled
        advice = ("Spusti hlavný súbor (run_code) a zhrň výsledok používateľovi." if can_run else
                  "Každý súbor prečítaj NAJVIAC RAZ (read_file) a hneď potom odpovedz používateľovi zhrnutím. "
                  "Kód spustiť nemôžeš (run_code je vypnutý), preto v odpovedi uveď, že nebol spustený.")
        return ("Klaster dokončil prácu (plán → kód → recenzia → finál). Uložené súbory: "
                + ", ".join(saved) + ". " + advice)
    return final[:TOOL_RESULT_MAX]                              # no code blocks: it was a text answer


SKILL = Skill(
    id="cluster", icon="🤝", name="Klastrová spolupráca", order=60, default=False, mode=True,
    short="Obe PC spolu: plán → kód → recenzia",
    description="Keď je zapnutá, každá správa v normálnom chate prejde pipeline: architekt vypracuje plán, "
                "programátor napíše kód, recenzent ho skontroluje a vylepší (PC a model pre každú rolu vyberieš sám). V agent chate ho agent pri kódovaní používa "
                "automaticky ako nástroj cluster_solve, výsledok uloží rovno do súborov a etapy vidíš naživo.",
    tools=(
        Tool("cluster_solve", "zadanie v tele značky – obe PC spolu navrhnú kód; výsledok sa uloží do súborov",
             '<tool name="cluster_solve">\nNapíš skript na zálohu priečinka do ZIP\n</tool>', _solve,
             params=(Param("goal", "zadanie, čo majú obe PC spolu navrhnúť a napísať"),), body="goal"),
    ),
)
