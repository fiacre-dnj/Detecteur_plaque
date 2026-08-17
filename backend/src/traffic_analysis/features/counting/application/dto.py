"""Objets de transfert entre l'orchestration et ce qui l'entoure.

Le domaine n'est **jamais** sérialisé directement : un renommage de champ métier
ne doit pas casser le contrat HTTP, et inversement. Ces DTO sont la charnière.

**Ce module est aussi le contrat publié de la feature `counting`.** Une autre
feature — `jobs`, `realtime`, `benchmark` — importe d'ici, et jamais de
`counting/domain/`. C'est pour cela que les quelques types de domaine dont un
appelant a réellement besoin pour *construire* une configuration sont réexportés
plus bas : sans eux, chaque appelant devrait fouiller dans le domaine, et la
frontière ne voudrait plus rien dire.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from traffic_analysis.features.counting.application.ports import (
    EngineFrame,
    EngineSpec,
    PlateText,
)
from traffic_analysis.features.counting.domain.geometry import Point
from traffic_analysis.features.counting.domain.models import (
    DETECTABLE_CLASS_IDS,
    DETECTABLE_CLASSES,
    VEHICLE_CLASS_IDS,
    BoundingBox,
    CountingLineDef,
    DetectableClass,
    DirectionRole,
    PlateDetection,
    TrackObservation,
    VideoInfo,
    ZoneDef,
)
from traffic_analysis.features.counting.domain.plate_geometry import (
    PlateGeometry,
    is_plausible,
    select_best,
)
from traffic_analysis.features.counting.domain.plate_policy import (
    PlateDetectOptions,
    PlateDetectPolicy,
    PlateOcrOptions,
    PlateOcrPolicy,
)
from traffic_analysis.features.counting.domain.tracking_session import (
    AnalysisSession,
    SessionConfig,
)

if TYPE_CHECKING:
    from traffic_analysis.features.counting.domain.models import (
        AnalysisStats,
        CrossingEvent,
        SessionTrack,
        VehicleRecord,
        ZoneEntryEvent,
    )

# Réexports : le vocabulaire minimal qu'un appelant doit manipuler pour décrire
# une analyse. Une feature qui a besoin d'autre chose du domaine du comptage a
# besoin d'un nouveau port, pas d'un import direct.
__all__ = [
    # Le catalogue des classes cochables et sa validation. Publiés parce que
    # `models_registry` les expose par HTTP et que le schéma de requête valide
    # contre eux : les deux ont besoin de la **même** liste, sinon une case cochable
    # côté interface serait refusée à l'envoi.
    "DETECTABLE_CLASSES",
    "DETECTABLE_CLASS_IDS",
    "TIMELINE_WARNING_THRESHOLD",
    # Réexporté pour le benchmark : il mesure sur **les mêmes classes** qu'une
    # analyse. Mesurer sur les 80 classes de COCO gonflerait le post-traitement, et
    # la colonne « détections » ne correspondrait plus à ce que compte une analyse.
    "VEHICLE_CLASS_IDS",
    "AnalysisCancelled",
    "AnalysisJobConfig",
    "AnalysisResultData",
    # Réexportée pour le **temps réel**, qui doit utiliser la *même* session que le
    # mode différé — c'est ce qui garantit qu'un même tracé donne les mêmes chiffres
    # dans les deux modes. Deux implémentations du comptage divergeraient, et on ne
    # saurait pas laquelle croire.
    "AnalysisSession",
    "BoundingBox",
    "CountingLineDef",
    "DetectableClass",
    # Le vocabulaire des sens de ligne, publié pour le schéma de requête : c'est lui
    # qui valide « entry | exit | neutral », et il ne doit pas recopier la liste.
    "DirectionRole",
    "EngineFrame",
    "EngineSpec",
    # Réexportés pour le conteneur et le banc de mesure. `PlateGeometry` en
    # particulier : le filtre géométrique vit dans le domaine et non dans
    # l'adaptateur, parce que derrière `ultralytics` il n'était jamais traversé par
    # la CI — aucun test ne pouvait donc prouver qu'une boîte « véhicule entier »
    # n'atteint pas l'OCR, le défaut même qui a motivé l'ADR 0008.
    "PlateDetectOptions",
    "PlateDetectPolicy",
    "PlateDetection",
    "PlateGeometry",
    # Réexportés pour l'adaptateur d'OCR, qui vit dans `models_registry` : une autre
    # feature n'importe jamais `counting/domain/`.
    "PlateOcrOptions",
    "PlateOcrPolicy",
    "PlateText",
    "Point",
    "PreviewSample",
    "Progress",
    "TimelineRow",
    "TrackObservation",
    "VideoInfo",
    "ZoneDef",
    "is_plausible",
    "select_best",
]

# Au-delà, la timeline devient un objet de plusieurs centaines de mégaoctets.
# On n'interdit pas — l'utilisateur peut avoir de bonnes raisons — mais on
# avertit et on suggère un pas d'analyse supérieur.
TIMELINE_WARNING_THRESHOLD = 200_000


@dataclass(frozen=True, slots=True)
class AnalysisJobConfig:
    """Configuration complète d'une analyse, telle que l'orchestration la reçoit.

    Un seul objet plutôt que douze paramètres : il traverse le service, le
    `JobManager` et le thread worker sans qu'aucun d'eux ait à connaître le détail
    de ce qu'il transporte.
    """

    model_id: str
    confidence_threshold: float = 0.35
    iou_threshold: float = 0.45
    min_hits: int = 2
    mask_outside_zones: bool = False
    frame_stride: int = 1
    detect_plates: bool = False
    #: Seuil du détecteur de plaques pour **cette** course. `None` garde celui du
    #: déploiement.
    #:
    #: Il voyage par requête, contrairement aux seuils d'OCR ci-dessous, parce qu'il
    #: répond à une question que seul l'utilisateur peut trancher devant sa vidéo :
    #: « trop de rectangles, ou pas assez ». Il descend jusqu'à l'adaptateur en
    #: argument de `detect_many`, ce qui lève l'impasse où ADR 0007 l'avait laissé
    #: mort — annoncé au contrat et sans effet, le pire état d'un réglage.
    plate_confidence: float | None = None
    #: Lire le **texte** des plaques localisées, en plus de les encadrer.
    #:
    #: Distinct de `detect_plates`, et subordonné à lui : lire sans détecter n'a pas
    #: de sens, il n'y aurait aucune boîte à lire. Un drapeau à part parce que l'OCR
    #: a son propre coût, son propre modèle — donc sa propre disponibilité — et parce
    #: que persister un texte de plaque franchit un cran de confidentialité qui
    #: mérite un consentement explicite plutôt qu'un effet de bord (ADR 0007).
    #:
    #: Aucun seuil OCR ici, délibérément : ils vivent tous dans `Settings`. Ce sont
    #: des arbitrages de déploiement — combien de cœurs, quelle cadence, quelles
    #: variantes de prétraitement — que l'utilisateur d'une analyse n'a pas à
    #: connaître, et dont il ne pourrait pas juger l'effet sur sa vidéo.
    read_plate_text: bool = False
    pixels_per_meter: float | None = None
    max_lost_ms: float = 2500.0
    lines: tuple[CountingLineDef, ...] = ()
    zones: tuple[ZoneDef, ...] = ()
    #: Classes à détecter **et** à compter, choisies par l'utilisateur.
    #:
    #: Elles voyagent par requête, contrairement aux réglages de débit du moteur :
    #: c'est une question que seul l'utilisateur peut trancher devant sa scène —
    #: compte-t-on les piétons de ce carrefour, les vélos de cette piste ?
    #:
    #: Le défaut est le comportement historique, les quatre véhicules : qui ne
    #: touche à rien obtient ce que l'application faisait avant.
    #:
    #: **Restreindre les classes ne suffit pas à éviter les doublons** : le NMS
    #: d'Ultralytics est *class-aware*, et c'est `agnostic_nms=True` posé dans
    #: l'adaptateur qui empêche une camionnette de survivre en `car` **et** en
    #: `truck` (piège 5 de prompt/13).
    class_ids: tuple[int, ...] = VEHICLE_CLASS_IDS
    #: Cadence maximale d'analyse, en multiples de la vitesse réelle de la scène.
    #: `None` — le défaut — n'impose aucune borne.
    #:
    #: `1.0` fait durer l'analyse exactement le temps de la vidéo, et c'est le seul
    #: réglage qui rend l'aperçu live regardable : le client cale sa vidéo sur le
    #: temps de scène analysé, donc un serveur deux fois plus rapide que la scène
    #: produit un aperçu deux fois trop rapide (voir `domain/pacing.py`).
    #:
    #: Voyage par requête, comme les classes et pour la même raison : c'est un
    #: arbitrage que seul l'utilisateur devant sa vidéo peut trancher — regarder, ou
    #: obtenir ses chiffres au plus vite. Le défaut est le comportement historique.
    #:
    #: **Sans effet en direct**, où le client cadence lui-même son envoi. Comme
    #: `frame_stride`, ce champ ne concerne que la lecture d'un fichier.
    analysis_speed: float | None = None
    #: Plafond **absolu** de cadence, en images analysées par seconde réelle.
    #: `None` — le défaut — n'impose aucune borne.
    #:
    #: Indépendant d'`analysis_speed` : celui-ci borne la vitesse *relative* à la
    #: scène (« pas plus vite que la vidéo »), celui-ci borne le débit *absolu* du
    #: serveur (« jamais plus de N images par seconde », quelle que soit la
    #: cadence de la source). Les deux peuvent être posés ensemble — le plus
    #: restrictif des deux s'applique — et chacun peut s'appliquer même quand
    #: l'autre est `None` (`domain/pacing.py`).
    #:
    #: **Sans effet en direct**, comme `analysis_speed`.
    max_analysis_fps: float | None = None

    def engine_spec(self) -> EngineSpec:
        """Ce que le moteur doit savoir : les seuils **vivants** de la requête."""
        return EngineSpec(
            model_id=self.model_id,
            confidence=self.confidence_threshold,
            iou=self.iou_threshold,
            class_ids=self.class_ids,
            frame_stride=self.frame_stride,
        )

    def session_config(self) -> SessionConfig:
        """Ce que le domaine doit savoir : la géométrie et les règles de comptage."""
        return SessionConfig(
            lines=self.lines,
            zones=self.zones,
            mask_outside_zones=self.mask_outside_zones,
            min_hits=self.min_hits,
            max_lost_ms=self.max_lost_ms,
            pixels_per_meter=self.pixels_per_meter,
        )


@dataclass(frozen=True, slots=True)
class Progress:
    """Avancement d'une analyse, publié vers le SSE.

    `processed` et `total` sont en **images analysées**, pas en images du fichier :
    avec `frame_stride = 3`, diviser par le nombre total d'images ferait plafonner
    la barre à 33 % (piège 22 de prompt/13).
    """

    processed_frames: int
    total_frames: int
    processing_fps: float

    @property
    def ratio(self) -> float:
        """Fraction accomplie, bornée à 1.

        Bornée parce que le nombre d'images annoncé par un conteneur est parfois
        approximatif : une barre à 103 % est un bug visible par tout le monde.
        """
        if self.total_frames <= 0:
            return 0.0
        return min(1.0, self.processed_frames / self.total_frames)


@dataclass(frozen=True, slots=True)
class PreviewSample:
    """Un aperçu de l'analyse en cours, publié pendant qu'elle tourne.

    **C'est un échantillon, pas une frame de la timeline.** Une analyse produit
    des dizaines d'images par seconde ; les publier toutes noierait le flux SSE
    sans rien apporter à l'œil. Une sur N est publiée, et cet objet porte alors
    *tout* ce qui s'est passé depuis le précédent.

    D'où le point qui compte : `crossings` et `zone_events` sont **cumulés depuis
    l'aperçu précédent**, pas ceux de la seule frame publiée. Ne renvoyer que les
    événements de la frame échantillonnée en perdrait la grande majorité, et le
    journal affiché à l'utilisateur mentirait — alors même que les compteurs de
    `stats`, eux, seraient justes. Un journal en désaccord avec un total est pire
    qu'un journal absent.

    Les pistes sont des **snapshots**, comme dans la timeline et pour la même
    raison : la référence vivante convergerait vers l'état final.

    `frame_width` / `frame_height` sont les dimensions sondées par le serveur.
    Elles ne servent pas au dessin — la géométrie est déjà en pixels source — mais
    elles permettent au client de comparer avec ce que sa balise `<video>` lui
    rapporte et de **refuser de dessiner** en cas de désaccord, plutôt que
    d'afficher des boîtes décalées que rien n'expliquerait (invariant 13).

    `vehicles` est le **registre en cours de constitution** — les mêmes
    `VehicleRecord` que le résultat final, par le même agrégat et le même
    sérialiseur. C'est ce qui permet au registre et à la statistique de se
    remplir pendant l'analyse au lieu d'attendre la fin, sans qu'aucun compteur
    soit reconstruit côté navigateur : un agrégat parallèle divergerait, et le
    vote de plaque comme le vote de classe ne sont pas reproductibles depuis les
    seules images échantillonnées (invariants 3 et 4).

    Deux réserves portées par ce champ, et il ne faut pas les confondre :

    - **`None` veut dire « inchangé », jamais « aucun véhicule »** — une liste
      vide dit cela. Le registre entier est republié à sa propre cadence, plus
      lente que celle des boîtes : il grossit avec l'analyse, là où les pistes
      d'une image restent une poignée. Le client conserve alors la dernière liste
      reçue ;
    - il ne porte que les véhicules **ayant franchi au moins une ligne**
      (`crossed_only`), la population que l'écran affiche depuis ADR 0023. Le
      résultat archivé, lui, garde tout objet suivi confirmé.
    """

    frame_index: int
    timestamp_ms: float
    frame_width: int
    frame_height: int
    tracks: tuple[SessionTrack, ...]
    crossings: tuple[CrossingEvent, ...]
    zone_events: tuple[ZoneEntryEvent, ...]
    stats: AnalysisStats
    #: Le registre à cet instant, ou `None` s'il n'a pas été republié — voir la
    #: docstring de la classe : `None` n'est pas une liste vide.
    vehicles: tuple[VehicleRecord, ...] | None = None


@dataclass(frozen=True, slots=True)
class TimelineRow:
    """Une frame figée de la timeline.

    Les pistes sont des **snapshots**, pris après la passe ANPR. Stocker la
    référence vivante ferait converger toutes les frames vers l'état final.
    """

    frame_index: int
    timestamp_ms: float
    tracks: tuple[SessionTrack, ...]


@dataclass(slots=True)
class AnalysisResultData:
    """Le résultat complet d'une analyse, avant sérialisation.

    Mutable et non gelé : il se remplit au fil de l'analyse. Il ne quitte le
    processus que sérialisé en `json.gz` — une timeline de 30 minutes ne reste pas
    en mémoire après la fin du job.
    """

    job_id: str
    model_id: str
    video: VideoInfo
    processing_fps: float = 0.0
    timeline: list[TimelineRow] = field(default_factory=list)
    crossings: list[CrossingEvent] = field(default_factory=list)
    zone_events: list[ZoneEntryEvent] = field(default_factory=list)
    vehicles: tuple[VehicleRecord, ...] = ()
    stats: AnalysisStats | None = None


class AnalysisCancelled(Exception):
    """Une annulation demandée par l'utilisateur.

    **Ce n'est pas une erreur.** Le `JobManager` la traduit en statut `cancelled`,
    et l'interface n'affiche aucun message rouge : l'utilisateur sait ce qu'il a
    fait, lui dire que « l'analyse a échoué » serait faux.
    """
