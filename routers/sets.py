import logging
from collections import defaultdict

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import case, func, insert, select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session, joinedload, selectinload

from database import get_db
from dependencies import get_current_verified_user
from models.models import (
    Elements,
    Inventories,
    InventoryMinifigs,
    InventoryParts,
    MinifigImages,
    PartImages,
    SetImages,
    Sets,
    UserSetParts,
    UserSets,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/sets", tags=["sets"])


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _get_active_inventory(db: Session, normalized_set_num: str):
    """Latest inventory version for a set, with parts/minifigs eager loaded."""
    return (
        db.query(Inventories)
        .options(
            selectinload(Inventories.inventory_parts),
            selectinload(Inventories.inventory_minifigs).selectinload(
                InventoryMinifigs.minifig
            ),
        )
        .filter_by(set_num=normalized_set_num)
        .order_by(Inventories.version.desc())
        .first()
    )


def _iter_user_set_parts(user_set_id, parts, inv_id, minifig_num=None):
    for part in parts:
        yield UserSetParts(
            user_set_id=user_set_id,
            inventory_id=part.inventory_id,
            part_num=part.part_num,
            color_id=part.color_id,
            is_spare=part.is_spare,
            quantity_have=0,
            minifig_num=minifig_num,
            minifig_id=inv_id if minifig_num else None,
        )


def _chunks(items, size=500):
    for i in range(0, len(items), size):
        yield items[i : i + size]


def _build_part_rows(user_set_id, parts, minifig_inv_id=None, minifig_num=None):
    """Plain dicts voor een bulk insert (geen ORM-objecten)."""
    return [
        {
            "user_set_id": user_set_id,
            "inventory_id": part.inventory_id,
            "part_num": part.part_num,
            "color_id": part.color_id,
            "is_spare": part.is_spare,
            "quantity_have": 0,
            "minifig_num": minifig_num,
            "minifig_id": minifig_inv_id if minifig_num else None,
        }
        for part in parts
    ]


# ---------------------------------------------------------------------------
# Existing: set status check
# ---------------------------------------------------------------------------


@router.get("/{set_num}/status")
def get_set_status(
    set_num: str, user=Depends(get_current_verified_user), db: Session = Depends(get_db)
):
    normalized_set_num = f"{set_num}-1"

    set_obj = db.query(Sets).filter_by(set_num=normalized_set_num).first()
    if not set_obj:
        raise HTTPException(status_code=404, detail=f"Set: {set_num} not found")

    already_added = (
        db.query(UserSets)
        .filter_by(user_id=user.id, set_num=normalized_set_num)
        .first()
        is not None
    )

    return {
        "already_added": already_added,
        "set": {
            "set_num": set_obj.set_num,
            "name": set_obj.name,
        },
    }


# ---------------------------------------------------------------------------
# New: add a set (replaces add_set()'s DB portion + active_inventory())
# ---------------------------------------------------------------------------


@router.post("/{set_num}")
def add_user_set(
    set_num: str,
    user=Depends(get_current_verified_user),
    db: Session = Depends(get_db),
):
    """Creates a UserSets row + all UserSetParts (set + every minifig's parts)."""

    normalized_set_num = f"{set_num}-1"

    set_obj = db.query(Sets).filter_by(set_num=normalized_set_num).first()
    if not set_obj:
        raise HTTPException(status_code=404, detail=f"Set: {set_num} not found")

    already_added = (
        db.query(UserSets)
        .filter_by(user_id=user.id, set_num=normalized_set_num)
        .first()
    )
    if already_added:
        raise HTTPException(status_code=409, detail=f"Set: {set_num} is already added")

    active_inventory = _get_active_inventory(db, normalized_set_num)
    if not active_inventory:
        raise HTTPException(status_code=404, detail="No inventory found for this set")

    set_info = {"set_num": set_obj.set_num, "name": set_obj.name}
    user_id = user.id
    active_inventory_id = active_inventory.id

    minifig_list = [m.fig_num for m in active_inventory.inventory_minifigs]

    try:
        new_set = UserSets(user_id=user_id, set_num=normalized_set_num)
        db.add(new_set)
        db.flush()
        new_set_id = new_set.id

        rows = _build_part_rows(new_set_id, active_inventory.inventory_parts)

        minifig_invs = {}
        if minifig_list:
            invs = db.scalars(
                select(Inventories)
                .options(selectinload(Inventories.inventory_parts))
                .where(Inventories.set_num.in_(minifig_list))
                .order_by(Inventories.version)
            ).all()
            for inv in invs:
                minifig_invs[inv.set_num] = inv

        for fig_num in minifig_list:
            minifig_inventory = minifig_invs.get(fig_num)
            if minifig_inventory:
                rows.extend(
                    _build_part_rows(
                        new_set_id,
                        minifig_inventory.inventory_parts,
                        minifig_inv_id=active_inventory_id,
                        minifig_num=fig_num,
                    )
                )

        if rows:
            db.execute(insert(UserSetParts), rows)  # bulk insert
        db.commit()

    except SQLAlchemyError as e:
        db.rollback()
        logger.exception(
            "Failed to add set %s for user %s", normalized_set_num, user_id
        )
        raise HTTPException(status_code=500, detail="Error while saving set") from e

    part_keys = {(r["part_num"], r["color_id"]) for r in rows}
    part_nums = list({pn for pn, _ in part_keys})

    part_images = {}
    element_ids_map = defaultdict(list)

    for chunk in _chunks(part_nums):
        for r in db.execute(
            select(PartImages.part_num, PartImages.color_id, PartImages.img_url).where(
                PartImages.part_num.in_(chunk)
            )
        ):
            if (r.part_num, r.color_id) in part_keys:
                part_images[(r.part_num, r.color_id)] = r.img_url

        for r in db.execute(
            select(Elements.part_num, Elements.color_id, Elements.element_id).where(
                Elements.part_num.in_(chunk)
            )
        ):
            if (r.part_num, r.color_id) in part_keys:
                element_ids_map[(r.part_num, r.color_id)].append(r.element_id)

    minifig_images = {}
    for chunk in _chunks(minifig_list):
        for r in db.execute(
            select(MinifigImages.fig_num, MinifigImages.img_url).where(
                MinifigImages.fig_num.in_(chunk)
            )
        ):
            minifig_images[r.fig_num] = r.img_url

    set_img_url = db.execute(
        select(SetImages.img_url).where(SetImages.set_num == normalized_set_num)
    ).scalar_one_or_none()

    parts = [
        {
            "part_num": r["part_num"],
            "color_id": r["color_id"],
            "img_url": part_images.get((r["part_num"], r["color_id"])),
            "element_ids": element_ids_map.get((r["part_num"], r["color_id"]), []),
        }
        for r in rows
    ]

    minifigs = [
        {"fig_num": fig_num, "img_url": minifig_images.get(fig_num)}
        for fig_num in minifig_list
    ]

    logger.info("Set %s added for user %s", normalized_set_num, user_id)

    return {
        "user_set_id": new_set_id,
        "set": set_info,
        "set_img_url": set_img_url,
        "parts": parts,
        "minifigs": minifigs,
    }


# ---------------------------------------------------------------------------
# New: list current user's sets with progress (replaces get_all_user_sets)
# ---------------------------------------------------------------------------


@router.get("/mine")
def get_my_sets(
    include_spares: bool = True,
    user=Depends(get_current_verified_user),
    db: Session = Depends(get_db),
):
    user_sets = (
        db.query(UserSets)
        .options(selectinload(UserSets.set))
        .filter_by(user_id=user.id)
        .all()
    )

    if not user_sets:
        return []

    user_set_ids = [us.id for us in user_sets]

    multiplier = case(
        (UserSetParts.minifig_num.isnot(None), InventoryMinifigs.quantity),
        else_=1,
    )

    stmt = (
        select(
            UserSetParts.user_set_id,
            func.coalesce(func.sum(InventoryParts.quantity * multiplier), 0).label(
                "total"
            ),
            func.coalesce(func.sum(UserSetParts.quantity_have), 0).label("found"),
        )
        .select_from(UserSetParts)
        .join(
            InventoryParts,
            (InventoryParts.inventory_id == UserSetParts.inventory_id)
            & (InventoryParts.part_num == UserSetParts.part_num)
            & (InventoryParts.color_id == UserSetParts.color_id)
            & (InventoryParts.is_spare == UserSetParts.is_spare),
        )
        .outerjoin(
            InventoryMinifigs,
            (InventoryMinifigs.inventory_id == UserSetParts.minifig_id)
            & (InventoryMinifigs.fig_num == UserSetParts.minifig_num),
        )
        .where(UserSetParts.user_set_id.in_(user_set_ids))
        .group_by(UserSetParts.user_set_id)
    )

    if not include_spares:
        stmt = stmt.where(UserSetParts.is_spare.is_(False))

    progress_map = {row.user_set_id: row for row in db.execute(stmt)}

    result = []
    for user_set in user_sets:
        progress = progress_map.get(user_set.id)
        total = progress.total if progress else 0
        found = progress.found if progress else 0
        progress_pct = int((found / total) * 100) if total > 0 else 0

        result.append(
            {
                "user_set_id": user_set.id,
                "set_num": user_set.set_num,
                "set_name": user_set.set.name,
                "completed": user_set.completed,
                "started_at": user_set.started_at,
                "total_parts": total,
                "found_parts": found,
                "progress_pct": progress_pct,
            }
        )

    return result


# ---------------------------------------------------------------------------
# New: get / delete a single user set (both now check ownership!)
# ---------------------------------------------------------------------------


@router.get("/{user_set_id}")
def get_user_set(
    user_set_id: int,
    user=Depends(get_current_verified_user),
    db: Session = Depends(get_db),
):
    user_set = (
        db.query(UserSets)
        .options(joinedload(UserSets.set))
        .filter_by(id=user_set_id, user_id=user.id)
        .first()
    )

    if user_set is None:
        raise HTTPException(status_code=404, detail=f"Userset {user_set_id} not found")

    return {
        "id": user_set.id,
        "set_num": user_set.set_num,
        "completed": user_set.completed,
        "started_at": user_set.started_at,
        "name": user_set.set.name,
    }


@router.delete("/{user_set_id}")
def delete_user_set(
    user_set_id: int,
    user=Depends(get_current_verified_user),
    db: Session = Depends(get_db),
):
    set_to_delete = (
        db.query(UserSets).filter_by(id=user_set_id, user_id=user.id).first()
    )
    if set_to_delete is None:
        raise HTTPException(
            status_code=404, detail=f"Set with id: {user_set_id} was not found"
        )

    try:
        db.delete(set_to_delete)
        db.commit()
    except SQLAlchemyError as e:
        db.rollback()
        logger.exception("Failed to delete set %s", user_set_id)
        raise HTTPException(status_code=500, detail="Failed to delete set") from e

    logger.info("Set deleted: %s", user_set_id)
    return {"status": "deleted", "user_set_id": user_set_id}
