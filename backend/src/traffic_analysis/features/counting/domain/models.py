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
from typing import Literal

from traffic_analysis.features.counting.domain.geometry import Point

#: Pourquoi aucune plaque n'est publiée pour un véhicule — **cinq causes, cinq
#: gestes différents**.
#:
#: - `ocr_disabled` : la lecture n'a pas été demandée, ou son modèle est absent.
#:   Rien n'a été tenté ; ce n'est pas un échec.
#: - `not_detected` : aucune plaque n'a été localisée. Angle de vue, occlusion, ou
#:   véhicule vu de côté — pas une affaire de résolution.
#: - `too_small` : des plaques ont été vues, toutes sous le plancher de lecture.
#:   **La cause dominante sur les vidéos disponibles** (27 à 88 px pour un plancher
#:   mesuré à ~64). Un plan plus serré ou un capteur plus défini y répondrait.
#: - `too_blurry` : assez larges, mais trop floues — flou de mouvement ou mise au
#:   point. Une vitesse d'obturation plus courte y répondrait.
#: - `no_consensus` : plusieurs lectures, aucune majorité. C'est le refus honnête
#:   du vote, et non une panne : publier une des lectures divergentes ferait
#:   apparaître une plaque fausse et parfaitement plausible.
type PlateUnreadReason = Literal[
    "ocr_disabled",
    "not_detected",
    "too_small",
    "too_blurry",
    "no_consensus",
]

# Les quatre classes COCO comptées, traitées à l'identique.
#
# `car`, `motorcycle`, `bus` et `truck` sont mutuellement exclusives sur un objet
# physique : une camionnette ne doit pas survivre comme `car 0.52` ET `truck 0.41`,
# sinon elle devient deux pistes, deux identités, et compte deux fois (piège 5 de
# prompt/13).
#
# Deux réglages sont nécessaires, et **le second manquait** : `classes=[2,3,5,7]`
# restreint les détections à ces quatre classes, mais le NMS par défaut
# d'Ultralytics est *class-aware* — il ne compare que des boîtes de même classe et
# laisse donc passer le doublon. C'est `agnostic_nms=True`, posé sur les deux
# appels de `ultralytics_engine.py`, qui traite réellement le cas.
VEHICLE_CLASS_IDS: tuple[int, ...] = (2, 3, 5, 7)

#: Catégorie d'un objet compté. **Les catégories ne se mélangent jamais dans un
#: total affiché** : une personne qui traverse n'est pas un véhicule de plus.
type CountCategory = Literal["vehicle", "person"]


@dataclass(frozen=True, slots=True)
class DetectableClass:
    """Une classe que l'utilisateur peut cocher pour la détecter et la compter.

    `coco_name` est le nom que **le modèle** rend (`result.names`), et c'est donc
    la clé sous laquelle les tallies s'accumulent. `label` est ce que l'interface
    affiche. Les deux sont séparés parce que traduire à l'affichage est un choix de
    présentation, alors que le nom du modèle est un contrat : le confondre avec sa
    traduction ferait rater toutes les correspondances de `by_class`.

    **Ne rien déduire d'un nom de fichier ni d'un identifiant** (invariant 10) : la
    catégorie est portée ici, explicitement, et non calculée depuis l'indice COCO.
    """

    id: int
    coco_name: str
    label: str
    category: CountCategory


#: Les classes proposées à la sélection, dans l'ordre d'affichage.
#:
#: **Ce sont exactement celles que les modèles du catalogue savent reconnaître.**
#: Ils sont tous entraînés sur COCO ; une classe absente de COCO — une charrette,
#: par exemple — ne s'ajoute pas ici, elle demande un autre modèle. Écrire la ligne
#: sans le modèle donnerait une case à cocher qui ne détecte jamais rien, ce qui se
#: lit comme une panne.
#:
#: L'ordre est celui de la circulation la plus fréquente vers la plus rare, parce
#: que c'est l'ordre dans lequel on coche.
DETECTABLE_CLASSES: tuple[DetectableClass, ...] = (
    DetectableClass(2, "car", "Voiture", "vehicle"),
    DetectableClass(3, "motorcycle", "Moto", "vehicle"),
    DetectableClass(5, "bus", "Bus", "vehicle"),
    DetectableClass(7, "truck", "Camion", "vehicle"),
    DetectableClass(1, "bicycle", "Vélo", "vehicle"),
    DetectableClass(0, "person", "Personne", "person"),
    DetectableClass(6, "train", "Train", "vehicle"),
)

#: `coco_name` → catégorie. Construit une fois : `stats()` l'interroge par classe
#: comptée et à chaque publication d'aperçu.
CATEGORY_OF_CLASS: dict[str, CountCategory] = {
    entry.coco_name: entry.category for entry in DETECTABLE_CLASSES
}

#: Identifiants sélectionnables, pour la validation de la requête.
DETECTABLE_CLASS_IDS: frozenset[int] = frozenset(entry.id for entry in DETECTABLE_CLASSES)


def category_of(label: str) -> CountCategory:
    """Catégorie d'un label de classe. Inconnu ⇒ `vehicle`.

    Le repli ne masque rien d'important : un label inconnu ne peut venir que d'un
    modèle entraîné sur autre chose que COCO, et le compter comme véhicule vaut
    mieux que de le faire disparaître d'un total. La somme des catégories reste
    donc égale au total des franchissements, ce qui est l'invariant qui compte.
    """
    return CATEGORY_OF_CLASS.get(label, "vehicle")


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

    def intersection_area(self, other: BoundingBox) -> float:
        """Aire commune aux deux boîtes, `0` si elles ne se touchent pas."""
        left = max(self.x, other.x)
        top = max(self.y, other.y)
        right = min(self.x + self.width, other.x + other.width)
        bottom = min(self.y + self.height, other.y + other.height)
        if right <= left or bottom <= top:
            return 0.0
        return (right - left) * (bottom - top)

    def containment(self, other: BoundingBox) -> float:
        """`intersection / min(aire)` — la mesure qui attrape la boîte incluse.

        **Pas l'IoU, et c'est tout le point.** Sur un bus ou un semi-remorque, le
        détecteur émet parfois une boîte sur la cabine *et* une sur le véhicule
        entier. Leur IoU vaut environ 0,3 — sous n'importe quel seuil raisonnable,
        donc le NMS les garde toutes les deux : deux pistes, deux identités, deux
        franchissements. Le total est simplement trop haut, et rien ne l'explique.

        La containment, elle, vaut 1,0 dans ce cas : la petite boîte est
        entièrement dans la grande. Diviser par la **plus petite** aire est ce qui
        rend la mesure insensible à la différence de taille, là où l'IoU la punit.

        Rend `0` si l'une des deux boîtes est dégénérée, plutôt que de diviser par
        zéro : une boîte d'aire nulle ne contient rien et n'est contenue par rien.
        """
        smallest = min(self.area, other.area)
        if smallest <= 0:
            return 0.0
        return self.intersection_area(other) / smallest


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

    `box`/`score` viennent du **détecteur**, `text`/`text_score` du **lecteur**,
    qui est une passe distincte et optionnelle. Les deux couples sont donc
    indépendants, et c'est ce qui rend trois états distinguables : aucune plaque,
    une plaque vue mais illisible (`text is None` avec un `score` bien réel), une
    plaque lue. Les confondre afficherait « aucune plaque » sur un véhicule dont le
    rectangle est visible à l'écran.
    """

    box: BoundingBox
    score: float
    #: Texte **normalisé** (A-Z, 0-9, tirets), ou `None` si rien n'a été lu.
    #: `None` et non `""` : « pas lu » et « lu vide » ne sont pas la même
    #: information, et le fil doit pouvoir les distinguer.
    text: str | None = None
    #: Confiance du décodage. `0.0` quand `text is None` — et c'est le sérialiseur
    #: qui traduit cela en `null`, pour ne pas annoncer « lu, sans aucune
    #: confiance ».
    text_score: float = 0.0
    #: Confiance de chaque caractère de `text`, le temps d'atteindre le vote.
    #:
    #: **De passage, jamais stockée** : `record_plates` la consomme pour alimenter le
    #: consensus par caractère, puis la remet à vide avant de ranger la détection dans
    #: la piste. Elle ne figure donc ni dans la timeline, ni sur le fil — une
    #: information utile pendant trois lignes n'a pas à peser sur chaque frame d'un
    #: clip de trente minutes, ni à élargir un contrat publié.
    text_char_scores: tuple[float, ...] = ()
    #: Cette boîte est une **reprojection**, pas une mesure de cette image.
    #:
    #: Le détecteur est étranglé (`PlateDetectPolicy`) ; les images qu'il saute
    #: reçoivent l'ancre de la dernière détection réelle, reprojetée sur la boîte
    #: courante du véhicule. Sans ce drapeau, rien ne distinguerait une plaque vue
    #: d'une plaque estimée, et deux règles en dépendent :
    #:
    #: - **l'OCR ne lit jamais une boîte `stale`** — une extrapolation n'est pas une
    #:   mesure, et la faire voter fabriquerait de la confiance à partir de rien ;
    #: - le canvas la dessine en trait plus fin, même vocabulaire visuel que les
    #:   pistes non confirmées en pointillés.
    #:
    #: **Sérialisé seulement quand il vaut `True`** — exception assumée à la règle
    #: « `null` explicite » du projet, pour la même raison qu'ADR 0008 justifie de
    #: jeter les confiances par caractère : un booléen sur 100 % des plaques de
    #: 45 000 images pèse, et il n'a de sens que dans le cas minoritaire.
    stale: bool = False
    #: Netteté de la vignette, en variance de laplacien. **De passage, jamais
    #: sérialisée** — exactement le statut de `text_char_scores`.
    #:
    #: Mesurée par le détecteur, seule couche qui ait les pixels et le droit
    #: d'importer `cv2` ; consommée par `PlateOcrPolicy`, qui décide s'il vaut la
    #: peine de relire cette identité. Elle ne va pas plus loin : la timeline n'a
    #: rien à en faire, et un flottant par plaque et par image d'un clip de trente
    #: minutes pèserait pour une information utile pendant trois lignes.
    #:
    #: `0.0` signifie « non mesurée » et non « parfaitement floue » : la politique
    #: retombe alors sur la largeur seule, ce qui garde tout utilisable sans mesure.
    sharpness: float = 0.0


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
    #: Texte de plaque **voté au moment du franchissement**, ou `None`.
    #:
    #: `None` est fréquent et légitime : les franchissements de la frame *N* sont
    #: émis dans `AnalysisSession.feed()`, donc **avant** la passe OCR de la frame
    #: *N*. Une plaque lue pour la première fois sur la frame même du
    #: franchissement n'apparaît donc pas sur cette ligne — elle apparaît dans le
    #: registre, qui agrège toute la vie du véhicule. Un franchissement dit ce que
    #: le serveur savait quand il a compté ; le registre dit ce qu'il sait à la
    #: fin, et c'est lui l'autorité. Voir ADR 0007.
    plate_text: str | None = None
    plate_text_score: float | None = None

    @property
    def category(self) -> CountCategory:
        """Véhicule ou personne, dérivé de `label`.

        Portée par l'événement plutôt que recalculée par ses lecteurs : la relecture
        côté navigateur ventile les franchissements par catégorie au fil de la tête
        de lecture, et lui faire deviner la catégorie depuis un libellé la
        forcerait à recopier la politique du serveur. Deux copies d'une règle de
        classement finissent par diverger, et c'est un franchissement qui change de
        colonne selon l'écran qui le montre.
        """
        return category_of(self.label)


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
    #: Texte **voté** de l'identité, recopié depuis son agrégat par
    #: `AnalysisSession._mirror_plate_text`. Pas la lecture de la frame : c'est
    #: l'invariant 4 appliqué au texte, et c'est ce champ — non `plates[].text` —
    #: que l'interface affiche. L'étranglement de l'OCR ne remplit `plates[].text`
    #: qu'une frame sur trois : dessiner cela ferait clignoter l'étiquette. Même
    #: raison d'être qu'`identity_label` à côté de `label`.
    #:
    #: `""` tant que le vote n'est pas concluant, et **survit** à ce que
    #: `_advance_tracks` efface : les *boîtes* appartiennent à la frame, le texte
    #: appartient à l'identité.
    plate_text: str = ""
    plate_text_score: float = 0.0

    def snapshot(self) -> SessionTrack:
        """Copie figée de l'état courant — **ce n'est pas une commodité**.

        La session mute la *même* instance d'une frame à l'autre. Une timeline
        qui stockerait la référence vivante verrait **toutes ses lignes converger
        vers l'état final** : à la relecture, chaque frame afficherait la position
        finale des véhicules (piège 24 de prompt/13).

        `plates` est copié explicitement : partager la liste ferait réapparaître
        le même bug un niveau plus bas.

        Le snapshot doit être pris **après** la passe ANPR **et** après la passe
        OCR, sinon les plaques manquent — ou, plus insidieux, y figurent sans leur
        texte, et la relecture afficherait des boîtes muettes que l'analyse avait su
        lire. C'est la responsabilité du service d'orchestration.
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
            plate_text=self.plate_text,
            plate_text_score=self.plate_text_score,
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
    #: Meilleure confiance de **détection** de plaque sur toute la vie du véhicule.
    best_plate_score: float | None
    #: Texte **voté** sur toute la vie du véhicule — l'autorité de l'interface, au
    #: même titre que `label` est le libellé du vote et non la dernière lecture.
    #:
    #: `None` avec un `best_plate_score` non nul veut dire quelque chose de précis :
    #: une plaque a bien été vue, aucune lecture ne fait consensus. L'interface doit
    #: dire *cela*, et non laisser une case vide en face d'un rectangle visible.
    plate_text: str | None = None
    #: Confiance moyenne de la **lecture** gagnante, distincte de celle de la
    #: détection. Une plaque affichée sans dire à quel point le serveur y croit
    #: invite à croire toutes les lignes également.
    plate_text_score: float | None = None
    #: **Pourquoi** aucune plaque n'est publiée pour ce véhicule.
    #:
    #: `None` quand il y en a une. Sinon, la cause exacte parmi cinq, parce que les
    #: cinq appellent des gestes différents : installer un modèle, resserrer le
    #: plan, stabiliser la caméra, ou rien du tout. Une case vide, elle, se lit
    #: comme une panne du service — et c'est ce que l'étranglement et le plancher
    #: de lecture rendent **plus** fréquent, pas moins.
    #:
    #: Au niveau **identité** et jamais au niveau image, pour la raison qu'ADR 0008
    #: donne à propos des confiances par caractère : `VehicleRecord` est en
    #: O(véhicules), `TrackSnapshot` en O(images × pistes), et une raison d'échec
    #: est un fait de la vie du véhicule.
    plate_unread_reason: PlateUnreadReason | None = None
    #: Largeur de la meilleure plaque vue, en pixels. `None` si aucune.
    #:
    #: C'est le chiffre qui rend la raison **actionnable** : « vue à 48 px » dit de
    #: resserrer le plan ou de changer de capteur, « non détectée » dit tout autre
    #: chose. Sans lui, `too_small` laisse l'utilisateur sans repère sur l'ampleur
    #: de l'écart.
    plate_best_width_px: float | None = None
    #: Le meilleur candidat lu même **sans** consensus, ou `None`. N'engage pas le
    #: serveur : contrairement à `plate_text`, ce n'est pas un vote qui a passé les
    #: seuils de publication, seulement le candidat en tête au moment où le vote a
    #: cessé de progresser.
    #:
    #: Rempli seulement quand `plate_unread_reason == "no_consensus"` — dans tous
    #: les autres cas de silence (plaque non détectée, trop petite, trop floue,
    #: OCR désactivé), aucune lecture n'a eu lieu et il n'y a rien à rapporter.
    plate_best_guess: str | None = None
    #: Confiance moyenne du candidat ci-dessus. `None` ssi `plate_best_guess` l'est.
    plate_best_guess_score: float | None = None


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
    #: Boîtes écartées parce qu'entièrement incluses dans une autre — la cabine
    #: d'un semi-remorque dans la boîte du véhicule entier. Publié plutôt que
    #: silencieux : une suppression invisible serait aussi opaque que le doublon
    #: qu'elle évite, et c'est ce chiffre qui dit si le seuil est bien réglé.
    contained_out: int = 0


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

    @property
    def by_category(self) -> dict[str, int]:
        """Franchissements par **catégorie** : les véhicules d'un côté, les
        personnes de l'autre.

        **Une propriété et non un champ**, précisément parce que c'est un dérivé :
        stocker cette ventilation à côté de `by_class` créerait un second compteur
        du même fait, et deux compteurs du même fait finissent toujours par se
        contredire — c'est l'invariant 3, celui qui a déjà coûté un bug ici. Calculée
        depuis `by_class`, sa somme **est** `crossings` par construction, sans
        qu'aucun test n'ait à le surveiller.

        C'est ce qui permet d'afficher « 42 véhicules, 7 personnes » sans jamais les
        additionner : un piéton n'est pas un véhicule de plus, et les mélanger
        rendrait le total inutilisable pour les deux usages.
        """
        totals: dict[str, int] = {}
        for label, count in self.by_class.items():
            key = category_of(label)
            totals[key] = totals.get(key, 0) + count
        return totals


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
