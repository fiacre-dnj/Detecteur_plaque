"""Le dépôt SQLAlchemy des presets.

Une session par opération, ouverte ici et jamais reçue de l'extérieur : c'est la
convention du projet, et elle garantit qu'aucun modèle ORM ne survit à la fermeture
de sa session — la cause du `MissingGreenlet` dont le message n'explique rien.

La traduction JSON ⇄ domaine est **défensive à la lecture**. Un preset écrit par une
version antérieure peut manquer un champ ; refuser de le rendre viderait la liste de
l'utilisateur, alors que rendre un preset partiellement dégradé lui laisse au moins la
possibilité de le corriger et de le réenregistrer.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any

from sqlalchemy import func, select

from traffic_analysis.core.pagination import Page
from traffic_analysis.features.counting.application.dto import DirectionRole
from traffic_analysis.features.presets.domain.records import (
    Preset,
    PresetLine,
    PresetPoint,
    PresetZone,
)
from traffic_analysis.features.presets.infrastructure.orm import PresetModel

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

    from traffic_analysis.core.pagination import PageParams


class SqlAlchemyPresetRepository:
    """Persistance des presets en base."""

    __slots__ = ("_session_factory",)

    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory

    async def add(self, preset: Preset) -> None:
        async with self._session_factory() as session, session.begin():
            session.add(_to_model(preset))

    async def get(self, preset_id: str) -> Preset | None:
        async with self._session_factory() as session:
            model = await session.scalar(select(PresetModel).where(PresetModel.id == preset_id))
            return _to_record(model) if model is not None else None

    async def get_by_name(self, name: str) -> Preset | None:
        async with self._session_factory() as session:
            model = await session.scalar(select(PresetModel).where(PresetModel.name == name))
            return _to_record(model) if model is not None else None

    async def list(self, page: PageParams) -> Page[Preset]:
        async with self._session_factory() as session:
            total = await session.scalar(select(func.count()).select_from(PresetModel))
            rows = await session.scalars(
                select(PresetModel)
                # Le plus récemment modifié d'abord, `id` en départage : sans ce
                # second critère, deux presets enregistrés dans la même seconde
                # changeraient d'ordre d'une page à l'autre, et l'un des deux
                # pourrait n'apparaître sur aucune.
                .order_by(PresetModel.updated_at.desc(), PresetModel.id.desc())
                .limit(page.limit)
                .offset(page.offset)
            )
            return Page.of([_to_record(row) for row in rows], total=total or 0, params=page)

    async def update(self, preset: Preset) -> bool:
        async with self._session_factory() as session, session.begin():
            model = await session.get(PresetModel, preset.id)
            if model is None:
                return False
            model.name = preset.name
            model.description = preset.description
            model.source_width = preset.source_width
            model.source_height = preset.source_height
            model.mask_outside_zones = preset.mask_outside_zones
            model.lines_json = json.dumps(
                [_line_payload(line) for line in preset.lines], ensure_ascii=False
            )
            model.zones_json = json.dumps(
                [_zone_payload(zone) for zone in preset.zones], ensure_ascii=False
            )
            return True

    async def delete(self, preset_id: str) -> bool:
        async with self._session_factory() as session, session.begin():
            # `session.get` puis `delete` plutôt qu'un `DELETE … WHERE` : le
            # `rowcount` d'un `Result` n'est pas typé par les stubs SQLAlchemy, et
            # surtout il n'est pas garanti par tous les pilotes. Deux requêtes pour
            # une suppression unitaire ne coûtent rien, et le verdict est sûr.
            model = await session.get(PresetModel, preset_id)
            if model is None:
                return False
            await session.delete(model)
            return True


# ── Traduction ORM ⇄ domaine ─────────────────────────────────────────────────


def _to_model(preset: Preset) -> PresetModel:
    return PresetModel(
        id=preset.id,
        name=preset.name,
        description=preset.description,
        source_width=preset.source_width,
        source_height=preset.source_height,
        mask_outside_zones=preset.mask_outside_zones,
        lines_json=json.dumps([_line_payload(line) for line in preset.lines], ensure_ascii=False),
        zones_json=json.dumps([_zone_payload(zone) for zone in preset.zones], ensure_ascii=False),
    )


def _to_record(model: PresetModel) -> Preset:
    return Preset(
        id=model.id,
        name=model.name,
        description=model.description,
        source_width=model.source_width,
        source_height=model.source_height,
        mask_outside_zones=model.mask_outside_zones,
        lines=tuple(_read_line(item) for item in _load(model.lines_json)),
        zones=tuple(_read_zone(item) for item in _load(model.zones_json)),
        created_at=model.created_at,
        updated_at=model.updated_at,
    )


def _line_payload(line: PresetLine) -> dict[str, Any]:
    """La ligne écrite en colonne texte.

    Les clés sont en `camelCase` comme le reste du JSON persisté ; c'est le format
    déjà en base pour `zoneId`, et un mélange de conventions dans le même document
    rendrait toute relecture manuelle piégeuse.

    **Aucune migration n'accompagne l'ajout des champs de sens ni celui des classes
    autorisées** : la géométrie vit dans une colonne JSON, précisément pour que sa
    forme puisse évoluer sans toucher au schéma. Un preset écrit avant ces ajouts se
    relit donc sans erreur — `_read_line` lui rend les défauts, et son propriétaire
    n'a qu'à redéclarer ses règles une fois puis réenregistrer.
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


def _zone_payload(zone: PresetZone) -> dict[str, Any]:
    return {
        "id": zone.id,
        "name": zone.name,
        "color": zone.color,
        "points": [{"x": point.x, "y": point.y} for point in zone.points],
    }


def _load(raw: str) -> list[dict[str, Any]]:
    """Relit une liste JSON sans jamais lever.

    Une colonne corrompue — écriture interrompue, migration manuelle malheureuse —
    rendrait la liste entière des presets inaccessible si elle levait ici. Rendre une
    liste vide dégrade **ce** preset et laisse les autres lisibles.
    """
    try:
        parsed = json.loads(raw)
    except (TypeError, ValueError):
        return []
    return parsed if isinstance(parsed, list) else []


def _point(raw: object) -> PresetPoint:
    """Un sommet relu du JSON, en tolérant tout ce qui n'en est pas un.

    `object` et non `Any` : le contenu vient d'une colonne texte, donc rien n'est
    garanti, et `object` force à le prouver par un `isinstance` au lieu de laisser
    mypy croire sur parole.
    """
    if not isinstance(raw, dict):
        return PresetPoint(x=0.0, y=0.0)
    return PresetPoint(x=_number(raw.get("x")), y=_number(raw.get("y")))


def _number(raw: object) -> float:
    """Une coordonnée, ou zéro. `float("abc")` lèverait, et une liste vide aussi."""
    if isinstance(raw, (int, float)) and not isinstance(raw, bool):
        return float(raw)
    return 0.0


def _role(raw: object) -> DirectionRole:
    """Un rôle de sens relu du JSON, ou `neutral`.

    **La validation ici n'est pas de la prudence de principe, elle protège toute la
    liste.** `PresetSchema` type ces champs par un `Literal` : une valeur inattendue
    en base — preset écrit à la main, colonne bricolée, futur rôle rétroporté — ferait
    échouer la validation de la *réponse*, donc un 500 sur `GET /presets` qui rendrait
    **tous** les presets inaccessibles à cause d'un seul. Le repli dégrade une ligne
    et laisse le reste lisible, comme `_load` le fait déjà pour une colonne corrompue.

    `neutral` et non une devinette : deviner « entrée » pour un rôle qu'on ne sait pas
    lire fausserait un bilan que personne n'a demandé, alors que `neutral` fait
    afficher le repère « à préciser » du panneau de géométrie.
    """
    return raw if raw in ("entry", "exit", "forbidden", "transit", "neutral") else "neutral"


def _read_line(raw: dict[str, Any]) -> PresetLine:
    return PresetLine(
        id=str(raw.get("id", "")),
        name=str(raw.get("name", "")),
        color=str(raw.get("color", "")),
        zone_id=raw.get("zoneId") if isinstance(raw.get("zoneId"), str) else None,
        a=_point(raw.get("a")),
        b=_point(raw.get("b")),
        # `str(raw.get(...))` rendrait la chaîne « None » sur une clé absente, que
        # l'interface afficherait telle quelle de part et d'autre du trait.
        positive_name=_text(raw.get("positiveName")),
        negative_name=_text(raw.get("negativeName")),
        positive_role=_role(raw.get("positiveRole")),
        negative_role=_role(raw.get("negativeRole")),
        allowed_class_ids=_class_ids(raw.get("allowedClassIds")),
    )


def _class_ids(raw: object) -> tuple[int, ...] | None:
    """Les classes autorisées relues du JSON, ou `None` — aucune restriction.

    Même rôle que `_role` et même raison : `PresetSchema` type ce champ, donc une
    valeur inattendue en base ferait échouer la validation de la **réponse** et
    emporterait toute la liste des presets pour une seule ligne fautive.

    Le repli est `None` et jamais une liste vide : `None` dit « rien n'est
    restreint », une liste vide dirait « aucune classe n'a le droit de passer » —
    donc **tout** franchissement en infraction. Se tromper de repli fabriquerait ici
    un écran d'alertes entièrement faux.
    """
    if not isinstance(raw, list):
        return None
    kept = [item for item in raw if isinstance(item, int) and not isinstance(item, bool)]
    return tuple(dict.fromkeys(kept)) if kept else None


def _text(raw: object) -> str:
    """Un libellé de sens, ou la chaîne vide qui demande le défaut géométrique."""
    return raw if isinstance(raw, str) else ""


def _read_zone(raw: dict[str, Any]) -> PresetZone:
    points = raw.get("points")
    return PresetZone(
        id=str(raw.get("id", "")),
        name=str(raw.get("name", "")),
        color=str(raw.get("color", "")),
        points=tuple(_point(item) for item in points) if isinstance(points, list) else (),
    )
