"""🔬 Deep Research: plan -> web search + reading pages per step -> report with numbered sources (core/research.py)."""
from core.skills import Skill

SKILL = Skill(
    id="research", icon="🔬", name="Deep Research", order=62, default=False, mode=True, scope="both",
    short="Plán → hľadanie na webe → správa so zdrojmi",
    description="Keď je zapnutý, každá správa (v normálnom aj agent chate) prejde výskumom: model navrhne plán krokov, pre každý krok "
                "vyhľadá na webe a prečíta stránky, zapíše poznámky a nakoniec napíše správu s číslovanými zdrojmi. "
                "Karta výskumu ukazuje kroky a priebeh; plán môžeš pred štartom skontrolovať a neskôr upraviť (✏️ Update). "
                "Správa vychádza len z toho, čo web naozaj vrátil – ak vyhľadávanie nefunguje, nič sa nevymýšľa. "
                "V agent chate sa správa uloží aj ako súbor vyskum_….md do workspace/ (agent ho potom vie prečítať). Úroveň premýšľania (u gpt-oss Low / Medium / High) sa berie z tlačidiel pod chatom.",
)
