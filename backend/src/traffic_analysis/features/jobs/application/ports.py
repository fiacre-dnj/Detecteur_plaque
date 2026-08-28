"""Ports de la feature `jobs`.

La persistance est remplaçable (mémoire → SQLite → Postgres) sans toucher aux
routes. Le `JobManager` ne connaît que ces protocoles.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Literal, Protocol

#: Les deux faces d'une capture de véhicule.
#:
#: Déclaré **ici**, dans la couche application, et non dans l'adaptateur qui écrit
#: les fichiers : c'est un élément de la signature du port, donc l'infrastructure en
#: dépend et jamais l'inverse (`infrastructure → application → domain`).
#:
#: Un `Literal` et non une chaîne libre : ce mot compose un nom de fichier, et un
#: type fermé est ce qui garantit qu'aucune valeur venue du client n'y entre.
type SnapshotKind = Literal["vehicle", "plate"]

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence
    from pathlib import Path
    from typing import Any

    from traffic_analysis.core.pagination import Page, PageParams
    from traffic_analysis.features.counting.application.dto import (
        AnalysisResultData,
        Progress,
        VehicleSnapshot,
    )
    from traffic_analysis.features.jobs.domain.records import JobRecord, VideoMetadata
    from traffic_analysis.features.jobs.domain.status import JobStatus


@dataclass(frozen=True, slots=True)
class JobFilters:
    """Filtres de l'historique. Tous optionnels, combinables."""

    status: JobStatus | None = None
    model_id: str | None = None


class JobRepository(Protocol):
    """Persistance de l'état des jobs."""

    async def add(self, job: JobRecord) -> None: ...

    async def get(self, job_id: str) -> JobRecord | None: ...

    async def list(self, filters: JobFilters, page: PageParams) -> Page[JobRecord]: ...

    async def update_progress(self, job_id: str, progress: Progress) -> None:
        """Enregistre l'avancement.

        **N'est pas appelée à chaque frame.** La progression vit en mémoire dans
        le `ProgressHub` et n'est persistée qu'à intervalle et aux transitions
        d'état : SQLite n'a qu'un écrivain, et une analyse à 25 images par seconde
        déclencherait 25 écritures par seconde.
        """
        ...

    async def set_status(
        self,
        job_id: str,
        status: JobStatus,
        *,
        error: str | None = None,
        error_code: str | None = None,
    ) -> None:
        """Change le statut, et **le message et le code** qui l'accompagnent.

        Les deux ensemble et jamais séparément : un message sans code oblige
        l'interface à faire une correspondance sur du texte français, un code sans
        message n'a rien à afficher.
        """
        ...

    async def set_video_metadata(self, job_id: str, video: VideoMetadata) -> None: ...

    async def save_result_aggregates(self, job_id: str, data: AnalysisResultData) -> None:
        """Écrit les agrégats en **une seule transaction**, en lot.

        Cinq mille franchissements insérés un par un prennent des minutes sur
        SQLite ; en lot, moins d'une seconde.
        """
        ...

    async def delete(self, job_id: str) -> None: ...

    async def list_expired(self, older_than_minutes: int) -> Sequence[JobRecord]:
        """Jobs **terminaux** plus vieux que le TTL, candidats à la purge."""
        ...


class ModelPreparer(Protocol):
    """Rend un modèle utilisable **avant** que le job prétende travailler.

    Port volontairement étroit — une seule méthode — parce que `jobs` n'a besoin
    que de cela du registre de modèles. Un port large ferait entrer dans la
    feature `jobs` des notions (baux, résidence mémoire, catalogue) dont son cycle
    de vie n'a que faire, et que le prochain lecteur croirait devoir comprendre.

    La règle de dépendance du projet est respectée : `jobs.application` parle à
    `models_registry.application`, jamais à son domaine ni à son infrastructure.
    """

    async def prepare(self, model_id: str) -> None:
        """Charge le modèle, en téléchargeant son poids si nécessaire.

        **Lève** une `AppError` — `UnknownModelError` ou `UnavailableError` — quand
        le modèle est inconnu ou impossible à charger. C'est le point de tout ce
        port : l'échec arrive alors *avant* le passage en « en cours », avec le
        message du registre, au lieu de survenir trente secondes plus tard sous la
        forme d'une progression bloquée à 0 %.

        **Effet de bord à connaître : la préparation prend un bail sur le modèle.**
        Si une session temps réel occupe déjà la même instance, l'appel attend
        qu'elle rende son bail. C'est correct — deux `track()` simultanés sur une
        même instance mélangeraient deux vidéos — mais cela signifie qu'un job peut
        rester quelques instants en préparation à cause d'un usage concurrent, et
        non à cause d'un téléchargement.
        """
        ...


class ResultStore(Protocol):
    """Stockage du résultat détaillé — le blob de relecture.

    Sur disque et non en base : une timeline de 30 minutes compte 54 000 lignes,
    ce n'est pas une donnée relationnelle et l'interroger n'a aucun sens.
    """

    def write(self, job_id: str, payload: dict[str, Any]) -> Path:
        """Écrit le résultat compressé et rend son chemin."""
        ...

    def path_for(self, job_id: str) -> Path | None:
        """Chemin du résultat s'il existe encore sur disque, `None` sinon.

        `None` plutôt qu'une exception : un fichier disparu (purge, volume
        démonté) doit produire un message clair, pas un 500.
        """
        ...

    def input_path_for(self, job_id: str) -> Path | None:
        """Chemin de **la vidéo déposée** si elle est encore là, `None` sinon.

        `None` est un état normal et non une anomalie : la vidéo a un TTL plus court
        que le job, donc un résultat intact peut très bien l'avoir perdue.

        Sert à rejouer une analyse archivée. Les chiffres, le registre et
        l'histogramme se rejouent depuis le seul résultat ; l'incrustation des boîtes
        et le déplacement dans la timeline, eux, ont besoin de la vidéo.
        """
        ...

    def write_snapshots(self, job_id: str, snapshots: Mapping[int, VehicleSnapshot]) -> int:
        """Écrit les captures de véhicules et rend le nombre de fichiers écrits.

        **Appelée au fil de l'analyse depuis ADR 0046**, une capture à la fois, par le
        rappel `on_snapshot` et depuis le thread worker — et non plus en une seule
        passe finale, ce que cette docstring a affirmé jusqu'au 2026-08-28. La règle
        monotone d'ADR 0042 borne le débit : une écriture par *amélioration retenue*,
        jamais par lecture. L'écriture finale subsiste comme filet.

        Ne lève pas sur une capture isolée — un disque plein ne doit pas faire échouer
        une analyse dont tous les chiffres sont justes.
        """
        ...

    def snapshot_path_for(self, job_id: str, global_id: int, kind: SnapshotKind) -> Path | None:
        """Chemin d'une capture si elle est encore là, `None` sinon.

        `None` est un état **normal** : les captures suivent le TTL de la vidéo, donc
        un résultat intact peut très bien les avoir perdues.
        """
        ...

    def delete_input(self, job_id: str) -> bool:
        """Supprime **la vidéo déposée et les captures**, garde le résultat. Idempotent.

        Une opération distincte de `delete` parce que les deux données n'ont pas la
        même durée de vie légitime : une scène de trafic contient des plaques
        réelles et des visages, un résultat ne contient que des boîtes et des
        compteurs. La donnée sensible a donc son propre TTL, plus court — et une
        capture recadrée sur une voiture et sa plaque est cette donnée-là, en plus
        concentré.

        Rend `True` si un fichier a réellement été supprimé — ce qui permet à la
        boucle de purge de ne journaliser que ce qui a changé.
        """
        ...

    def delete(self, job_id: str) -> None:
        """Supprime les artefacts d'un job. **Idempotent** : un fichier déjà
        absent n'est pas une erreur."""
        ...
