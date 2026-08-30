"""SQLAlchemy ORM models for PieceHunt.

The database consists of two parts:
- Lego data (read-only except during updates): Colors, Inventories, Parts,
  Sets, Themes, Elements, PartCategories, Minifigs and their relationships.
- User data: Users, UserSets and UserSetParts to track personal progress.
"""

from datetime import datetime
from uuid import UUID

from sqlalchemy import ForeignKey, ForeignKeyConstraint
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship
from sqlalchemy.sql.functions import current_timestamp


# The user columns or on the buttom, all the above are lego data (read only, except for updates)
class Base(DeclarativeBase):
    pass


class Colors(Base):
    __tablename__ = "colors"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(nullable=True)
    rgb: Mapped[str] = mapped_column(nullable=True)
    is_trans: Mapped[bool] = mapped_column(nullable=True)
    num_parts: Mapped[int] = mapped_column(nullable=True)
    num_sets: Mapped[int] = mapped_column(nullable=True)
    y1: Mapped[int] = mapped_column(nullable=True)
    y2: Mapped[int] = mapped_column(nullable=True)

    elements: Mapped[list[Elements]] = relationship("Elements", back_populates="color")
    inventory_parts: Mapped[list[InventoryParts]] = relationship(
        "InventoryParts", back_populates="color"
    )
    user_set_parts: Mapped[list[UserSetParts]] = relationship(
        "UserSetParts", back_populates="color", overlaps="inventory_part"
    )


class Inventories(Base):
    __tablename__ = "inventories"

    id: Mapped[int] = mapped_column(primary_key=True)
    version: Mapped[int] = mapped_column(nullable=True)
    set_num: Mapped[str] = mapped_column(nullable=True)

    inventory_minifigs: Mapped[list[InventoryMinifigs]] = relationship(
        "InventoryMinifigs", back_populates="inventory", passive_deletes=True
    )
    inventory_parts: Mapped[list[InventoryParts]] = relationship(
        "InventoryParts", back_populates="inventory", passive_deletes=True
    )
    inventory_sets: Mapped[list[InventorySets]] = relationship(
        "InventorySets", back_populates="inventory", passive_deletes=True
    )
    user_set_parts: Mapped[list[UserSetParts]] = relationship(
        "UserSetParts", back_populates="inventory", overlaps="inventory_part"
    )


class Minifigs(Base):
    __tablename__ = "minifigs"

    fig_num: Mapped[str] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(nullable=True)
    num_parts: Mapped[int] = mapped_column(nullable=True)

    inventory_minifigs: Mapped[list[InventoryMinifigs]] = relationship(
        "InventoryMinifigs", back_populates="minifig"
    )


class PartCategories(Base):
    __tablename__ = "part_categories"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(nullable=True)

    parts: Mapped[list[Parts]] = relationship("Parts", back_populates="part_cat")


class Themes(Base):
    __tablename__ = "themes"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(nullable=True)
    parent_id: Mapped[int] = mapped_column(
        ForeignKey("themes.id", ondelete="SET NULL"), nullable=True
    )

    parent: Mapped[Themes] = relationship(
        "Themes", remote_side=[id], back_populates="children"
    )
    children: Mapped[list[Themes]] = relationship("Themes", back_populates="parent")
    sets: Mapped[list[Sets]] = relationship("Sets", back_populates="theme")


class InventoryMinifigs(Base):
    __tablename__ = "inventory_minifigs"

    inventory_id: Mapped[int] = mapped_column(
        ForeignKey("inventories.id"), primary_key=True
    )
    fig_num: Mapped[str] = mapped_column(
        ForeignKey("minifigs.fig_num"), primary_key=True
    )
    quantity: Mapped[int] = mapped_column(nullable=True)

    minifig: Mapped[Minifigs] = relationship(
        "Minifigs", back_populates="inventory_minifigs"
    )
    inventory: Mapped[Inventories] = relationship(
        "Inventories", back_populates="inventory_minifigs"
    )


class Parts(Base):
    __tablename__ = "parts"

    part_num: Mapped[str] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(nullable=True)
    part_cat_id: Mapped[int] = mapped_column(
        ForeignKey("part_categories.id"), nullable=True
    )
    part_material: Mapped[str] = mapped_column(nullable=True)

    part_cat: Mapped[PartCategories] = relationship(
        "PartCategories", back_populates="parts"
    )
    elements: Mapped[list[Elements]] = relationship(
        "Elements", back_populates="parts", passive_deletes=True
    )
    inventory_parts: Mapped[list[InventoryParts]] = relationship(
        "InventoryParts", back_populates="parts"
    )

    user_set_parts: Mapped[list[UserSetParts]] = relationship(
        "UserSetParts", back_populates="part", overlaps="inventory_part"
    )

    child_relationships: Mapped[list[PartRelationships]] = relationship(
        "PartRelationships",
        foreign_keys="PartRelationships.child_part_num",
        back_populates="child_part",
    )
    parent_relationships: Mapped[list[PartRelationships]] = relationship(
        "PartRelationships",
        foreign_keys="PartRelationships.parent_part_num",
        back_populates="parent_part",
    )


class Sets(Base):
    __tablename__ = "sets"

    set_num: Mapped[str] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(nullable=True)
    year: Mapped[int] = mapped_column(nullable=True)
    theme_id: Mapped[int] = mapped_column(ForeignKey("themes.id"), nullable=True)
    num_parts: Mapped[int] = mapped_column(nullable=True)

    theme: Mapped[Themes] = relationship("Themes", back_populates="sets")
    inventory_sets: Mapped[list[InventorySets]] = relationship(
        "InventorySets", back_populates="sets"
    )


class Elements(Base):
    __tablename__ = "elements"

    element_id: Mapped[str] = mapped_column(primary_key=True)
    part_num: Mapped[str] = mapped_column(ForeignKey("parts.part_num"), nullable=True)
    color_id: Mapped[int] = mapped_column(ForeignKey("colors.id"), nullable=True)
    design_id: Mapped[int] = mapped_column(nullable=True)

    color: Mapped[Colors] = relationship("Colors", back_populates="elements")
    parts: Mapped[Parts] = relationship("Parts", back_populates="elements")


class InventoryParts(Base):
    __tablename__ = "inventory_parts"

    inventory_id: Mapped[int] = mapped_column(
        ForeignKey("inventories.id"), primary_key=True
    )
    part_num: Mapped[str] = mapped_column(
        ForeignKey("parts.part_num"), primary_key=True
    )
    color_id: Mapped[int] = mapped_column(ForeignKey("colors.id"), primary_key=True)
    is_spare: Mapped[bool] = mapped_column(primary_key=True)
    quantity: Mapped[int] = mapped_column(nullable=True)

    color: Mapped[Colors] = relationship("Colors", back_populates="inventory_parts")
    inventory: Mapped[Inventories] = relationship(
        "Inventories", back_populates="inventory_parts"
    )
    parts: Mapped[Parts] = relationship("Parts", back_populates="inventory_parts")
    user_set_parts: Mapped[list[UserSetParts]] = relationship(
        "UserSetParts",
        back_populates="inventory_part",
        overlaps="inventory,user_set_parts,part,color",
    )


class InventorySets(Base):
    __tablename__ = "inventory_sets"

    inventory_id: Mapped[int] = mapped_column(
        ForeignKey("inventories.id"), primary_key=True
    )
    set_num: Mapped[str] = mapped_column(ForeignKey("sets.set_num"), primary_key=True)
    quantity: Mapped[int] = mapped_column(nullable=True)

    inventory: Mapped[Inventories] = relationship(
        "Inventories", back_populates="inventory_sets"
    )
    sets: Mapped[Sets] = relationship("Sets", back_populates="inventory_sets")


class PartRelationships(Base):
    __tablename__ = "part_relationships"

    rel_type: Mapped[str] = mapped_column(primary_key=True)
    child_part_num: Mapped[str] = mapped_column(
        ForeignKey("parts.part_num"), primary_key=True
    )
    parent_part_num: Mapped[str] = mapped_column(
        ForeignKey("parts.part_num"), primary_key=True
    )

    child_part: Mapped[Parts] = relationship(
        "Parts", foreign_keys=[child_part_num], back_populates="child_relationships"
    )
    parent_part: Mapped[Parts] = relationship(
        "Parts", foreign_keys=[parent_part_num], back_populates="parent_relationships"
    )


class PartImages(Base):
    __tablename__ = "part_images"

    part_num: Mapped[str] = mapped_column(
        ForeignKey("parts.part_num", ondelete="CASCADE"), primary_key=True
    )
    color_id: Mapped[int] = mapped_column(
        ForeignKey("colors.id", ondelete="CASCADE"), primary_key=True
    )
    img_url: Mapped[str] = mapped_column(nullable=True)

    part: Mapped[Parts] = relationship("Parts")
    color: Mapped[Colors] = relationship("Colors")


class MinifigImages(Base):
    __tablename__ = "minifig_images"

    fig_num: Mapped[str] = mapped_column(
        ForeignKey("minifigs.fig_num", ondelete="CASCADE"), primary_key=True
    )
    img_url: Mapped[str] = mapped_column(nullable=True)

    minifig: Mapped[Minifigs] = relationship("Minifigs")


class SetImages(Base):
    __tablename__ = "set_images"

    set_num: Mapped[str] = mapped_column(
        ForeignKey("sets.set_num", ondelete="CASCADE"), primary_key=True
    )
    img_url: Mapped[str] = mapped_column(nullable=True)

    set: Mapped[Sets] = relationship("Sets")


# following are the user columns


class Users(Base):
    __tablename__ = "users"
    id: Mapped[UUID] = mapped_column(primary_key=True)
    username: Mapped[str] = mapped_column(nullable=True, unique=True)
    email: Mapped[str] = mapped_column(nullable=False)
    email_verified: Mapped[bool] = mapped_column(default=False, nullable=False)

    # passive_deletes=True: laat de ON DELETE CASCADE van de FK (UserSets.user_id)
    # het verwijderen in de databank doen, in plaats van dat SQLAlchemy eerst alle
    # user_sets (en via hun eigen cascade alle parts) in het geheugen laadt om ze
    # één voor één te verwijderen.
    user_sets: Mapped[list[UserSets]] = relationship(
        "UserSets",
        back_populates="user",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )


class UserSets(Base):
    __tablename__ = "user_sets"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    set_num: Mapped[str] = mapped_column(ForeignKey("sets.set_num"), nullable=False)
    started_at: Mapped[datetime] = mapped_column(server_default=current_timestamp())
    completed: Mapped[bool] = mapped_column(default=False)

    user: Mapped[Users] = relationship("Users", back_populates="user_sets")
    set: Mapped[Sets] = relationship("Sets")
    # passive_deletes=True: idem, steunt op ON DELETE CASCADE van UserSetParts.user_set_id
    # zodat parts in de databank worden opgeruimd i.p.v. object-per-object in Python.
    parts: Mapped[list[UserSetParts]] = relationship(
        "UserSetParts",
        back_populates="user_set",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )


class UserSetParts(Base):
    """Tracks the found quantity of each part for a user's set.

    Links to InventoryParts via a composite foreign key on
    inventory_id, part_num, color_id and is_spare.
    Optionally linked to a minifigure via a composite foreign key.
    """

    # inventory_id, part_num, color_id and is_spare are necessary because these form the pk of the inventoryparts table
    __tablename__ = "user_set_parts"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    user_set_id: Mapped[int] = mapped_column(
        ForeignKey("user_sets.id", ondelete="CASCADE"), nullable=False
    )
    inventory_id: Mapped[int] = mapped_column(ForeignKey("inventories.id"))
    part_num: Mapped[str] = mapped_column(ForeignKey("parts.part_num"))
    color_id: Mapped[int] = mapped_column(ForeignKey("colors.id"))
    is_spare: Mapped[bool] = mapped_column(nullable=False)
    quantity_have: Mapped[int] = mapped_column(default=0)
    minifig_num: Mapped[str] = mapped_column(nullable=True)
    minifig_id: Mapped[int] = mapped_column(nullable=True)

    user_set: Mapped[UserSets] = relationship("UserSets", back_populates="parts")
    part: Mapped[Parts] = relationship(
        "Parts", back_populates="user_set_parts", overlaps="inventory_part"
    )
    inventory: Mapped[Inventories] = relationship(
        "Inventories", back_populates="user_set_parts", overlaps="inventory_part"
    )
    color: Mapped[Colors] = relationship(
        "Colors", back_populates="user_set_parts", overlaps="inventory_part"
    )
    inventory_part: Mapped[InventoryParts] = relationship(
        back_populates="user_set_parts", overlaps="inventory,part,color"
    )
    inventory_minifig: Mapped[InventoryMinifigs] = relationship(
        "InventoryMinifigs", foreign_keys=[minifig_id, minifig_num]
    )

    __table_args__ = (
        ForeignKeyConstraint(
            ["minifig_id", "minifig_num"],
            ["inventory_minifigs.inventory_id", "inventory_minifigs.fig_num"],
        ),
        ForeignKeyConstraint(
            ["inventory_id", "part_num", "color_id", "is_spare"],
            [
                "inventory_parts.inventory_id",
                "inventory_parts.part_num",
                "inventory_parts.color_id",
                "inventory_parts.is_spare",
            ],
        ),
    )


class EmailVerificationToken(Base):
    __tablename__ = "email_verification_tokens"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    user_id: Mapped[UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    token_hash: Mapped[str] = mapped_column(nullable=False)
    expires_at: Mapped[datetime] = mapped_column(nullable=False)
    used_at: Mapped[datetime] = mapped_column(nullable=True)
    created_at: Mapped[datetime] = mapped_column(server_default=current_timestamp())

    user: Mapped[Users] = relationship("Users")


class PasswordResetToken(Base):
    __tablename__ = "password_reset_tokens"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    user_id: Mapped[UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    token_hash: Mapped[str] = mapped_column(nullable=False)
    expires_at: Mapped[datetime] = mapped_column(nullable=False)
    used_at: Mapped[datetime] = mapped_column(nullable=True)
    created_at: Mapped[datetime] = mapped_column(server_default=current_timestamp())

    user: Mapped[Users] = relationship("Users")
