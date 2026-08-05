"""Catalogue des détecteurs — **une donnée, pas du code dispersé**.

Ajouter un modèle est *une ligne*. Le sélecteur de l'interface, le benchmark, le
registre mémoire et l'API suivent tout seuls, parce qu'ils lisent tous ce tuple.

Deux règles à ne jamais enfreindre :

1. **Ne jamais déduire une caractéristique d'un modèle de son nom de fichier.**
   Le palier vit dans `tier`, jamais dans le nom. La version précédente encodait
   le palier dans le nom (`yolo11l_large.onnx`), et c'est la seule raison pour
   laquelle le modèle de plaques paraissait mal rangé (piège 34 de prompt/13).
2. **Les poids véhicules sont des `.pt` natifs.** `model.track()` a besoin du
   pipeline complet d'Ultralytics — BoT-SORT, embeddings de ré-identification,
   compensation de mouvement — qu'un export ONNX ne porte pas. Le modèle de
   plaques est l'exception assumée : il fait du `predict`, pas du `track`, et
   `YOLO(path, task="detect")` charge très bien un `.onnx`.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

type ModelTier = Literal["nano", "small", "medium", "large", "xlarge"]
type ModelFamily = Literal["yolov8", "yolo11", "yolo12", "yolo26"]

# Ordre d'affichage des paliers. Croissant en coût, ce qui est aussi l'ordre dans
# lequel un utilisateur explore : on essaie le rapide avant le précis.
TIER_ORDER: tuple[ModelTier, ...] = ("nano", "small", "medium", "large", "xlarge")

TIER_LABELS: dict[ModelTier, str] = {
    "nano": "Nano",
    "small": "Small",
    "medium": "Medium",
    "large": "Large",
    "xlarge": "Extra Large",
}


@dataclass(frozen=True, slots=True)
class ModelDescriptor:
    """Une entrée du catalogue.

    `id` est **identique côté frontend** : c'est un contrat, pas un détail
    d'implémentation. Le renommer casse les configurations enregistrées et
    l'historique.
    """

    id: str
    label: str
    family: ModelFamily
    tier: ModelTier
    # Taille approximative du `.pt`, pour l'avertissement de téléchargement.
    # **Indicative** : la vérité vient du disque une fois le fichier présent, et
    # l'API renvoie alors la taille réelle.
    size_mb: int
    note: str
    weights: str
    task: Literal["detect"] = "detect"


CATALOGUE: tuple[ModelDescriptor, ...] = (
    # ── YOLOv8 : la génération de référence, la mieux documentée ─────────────
    ModelDescriptor(
        "yolov8n", "YOLOv8n", "yolov8", "nano", 6, "Le plus rapide — bon défaut", "yolov8n.pt"
    ),
    ModelDescriptor(
        "yolov8s", "YOLOv8s", "yolov8", "small", 22, "Un cran au-dessus du nano", "yolov8s.pt"
    ),
    ModelDescriptor(
        "yolov8m", "YOLOv8m", "yolov8", "medium", 52, "Référence historique", "yolov8m.pt"
    ),
    ModelDescriptor(
        "yolov8l", "YOLOv8l", "yolov8", "large", 88, "Précision accrue, coût notable", "yolov8l.pt"
    ),
    ModelDescriptor(
        "yolov8x", "YOLOv8x", "yolov8", "xlarge", 137, "Le plus lourd de la famille 8", "yolov8x.pt"
    ),
    # ── YOLO11 : meilleur rapport précision/cadence à taille égale ───────────
    ModelDescriptor(
        "yolo11n", "YOLO11n", "yolo11", "nano", 6, "Nano de dernière génération", "yolo11n.pt"
    ),
    ModelDescriptor("yolo11s", "YOLO11s", "yolo11", "small", 19, "Léger et précis", "yolo11s.pt"),
    ModelDescriptor(
        "yolo11m",
        "YOLO11m",
        "yolo11",
        "medium",
        39,
        "Meilleur compromis précision/cadence",
        "yolo11m.pt",
    ),
    ModelDescriptor(
        "yolo11l", "YOLO11l", "yolo11", "large", 49, "Précision supérieure", "yolo11l.pt"
    ),
    ModelDescriptor(
        "yolo11x",
        "YOLO11x",
        "yolo11",
        "xlarge",
        109,
        "Précision maximale (famille 11)",
        "yolo11x.pt",
    ),
    # ── YOLO12 : attentionnel, plus lent à taille égale ─────────────────────
    ModelDescriptor(
        "yolo12n", "YOLO12n", "yolo12", "nano", 6, "Attentionnel, palier nano", "yolo12n.pt"
    ),
    ModelDescriptor(
        "yolo12s", "YOLO12s", "yolo12", "small", 19, "Attentionnel, palier small", "yolo12s.pt"
    ),
    ModelDescriptor(
        "yolo12m", "YOLO12m", "yolo12", "medium", 39, "Attentionnel, palier medium", "yolo12m.pt"
    ),
    ModelDescriptor(
        "yolo12l",
        "YOLO12l",
        "yolo12",
        "large",
        52,
        "Attentionnel — lourd à l'inférence",
        "yolo12l.pt",
    ),
    ModelDescriptor(
        "yolo12x",
        "YOLO12x",
        "yolo12",
        "xlarge",
        113,
        "Le plus gros — hors temps réel",
        "yolo12x.pt",
    ),
    # ── YOLO26 : NMS intégré au graphe, post-traitement allégé ──────────────
    ModelDescriptor(
        "yolo26n", "YOLO26n", "yolo26", "nano", 6, "NMS intégré au graphe", "yolo26n.pt"
    ),
    ModelDescriptor(
        "yolo26s", "YOLO26s", "yolo26", "small", 19, "NMS intégré au graphe", "yolo26s.pt"
    ),
    ModelDescriptor(
        "yolo26m", "YOLO26m", "yolo26", "medium", 39, "NMS intégré au graphe", "yolo26m.pt"
    ),
    ModelDescriptor(
        "yolo26l", "YOLO26l", "yolo26", "large", 48, "NMS intégré au graphe", "yolo26l.pt"
    ),
    ModelDescriptor(
        "yolo26x", "YOLO26x", "yolo26", "xlarge", 107, "NMS intégré, précision max", "yolo26x.pt"
    ),
)

DEFAULT_MODEL_ID = "yolov8n"

_BY_ID: dict[str, ModelDescriptor] = {model.id: model for model in CATALOGUE}


def all_models() -> tuple[ModelDescriptor, ...]:
    return CATALOGUE


def find(model_id: str) -> ModelDescriptor | None:
    return _BY_ID.get(model_id)


def known_ids() -> tuple[str, ...]:
    return tuple(_BY_ID)


def by_tier() -> dict[ModelTier, tuple[ModelDescriptor, ...]]:
    """Catalogue groupé par palier, dans l'ordre d'affichage du sélecteur."""
    return {tier: tuple(model for model in CATALOGUE if model.tier == tier) for tier in TIER_ORDER}
