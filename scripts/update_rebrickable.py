"""Rebrickable database update script.

Downloads the latest CSV files from Rebrickable and upserts them into
the database. Existing user data (users, user_sets, user_set_parts) is
never touched. Designed to run as a Railway cron job.
"""

import io
import logging
import zipfile
from email.utils import parsedate_to_datetime
from pathlib import Path

import httpx
import pandas as pd
from sqlalchemy import String, text
from sqlalchemy.dialects.postgresql import insert

from database import SessionLocal
from models.models import (
    Colors,
    Elements,
    Inventories,
    InventoryMinifigs,
    InventoryParts,
    InventorySets,
    MinifigImages,
    Minifigs,
    PartCategories,
    PartImages,
    PartRelationships,
    Parts,
    SetImages,
    Sets,
    Themes,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)-8s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)

REBRICKABLE_BASE_URL = "https://cdn.rebrickable.com/media/downloads/"
LAST_MODIFIED_FILE = Path(__file__).parent / "last_modified.txt"

REBRICKABLE_TABLES = [
    (PartCategories, "part_categories.csv"),
    (Colors, "colors.csv"),
    (Themes, "themes.csv"),
    (Parts, "parts.csv"),
    (Elements, "elements.csv"),
    (Minifigs, "minifigs.csv"),
    (Sets, "sets.csv"),
    (Inventories, "inventories.csv"),
    (InventoryParts, "inventory_parts.csv"),
    (InventorySets, "inventory_sets.csv"),
    (InventoryMinifigs, "inventory_minifigs.csv"),
    (PartRelationships, "part_relationships.csv"),
]

# columns: de kolommen die we extraheren uit de hoofd-CSV
# pk_cols: de PK van de image-tabel zelf (voor drop_duplicates)
IMAGE_TABLE_MAP = {
    "inventory_parts": (
        PartImages,
        ["part_num", "color_id", "img_url"],
        ["part_num", "color_id"],
    ),
    "minifigs": (MinifigImages, ["fig_num", "img_url"], ["fig_num"]),
    "sets": (SetImages, ["set_num", "img_url"], ["set_num"]),
}


def get_last_modified_on_web(client: httpx.Client) -> str | None:
    try:
        response = client.head(f"{REBRICKABLE_BASE_URL}sets.csv.zip")
        response.raise_for_status()
        return response.headers.get("Last-Modified")
    except Exception:
        logger.exception("Failed to get Last-Modified header from Rebrickable")
        return None


def get_last_modified_local() -> str | None:
    try:
        return LAST_MODIFIED_FILE.read_text(encoding="utf-8").strip()
    except FileNotFoundError:
        return None


def save_last_modified(value: str) -> None:
    LAST_MODIFIED_FILE.write_text(value, encoding="utf-8")


def update_available(client: httpx.Client) -> tuple[bool, str | None]:
    local = get_last_modified_local()
    web = get_last_modified_on_web(client)

    if web is None:
        logger.error("Could not determine web version — aborting update")
        return False, None

    if local is None:
        logger.info("No local version found — first run, update needed")
        return True, web

    local_dt = parsedate_to_datetime(local)
    web_dt = parsedate_to_datetime(web)

    if web_dt > local_dt:
        logger.info("New version available: %s > %s", web_dt, local_dt)
        return True, web

    logger.info("Already up to date (%s)", local_dt)
    return False, None


def download_csv(client: httpx.Client, filename: str) -> pd.DataFrame:
    url = f"{REBRICKABLE_BASE_URL}{filename}.zip"
    logger.info("Downloading %s", filename)
    response = client.get(url, timeout=60.0)
    response.raise_for_status()

    with zipfile.ZipFile(io.BytesIO(response.content)) as zf, zf.open(filename) as f:
        # Read everything as string first — we coerce types explicitly
        # per-column afterwards based on the SQLAlchemy model, so we
        # never rely on pandas' automatic dtype inference.
        return pd.read_csv(f, dtype=str, keep_default_na=True)


def extract_and_remove_image_urls(
    df: pd.DataFrame, table_name: str
) -> tuple[pd.DataFrame, pd.DataFrame | None]:
    """Split img_url uit de hoofdtabel naar een aparte image-DataFrame.

    Voor inventory_parts: dezelfde (part_num, color_id) kan meerdere keren
    voorkomen (verschillende inventory_id of is_spare). We dedupliceren op
    de PK van de image-tabel en houden de eerste rij met een echte URL.

    Returns (df_zonder_img_url, df_images | None)
    """
    if table_name not in IMAGE_TABLE_MAP or "img_url" not in df.columns:
        return df, None

    _, columns, pk_cols = IMAGE_TABLE_MAP[table_name]

    # Alleen rijen met een echte URL, dan dedupliceren op de image-tabel PK
    df_images = (
        df[columns]
        .dropna(subset=["img_url"])
        .drop_duplicates(subset=pk_cols, keep="first")
        .copy()
    )
    logger.info("Extracted %s unique image URLs from %s", len(df_images), table_name)

    df_main = df.drop(columns=["img_url"])
    return df_main, df_images


def coerce_dataframe_to_model(df: pd.DataFrame, model) -> pd.DataFrame:
    """Cast every column in df to match the actual DB column type on model.

    This is the key fix: pandas/CSV values arrive as strings (see
    download_csv), and here we convert each column to int, bool, or leave
    as string based on what the database column actually expects. This
    guarantees the bind parameters SQLAlchemy generates match the column
    type, avoiding "operator does not exist" errors from mismatched casts.
    """
    df = df.copy()
    columns = model.__table__.columns

    for col_name in df.columns:
        if col_name not in columns:
            continue
        col = columns[col_name]

        if isinstance(col.type, String):
            # Keep as string; turn the literal "nan" text back into None
            df[col_name] = df[col_name].where(df[col_name].notna(), None)
        else:
            # Numeric or boolean column: convert, coercing bad/empty values to NaN/None
            if str(col.type).upper() in ("BOOLEAN",):
                df[col_name] = df[col_name].map(
                    lambda v: (
                        None
                        if v is None or (isinstance(v, float) and pd.isna(v))
                        else str(v).strip().lower() in ("true", "t", "1", "yes")
                    )
                )
            else:
                df[col_name] = pd.to_numeric(df[col_name], errors="coerce")
                # Convert to pandas nullable Int64 so NaN survives as <NA> not float
                if (
                    pd.api.types.is_float_dtype(df[col_name])
                    and (df[col_name].dropna() % 1 == 0).all()
                ):
                    df[col_name] = df[col_name].astype("Int64")

    return df


def get_primary_keys(model) -> list[str]:
    return [col.name for col in model.__table__.primary_key.columns]


def dataframe_to_records(df: pd.DataFrame) -> list[dict]:
    """Convert a coerced DataFrame to a list of plain-Python dicts,
    turning pandas NA/NaT/NaN into None for every cell.
    """
    records = df.to_dict(orient="records")
    for record in records:
        for key, value in record.items():
            if value is None:
                continue
            if isinstance(value, float) and pd.isna(value) or value is pd.NA:
                record[key] = None
            elif hasattr(value, "item"):  # numpy scalar (Int64, etc.) -> native Python
                record[key] = value.item()
    return records


def upsert_dataframe(session, model, df: pd.DataFrame) -> None:
    """Upsert DataFrame into model table without committing.

    Commit happens in run_update() after both main and image tables.
    """
    if df.empty:
        logger.warning("Empty DataFrame for %s — skipping", model.__tablename__)
        return

    df = coerce_dataframe_to_model(df, model)
    records = dataframe_to_records(df)
    primary_keys = get_primary_keys(model)

    chunk_size = 10000
    total = len(records)
    for i in range(0, total, chunk_size):
        chunk = records[i : i + chunk_size]

        # BUILD STATEMENT FRESH VOOR ELKE CHUNK
        stmt = insert(model.__table__).values(chunk)

        update_cols = {
            col.name: stmt.excluded[col.name]
            for col in model.__table__.columns
            if col.name not in primary_keys
        }

        if update_cols:
            stmt = stmt.on_conflict_do_update(
                index_elements=primary_keys, set_=update_cols
            )
        else:
            stmt = stmt.on_conflict_do_nothing()

        session.execute(stmt, execution_options={"synchronize_session": False})
        logger.info(
            "Upserted %s/%s rows into %s",
            min(i + chunk_size, total),
            total,
            model.__tablename__,
        )


def delete_removed_rows(session, model, df: pd.DataFrame) -> None:
    """Delete rows no longer present in the CSV, using a temp table to
    avoid both huge IN-clauses and bind-type mismatches: everything is
    compared as TEXT on both sides, regardless of the column's real type.
    """
    skip_delete = {"inventory_parts", "inventories", "parts", "colors", "minifigs"}
    if model.__tablename__ in skip_delete:
        logger.info(
            "Skipping delete for %s (referenced by user data)", model.__tablename__
        )
        return

    primary_keys = get_primary_keys(model)
    if len(primary_keys) != 1:
        logger.info("Skipping delete for %s (composite PK)", model.__tablename__)
        return

    pk = primary_keys[0]
    table = model.__tablename__

    if pk not in df.columns:
        logger.warning(
            "PK column %s not found in CSV for %s — skipping delete", pk, table
        )
        return

    current_ids = [str(v) for v in df[pk].tolist() if pd.notna(v)]
    if not current_ids:
        logger.warning(
            "No current IDs found for %s — skipping delete to avoid wiping table", table
        )
        return

    session.execute(text("DROP TABLE IF EXISTS _tmp_current_ids"))
    session.execute(text("CREATE TEMP TABLE _tmp_current_ids (id TEXT)"))

    chunk_size = 10000
    for i in range(0, len(current_ids), chunk_size):
        chunk = current_ids[i : i + chunk_size]
        placeholders = ", ".join(f"(:v{j})" for j in range(len(chunk)))
        session.execute(
            text(f"INSERT INTO _tmp_current_ids (id) VALUES {placeholders}"),
            {f"v{j}": v for j, v in enumerate(chunk)},
        )

    result = session.execute(
        text(
            f'DELETE FROM {table} WHERE "{pk}"::TEXT NOT IN (SELECT id FROM _tmp_current_ids)'
        )
    )
    deleted = result.rowcount
    if deleted:
        logger.info("Deleted %s removed rows from %s", deleted, table)

    session.execute(text("DROP TABLE IF EXISTS _tmp_current_ids"))


def run_update() -> None:
    client = httpx.Client(timeout=30.0)

    available, web_timestamp = update_available(client)
    if not available:
        return

    session = SessionLocal()

    try:
        # DISABLE FOREIGN KEY CHECKS DURING SYNC
        session.execute(text("SET session_replication_role = 'replica'"))
        session.commit()

        for model, filename in REBRICKABLE_TABLES:
            logger.info("Processing %s", filename)

            df = download_csv(client, filename)
            df, df_images = extract_and_remove_image_urls(df, model.__tablename__)

            if model.__tablename__ == "themes":
                df["_parent_sort"] = pd.to_numeric(df["parent_id"], errors="coerce")
                df = df.sort_values("_parent_sort", na_position="first").drop(
                    columns=["_parent_sort"]
                )

            # Upsert main table
            upsert_dataframe(session, model, df)
            delete_removed_rows(session, model, df)

            # Upsert image table if it exists
            if df_images is not None:
                image_model, _, _ = IMAGE_TABLE_MAP[model.__tablename__]
                upsert_dataframe(session, image_model, df_images)
                delete_removed_rows(session, image_model, df_images)

            # Commit after each table is processed
            session.commit()

        # RE-ENABLE FOREIGN KEY CHECKS
        session.execute(text("SET session_replication_role = 'origin'"))
        session.commit()

        save_last_modified(web_timestamp)
        logger.info("Update complete")

    except Exception:
        logger.exception("Update failed — rolling back")
        session.rollback()
        raise

    finally:
        session.close()
        client.close()


if __name__ == "__main__":
    run_update()
