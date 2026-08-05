"""Le vocabulaire du domaine.

Deux familles d'objets, et la distinction est essentielle :

- **immuables** (`frozen=True`) — ce que le moteur rapporte, ce que la géométrie
  décrit, ce que la session émet. Personne ne peut les modifier après coup ;
- **vivants** (`slots=True` seul) — `SessionTrack`, muté frame après frame.

`slots=True` partout n'est pas cosmétique : une timeline de 30 minutes à 30 fps
compte 54 000 lignes, soit ~430 000 instantanés de pistes à 8 pistes moyennes.
L'empreinte mémoire devient visible.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from traffic_analysis.features.counting.domain.geometry import Point

# Les quatre classes COCO comptées, traitées à l'identique.
# `car`, `motorcycle`, `bus` et `truck` sont mutuellement exclusives sur un objet
# physique : une camionnette ne doit pas survivre comme `car 0.52` ET `truck 0.41`,
# sinon elle devient deux pistes, deux identités, et compte deux fois
# (piège 5 de prompt/13). C'est `classes=[2,3,5,7]` passé au moteur, plus le NMS
# d'Ultralytics, qui traitent le cas.
VEHICLE_CLASS_IDS: tuple[int, ...] = (2, 3, 5, 7)


@dataclass(frozen=True, slots=True)
class BoundingBox:
    """Boîte en pixels source, coin supérieur gauche + dimensions."""

    x: float
    y: float
    width: float
    height: float

    @property
    def centroid(self) -> Point:
        """Centre de la boîte — le point qui décide de tout.

        C'est le centroïde, et non un coin ni le bord inférieur, qui sert au
        franchissement, à l'appartenance à une zone et à la vitesse. Conséquence
        à énoncer dans l'interface : avec « ignorer hors zone », un véhicule dont
        le *centroïde* sort du polygone cesse d'être compté — d'où le conseil de
        dessiner large (piège 10 de prompt/13).
        """
        return Point(self.x + self.width / 2.0, self.y + self.height / 2.0)

    @property
    def area(self) -> float:
        return self.width * self.height


@dataclass(frozen=True, slots=True)
class TrackObservation:
    """Ce que le moteur rapporte pour une piste sur une frame.

    C'est la frontière du domaine : l'adaptateur Ultralytics est le seul à savoir
    transformer un `Results`/`Boxes`/`xyxy` en cet objet-ci.
    """

    track_id: int
    class_id: int
    label: str
    score: float
    box: BoundingBox


@dataclass(frozen=True, slots=True)
class CountingLineDef:
    """Une ligne de comptage, éventuellement restreinte à une zone.

    `zone_id` renseigné signifie « ne compter que les franchissements dont le
    centroïde est dans cette zone ». C'est ce qui permet de compter une voie
    précise d'un carrefour sans compter la voie voisine que la même ligne
    traverse.
    """

    id: str
    name: str
    a: Point
    b: Point
    zone_id: str | None = None


@dataclass(frozen=True, slots=True)
class ZoneDef:
    """Une zone polygonale."""

    id: str
    name: str
    points: tuple[Point, ...]


@dataclass(frozen=True, slots=True)
class VideoInfo:
    """Caractéristiques de la source, établies par `probe()`."""

    width: int
    height: int
    fps: float
    frame_count: int

    @property
    def duration_ms(self) -> float:
        """Durée en millisecondes de scène.

        `fps` nul est possible sur un conteneur mal formé : rendre `0.0` plutôt
        que de lever, parce qu'une durée inconnue n'empêche pas de compter.
        """
        if self.fps <= 0:
            return 0.0
        return self.frame_count / self.fps * 1000.0

    @property
    def diagonal(self) -> float:
        """Diagonale de l'image, en pixels.

        Sert de référence au gate de déplacement de la ré-identification : un
        budget exprimé en fraction de la diagonale reste valable quelle que soit
        la résolution.
        """
        return float((self.width**2 + self.height**2) ** 0.5)


@dataclass(frozen=True, slots=True)
class PlateDetection:
    """Une plaque localisée, en coordonnées de l'image **complète**.

    L'adaptateur ANPR travaille sur un recadrage mais réexprime ses boîtes dans
    le référentiel de l'image entière : aucune couche en aval ne doit avoir à le
    savoir.
    """

    box: BoundingBox
    score: float


@dataclass(frozen=True, slots=True)
class CrossingEvent:
    """Un franchissement qui a **réellement atteint un compteur**.

    Le compteur n'émet pas d'événement pour un franchissement supprimé par le
    garde d'identité : sinon le badge ✓ de l'interface affirmerait qu'un véhicule
    est compté alors que le total n'a pas bougé (piège 2 de prompt/13).
    """

    line_id: str
    global_id: int
    track_id: int
    label: str
    direction: int  # +1 (A→B) | -1 (B→A)
    timestamp_ms: float
    frame_index: int


@dataclass(frozen=True, slots=True)
class ZoneEntryEvent:
    """Un front dehors→dedans, dédupliqué par identité."""

    zone_id: str
    global_id: int
    label: str
    timestamp_ms: float
    frame_index: int


@dataclass(slots=True)
class SessionTrack:
    """État **vivant** d'une piste, muté d'une frame à l'autre.

    Cet objet est délibérément mutable : la session le fait avancer frame après
    frame plutôt que d'en recréer un, ce qui évite des centaines de milliers
    d'allocations sur un clip long.

    C'est aussi précisément la raison d'être de `snapshot()`.
    """

    track_id: int
    class_id: int
    label: str
    score: float
    box: BoundingBox
    centroid: Point
    previous_centroid: Point | None = None
    hits: int = 0
    global_id: int = 0  # 0 tant que la galerie n'a pas tranché
    reid_count: int = 0
    identity_label: str = ""  # vote majoritaire — c'est LUI qui sert au comptage
    counted: bool = False  # écrit par la session depuis le tally, jamais deviné
    last_seen_ms: float = 0.0
    speed_px_s: float | None = None
    plates: list[PlateDetection] = field(default_factory=list)

    def snapshot(self) -> SessionTrack:
        """Copie figée de l'état courant — **ce n'est pas une commodité**.

        La session mute la *même* instance d'une frame à l'autre. Une timeline
        qui stockerait la référence vivante verrait **toutes ses lignes converger
        vers l'état final** : à la relecture, chaque frame afficherait la position
        finale des véhicules (piège 24 de prompt/13).

        `plates` est copié explicitement : partager la liste ferait réapparaître
        le même bug un niveau plus bas.

        Le snapshot doit être pris **après** la passe ANPR, sinon les plaques
        manquent — c'est la responsabilité du service d'orchestration.
        """
        return SessionTrack(
            track_id=self.track_id,
            class_id=self.class_id,
            label=self.label,
            score=self.score,
            box=self.box,
            centroid=self.centroid,
            previous_centroid=self.previous_centroid,
            hits=self.hits,
            global_id=self.global_id,
            reid_count=self.reid_count,
            identity_label=self.identity_label,
            counted=self.counted,
            last_seen_ms=self.last_seen_ms,
            speed_px_s=self.speed_px_s,
            plates=list(self.plates),
        )

    @property
    def counting_label(self) -> str:
        """Le libellé sous lequel ce véhicule est compté.

        Le vote majoritaire de la galerie gagne sur la lecture de la frame
        courante : un véhicule dont la classe vacille entre bus et camion ne doit
        pas changer de compteur au gré des images (invariant 4 de prompt/03).
        """
        return self.identity_label or self.label


@dataclass(slots=True)
class LineTally:
    """Compteurs d'une ligne. `total` vaut toujours `positive + negative`."""

    total: int = 0
    by_class: dict[str, int] = field(default_factory=dict)
    positive: int = 0  # sens A→B
    negative: int = 0  # sens B→A


@dataclass(slots=True)
class ZoneTally:
    """Compteurs d'une zone.

    `entries` est un **cumul** qui ne décroît jamais ; `inside` est une **lecture
    instantanée**, réécrite à chaque frame. Les confondre est l'erreur classique :
    accumuler `inside` produirait un nombre de présents qui ne cesse de croître.
    """

    entries: int = 0
    inside: int = 0
    by_class: dict[str, int] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class LineCrossing:
    """Un franchissement tel que le registre d'un véhicule le mémorise."""

    line_id: str
    direction: int
    timestamp_ms: float


@dataclass(frozen=True, slots=True)
class VehicleRecord:
    """Une ligne du registre : l'agrégat d'une identité sur toute la session.

    Le registre existe parce que les cartes de synthèse disent *combien* et que
    lui seul dit *lesquels*. C'est ce qui rend un total vérifiable plutôt que
    croyable.
    """

    global_id: int
    label: str
    first_seen_ms: float
    last_seen_ms: float
    crossed_lines: tuple[LineCrossing, ...]
    zones_visited: tuple[str, ...]
    reid_count: int
    avg_speed_px_s: float | None
    avg_speed_kmh: float | None
    best_plate_score: float | None


@dataclass(frozen=True, slots=True)
class Diagnostics:
    """Compteurs de diagnostic, pour rendre « le compte est faux » explicable.

    Sans eux, un véhicule manquant est indiscernable : n'a-t-il jamais été
    détecté, l'a-t-il été faiblement, n'était-il pas confirmé, ou a-t-il été
    masqué par une zone ? Le panneau de diagnostic de l'interface répond, et ces
    champs sont sa source.
    """

    high_detections: int = 0
    low_detections: int = 0
    masked_out: int = 0
    confirmed_tracks: int = 0
    tentative_tracks: int = 0
    rescued_by_low_score: int = 0


@dataclass(frozen=True, slots=True)
class AnalysisStats:
    """Le bloc de statistiques, dans la forme exacte que l'interface affiche.

    `crossings` et `by_class` sont **dérivés** de `by_line` : les accumuler en
    parallèle produirait tôt ou tard deux compteurs qui se contredisent
    (invariant 3 de prompt/03).
    """

    unique_vehicles: int
    unique_by_class: dict[str, int]
    crossings: int
    by_class: dict[str, int]
    by_line: dict[str, LineTally]
    by_zone: dict[str, ZoneTally]
    reid_hits: int
    vehicles_per_minute: float
    active_tracks: int
    elapsed_ms: float
    analysed_scene_ms: float
    diagnostics: Diagnostics = field(default_factory=Diagnostics)


@dataclass(frozen=True, slots=True)
class FrameOutcome:
    """Ce qu'une frame a produit.

    `tracks` porte les pistes **vivantes** (pas des snapshots) : le service en a
    besoin pour la passe ANPR, qui doit écrire dedans avant que le snapshot soit
    pris.
    """

    frame_index: int
    timestamp_ms: float
    tracks: tuple[SessionTrack, ...]
    crossings: tuple[CrossingEvent, ...]
    zone_events: tuple[ZoneEntryEvent, ...]
