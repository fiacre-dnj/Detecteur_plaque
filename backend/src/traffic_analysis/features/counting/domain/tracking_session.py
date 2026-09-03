"""La session de comptage : la composition, une frame à la fois.

**La même session sert le fichier différé et le flux temps réel.** C'est tout
l'intérêt du découpage : il n'existe qu'une implémentation du comptage, donc les
deux modes ne peuvent pas diverger.

L'ordre des étapes de `feed()` est impératif :

- **`_mask` avant le suivi**, jamais après : avec « ignorer hors zone », une
  détection hors zone ne doit jamais devenir une piste ;
- **numéroter avant de compter** : un franchissement doit porter le numéro de son
  véhicule, et l'émission différée d'un franchissement en attente tombe sur la
  frame même où la piste se confirme — donc où son numéro est émis.

L'ancienne contrainte « relâcher avant d'admettre » a disparu avec la galerie de
ré-identification (ADR 0016) : plus rien n'est admis, donc plus rien ne se dispute
une identité relâchée.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from typing import TYPE_CHECKING

from traffic_analysis.features.counting.domain.line_counter import LineCrossingCounter
from traffic_analysis.features.counting.domain.models import (
    SNAPSHOT_CAUSE_PRIORITY,
    AnalysisStats,
    CountingLineDef,
    CrossingEvent,
    Diagnostics,
    DirectionTally,
    FrameOutcome,
    LineCrossing,
    LineTally,
    PlateDetection,
    SessionTrack,
    SnapshotCause,
    TrackObservation,
    VehicleRecord,
    ZoneDef,
    ZoneTally,
    class_group,
)
from traffic_analysis.features.counting.domain.plate_geometry import unread_reason
from traffic_analysis.features.counting.domain.plate_text import normalise_plate_reading
from traffic_analysis.features.counting.domain.plate_vote import PlateTextVote
from traffic_analysis.features.counting.domain.track_numbering import TrackNumbering
from traffic_analysis.features.counting.domain.zone_counter import ZonePresenceCounter
from traffic_analysis.features.counting.domain.zone_geometry import point_is_in_any_zone

if TYPE_CHECKING:
    from collections.abc import Sequence


# En dessous de trois secondes de flux analysé, l'extrapolation du débit oscille
# trop pour être publiable : on rend 0 et l'interface le dit.
MIN_SCENE_MS_FOR_FLOW = 3000.0
_MS_PER_MINUTE = 60_000.0

#: Seuil de containment au-delà duquel la plus petite boîte est écartée.
#:
#: Sévère à dessein. Le cas cible — cabine incluse dans le véhicule entier —
#: atteint 1,0, tandis qu'une voiture roulant devant un camion peut être à 0,8
#: dans la boîte du camion : la supprimer effacerait un vrai véhicule. Sous-compter
#: est l'erreur la plus difficile à remarquer, donc en cas de doute on garde
#: (piège 6 de prompt/13).
CONTAINMENT_THRESHOLD = 0.9


@dataclass(frozen=True, slots=True)
class SessionConfig:
    """Réglages de comptage d'une session.

    Tous viennent de la requête : ce sont les réglages *vivants* de l'utilisateur,
    et non des constantes du catalogue.
    """

    lines: tuple[CountingLineDef, ...] = ()
    zones: tuple[ZoneDef, ...] = ()
    mask_outside_zones: bool = False
    min_hits: int = 2
    #: Miroir exact de `track_buffer: 75` du tracker Ultralytics (≈ 2,5 s à 30 fps).
    #: Si l'une des deux valeurs change, l'autre doit suivre, sinon le moteur et le
    #: domaine ne sont plus d'accord sur ce qu'est « une piste perdue ».
    #:
    #: Au-delà de ce silence, la session abandonne la piste **et oublie son
    #: numéro** : un identifiant de piste réémis par le tracker après ce délai
    #: désigne un autre véhicule.
    max_lost_ms: float = 2500.0
    #: Le seuil de confiance de l'utilisateur, **pour le diagnostic seul**.
    #:
    #: Le comptage ne le lit pas : il arrive au domaine déjà appliqué, puisque c'est
    #: le tracker qui décide avec lui ce qui devient une piste (`track_high_thresh` /
    #: `new_track_thresh`, ADR 0024). Mais lui seul permet de ranger une observation
    #: suivie dans « au-dessus du seuil » ou « rattrapée par la bande basse » — la
    #: distinction que le panneau de diagnostic affiche, et qui était impossible à
    #: établir sans cette valeur. Le défaut est celui du schéma de requête.
    confidence_threshold: float = 0.35
    #: La lecture du texte de plaque tourne-t-elle réellement ?
    #:
    #: Ce que le service a **résolu**, et non ce que la requête a demandé : le
    #: modèle d'OCR peut être absent. Sert uniquement à distinguer
    #: `ocr_disabled` — rien n'a été tenté, ce n'est pas un échec — des quatre
    #: autres raisons de non-lecture.
    plate_ocr_enabled: bool = False
    #: Plancher de lecture effectif, en pixels. Recopié de `PlateOcrOptions` : le
    #: registre doit dire « vue à 48 px, sous le plancher de 64 » avec **le** seuil
    #: réellement appliqué, pas une constante rappelée de mémoire.
    plate_ocr_min_width_px: float = 64.0


def _copy_direction_tally(tally: DirectionTally) -> DirectionTally:
    return DirectionTally(
        total=tally.total,
        by_class=dict(tally.by_class),
        first_ms=tally.first_ms,
        last_ms=tally.last_ms,
    )


def _copy_line_tally(tally: LineTally) -> LineTally:
    """Copie profonde d'un tally de ligne — les deux sens et leurs `by_class`."""
    return LineTally(
        positive=_copy_direction_tally(tally.positive),
        negative=_copy_direction_tally(tally.negative),
    )


def _copy_zone_tally(tally: ZoneTally) -> ZoneTally:
    return ZoneTally(entries=tally.entries, inside=tally.inside, by_class=dict(tally.by_class))


@dataclass(slots=True)
class _VehicleAggregate:
    """Ce que la session retient d'un véhicule sur toute sa vie.

    `TrackNumbering` connaît son numéro et son type voté ; cet agrégat connaît
    l'histoire — vu de/à, lignes franchies, zones visitées, meilleure plaque.
    """

    first_seen_ms: float
    last_seen_ms: float
    crossings: list[LineCrossing] = field(default_factory=list)
    best_plate_score: float | None = None
    #: Le vote du texte de plaque. Sur l'agrégat et non sur la piste : la piste
    #: perd ses boîtes à chaque image, le véhicule non. C'est aussi ce qui rend la
    #: réhydratation gratuite quand le tracker réactive un identifiant après une
    #: occlusion courte — la piste est neuve, l'agrégat est intact.
    plate_vote: PlateTextVote = field(default_factory=PlateTextVote)
    #: Largeur de la meilleure plaque **mesurée** de cette identité, en pixels.
    #:
    #: Le chiffre qui rend une raison de non-lecture actionnable : « vue à 48 px »
    #: dit de resserrer le plan, là où « non détectée » dit tout autre chose.
    best_plate_width_px: float | None = None
    #: Une lecture a-t-elle été **tentée** sur cette identité ?
    #:
    #: Distingue `too_small` — des plaques vues, aucune assez grande pour être
    #: tentée — de `no_consensus`, où l'OCR a tourné sans qu'aucune majorité ne se
    #: dégage. Sans ce drapeau, les deux se confondraient en « pas de texte », et
    #: les deux appellent pourtant des gestes opposés.
    plate_read_attempted: bool = False
    #: Confiance de lecture de la **capture** retenue, ou `None`.
    #:
    #: Le pendant exact de `best_plate_score` pour l'image plutôt que pour la boîte,
    #: et la règle est la même : strictement croissante. Une lecture moins sûre que
    #: la précédente ne remplace rien.
    #:
    #: **`None` n'est plus « aucune capture »** depuis ADR 0051 : les causes
    #: `plate_box` et `appearance` n'ont aucune lecture à porter. Ce champ est
    #: **dérivé** de `snapshot_rank` par `record_snapshot`, et n'existe que pour
    #: publier une confiance sans obliger l'écran à savoir quel tier porte quoi.
    snapshot_score: float | None = None
    #: Instant de scène de cette capture. `None` ssi `snapshot_cause` l'est.
    snapshot_ms: float | None = None
    #: Pourquoi la capture retenue existe, ou `None` — il n'y en a aucune.
    #:
    #: **C'est le drapeau de présence**, avec `snapshot_ms` : voir `SnapshotCause`.
    snapshot_cause: SnapshotCause | None = None
    #: Valeur de rang de la capture retenue, **dans son tier et jamais au-delà**.
    #:
    #: `plate_text` → une confiance de lecture, dans [0, 1]. `plate_box` → la largeur
    #: de la boîte de plaque, en pixels. `appearance` → la largeur de la boîte du
    #: véhicule, en pixels. Les fondre en un seul nombre comparable ferait comparer
    #: des pixels à une probabilité : la comparaison serait vraie **par accident**, et
    #: une plaque lue à 0,95 perdrait contre n'importe quelle boîte de 40 px.
    snapshot_rank: float | None = None
    #: Largeur, en pixels, de la vue dont l'apparence a été encodée. `None` = jamais.
    #:
    #: Même rôle que `snapshot_score` pour la capture, et même règle : strictement
    #: croissante. Ce n'est **pas** une ressemblance — c'est la valeur de la *vue*, et
    #: les confondre ferait réencoder chaque fois que la ressemblance change, donc sans
    #: rapport avec la qualité de l'image courante (le piège qu'ADR 0042 documente sur
    #: le score du vote de plaque).
    #:
    #: **La largeur de boîte et non « largeur × netteté »**, contrairement à ce que le
    #: choix de l'OCR aurait suggéré, et pour une raison structurelle : la netteté
    #: demande les pixels, donc un recadrage. Le service doit pouvoir demander « est-ce
    #: que ça vaut une inférence » **avant** de payer quoi que ce soit, et il ne connaît
    #: à ce moment que la boîte. Une clé que le domaine ne peut pas évaluer force un
    #: pré-filtre approximatif — et la première version de ce code en est morte : elle
    #: interrogeait la règle avec `0.0`, ce qui excluait définitivement tout véhicule
    #: déjà encodé et rendait impossible le remplacement d'une vue par une meilleure.
    #: La netteté reste un **plancher** dans l'adaptateur, jamais un critère de rang.
    appearance_width_px: float | None = None
    #: Ressemblance à l'image de requête, dans [-1, 1], ou `None`.
    #:
    #: **Aucun compteur ne la lit.** Elle ne sert qu'à la recherche par image, et
    #: c'est ce qui met cette fonctionnalité hors du champ d'ADR 0016 : un véhicule
    #: ressemblant n'est pas un véhicule compté deux fois.
    match_score: float | None = None
    #: Numéro du véhicule **antérieur** auquel celui-ci ressemble, ou `None`.
    #:
    #: Le résultat de la galerie interne au clip (ADR 0055). Se lit « on a déjà vu
    #: ce véhicule, c'était le #N » — une **hypothèse à vérifier sur la capture**,
    #: jamais une fusion : les deux numéros continuent d'exister, les deux véhicules
    #: restent comptés, et les deux franchissements aussi.
    #:
    #: **Aucun compteur ne le lit**, même clause que `match_score` juste au-dessus,
    #: et pour la même raison — c'est elle qui met la galerie hors du champ
    #: d'ADR 0016, dont la galerie supprimée alimentait le comptage.
    rematch_of: int | None = None
    #: Ressemblance au véhicule ci-dessus, dans [-1, 1]. `None` ssi `rematch_of` l'est.
    rematch_score: float | None = None


class AnalysisSession:
    """Compte les véhicules d'un flux de détections suivies, frame par frame."""

    __slots__ = (
        "_active_count",
        "_aggregates",
        "_config",
        "_contained_out",
        "_counter",
        "_first_timestamp_ms",
        "_frame_index",
        "_high_detections",
        "_last_timestamp_ms",
        "_masked_out",
        "_numbering",
        "_rescued_by_low_score",
        "_tracks",
        "_zones",
    )

    def __init__(self, config: SessionConfig, frame_width: int, frame_height: int) -> None:
        # `frame_width` / `frame_height` ne servent plus au comptage : ils
        # alimentaient le gate de déplacement de la ré-identification, supprimée par
        # ADR 0016. La signature est conservée parce que trois appelants la
        # traversent et qu'un futur réglage dépendant de la résolution — un plancher
        # de taille de boîte, par exemple — la redemanderait aussitôt.
        del frame_width, frame_height

        self._config = config
        self._counter = LineCrossingCounter(config.lines, config.zones, config.min_hits)
        self._zones = ZonePresenceCounter(config.zones, config.min_hits)
        self._numbering = TrackNumbering()
        # Toutes les pistes connues, pas seulement les actives : `_release_lost`
        # doit pouvoir abandonner une piste qui a cessé d'être rapportée.
        self._tracks: dict[int, SessionTrack] = {}
        # Pistes rapportées sur la **dernière** frame : le chiffre qu'affiche
        # « Objets suivis », donc exactement le nombre de boîtes dessinées.
        # `len(self._tracks)` ne peut pas jouer ce rôle — il compte aussi les pistes
        # perdues encore retenues pour `max_lost_ms`, et redescendait donc deux
        # secondes et demie après les boîtes.
        self._active_count = 0
        # Numéro de véhicule → son histoire. **Jamais purgé** : le registre s'en
        # sert à la fin, et un véhicule sorti du champ à la dixième seconde doit
        # encore y figurer.
        self._aggregates: dict[int, _VehicleAggregate] = {}
        self._first_timestamp_ms: float | None = None
        self._last_timestamp_ms: float = 0.0
        self._frame_index = 0
        self._masked_out = 0
        # Boîtes écartées parce qu'incluses dans une autre. Compté et publié : une
        # suppression silencieuse serait aussi opaque que le doublon qu'elle évite,
        # et c'est ce chiffre qui permettra de savoir si le seuil est bien réglé.
        self._contained_out = 0
        # Les deux compteurs de score, en **observations suivies** et non en images :
        # un même véhicule vu sur trente images pèse trente. C'est voulu — la question
        # à laquelle ils répondent est « le suivi tient-il malgré des scores qui
        # plongent ? », qui se mesure sur des observations.
        self._high_detections = 0
        self._rescued_by_low_score = 0

    def feed(
        self,
        frame_index: int,
        timestamp_ms: float,
        observations: Sequence[TrackObservation],
    ) -> FrameOutcome:
        """Fait avancer la session d'une frame. **L'ordre des étapes est le contrat.**"""
        # Le doublon cabine/véhicule est écarté **avant** le masque et avant le
        # suivi : une boîte incluse ne doit jamais devenir une piste, sinon elle
        # porte une identité et un franchissement qu'aucune suppression ultérieure
        # ne pourrait défaire.
        kept = self._mask(self._drop_contained(observations))
        # Rangé **après** le masque et le doublon, pour que le diagnostic parle des
        # observations qui ont réellement nourri le suivi : une boîte masquée est déjà
        # comptée par `masked_out`, la compter deux fois brouillerait la lecture.
        self._count_scores(kept)
        active = self._advance_tracks(kept, timestamp_ms)

        # Abandonner les pistes silencieuses **avant** de numéroter : c'est ce qui
        # libère leur identifiant de piste, pour qu'un identifiant réémis par le
        # tracker reçoive un numéro neuf plutôt que de fusionner deux véhicules.
        self._release_lost(timestamp_ms)
        self._number_tracks(active)

        # Le texte voté est recopié de l'agrégat vers la piste vivante **ici**, et
        # pas ailleurs : après `_number_tracks` le numéro de chaque piste est arrêté
        # pour la frame, et avant `observe` le tampon du compteur a de quoi lire.
        # C'est ce qui fait qu'un franchissement porte le texte que le véhicule
        # avait **avant** cette frame — le seul texte qui existe à cet instant, la
        # passe OCR de cette frame n'ayant pas encore eu lieu.
        self._mirror_plate_text(active)

        crossings = self._counter.observe(active, timestamp_ms, frame_index)
        zone_events = self._zones.observe(active, timestamp_ms, frame_index)

        # Le badge ✓ dérive du tally, jamais de la comptabilité d'une piste : c'est
        # la même source que `crossed_unique`, donc les deux ne peuvent pas se
        # contredire à l'écran.
        counted = self._counter.counted_identities()
        for track in active:
            track.counted = track.global_id != 0 and track.global_id in counted

        self._aggregate(active, crossings, timestamp_ms)

        self._frame_index = frame_index
        self._active_count = len(active)
        if self._first_timestamp_ms is None:
            self._first_timestamp_ms = timestamp_ms
        self._last_timestamp_ms = timestamp_ms

        return FrameOutcome(
            frame_index=frame_index,
            timestamp_ms=timestamp_ms,
            tracks=active,
            crossings=crossings,
            zone_events=zone_events,
        )

    # ── Étapes de `feed` ─────────────────────────────────────────────────────

    def _count_scores(self, observations: Sequence[TrackObservation]) -> None:
        """Range chaque observation suivie de part et d'autre du seuil utilisateur.

        **Le diagnostic n'a rien d'autre à observer.** Depuis ADR 0024 le détecteur
        reçoit le plancher du tracker et non le seuil de l'utilisateur : les
        détections faibles arrivent donc jusqu'au suivi, où elles prolongent une piste
        sans jamais en ouvrir une. Celles qui n'ont été associées à aucune piste ne
        sortent pas d'Ultralytics — il ne rend que les boîtes porteuses d'un
        identifiant — donc « détections faibles jetées » n'est mesurable nulle part, et
        le compteur qui prétendait le faire est supprimé.

        Ce qui reste est mesurable et utile : combien d'observations tenaient le seuil,
        et combien étaient **en dessous**, c'est-à-dire autant de pistes qui se
        seraient coupées en deux sans la bande basse.
        """
        for observation in observations:
            if observation.score >= self._config.confidence_threshold:
                self._high_detections += 1
            else:
                self._rescued_by_low_score += 1

    def _mask(self, observations: Sequence[TrackObservation]) -> tuple[TrackObservation, ...]:
        """Filtre les détections hors zone quand le masque est actif.

        **Avant le suivi, jamais après.** Avec `mask_outside_zones`, les zones sont
        la région d'intérêt : une détection en dehors ne devient jamais une piste,
        donc les voitures en stationnement et le parking dans un coin de l'image ne
        coûtent rien et n'entrent dans aucun compteur. Sans le masque, une zone
        n'est qu'un filtre de comptage.
        """
        if not self._config.mask_outside_zones or not self._config.zones:
            return tuple(observations)

        kept: list[TrackObservation] = []
        for observation in observations:
            if point_is_in_any_zone(observation.box.centroid, self._config.zones):
                kept.append(observation)
            else:
                self._masked_out += 1
        return tuple(kept)

    def _drop_contained(
        self, observations: Sequence[TrackObservation]
    ) -> tuple[TrackObservation, ...]:
        """Supprime une boîte **entièrement incluse** dans une autre.

        Le cas cible est le bus ou le semi-remorque : le détecteur émet une boîte
        sur la cabine **et** une sur le véhicule entier. Leur IoU vaut environ 0,3,
        donc le NMS les garde toutes les deux — même inter-classes. Résultat : deux
        pistes, deux identités, deux franchissements. Le total est trop haut, et
        rien ne l'explique (piège 6 de prompt/13).

        **Le seuil est sévère — 0,9 — et c'est délibéré.** Le cas cible atteint 1,0,
        tandis qu'une voiture roulant devant un camion peut être à 0,8 dans la boîte
        du camion : la supprimer effacerait un vrai véhicule. Sous-compter est
        l'erreur la plus difficile à remarquer, donc en cas de doute on garde.

        **Et le seuil ne suffit pas : il a été calibré sur la seule classe qui y
        échappe.** L'argument ci-dessus vaut pour une *voiture* devant un camion, à
        0,8. La mesure est `intersection / min(aire)`, donc elle est structurellement
        asymétrique : un camion ne peut jamais être contenu dans une moto, une moto
        l'est trivialement dans un camion. Mesuré sur ce code, un pilote dans la
        boîte de sa propre moto, un piéton devant un bus et une moto devant un camion
        rendent tous **1,000** — les trois passent le seuil, et c'est toujours le plus
        petit objet qui part, c'est-à-dire exactement les deux classes qu'on peine à
        détecter. Conséquences mesurées en bout de chaîne : une moto suivie cinq
        images devant un camion ne laisse **aucune** trace nulle part, et une moto
        englobée trois secondes ressort en **deux** véhicules — le même mécanisme
        sous-compte et double-compte.

        La suppression est donc bornée aux objets **physiquement exclusifs entre
        eux** (`class_group`). Le cas cible reste traité : la cabine et le semi sont
        tous deux `truck`, donc du même groupe — et deux boîtes de même label le sont
        quelle que soit la table. La garde porte sur le **groupe** et jamais sur
        l'égalité de label, sinon une cabine détectée `car` dans un semi `truck`
        redeviendrait deux pistes, deux véhicules, deux franchissements : le piège 6
        rouvert par le correctif censé le préserver.

        Ce que la garde **ne** protège pas, et il faut le savoir : deux objets de la
        même famille. Un enfant marchant contre un adulte est à 1,0, une voiture
        entièrement dans la boîte d'un bus aussi. Ce dernier cas existait déjà avant
        ce correctif ; le traiter demanderait un critère de plausibilité — la cabine
        partage un bord de la boîte du semi, la moto au milieu du camion non — à
        mesurer, jamais à adopter en défaut. Voir ADR 0056.

        **La plus petite part**, jamais la plus grande : la cabine est un morceau du
        véhicule, et c'est la boîte du véhicule entier qui décrit l'objet physique.

        Complexité quadratique, assumée : une frame de trafic dense compte quelques
        dizaines de détections après le filtrage par classe, et le coût est sans
        commune mesure avec celui de l'inférence qui les a produites.
        """
        if len(observations) < 2:
            return tuple(observations)

        dropped: set[int] = set()
        for i, first in enumerate(observations):
            if i in dropped:
                continue
            for j, second in enumerate(observations[i + 1 :], start=i + 1):
                if j in dropped:
                    continue
                # **Avant la géométrie** : que deux objets puissent être le même
                # objet physique ne dépend pas de l'endroit où ils se trouvent. Un
                # pilote et sa moto se recouvrent à 1,0 et restent deux objets.
                if class_group(first.label) != class_group(second.label):
                    continue
                if first.box.containment(second.box) < CONTAINMENT_THRESHOLD:
                    continue
                smaller = j if second.box.area <= first.box.area else i
                dropped.add(smaller)
                if smaller == i:
                    # La boîte courante vient d'être écartée : inutile de la
                    # comparer aux suivantes.
                    break

        if not dropped:
            return tuple(observations)
        self._contained_out += len(dropped)
        return tuple(obs for index, obs in enumerate(observations) if index not in dropped)

    def _advance_tracks(
        self, observations: Sequence[TrackObservation], timestamp_ms: float
    ) -> tuple[SessionTrack, ...]:
        """Met à jour l'état vivant des pistes rapportées sur cette frame."""
        active: list[SessionTrack] = []
        for observation in observations:
            centroid = observation.box.centroid
            track = self._tracks.get(observation.track_id)
            if track is None:
                # `global_id` reste à `0` : le numéro est émis à la confirmation,
                # par `_number_tracks`. Une piste d'une seule image ne consomme donc
                # aucun numéro, et la suite reste sans trou.
                track = SessionTrack(
                    track_id=observation.track_id,
                    class_id=observation.class_id,
                    label=observation.label,
                    score=observation.score,
                    box=observation.box,
                    centroid=centroid,
                    hits=1,
                    last_seen_ms=timestamp_ms,
                )
                self._tracks[observation.track_id] = track
            else:
                track.previous_centroid = track.centroid
                track.class_id = observation.class_id
                track.label = observation.label
                track.score = observation.score
                track.box = observation.box
                track.centroid = centroid
                track.hits += 1
                track.last_seen_ms = timestamp_ms
            # Les *boîtes* de plaques appartiennent à la frame courante : les garder
            # d'une frame à l'autre ferait afficher un rectangle là où le modèle n'en
            # voit plus.
            #
            # `plate_text`, en revanche, n'est **pas** touché ici, et ce n'est pas un
            # oubli : il est identitaire, recopié du vote par `_mirror_plate_text`.
            # L'effacer par symétrie viderait le tampon que le compteur lit juste
            # après, et aucun franchissement ne porterait plus de plaque.
            #
            # **Cet effacement reste inconditionnel**, y compris depuis que le
            # détecteur est étranglé : c'est le service qui repose une boîte à
            # chaque image via `record_plates`, mesurée ou reprojetée. L'ancre qui
            # rend cela possible vit dans la politique, côté application, et **pas
            # ici** — une piste ne peut pas dater ce qu'elle porte, donc elle serait
            # incapable de dire qu'une plaque a trois images de retard.
            track.plates.clear()
            active.append(track)
        return tuple(active)

    def _release_lost(self, timestamp_ms: float) -> None:
        """Abandonne les pistes silencieuses depuis trop longtemps.

        Parcourt **toutes** les pistes connues, pas seulement les actives : une
        piste qui a cessé d'être rapportée n'apparaît plus dans `active` et ne
        serait donc jamais abandonnée.

        Deux effets, et le second est le plus important : la mémoire est bornée, et
        l'identifiant de piste est **rendu au tracker**. Ultralytics réactive une
        piste perdue avec son propre identifiant tant qu'elle tient dans
        `track_buffer` (75 images ≈ 2,5 s, le miroir exact de `max_lost_ms`) ; au
        delà, un identifiant qui réapparaît désigne un autre objet, et lui rendre
        l'ancien numéro fusionnerait deux véhicules.

        Le véhicule, lui, n'est pas oublié : son numéro, son type voté et son
        agrégat restent, parce que le registre les republie à la fin.
        """
        lost = [
            track_id
            for track_id, track in self._tracks.items()
            if timestamp_ms - track.last_seen_ms > self._config.max_lost_ms
        ]
        for track_id in lost:
            del self._tracks[track_id]
            self._numbering.forget(track_id)

    def _number_tracks(self, active: Sequence[SessionTrack]) -> None:
        """Numérote les pistes, vote leur type, et confirme celles qui le méritent.

        Tout ce qui reste de l'ancien `_resolve_identities` : plus de descripteur
        d'apparence calculé par image, plus d'appariement, plus d'accès aux pixels.

        **Le numéro est émis dès la première image**, avant toute confirmation. Une
        piste sans numéro n'aurait pas d'agrégat, donc ni `first_seen_ms` juste, ni
        vote de plaque sur sa première lecture. Ce qui attend la confirmation, c'est
        l'entrée dans le **comptage** — deux gestes distincts, voir `TrackNumbering`.
        """
        for track in active:
            if track.global_id == 0:
                track.global_id = self._numbering.assign(
                    track.track_id, track.class_id, track.label
                )
            self._numbering.vote(track.global_id, track.class_id, track.label)
            if track.hits >= self._config.min_hits:
                self._numbering.confirm(track.global_id)
            track.identity_label = self._numbering.label_of(track.global_id)

    def _mirror_plate_text(self, active: Sequence[SessionTrack]) -> None:
        """Recopie le texte voté de chaque identité sur sa piste vivante.

        **Un miroir et non une source** : la vérité est dans l'agrégat, qui survit à
        la destruction de la piste. C'est *aussi* ce qui règle la réhydratation après
        occlusion sans une ligne de code dédiée — quand BoT-SORT ressuscite un id
        (`_recover_identity`) ou que la galerie réapparie une identité relâchée
        (`admit_batch`), la piste est neuve mais l'agrégat est intact, et le miroir de
        cette frame y repose le texte.

        Réécrit à chaque frame, **y compris pour l'effacer** : une identité dont le
        vote n'est pas concluant doit afficher « rien », pas le reste d'une frame
        précédente.
        """
        for track in active:
            aggregate = self._aggregates.get(track.global_id) if track.global_id else None
            if aggregate is None:
                track.plate_text = ""
                track.plate_text_score = 0.0
                continue
            track.plate_text = aggregate.plate_vote.text or ""
            track.plate_text_score = aggregate.plate_vote.score if track.plate_text else 0.0

    def _aggregate(
        self,
        active: Sequence[SessionTrack],
        crossings: Sequence[CrossingEvent],
        timestamp_ms: float,
    ) -> None:
        """Tient à jour l'histoire de chaque véhicule, pour le registre."""
        for track in active:
            if track.global_id == 0:
                continue
            aggregate = self._aggregates.get(track.global_id)
            if aggregate is None:
                self._aggregates[track.global_id] = _VehicleAggregate(
                    first_seen_ms=timestamp_ms, last_seen_ms=timestamp_ms
                )
            else:
                aggregate.last_seen_ms = timestamp_ms

        for crossing in crossings:
            aggregate = self._aggregates.get(crossing.global_id)
            if aggregate is not None:
                aggregate.crossings.append(
                    LineCrossing(crossing.line_id, crossing.direction, crossing.timestamp_ms)
                )

    # ── ANPR ─────────────────────────────────────────────────────────────────

    def record_plates(self, track: SessionTrack, plates: Sequence[PlateDetection]) -> None:
        """Attache les plaques détectées à une piste et met à jour son agrégat.

        Appelée par le service **après** `feed` et **avant** le snapshot : la
        timeline doit porter les plaques, sinon la relecture n'en affiche aucune.

        C'est ici — et nulle part ailleurs — que le texte brut du lecteur prend sa
        forme canonique, et que le vote de l'identité l'enregistre. Normaliser dans
        l'adaptateur laisserait une doublure de test faire le travail de la
        production, et les tests ne prouveraient plus rien de la normalisation.
        """
        if not plates:
            return

        aggregate = self._aggregates.get(track.global_id)
        best = 0.0
        stored: list[PlateDetection] = []
        for plate in plates:
            # **Une reprojection ne nourrit aucun agrégat.** Elle reproduit le score
            # de la détection dont elle est issue ; le compter à nouveau ferait
            # remonter le même chiffre à chaque image sautée, et `best_plate_score`
            # décrirait la fréquence des reprojections plutôt que la qualité de la
            # meilleure vue. Le rectangle, lui, est bien stocké : il est là pour
            # être dessiné.
            if not plate.stale:
                best = max(best, plate.score)
            text, char_scores = (
                normalise_plate_reading(plate.text, plate.text_char_scores)
                if plate.text
                else ("", ())
            )
            # `replace` seulement quand la forme canonique diffère du brut, ou qu'il
            # reste des confiances par caractère à jeter : sur un lecteur qui rend
            # déjà du propre, cela évite une allocation par plaque et par frame.
            if text == plate.text and not plate.text_char_scores:
                stored.append(plate)
            else:
                # Les confiances par caractère s'arrêtent ici : elles ont servi au
                # vote, elles n'ont rien à faire dans la timeline.
                stored.append(replace(plate, text=text or None, text_char_scores=()))
            if text and aggregate is not None:
                aggregate.plate_vote.observe(text, plate.text_score, char_scores)

        # Étendu même sans agrégat : une piste qui n'a pas encore d'identité doit
        # quand même voir ses rectangles dessinés.
        track.plates.extend(stored)

        if aggregate is None:
            return
        if aggregate.best_plate_score is None or best > aggregate.best_plate_score:
            aggregate.best_plate_score = best
        # La largeur suit la **meilleure vue**, jamais la dernière : c'est elle qui
        # décide si un plan plus serré aurait suffi.
        widest = max(
            (plate.box.width for plate in plates if not plate.stale),
            default=0.0,
        )
        if widest > 0.0 and (
            aggregate.best_plate_width_px is None or widest > aggregate.best_plate_width_px
        ):
            aggregate.best_plate_width_px = widest
        # Une lecture a été tentée si au moins une plaque porte un texte — même
        # illisible, `text` vaut alors `None` mais `text_score` a été renseigné par
        # l'adaptateur. On se contente du signal le plus sûr : un texte présent.
        if any(plate.text for plate in plates):
            aggregate.plate_read_attempted = True

    def plate_text_is_confident(self, global_id: int) -> bool:
        """Le vote de plaque de cette identité est-il établi ?

        Publié parce que c'est le **service** qui décide de dépenser une inférence —
        le domaine n'a pas à savoir que l'OCR coûte cher. Rend `False` sans lever sur
        une identité inconnue : `0` en est une, et le service la rencontre.
        """
        aggregate = self._aggregates.get(global_id)
        return aggregate is not None and aggregate.plate_vote.is_confident

    def should_capture(
        self,
        global_id: int,
        cause: SnapshotCause,
        rank: float,
        improvement: float = 1.0,
    ) -> bool:
        """Cette vue bat-elle la capture déjà retenue pour ce véhicule ?

        **Deux questions dans l'ordre, et l'ordre est la décision d'ADR 0051.**
        D'abord la cause : une plaque lue prouve plus qu'une plaque vue, qui prouve
        plus qu'une ressemblance, donc un tier plus haut passe **toujours** et un tier
        plus bas ne passe **jamais**. Ensuite, et seulement à tier égal, le rang.

        Comparer les rangs entre tiers serait une erreur d'unité invisible : l'un est
        une probabilité, les deux autres des pixels. `0,95` de confiance perdrait
        contre une boîte de 40 px, et le chiffre resterait plausible.

        À tier égal, **la règle que l'utilisateur a décrite pour la lecture** : à 0,80
        on capture, à 0,90 on remplace, à 0,85 ensuite on ne touche plus à rien. Une
        comparaison stricte, donc monotone croissante — une capture ne peut jamais
        être remplacée par moins bien.

        **`improvement` est la marge, et elle est obligatoire sur les deux tiers dont
        le rang est une largeur.** « Strictement plus large » est vrai à presque chaque
        image d'un véhicule qui approche : c'est exactement ce qu'ADR 0050 a payé sur
        l'encodage d'apparence, et la largeur d'une boîte de plaque croît de la même
        façon — l'étranglement du détecteur (une image sur trois) ne divise le problème
        que par trois. Sur `plate_text`, la marge doit rester à `1.0` : son rang est une
        probabilité, il ne croît pas avec l'approche, et une marge y affamerait la
        meilleure preuve pour rien.

        `1.0` reproduit l'ancien comportement au bit près (`r > best * 1.0` ≡
        `r > best`), ce qui rend le tier `plate_text` inchangé.

        Une **question pure**, séparée de `record_snapshot` : l'appelant doit
        pouvoir demander « est-ce que ça vaut le coup » *avant* de dépenser un
        encodage, et n'enregistrer qu'une fois les octets réellement produits. Les
        fondre en un seul appel laisserait, sur un encodage raté, un véhicule qui
        annonce une capture sans fichier.

        Rend `False` sur une identité inconnue — `0` en est une, et le service la
        rencontre — comme `plate_text_is_confident` juste au-dessus.
        """
        aggregate = self._aggregates.get(global_id)
        if aggregate is None:
            return False
        current = aggregate.snapshot_cause
        if current is None:
            return True
        if SNAPSHOT_CAUSE_PRIORITY[cause] != SNAPSHOT_CAUSE_PRIORITY[current]:
            return SNAPSHOT_CAUSE_PRIORITY[cause] > SNAPSHOT_CAUSE_PRIORITY[current]
        return rank > (aggregate.snapshot_rank or 0.0) * max(1.0, improvement)

    def record_snapshot(
        self,
        global_id: int,
        cause: SnapshotCause,
        rank: float,
        timestamp_ms: float,
    ) -> None:
        """Retient la capture qui vient d'être produite. À appeler **après** succès.

        Ne revérifie pas `should_capture` : le service a déjà posé la question, et
        la reposer ici ferait exister deux endroits qui décident de la même chose.

        **La confiance publiée est dérivée ici**, et non passée en cinquième
        paramètre : c'est ce qui interdit à un appelant d'annoncer `plate_box` en
        posant une confiance de lecture, donc de publier un `snapshot_score` que rien
        n'a lu. L'invariant « non-nul implique `plate_text` » tient par construction
        et pas par discipline.
        """
        aggregate = self._aggregates.get(global_id)
        if aggregate is None:
            return
        aggregate.snapshot_cause = cause
        aggregate.snapshot_rank = rank
        aggregate.snapshot_ms = timestamp_ms
        aggregate.snapshot_score = rank if cause == "plate_text" else None

    def should_embed(self, global_id: int, width_px: float, improvement: float = 1.0) -> bool:
        """Cette vue bat-elle **franchement** celle dont l'apparence est déjà encodée ?

        **Le jumeau exact de `should_capture`**, et pour la même raison d'être : sans
        règle monotone, on encoderait à chaque image de chaque véhicule, ce qui est
        précisément le profil de coût qu'ADR 0032 a démonté sur le détecteur de
        plaques. Avec elle, on encode quelques fois dans la vie d'un véhicule.

        `width_px` est la largeur de la **boîte du véhicule**, et le choix de cette
        unité est ce qui rend la question posable avant toute dépense : la netteté
        demanderait un recadrage, donc des pixels que le domaine n'a pas. Ce n'est
        **pas** la ressemblance : classer les vues sur la ressemblance ferait réencoder
        quand une *autre* image change le score, sans rapport avec la qualité de
        celle-ci.

        Une **question pure**, séparée de `record_embedding` : l'appelant demande
        « est-ce que ça vaut une inférence » avant de la payer.

        Rend `False` sur une identité inconnue — `0` en est une.

        **`improvement` est la marge, et sans elle la règle monotone ne bornait
        rien.** « Strictement plus large » est vrai à *presque chaque image* d'un
        véhicule qui approche, puisque sa largeur croît de façon quasi monotone : on
        payait donc jusqu'à un encodage par image analysée — 21,8 ms de CPU mesurés
        par vignette — pour un étage que la docstring de l'adaptateur annonçait
        comme « une fois par véhicule ». Ce que la mesure d'ADR 0048 comptait (« 8
        suivis, 2 encodés ») était un nombre de *véhicules*, pas d'*encodages*.

        La marge borne le **total sur la vie d'une piste**, et c'est ce qui la
        distingue d'une cadence : elle autorise au plus `log_k(W_max / W_min)`
        encodages, soit onze à `1,15` entre le plancher de 96 px et 400 px, quelle
        que soit la cadence de la vidéo. Une cadence `every_n_frames = 3` en
        laisserait passer une cinquantaine sur un passage de six secondes.

        **Le mode de panne d'ADR 0029 ne se rejoue pas ici**, et la raison est
        structurelle : le consommateur de l'OCR est *statistique* — `PlateTextVote`
        exige plusieurs lectures concordantes, donc raréfier les lectures empêche un
        texte d'exister. Celui de la ReID est un *maximum* : `record_embedding` retient
        la meilleure des mesures, chacune indépendante des autres. Raréfier les vues
        ne peut donc que priver d'une chance de mieux faire, jamais empêcher un score
        d'exister — et la première vue reste inconditionnelle
        (`appearance_width_px is None`), donc **aucun véhicule candidat ne perd son
        score** : la marge ne peut refuser qu'une amélioration.

        Cette docstring a annoncé un *remplacement* et non un maximum, et c'était la
        description d'un défaut : le score publié était celui de la dernière vue
        acceptée, donc arbitraire. Voir `record_embedding`.

        `1.0` reproduit l'ancien comportement au bit près (`w > best * 1.0` ≡
        `w > best`), ce qui rend le réglage strictement additif.
        """
        aggregate = self._aggregates.get(global_id)
        if aggregate is None:
            return False
        best = aggregate.appearance_width_px
        return best is None or width_px > best * max(1.0, improvement)

    def has_appearance(self, global_id: int) -> bool:
        """Cette piste a-t-elle **déjà** été encodée, une fois au moins ?

        Sert le classement du plafond par image : une piste jamais encodée passe
        devant, sans quoi un véhicule apparu au milieu d'un embouteillage pourrait
        traverser tout le champ sans jamais recevoir de score de ressemblance.

        **Ce n'est pas `match_score is not None`**, et la nuance décide du
        comportement : le score reste `None` après un encodage réussi quand il tombe
        sous `reid_min_similarity`, ou quand il n'y a pas d'image de requête. Le
        prendre pour prédicat ferait réencoder indéfiniment tous les véhicules qui ne
        ressemblent pas à la requête — c'est-à-dire l'immense majorité.
        """
        aggregate = self._aggregates.get(global_id)
        return aggregate is not None and aggregate.appearance_width_px is not None

    def record_embedding(self, global_id: int, width_px: float, match_score: float | None) -> None:
        """Retient la vue encodée et la ressemblance mesurée dessus.

        Ne revérifie pas `should_embed` : le service a déjà posé la question, et la
        reposer ici ferait exister deux endroits qui décident de la même chose.

        **Les deux champs sont monotones**, et aucun des deux ne l'était.

        **La largeur ne redescend jamais.** Depuis ADR 0055, un franchissement force
        un encodage quelle que soit la largeur de la boîte : écrire cette largeur
        telle quelle rabaissait la référence de la règle monotone, qui rouvrait alors
        des ré-encodages déjà payés — ADR 0050 à l'envers. `appearance_width_px`
        décrit « la meilleure vue déjà encodée », pas « la dernière ».

        **La ressemblance non plus.** Cette docstring a longtemps affirmé le
        contraire — « c'est une mesure sur la vue courante, pas un rang » — et
        l'argument était faux. Un véhicule est encodé six à onze fois ; publier la
        **dernière** mesure ne rend pas la chose plus honnête, cela la rend
        **arbitraire**. La question posée est « ce véhicule ressemble-t-il à la photo
        cherchée ? », et la réponse est le meilleur de ce qu'on a mesuré : deux vues
        du même véhicule ne se ressemblent pas autant qu'on croit (0,387 au plus bas,
        ADR 0048), donc une vue oblique ne réfute pas une vue franche. C'est le même
        défaut que `record_rematch` a payé, et sur le même étage.

        Depuis ADR 0055 il était même devenu pire : un franchissement forcé contourne
        la marge de largeur, donc une vue étroite prise au passage du trait pouvait
        écraser le score d'une vue trois fois plus large.

        **`None` ne retire rien.** Il couvre deux états qui ne sont pas des
        rétractations : aucune image de requête, ou une mesure sous
        `reid_min_similarity`. Ce plancher décide de ce qu'on **publie**, jamais de ce
        qu'on **efface** — et il mordait au défaut, `cosine_similarity` étant bornée à
        `[-1, 1]` : une similarité négative échouait `score >= 0.0`, donc un `None`
        passait par-dessus un 0,83 légitime et le véhicule disparaissait des résultats
        qu'il avait mérités, tout en gardant la photo qui servait à le vérifier.
        """
        aggregate = self._aggregates.get(global_id)
        if aggregate is None:
            return
        best = aggregate.appearance_width_px
        aggregate.appearance_width_px = width_px if best is None else max(best, width_px)
        if match_score is None:
            return
        current = aggregate.match_score
        if current is None or match_score > current:
            aggregate.match_score = match_score

    def record_rematch(self, global_id: int, other_id: int, score: float) -> None:
        """Retient la **meilleure** ressemblance mesurée à un franchisseur antérieur.

        Ne revérifie pas le plancher de déploiement : le service l'a déjà appliqué.
        Reposer cette question-là ferait exister deux endroits qui décident de la
        même chose.

        **Le maximum, et non la dernière mesure.** Cette méthode a écrasé sans
        comparer, et c'était le défaut qui rendait la fonctionnalité inutilisable.
        Un véhicule franchit plusieurs lignes, donc interroge la galerie plusieurs
        fois, et chaque interrogation compare une vue *différente* à la galerie —
        deux vues d'un même véhicule ne se ressemblant pas autant qu'on croit
        (0,387 mesuré au plus bas, ADR 0048), la dernière mesure est souvent la plus
        mauvaise.

        Mesuré sur une vidéo doublée bout à bout, où la bonne réponse vaut 1,00 par
        construction : trois jumeaux sur sept publiaient 0,42, 0,60 et 0,27, et le
        dernier désignait **un autre véhicule** — parce que sa seconde mesure, prise
        sous un angle qui ne correspondait pas, trouvait mieux ailleurs. Le maximum
        publie la mesure la plus favorable, qui est aussi la seule qui ait comparé
        deux vues comparables.

        **Le numéro suit le score**, jamais l'inverse : on ne garde pas le meilleur
        score d'un antécédent et le numéro d'un autre.

        **N'écrit rien qu'un compteur puisse lire.** C'est la clause qui tient
        ADR 0016 à distance, et elle est vérifiable : `test_redetection.py` compare
        comptages, ventilations et horodatages avec et sans galerie.
        """
        aggregate = self._aggregates.get(global_id)
        if aggregate is None:
            return
        if aggregate.rematch_score is not None and score <= aggregate.rematch_score:
            return
        aggregate.rematch_of = other_id
        aggregate.rematch_score = score

    # ── Sorties ──────────────────────────────────────────────────────────────

    def stats(self) -> AnalysisStats:
        """Statistiques courantes, dans la forme exacte que l'interface affiche.

        `crossings` et `by_class` sont **dérivés** de `by_line` : les accumuler en
        parallèle produirait tôt ou tard deux compteurs qui se contredisent.

        **C'est une photographie, pas une vue.** Les tallies sont recopiés, et pas
        seulement leur dictionnaire : `dict(by_line)` ne copie que les clés, et les
        `LineTally` continueraient de grossir dans l'objet qu'on vient de rendre.
        Un appelant qui garde ce bloc quelques millisecondes — le temps de le
        publier — verrait alors `total` avancer pendant que `crossings`, lui, reste
        figé. Le résultat est un bloc qui **viole son propre invariant** :
        `crossings != Σ by_line[*].total`, sur des données pourtant justes.
        """
        by_line = self._counter.by_line
        crossings = sum(tally.total for tally in by_line.values())

        by_class: dict[str, int] = {}
        for tally in by_line.values():
            for label, count in tally.by_class.items():
                by_class[label] = by_class.get(label, 0) + count

        analysed_ms = (
            self._last_timestamp_ms - self._first_timestamp_ms
            if self._first_timestamp_ms is not None
            else 0.0
        )
        # En dessous de trois secondes de flux, le débit oscille trop pour être
        # publiable : rendre 0 et le dire dans l'interface vaut mieux qu'un chiffre
        # qui saute de 12 à 240 véhicules par minute.
        vehicles_per_minute = (
            crossings / analysed_ms * _MS_PER_MINUTE
            if analysed_ms >= MIN_SCENE_MS_FOR_FLOW
            else 0.0
        )

        confirmed = sum(1 for track in self._tracks.values() if track.hits >= self._config.min_hits)

        return AnalysisStats(
            tracked_vehicles=self._numbering.size,
            tracked_by_class=self._numbering.count_by_class(),
            crossings=crossings,
            # La **même** source que le badge ✓ de l'overlay, et c'est voulu : le
            # taux de franchissement et le badge répondent à la même question — « ce
            # véhicule est-il passé ? ». Les faire dériver de deux endroits
            # différents finirait par afficher un ✓ sur un véhicule que le taux ne
            # compte pas.
            crossed_unique=len(self._counter.counted_identities()),
            by_class=by_class,
            by_line={line_id: _copy_line_tally(tally) for line_id, tally in by_line.items()},
            by_zone={
                zone_id: _copy_zone_tally(tally) for zone_id, tally in self._zones.by_zone.items()
            },
            vehicles_per_minute=vehicles_per_minute,
            # Les pistes de la **dernière frame**, pas toutes les pistes retenues :
            # c'est ce que l'écran dessine, et c'est la même définition que
            # `activeTracks` de la relecture côté client (`tracks.length`). Compter
            # `self._tracks` faisait traîner le chiffre jusqu'à `max_lost_ms` après
            # la sortie du champ des véhicules — un retard visible, sur un chiffre
            # dont tout l'intérêt est d'être un instantané.
            active_tracks=self._active_count,
            # Côté serveur, le temps « écoulé » **est** le temps de scène analysé :
            # il n'y a pas d'attente d'utilisateur à mesurer. Le champ reste dans
            # le contrat parce que l'interface affiche les deux.
            elapsed_ms=analysed_ms,
            analysed_scene_ms=analysed_ms,
            diagnostics=Diagnostics(
                # **Renseignés depuis le domaine, et c'est nouveau.** Le commentaire
                # d'avant annonçait que l'adaptateur les remplirait « s'il peut les
                # observer » : il ne l'a jamais fait, donc le panneau de diagnostic
                # affichait deux zéros immuables et son alerte « aucune détection, à
                # aucun seuil » se déclenchait sur *toutes* les analyses — un message
                # alarmant et faux, qui envoyait chercher le bug dans la vidéo.
                #
                # Ce que le domaine peut observer est plus étroit que ce que ces noms
                # promettaient, et c'est ce qui a fait supprimer `low_detections` :
                # après le suivi, une détection non associée n'existe plus.
                high_detections=self._high_detections,
                rescued_by_low_score=self._rescued_by_low_score,
                masked_out=self._masked_out,
                contained_out=self._contained_out,
                confirmed_tracks=confirmed,
                tentative_tracks=len(self._tracks) - confirmed,
                # Les pistes **encore vivantes** sont exclues : une piste qui
                # approche de la ligne à l'instant où l'on publie n'a rien manqué,
                # elle n'a pas fini. C'est `self._tracks` qui fait foi — une piste
                # en sort quand `_release_lost` l'abandonne, ce qui est exactement
                # l'instant où « elle s'est éteinte là » devient vrai.
                near_misses=self._counter.near_misses(ignore=self._tracks.keys()),
            ),
        )

    def vehicles(self, *, crossed_only: bool = False) -> tuple[VehicleRecord, ...]:
        """Le registre : une ligne par véhicule **compté**, triée par numéro.

        Les cartes de synthèse disent *combien*, le registre dit *lesquels*. C'est
        ce qui rend un total vérifiable plutôt que croyable — et depuis ADR 0016 la
        vérification est immédiate : `len(vehicles()) == stats().tracked_vehicles`,
        parce que les deux filtrent sur la même confirmation.

        Les numéros ont donc des trous, et c'est voulu : une piste d'une seule image
        a bien reçu un numéro — il lui fallait un agrégat pour voter sa plaque — mais
        elle n'est pas un véhicule. La publier remplirait le registre de fantômes que
        rien à l'écran ne justifierait.

        `crossed_only` restreint aux véhicules ayant franchi au moins une ligne,
        tous sens confondus — exactement la population que le registre affiche
        depuis ADR 0023. Le résultat archivé, lui, garde **tout** objet suivi
        confirmé : le filtre existe pour l'aperçu d'une analyse en cours, qui
        republie la liste entière plusieurs fois par minute et n'a aucune raison de
        transporter des lignes que l'écran écarte. Il ne change donc rien à ce qui
        s'affiche, seulement à ce qui voyage — et l'égalité
        `len(vehicles()) == tracked_vehicles` ne vaut que sans lui.
        """
        records: list[VehicleRecord] = []
        for global_id in sorted(self._aggregates):
            if not self._numbering.is_confirmed(global_id):
                continue
            aggregate = self._aggregates[global_id]
            # **Avant** le vote de plaque, pas après : sur
            # une scène réelle deux tiers des objets suivis n'ont franchi aucune
            # ligne, et construire leurs enregistrements pour les jeter aussitôt
            # taxerait chaque aperçu au profit de personne.
            if crossed_only and not aggregate.crossings:
                continue
            reason = (
                None
                if aggregate.plate_vote.text
                else unread_reason(
                    ocr_enabled=self._config.plate_ocr_enabled,
                    plate_seen=aggregate.best_plate_score is not None,
                    best_width_px=aggregate.best_plate_width_px,
                    read_attempted=aggregate.plate_read_attempted,
                    min_width_px=self._config.plate_ocr_min_width_px,
                )
            )
            # Le candidat sans consensus n'a de sens que dans **ce** cas précis :
            # dans toute autre raison de silence, aucune lecture n'a eu lieu et il
            # n'y a rien à rapporter en plus de la raison elle-même.
            best_guess = aggregate.plate_vote.best_guess if reason == "no_consensus" else None
            records.append(
                VehicleRecord(
                    global_id=global_id,
                    # Le libellé du **vote**, pas la dernière lecture.
                    label=self._numbering.label_of(global_id),
                    first_seen_ms=aggregate.first_seen_ms,
                    last_seen_ms=aggregate.last_seen_ms,
                    crossed_lines=tuple(aggregate.crossings),
                    zones_visited=self._zones.zones_visited(global_id),
                    best_plate_score=aggregate.best_plate_score,
                    # Le texte du **vote**, comme `label` est le libellé du vote :
                    # jamais la dernière lecture, qui est souvent la plus oblique.
                    plate_text=aggregate.plate_vote.text,
                    plate_text_score=aggregate.plate_vote.score or None,
                    # **Dérivée à la fin**, jamais accumulée : l'état final donne la
                    # cause sans ambiguïté, là où accumuler obligerait à décider
                    # laquelle gagne quand deux causes se succèdent.
                    plate_unread_reason=reason,
                    plate_best_width_px=aggregate.best_plate_width_px,
                    plate_best_guess=best_guess[0] if best_guess else None,
                    plate_best_guess_score=best_guess[1] if best_guess else None,
                    snapshot_score=aggregate.snapshot_score,
                    snapshot_ms=aggregate.snapshot_ms,
                    snapshot_kind=aggregate.snapshot_cause,
                    match_score=aggregate.match_score,
                    rematch_of=aggregate.rematch_of,
                    rematch_score=aggregate.rematch_score,
                )
            )
        return tuple(records)
