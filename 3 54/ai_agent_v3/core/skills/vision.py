"""👁 Image recognition (vision model)."""
from core import workspace
from core.ollama_client import OllamaError
from core.router import RoutingError
from core.skills import Param, Skill, Tool, ToolError
from core.vision import describe_bytes


def _describe(args, body, ctx):
    try:
        data = workspace.safe_path(args.get("path", "")).read_bytes()
        return describe_bytes(ctx.node, data, body.strip() or "")
    except (workspace.WorkspaceError, OSError) as e:
        raise ToolError(str(e))
    except (RoutingError, OllamaError) as e:
        raise ToolError(str(e))


SKILL = Skill(
    id="vision", icon="👁", name="Rozpoznávanie obrázkov", order=50,
    short="Popis a analýza priložených obrázkov",
    description="Povolí prikladať obrázky. V normálnom chate odpovedá priamo vision model, v agent chate "
                "sa obrázok najprv popíše a agent s popisom pracuje. Potrebuje vision model (config.py).",
    tools=(
        Tool("describe_image", 'path="obrazok.png" [otázka v tele] – popíše obrázok z workspace',
             '<tool name="describe_image" path="foto.png"/>', _describe,
             params=(Param("path", "obrázok vo workspace/"),
                     Param("question", "voliteľná otázka k obrázku", required=False)), body="question"),
    ),
)
