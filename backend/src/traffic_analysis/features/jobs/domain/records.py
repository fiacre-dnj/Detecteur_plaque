"""Entité de domaine d'un job d'analyse.

Une dataclass et non un modèle ORM : un modèle ORM qui remonte jusqu'à une route
emporte avec lui une session et des chargements paresseux, qui explosent en
contexte async (`MissingGreenlet`). Le repository traduit dans les deux sens.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from typing import TYPE_CHECKING, Any

from traffic_analysis.features.jobs.domain.status import JobStatus

if TYPE_CHECKING:
    from datetime import datetime


@dataclass(frozen=True, slots=True)
class VideoMetadata:
    """Ce que `probe()` a appris de la vidéo déposée."""

    width: int = 0
    height: int = 0
    fps: float = 0.0
    frame_count: int = 0
    duration_ms: float = 0.0


@dataclass(frozen=True, slots=True)
class JobRecord:
    """L'état persisté d'un job. Immuable : chaque mise à jour produit une copie.

    L'immuabilité n'est pas de la cérémonie ici : le job est lu depuis la boucle
    asyncio pendant qu'un thread worker le fait avancer. Un objet muté depuis deux
    threads est un bug qui ne se reproduit qu'en charge.
    """

    id: str
    status: JobStatus
    model_id: str
    file_name: str
    file_size_bytes: int
    created_at: datetime
    # La requête telle qu'elle a été reçue : rejouer une analyse à l'identique
    # doit être possible, et c'est aussi ce qui permet à l'historique de
    # recharger la géométrie dans le studio.
    config_json: dict[str, Any] = field(default_factory=dict)
    progress: float = 0.0
    processed_frames: int = 0
    total_frames: int = 0
    processing_fps: float = 0.0
    # Message destiné à l'utilisateur, **jamais** une trace de pile.
    error: str | None = None
    # Le code **stable** de l'erreur (`AppError.code`), pour les machines.
    #
    # Deux champs et non un, pour la même raison qu'`AppError` en porte deux : le
    # message d'interface se réécrit sans casser de client, le code non. C'est ce
    # qui permet au frontend de brancher une action — « précharger puis relancer »
    # sur `model_unavailable` — sans faire de correspondance sur du texte français.
    error_code: str | None = None
    video: VideoMetadata = field(default_factory=VideoMetadata)
    stats_json: dict[str, Any] | None = None
    # Dénormalisés pour trier l'historique sans ouvrir le fichier de résultat.
    tracked_vehicles: int = 0
    crossings_total: int = 0
    result_path: str | None = None
    started_at: datetime | None = None
    finished_at: datetime | None = None

    def with_changes(self, **changes: Any) -> JobRecord:  # noqa: ANN401
        return replace(self, **changes)
