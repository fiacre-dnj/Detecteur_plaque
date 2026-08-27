"""Le service des presets : créer, relire, mettre à jour, supprimer.

Peu de logique, et c'est normal — un preset est de la donnée. Les deux seules
décisions du service méritent d'être écrites :

**L'unicité du nom est refusée en 409, jamais silencieusement écrasée.** Un
enregistrement qui remplace un preset homonyme sans le dire fait perdre une géométrie
qu'on croyait garder, et l'utilisateur ne s'en aperçoit qu'en la rechargeant. Le
conflit est explicite, et le message dit quoi faire.

**Le service décide de la mise à l'échelle, pas le dépôt.** Le preset est stocké tel
qu'il a été tracé ; la conversion vers la résolution courante a lieu à la lecture, sur
demande. Stocker une version convertie perdrait l'original et rendrait chaque
rechargement suivant un peu plus faux.
"""

from __future__ import annotations

from dataclasses import replace as dataclass_replace
from typing import TYPE_CHECKING, Any
from uuid import uuid4

from traffic_analysis.core.errors import ConflictError, NotFoundError
from traffic_analysis.core.logging import get_logger
from traffic_analysis.features.presets.domain.records import Preset

if TYPE_CHECKING:
    from traffic_analysis.core.pagination import Page, PageParams
    from traffic_analysis.features.presets.application.ports import PresetRepository
    from traffic_analysis.features.presets.domain.records import (
        PresetDraft,
        PresetLine,
        PresetZone,
    )

logger = get_logger("traffic_analysis.presets")


class PresetNotFoundError(NotFoundError):
    code = "preset_not_found"


class PresetNameTakenError(ConflictError):
    code = "preset_name_taken"


class PresetService:
    """Orchestration des presets. Sans état : tout vit dans le dépôt."""

    __slots__ = ("_repository",)

    def __init__(self, repository: PresetRepository) -> None:
        self._repository = repository

    async def create(self, draft: PresetDraft) -> Preset:
        """Enregistre une nouvelle géométrie.

        L'identifiant est décidé **ici** et jamais accepté du client : laisser choisir
        un `id` permettrait d'écraser un preset existant par un `POST`, ce qui n'est
        pas ce que `POST` veut dire.
        """
        existing = await self._repository.get_by_name(draft.name)
        if existing is not None:
            raise PresetNameTakenError(
                f"Un preset nommé « {draft.name} » existe déjà. "
                "Choisissez un autre nom, ou modifiez le preset existant."
            )

        preset = Preset(
            id=uuid4().hex,
            name=draft.name,
            description=draft.description,
            source_width=draft.source_width,
            source_height=draft.source_height,
            mask_outside_zones=draft.mask_outside_zones,
            lines=draft.lines,
            zones=draft.zones,
        )
        await self._repository.add(preset)
        logger.info(
            "preset enregistré",
            preset_id=preset.id,
            name=preset.name,
            lines=len(preset.lines),
            zones=len(preset.zones),
        )
        return preset

    async def get(self, preset_id: str) -> Preset:
        preset = await self._repository.get(preset_id)
        if preset is None:
            raise PresetNotFoundError(
                f"Le preset « {preset_id} » n'existe pas. Il a peut-être été supprimé."
            )
        return preset

    async def list(self, page: PageParams) -> Page[Preset]:
        return await self._repository.list(page)

    async def replace(self, preset_id: str, draft: PresetDraft) -> Preset:
        """Remplace une géométrie enregistrée.

        Le nom est vérifié contre les **autres** presets seulement : renommer un
        preset en lui-même n'est pas un conflit, et refuser ce cas rendrait toute
        modification impossible sans changer de nom.
        """
        current = await self.get(preset_id)

        clash = await self._repository.get_by_name(draft.name)
        if clash is not None and clash.id != preset_id:
            raise PresetNameTakenError(f"Un autre preset porte déjà le nom « {draft.name} ».")

        updated = dataclass_replace(
            current,
            name=draft.name,
            description=draft.description,
            source_width=draft.source_width,
            source_height=draft.source_height,
            mask_outside_zones=draft.mask_outside_zones,
            lines=draft.lines,
            zones=draft.zones,
        )
        if not await self._repository.update(updated):
            # La course est réelle : le preset a pu être supprimé entre le `get` et
            # l'`update`. Le dire plutôt que de rendre un succès mensonger.
            raise PresetNotFoundError(
                f"Le preset « {preset_id} » a été supprimé pendant la modification."
            )
        logger.info("preset modifié", preset_id=preset_id, name=updated.name)
        return updated

    async def delete(self, preset_id: str) -> None:
        if not await self._repository.delete(preset_id):
            raise PresetNotFoundError(f"Le preset « {preset_id} » n'existe pas.")
        logger.info("preset supprimé", preset_id=preset_id)


# ── Sérialisation ────────────────────────────────────────────────────────────


def describe(
    preset: Preset, *, width: int | None = None, height: int | None = None
) -> dict[str, Any]:
    """Le preset tel que l'API l'expose, éventuellement mis à l'échelle.

    Quand `width`/`height` sont fournis, la géométrie rendue est convertie **et**
    `scaled` vaut vrai. C'est ce drapeau que l'interface utilise pour dire à
    l'utilisateur que ses lignes ont été déplacées — sans lui, la conversion serait
    silencieuse, et une géométrie qui bouge sans prévenir se lit comme un bug.

    `sourceWidth`/`sourceHeight` décrivent alors la résolution **demandée**, puisque
    c'est celle dans laquelle les coordonnées rendues sont exprimées. Les dimensions
    d'origine restent lisibles dans `originalWidth`/`originalHeight`, pour que
    l'utilisateur sache d'où vient le preset.
    """
    target = preset
    scaled = False
    if width is not None and height is not None and width > 0 and height > 0:
        scaled = preset.needs_scaling_for(width, height)
        target = preset.scaled_to(width, height)

    return {
        "id": preset.id,
        "name": preset.name,
        "description": preset.description,
        "sourceWidth": target.source_width,
        "sourceHeight": target.source_height,
        "originalWidth": preset.source_width,
        "originalHeight": preset.source_height,
        "scaled": scaled,
        "maskOutsideZones": preset.mask_outside_zones,
        "lines": [_describe_line(line) for line in target.lines],
        "zones": [_describe_zone(zone) for zone in target.zones],
        "createdAt": preset.created_at.isoformat() if preset.created_at else None,
        "updatedAt": preset.updated_at.isoformat() if preset.updated_at else None,
    }


def _describe_line(line: PresetLine) -> dict[str, Any]:
    """La ligne telle que l'API la rend, `LineSchema` comprise.

    **Ni les champs de sens ni les classes autorisées ne sont mis à l'échelle**,
    contrairement aux sommets : `scaled_to` ne touche qu'à des coordonnées. Un rôle,
    un libellé et une règle de voie réservée décrivent le trait, pas sa position —
    recharger un preset sur une autre résolution déplace la ligne sans jamais changer
    ce qui entre, ce qui sort ni ce qui est interdit.
    """
    return {
        "id": line.id,
        "name": line.name,
        "color": line.color,
        "zoneId": line.zone_id,
        "a": {"x": line.a.x, "y": line.a.y},
        "b": {"x": line.b.x, "y": line.b.y},
        "positiveName": line.positive_name,
        "negativeName": line.negative_name,
        "positiveRole": line.positive_role,
        "negativeRole": line.negative_role,
        "allowedClassIds": (
            None if line.allowed_class_ids is None else list(line.allowed_class_ids)
        ),
    }


def _describe_zone(zone: PresetZone) -> dict[str, Any]:
    return {
        "id": zone.id,
        "name": zone.name,
        "color": zone.color,
        "points": [{"x": point.x, "y": point.y} for point in zone.points],
    }
