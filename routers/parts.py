import logging
from collections import defaultdict

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select, tuple_
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session, selectinload

from database import get_db
from dependencies import get_current_verified_user
from models.models import Colors, Elements, Inventories, InventoryMinifigs, UserSetParts
from routers.ownership import get_owned_userset

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/sets", tags=["parts"])


class QuantityUpdate(BaseModel):
    quantity: int


class PartsAction(BaseModel):
    action: str  # "reset_set" of "complete_set"


@router.get("/{user_set_id}/parts")
def get_userset_parts(
    user_set_id: int,
    user=Depends(get_current_verified_user),
    db: Session = Depends(get_db),
):
    """Retrieves all parts for a user's set with progress and metadata.

    Note: does NOT include img_path - that stays a client-side concern.
    """
    get_owned_userset(db, user_set_id, user.id)

    all_parts = (
        db.query(UserSetParts)
        .options(
            selectinload(UserSetParts.inventory_part),
            selectinload(UserSetParts.part),
            selectinload(UserSetParts.color),
            selectinload(UserSetParts.inventory_minifig),
        )
        .filter(UserSetParts.user_set_id == user_set_id)
        .order_by(UserSetParts.color_id)
        .all()
    )

    if not all_parts:
        return []

    pairs = {
        (p.inventory_part.part_num, p.inventory_part.color_id)
        for p in all_parts
        if p.inventory_part
    }
    element_ids_map = defaultdict(list)
    if pairs:
        stmt = select(Elements.part_num, Elements.color_id, Elements.element_id).where(
            tuple_(Elements.part_num, Elements.color_id).in_(pairs)
        )
        for part_num, color_id, element_id in db.execute(stmt):
            element_ids_map[(part_num, color_id)].append(element_id)

    result = []
    for userpart in all_parts:
        inv_part = userpart.inventory_part
        if not inv_part:
            logger.warning("No inventory part found for userpart: %s", userpart.id)
            continue

        multiplier = (
            userpart.inventory_minifig.quantity
            if userpart.minifig_num and userpart.inventory_minifig
            else 1
        )
        element_ids = element_ids_map.get((inv_part.part_num, inv_part.color_id), [])

        result.append(
            {
                "id": userpart.id,
                "part_num": userpart.part_num,
                "element_ids": element_ids,
                "name": userpart.part.name,
                "color_id": userpart.color_id,
                "color": userpart.color.name,
                "total_num": inv_part.quantity * multiplier,
                "found_num": userpart.quantity_have,
                "is_spare": userpart.is_spare,
                "part_categorie": userpart.part.part_cat_id,
                "is_trans": userpart.color.is_trans,
            }
        )

    return result


@router.get("/{user_set_id}/minifigs")
def get_userset_minifigs(
    user_set_id: int,
    user=Depends(get_current_verified_user),
    db: Session = Depends(get_db),
):
    """Retrieves all minifigures for a user's set. img_url only - client resolves the local path."""
    userset = get_owned_userset(db, user_set_id, user.id)

    inventory = (
        db.query(Inventories).filter(Inventories.set_num == userset.set_num).first()
    )
    if not inventory:
        return []

    minifigs_inv = (
        db.query(InventoryMinifigs)
        .options(selectinload(InventoryMinifigs.minifig))
        .filter(InventoryMinifigs.inventory_id == inventory.id)
        .all()
    )

    return [
        {
            "name": m.minifig.name,
            "quantity": m.quantity,
            "number_of_parts": m.minifig.num_parts,
            "fig_num": m.fig_num,
        }
        for m in minifigs_inv
    ]


@router.get("/{user_set_id}/colors")
def get_userset_colors(
    user_set_id: int,
    user=Depends(get_current_verified_user),
    db: Session = Depends(get_db),
):
    """Distinct colors used across a user's set."""
    get_owned_userset(db, user_set_id, user.id)

    colors = (
        db.query(Colors)
        .join(UserSetParts, UserSetParts.color_id == Colors.id)
        .filter(UserSetParts.user_set_id == user_set_id)
        .distinct()
        .all()
    )
    return [{"id": c.id, "name": c.name, "rgb": c.rgb} for c in colors]


@router.patch("/{user_set_id}/parts/{userpart_id}")
def update_part_quantity(
    user_set_id: int,
    userpart_id: int,
    body: QuantityUpdate,
    user=Depends(get_current_verified_user),
    db: Session = Depends(get_db),
):
    """Updates the found quantity for a single part."""
    get_owned_userset(db, user_set_id, user.id)

    obj = (
        db.query(UserSetParts)
        .filter_by(id=userpart_id, user_set_id=user_set_id)
        .first()
    )
    if not obj:
        raise HTTPException(status_code=404, detail="Part not found")

    obj.quantity_have = body.quantity
    try:
        db.commit()

    except SQLAlchemyError:
        db.rollback()
        logger.exception("Failed to update quantity for part %s", userpart_id)
        raise HTTPException(
            status_code=500, detail="Failed to update quantity"
        ) from None

    return {"id": obj.id, "quantity_have": obj.quantity_have}


@router.post("/{user_set_id}/parts/actions")
def apply_parts_action(
    user_set_id: int,
    body: PartsAction,
    user=Depends(get_current_verified_user),
    db: Session = Depends(get_db),
):
    """Applies a bulk action to all parts in a set: 'reset_set' or 'complete_set'."""
    get_owned_userset(db, user_set_id, user.id)

    try:
        if body.action == "reset_set":
            db.query(UserSetParts).filter(
                UserSetParts.user_set_id == user_set_id
            ).update({UserSetParts.quantity_have: 0})
            db.commit()

        elif body.action == "complete_set":
            parts = (
                db.query(UserSetParts)
                .options(
                    selectinload(UserSetParts.inventory_part),
                    selectinload(UserSetParts.inventory_minifig),
                )
                .filter(UserSetParts.user_set_id == user_set_id)
                .all()
            )
            for part in parts:
                multiplier = (
                    part.inventory_minifig.quantity
                    if part.minifig_num and part.inventory_minifig
                    else 1
                )
                part.quantity_have = part.inventory_part.quantity * multiplier
            db.commit()

        else:
            raise HTTPException(
                status_code=400, detail=f"Unknown action: {body.action}"
            )

    except SQLAlchemyError as e:
        db.rollback()
        logger.exception(
            "Failed to apply action %s for userset %s", body.action, user_set_id
        )
        raise HTTPException(status_code=500, detail="Failed to apply action") from e

    return {"status": "ok", "action": body.action}
