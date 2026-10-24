"""📋 Task plan: the agent writes a checklist first and ticks steps off while it works."""
from core import plan
from core.skills import Param, Skill, Tool, ToolError


def _set(args, body, ctx):
    steps = plan.parse_steps(body)
    if len(steps) < 2:
        raise ToolError("plan_set potrebuje aspoň 2 kroky, každý na samostatnom riadku v tele značky.")
    ctx.plan[:] = steps
    plan.save(ctx.chat_id, ctx.plan)
    return "Plán uložený:\n" + plan.render(ctx.plan)


def _done(args, body, ctx):
    if not ctx.plan:
        raise ToolError("Plán ešte neexistuje – najprv zavolaj plan_set.")
    idx = plan.parse_numbers(args.get("step", "") or body, len(ctx.plan))
    if not idx:
        raise ToolError(f"Zadaj číslo hotového kroku (1 – {len(ctx.plan)}), napr. step=\"2\".")
    for i in idx:
        ctx.plan[i]["done"] = True
    plan.save(ctx.chat_id, ctx.plan)
    text = plan.render(ctx.plan)
    if not plan.pending(ctx.plan):
        text += "\nVšetky kroky sú hotové – over výsledok a odpovedz používateľovi."
    return text


SKILL = Skill(
    id="planning", icon="📋", name="Plán úlohy", order=8, scope="agent",
    short="Agent si napíše plán a odškrtáva kroky",
    description="Pri úlohe s viacerými krokmi si agent najprv napíše zoznam krokov, uloží ho (workspace/.plan) a "
                "odškrtáva ho. Plán vidí pri každom kroku, takže sa nestratí ani pri dlhej práci, a agent "
                "neskončí, kým nie sú kroky hotové.",
    tools=(
        Tool("plan_set", "kroky plánu, každý na jeden riadok v tele značky (3 – 8 krátkych krokov)",
             '<tool name="plan_set">\nVytvoriť modul s výpočtami\nVytvoriť hlavný program s menu\nSpustiť a overiť\n</tool>', _set,
             params=(Param("steps", "kroky plánu, každý na samostatnom riadku (3 – 8 krátkych krokov)"),), body="steps"),
        Tool("plan_done", 'step="číslo" – označí krok(y) ako hotové (napr. step="2" alebo step="1,2")',
             '<tool name="plan_done" step="1"/>', _done,
             params=(Param("step", "číslo hotového kroku, napr. 2 alebo 1,2"),)),
    ),
)
