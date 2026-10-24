"""🌐 Web search (automatic in normal chats, a tool in agent chats)."""
from config import TOOL_RESULT_MAX
from core.skills import Param, Skill, Tool, ToolError
from core.web_search import search


def _search(args, body, ctx):
    query = args.get("query") or body.strip()
    if not query:
        raise ToolError("web_search potrebuje argument query.")
    res = search(query)
    if not res.ok:
        raise ToolError(f"Vyhľadávanie sa nepodarilo: {res.error}")
    return res.as_text()[:TOOL_RESULT_MAX]


def _fetch(args, body, ctx):
    from core.research import fetch_page
    url = (args.get("url") or body or "").strip()
    if not url.startswith(("http://", "https://")):
        raise ToolError("fetch_url potrebuje úplnú adresu url=\"https://…\".")
    text = fetch_page(url, TOOL_RESULT_MAX)
    if not text:
        raise ToolError("Stránku sa nepodarilo prečítať (nie je HTML, vyžaduje prihlásenie, je blokovaná, alebo vedie "
                        "na lokálnu / súkromnú adresu).")
    return text


SKILL = Skill(
    id="web_search", icon="🌐", name="Webové vyhľadávanie", order=40,
    short="Aktuálne správy a informácie z webu",
    description="V normálnom chate sa web prehľadá automaticky, keď otázka vyzerá, že potrebuje "
                "aktuálne dáta (alebo vždy, ak zapneš „Vždy hľadať na webe“). Agent ho dostane ako nástroj.",
    tools=(
        Tool("web_search", 'query="hľadaný výraz" – vráti výsledky z DuckDuckGo',
             '<tool name="web_search" query="najnovšia verzia pythonu"/>', _search,
             params=(Param("query", "hľadaný výraz"),)),
        Tool("fetch_url", 'url="https://…" – prečíta text jednej webovej stránky (použi po web_search na zdroj, ktorý ťa zaujal)',
             '<tool name="fetch_url" url="https://docs.python.org/3/library/zipfile.html"/>', _fetch,
             params=(Param("url", "úplná adresa stránky"),)),
    ),
)
