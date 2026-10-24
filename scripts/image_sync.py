"""Sync Rebrickable images (minifigs, sets, parts) to Cloudflare R2.

Bron: de tabellen minifig_images / set_images / part_images (img_url).
Administratie: de tabel image_status (één rij per R2-key).

Een afbeelding is "aan de beurt" als:
  - er nog geen rij in image_status bestaat voor de R2-key, of
  - de status 'error' is (wordt telkens opnieuw geprobeerd), of
  - de status 'not_found' is en de laatste check ouder is dan --retry-not-found-days, of
  - de img_url in de image-tabel verschilt van source_url in image_status
    (Rebrickable heeft de afbeelding vervangen).

Elke afbeelding wordt voor het uploaden verkleind (langste zijde max. --max-side
pixels, nooit vergroot) en als JPEG opgeslagen (--quality). De maat zit in de
R2-key: minifigs/w300/fig-000001.jpg. Een andere maat betekent dus een andere
map en een verse set taken, en de oude bestanden blijven ongemoeid.

Het script is idempotent: opnieuw draaien kan nooit kwaad.

Gebruik (vanuit de rootmap van het project):
    uv run python scripts/image_sync.py --kind minifigs --limit 10 --dry-run
    uv run python scripts/image_sync.py --kind minifigs --limit 10
    uv run python scripts/image_sync.py --kind parts --max-side 300 --quality 85

Vereist in .env (of als environment variables op Railway):
    R2_ACCOUNT_ID, R2_ACCESS_KEY_ID, R2_SECRET_ACCESS_KEY, R2_BUCKET
plus de database-configuratie die database.py al gebruikt.
"""

import argparse
import io
import logging
import os
import re
import sys
import time
from datetime import UTC, datetime
from pathlib import Path

# Zorgt dat "from database import ..." werkt, ook als je het script rechtstreeks
# vanuit de scripts-map start.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

try:
    from dotenv import load_dotenv

    load_dotenv()
except (
    ImportError
):  # python-dotenv is optioneel (op Railway staan de variabelen al in de omgeving)
    pass

import boto3
import httpx
from botocore.config import Config
from PIL import Image, ImageOps
from sqlalchemy import text
from sqlalchemy.dialects.postgresql import insert

from database import SessionLocal
from models.models import ImageStatus

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)-8s] %(name)s: %(message)s",
)
logger = logging.getLogger("image_sync")

# Constanten (geen gebruikersinvoer, dus veilig om in SQL te gebruiken).
KINDS = {
    "minifigs": {
        "table": "minifig_images",
        "id_expr": "img.fig_num",
        "folder": "minifigs",
    },
    "sets": {
        "table": "set_images",
        "id_expr": "img.set_num",
        "folder": "sets",
    },
    # Sleutel = onderdeelnummer + kleur, bv. parts/w300/3001_5.jpg
    "parts": {
        "table": "part_images",
        "id_expr": "img.part_num || '_' || img.color_id",
        "folder": "parts",
    },
}

# Een id mag enkel URL-veilige tekens bevatten, anders zou de afbeeldings-URL
# kunnen breken (bv. bij een '#' of '?'). Afwijkende ids krijgen status 'error'.
SAFE_ID = re.compile(r"[A-Za-z0-9._-]+")

USER_AGENT = "PieceHunt-image-sync/1.0 (non-commercial LEGO set completion app)"
CACHE_CONTROL = "public, max-age=31536000, immutable"
MIN_IMAGE_BYTES = 500  # kleiner dan dit is vrijwel zeker geen echte afbeelding
# Worden naar JPEG omgezet. MPO is een JPEG-variant (camera's); we maken er een
# standaard JPEG van met enkel het eerste beeld.
CONVERTIBLE_FORMATS = {"PNG", "WEBP", "GIF", "MPO"}
MAX_429_RETRIES = 3
DEFAULT_MAX_SIDE = 300  # 2x de weergavegrootte van 150 px, voor scherpe schermen
DEFAULT_QUALITY = 85


# --------------------------------------------------------------------------
# R2
# --------------------------------------------------------------------------
def make_r2_client():
    missing = [
        name
        for name in (
            "R2_ACCOUNT_ID",
            "R2_ACCESS_KEY_ID",
            "R2_SECRET_ACCESS_KEY",
            "R2_BUCKET",
        )
        if not os.environ.get(name)
    ]
    if missing:
        logger.error("Ontbrekende environment variables: %s", ", ".join(missing))
        sys.exit(1)

    return boto3.client(
        "s3",
        endpoint_url=f"https://{os.environ['R2_ACCOUNT_ID']}.r2.cloudflarestorage.com",
        aws_access_key_id=os.environ["R2_ACCESS_KEY_ID"],
        aws_secret_access_key=os.environ["R2_SECRET_ACCESS_KEY"],
        region_name="auto",
        config=Config(retries={"max_attempts": 3, "mode": "standard"}),
    )


def upload_to_r2(r2, key: str, data: bytes) -> None:
    r2.put_object(
        Bucket=os.environ["R2_BUCKET"],
        Key=key,
        Body=data,
        ContentType="image/jpeg",
        CacheControl=CACHE_CONTROL,
    )


# --------------------------------------------------------------------------
# Taken ophalen
# --------------------------------------------------------------------------
def fetch_tasks(
    session, kind: str, prefix: str, limit: int | None, retry_not_found_days: int
):
    cfg = KINDS[kind]
    table, id_expr = cfg["table"], cfg["id_expr"]

    sql = f"""
        SELECT {id_expr} AS ident,
               img.img_url AS img_url,
               '{prefix}' || {id_expr} || '.jpg' AS r2_key
        FROM {table} img
        LEFT JOIN image_status s
               ON s.r2_key = '{prefix}' || {id_expr} || '.jpg'
        WHERE img.img_url IS NOT NULL
          AND (
                s.r2_key IS NULL
             OR s.source_url IS DISTINCT FROM img.img_url
             OR s.status = 'error'
             OR (s.status = 'not_found'
                 AND s.checked_at < now() - make_interval(days => :days))
          )
        ORDER BY (s.r2_key IS NULL) DESC, {id_expr}
    """
    params = {"days": retry_not_found_days}
    if limit:
        sql += " LIMIT :limit"
        params["limit"] = limit

    return session.execute(text(sql), params).mappings().all()


# --------------------------------------------------------------------------
# Downloaden + valideren
# --------------------------------------------------------------------------
def download(client: httpx.Client, url: str) -> tuple[str, bytes | None, str | None]:
    """Geeft (status, data, error) terug.

    status: 'ok' | 'not_found' | 'error'
    """
    for attempt in range(MAX_429_RETRIES + 1):
        try:
            response = client.get(url)
        except httpx.HTTPError as exc:
            return "error", None, f"netwerkfout: {exc!r}"

        if response.status_code == 200:
            return "ok", response.content, None
        if response.status_code in (404, 410):
            return "not_found", None, f"HTTP {response.status_code}"
        if response.status_code == 429 and attempt < MAX_429_RETRIES:
            wait = int(response.headers.get("Retry-After", "30"))
            logger.warning("Rate limit (429), wacht %s s", wait)
            time.sleep(wait)
            continue
        return "error", None, f"HTTP {response.status_code}"

    return "error", None, "rate limit niet opgelost na meerdere pogingen"


def prepare_jpeg(
    data: bytes, max_side: int, quality: int
) -> tuple[bytes | None, str | None]:
    """Geeft (jpeg_bytes, None) bij succes, of (None, foutmelding).

    Elke afbeelding wordt (indien nodig) verkleind tot de langste zijde max_side
    is, nooit vergroot, en als JPEG opgeslagen. Transparantie komt op een witte
    achtergrond. PNG, WebP, GIF en MPO worden zo ook naar JPEG omgezet, zodat
    elke R2-key deterministisch op .jpg eindigt.
    """
    if len(data) < MIN_IMAGE_BYTES:
        return None, f"bestand te klein ({len(data)} bytes)"
    try:
        with Image.open(io.BytesIO(data)) as source:
            fmt = source.format
            if fmt != "JPEG" and fmt not in CONVERTIBLE_FORMATS:
                return None, f"onverwacht formaat: {fmt}"

            source.load()

            # Een JPEG die al klein genoeg is en geen rotatie of kleurconversie
            # nodig heeft, blijft byte-voor-byte ongewijzigd: geen kwaliteitsverlies.
            if (
                fmt == "JPEG"
                and max(source.size) <= max_side
                and source.mode in ("RGB", "L")
                and source.getexif().get(0x0112, 1) in (0, 1)
            ):
                return data, None

            image = ImageOps.exif_transpose(source)  # respecteer EXIF-rotatie

            if image.mode in ("RGBA", "LA") or "transparency" in image.info:
                rgba = image.convert("RGBA")
                flat = Image.new("RGB", rgba.size, (255, 255, 255))
                flat.paste(rgba, mask=rgba.getchannel("A"))
            else:
                flat = image.convert("RGB")

            flat.thumbnail((max_side, max_side), Image.Resampling.LANCZOS)

            out = io.BytesIO()
            flat.save(out, format="JPEG", quality=quality, optimize=True)
            return out.getvalue(), None
    except Exception as exc:
        return None, f"geen geldige afbeelding: {exc!r}"


# --------------------------------------------------------------------------
# Status wegschrijven
# --------------------------------------------------------------------------
def save_status(
    session, r2_key: str, source_url: str, status: str, error: str | None = None
) -> None:
    now = datetime.now(UTC)
    stmt = insert(ImageStatus).values(
        r2_key=r2_key,
        source_url=source_url,
        status=status,
        checked_at=now,
        last_error=error,
    )
    stmt = stmt.on_conflict_do_update(
        index_elements=["r2_key"],
        set_={
            "source_url": stmt.excluded.source_url,
            "status": stmt.excluded.status,
            "checked_at": stmt.excluded.checked_at,
            "last_error": stmt.excluded.last_error,
        },
    )
    session.execute(stmt)
    session.commit()  # per afbeelding, zodat een onderbreking niets verliest


# --------------------------------------------------------------------------
# Hoofdlogica
# --------------------------------------------------------------------------
def process_kind(
    session,
    http: httpx.Client,
    r2,
    kind: str,
    limit: int | None,
    retry_not_found_days: int,
    delay: float,
    dry_run: bool,
    max_side: int,
    quality: int,
) -> dict:
    stats = {"uploaded": 0, "not_found": 0, "error": 0}

    prefix = f"{KINDS[kind]['folder']}/w{max_side}/"
    tasks = fetch_tasks(session, kind, prefix, limit, retry_not_found_days)
    logger.info("[%s] %s afbeeldingen aan de beurt (map %s)", kind, len(tasks), prefix)

    if dry_run:
        for task in tasks[:20]:
            logger.info("[dry-run] %s  <-  %s", task["r2_key"], task["img_url"])
        if len(tasks) > 20:
            logger.info("[dry-run] ... en nog %s meer", len(tasks) - 20)
        return stats

    for i, task in enumerate(tasks, start=1):
        key, url = task["r2_key"], task["img_url"]

        if not SAFE_ID.fullmatch(task["ident"]):
            error = "id bevat tekens die niet URL-veilig zijn"
            save_status(session, key, url, "error", error)
            stats["error"] += 1
            logger.warning("[%s] %s -> error (%s)", kind, key, error)
            continue

        status, data, error = download(http, url)

        if status == "ok":
            data, problem = prepare_jpeg(data, max_side, quality)
            if problem:
                status, error = "error", problem

        if status == "ok":
            try:
                upload_to_r2(r2, key, data)
            except Exception as exc:
                status, error = "error", f"R2-upload mislukt: {exc!r}"

        db_status = "uploaded" if status == "ok" else status
        save_status(session, key, url, db_status, error)

        stats["uploaded" if status == "ok" else status] += 1
        if status != "ok":
            logger.warning("[%s] %s -> %s (%s)", kind, key, status, error)

        if i % 50 == 0:
            logger.info("[%s] %s/%s verwerkt", kind, i, len(tasks))

        time.sleep(delay)

    return stats


def main() -> None:
    parser = argparse.ArgumentParser(description="Sync Rebrickable images naar R2")
    parser.add_argument(
        "--kind",
        choices=[*KINDS, "all"],
        default="all",
        help="welke soort afbeeldingen (default: all)",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="maximum aantal afbeeldingen per soort in deze run",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="toon wat er zou gebeuren, zonder te downloaden, uploaden of schrijven",
    )
    parser.add_argument(
        "--retry-not-found-days",
        type=int,
        default=7,
        help="probeer 'not_found' pas opnieuw na dit aantal dagen (default: 7)",
    )
    parser.add_argument(
        "--delay",
        type=float,
        default=0.3,
        help="pauze in seconden tussen twee downloads (default: 0.3)",
    )
    parser.add_argument(
        "--max-side",
        type=int,
        default=DEFAULT_MAX_SIDE,
        help=f"langste zijde in pixels, nooit vergroot (default: {DEFAULT_MAX_SIDE})",
    )
    parser.add_argument(
        "--quality",
        type=int,
        default=DEFAULT_QUALITY,
        help=f"JPEG-kwaliteit 1-100 (default: {DEFAULT_QUALITY})",
    )
    args = parser.parse_args()

    kinds = list(KINDS) if args.kind == "all" else [args.kind]

    r2 = None if args.dry_run else make_r2_client()
    http = httpx.Client(
        timeout=30.0, headers={"User-Agent": USER_AGENT}, follow_redirects=True
    )
    session = SessionLocal()

    totals = {"uploaded": 0, "not_found": 0, "error": 0}
    try:
        for kind in kinds:
            stats = process_kind(
                session,
                http,
                r2,
                kind,
                args.limit,
                args.retry_not_found_days,
                args.delay,
                args.dry_run,
                args.max_side,
                args.quality,
            )
            for k, v in stats.items():
                totals[k] += v
    except KeyboardInterrupt:
        logger.warning("Onderbroken — wat al verwerkt is, staat in image_status")
    finally:
        session.close()
        http.close()

    logger.info(
        "Klaar: %s geüpload, %s niet gevonden, %s fouten",
        totals["uploaded"],
        totals["not_found"],
        totals["error"],
    )


if __name__ == "__main__":
    main()

    # uv run python scripts/image_sync.py --kind parts --max-side 500 --quality 90 > parts_w500.log 2>&1
