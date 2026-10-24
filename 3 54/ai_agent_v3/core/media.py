"""Image helpers: downscale uploads, encode for Ollama."""
import base64
import io

from config import BASE_DIR, MAX_IMAGE_SIDE


def prepare_image(data: bytes) -> bytes:
    """Fix rotation, downscale and re-encode as JPEG (smaller = faster for the vision model)."""
    try:
        from PIL import Image, ImageOps
        im = ImageOps.exif_transpose(Image.open(io.BytesIO(data)))
        im.thumbnail((MAX_IMAGE_SIDE, MAX_IMAGE_SIDE))
        buf = io.BytesIO()
        im.convert("RGB").save(buf, "JPEG", quality=90)
        return buf.getvalue()
    except Exception:
        return data


def resolve_upload(rel_path: str):
    return BASE_DIR / rel_path


def encode_b64(rel_path: str) -> str:
    return base64.b64encode(resolve_upload(rel_path).read_bytes()).decode("ascii")
