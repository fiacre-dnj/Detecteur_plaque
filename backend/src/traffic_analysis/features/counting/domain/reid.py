"""Ré-identification longue durée par apparence.

BoT-SORT maintient l'identité à travers les occlusions **courtes**
(`track_buffer`). Au-delà, l'id de piste change et le véhicule serait compté comme
neuf. Ce module donne une **identité globale** qui survit à la disparition d'une
piste : c'est elle qui distingue « véhicules uniques » de « passages ».

`numpy` est utilisé ici et c'est volontairement autorisé dans le domaine : un
descripteur d'apparence est du calcul, pas de l'infrastructure. Aucun import de
`cv2` en revanche — la conversion de teinte est faite à la main, ce qui garde le
module testable sans OpenCV.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

import numpy as np

from traffic_analysis.features.counting.domain.geometry import Point, distance

if TYPE_CHECKING:
    from collections.abc import Sequence

    import numpy.typing as npt

    from traffic_analysis.features.counting.domain.models import BoundingBox

# ─── Paramètres du descripteur ───────────────────────────────────────────────

# Les coins d'une boîte de détection sont surtout du fond : on rogne 10 % par côté
# avant de décrire l'apparence.
CROP_INSET_RATIO = 0.1

# Sous 20 px de côté, il n'y a pas assez de pixels pour décrire quoi que ce soit.
MIN_BOX_SIDE_PX = 20

# Côté de la vignette. *Historique : elle était 8×8, chaque cellule moyennant un
# patch 2×2 — à peine au-dessus du bruit, assez instable pour que des retours
# légitimes échouent, chaque échec devenant une identité neuve et un second
# franchissement. En 16×16, une cellule moyenne 16 pixels pour le même coût.*
THUMBNAIL_SIDE = 16

# Grille de moyennes RGB : 4×4×3 = 48 valeurs.
COLOUR_GRID_SIDE = 4
# Histogramme de teinte pondéré par la saturation : 16 valeurs.
HUE_BINS = 16
SIGNATURE_LENGTH = COLOUR_GRID_SIDE * COLOUR_GRID_SIDE * 3 + HUE_BINS  # 64


@dataclass(frozen=True, slots=True)
class Signature:
    """Descripteur d'apparence de 64 valeurs, centré puis normalisé L2.

    **Le centrage n'est pas un détail de forme.** Toutes les composantes sont des
    intensités positives : sans centrage, deux véhicules *sans rapport* scorent
    déjà ~0,7 et la plage utile du cosinus s'écrase, ce qui rend tout seuil
    arbitraire. Mesuré après centrage : même objet 1,00, objets différents ≈ 0,01.
    """

    values: npt.NDArray[np.float32]
    aspect: float


@dataclass(frozen=True, slots=True)
class ReidOptions:
    """Réglages de la galerie. Chaque défaut a une raison, pas une préférence."""

    # Trop haut : un véhicule qui revient est recompté. Trop bas : deux sosies
    # fusionnent et le second n'est jamais compté. Exposé dans l'interface.
    min_similarity: float = 0.80
    # Volontairement **petite** : car, bus et truck sont réellement confondus par
    # le détecteur et doivent rester appariables.
    class_mismatch_penalty: float = 0.12
    # C'est **ceci** qui sépare les classes. Une moto (~0,7) et une voiture (~1,5)
    # donnent une pénalité d'environ 0,25, assez pour mettre l'identité d'une
    # voiture hors de portée d'une moto.
    aspect_penalty_weight: float = 0.30
    # Doit valoir 0 : le tracker détruit une piste morte et crée sa remplaçante
    # dans le *même* appel, donc un écart minimum non nul refuserait le match
    # légitime (piège 4 de prompt/13).
    min_gap_ms: float = 0.0
    # 30 s de *footage*, pas d'horloge murale.
    max_gap_ms: float = 30_000.0
    # Plusieurs points de vue par identité : un véhicule vu de face puis de profil
    # a deux apparences, et les moyenner produirait un descripteur qui ne
    # ressemble à aucune des deux.
    signatures_per_entry: int = 5
    # Coût maîtrisé de la mise à jour d'apparence : une frame sur huit.
    refresh_every_frames: int = 8
    # Fraction de la diagonale de l'image franchissable par `travel_reference_ms`.
    max_travel_ratio: float = 0.35
    travel_reference_ms: float = 200.0


@dataclass(frozen=True, slots=True)
class ReidCandidate:
    """Une piste sans identité, candidate à l'appariement.

    `signature` vaut `None` quand la boîte était trop petite ou hors image. Ces
    candidats reçoivent **toujours** une identité neuve : deviner sur du bruit est
    pire que créer une identité.
    """

    track_id: int
    class_id: int
    label: str
    centroid: Point
    signature: Signature | None


@dataclass(frozen=True, slots=True)
class Admission:
    """Résultat de l'appariement pour un candidat."""

    track_id: int
    global_id: int
    reidentified: bool


@dataclass(slots=True)
class _Entry:
    """Une identité connue de la galerie."""

    global_id: int
    # label → (class_id, nombre de voix). Le vote majoritaire cumulé décide de la
    # classe sous laquelle le véhicule est compté.
    votes: dict[str, tuple[int, int]]
    class_id: int
    label: str
    signatures: list[Signature]
    # `None` signifie « relâchée », donc éligible à un appariement. Une identité
    # portée par une piste vivante n'est pas une réapparition.
    active_track_id: int | None
    last_seen_ms: float
    last_centroid: Point
    reid_count: int = 0


def similarity(left: Signature, right: Signature) -> float:
    """Cosinus des deux descripteurs.

    Les descripteurs étant normalisés L2, le produit scalaire *est* le cosinus :
    inutile de rediviser par les normes à chaque comparaison, et la galerie en fait
    des milliers par frame.
    """
    return float(np.dot(left.values, right.values))


def build_signature(image: npt.NDArray[np.uint8], box: BoundingBox) -> Signature | None:
    """Décrit l'apparence du contenu de `box`, ou rend `None` si c'est impossible.

    `None` n'est pas une erreur : c'est un refus honnête. Le candidat recevra une
    identité neuve, ce qui surcompte au pire d'un véhicule — alors qu'un mauvais
    appariement en perdrait *deux* : celui qui hérite à tort et le vrai.

    L'ordre des canaux (RGB ou BGR selon l'adaptateur) est indifférent : le
    descripteur n'a besoin que d'être **cohérent** d'un appel à l'autre.
    """
    if box.width < MIN_BOX_SIDE_PX or box.height < MIN_BOX_SIDE_PX:
        return None

    crop = _inset_crop(image, box)
    if crop is None:
        return None

    thumbnail = _mean_pool(crop, THUMBNAIL_SIDE)
    values = np.concatenate([_colour_grid(thumbnail), _hue_histogram(thumbnail)])
    return Signature(values=_centre_and_normalise(values), aspect=box.width / box.height)


def _inset_crop(image: npt.NDArray[np.uint8], box: BoundingBox) -> npt.NDArray[np.uint8] | None:
    """Recadre la boîte rognée de 10 % par côté, bornée à l'image.

    Rogné parce que les coins d'une boîte de détection sont surtout du fond ; borné
    parce que le suivi extrapole parfois une boîte au-delà du bord de l'image.
    """
    height, width = image.shape[:2]
    inset_x = box.width * CROP_INSET_RATIO
    inset_y = box.height * CROP_INSET_RATIO

    x1 = max(0, int(box.x + inset_x))
    y1 = max(0, int(box.y + inset_y))
    x2 = min(width, int(box.x + box.width - inset_x))
    y2 = min(height, int(box.y + box.height - inset_y))

    # La vignette moyenne des blocs : un crop plus petit que la vignette n'aurait
    # pas un pixel par cellule, et le descripteur décrirait l'interpolation
    # plutôt que le véhicule.
    if x2 - x1 < THUMBNAIL_SIDE or y2 - y1 < THUMBNAIL_SIDE:
        return None
    return image[y1:y2, x1:x2]


def _mean_pool(crop: npt.NDArray[np.uint8], side: int) -> npt.NDArray[np.float32]:
    """Réduit le recadrage à `side`×`side` par moyenne de blocs.

    Une moyenne de blocs et non un sous-échantillonnage : prendre un pixel sur N
    échantillonnerait le bruit de compression au lieu de le moyenner.
    """
    height, width = crop.shape[:2]
    row_edges = np.linspace(0, height, side + 1).astype(int)
    col_edges = np.linspace(0, width, side + 1).astype(int)

    as_float = crop.astype(np.float32)
    # `reduceat` somme par tranche ; on divise ensuite par la hauteur puis la
    # largeur réelle de chaque tranche, qui ne sont pas toutes identiques.
    rows = np.add.reduceat(as_float, row_edges[:-1], axis=0)
    rows /= np.diff(row_edges)[:, None, None]
    blocks = np.add.reduceat(rows, col_edges[:-1], axis=1)
    blocks /= np.diff(col_edges)[None, :, None]
    return blocks.astype(np.float32)


def _colour_grid(thumbnail: npt.NDArray[np.float32]) -> npt.NDArray[np.float32]:
    """Grille 4×4 de moyennes de canaux — 48 valeurs, ramenées dans [0, 1].

    La mise à l'échelle importe : sans elle, des moyennes de 0 à 255 écraseraient
    l'histogramme de teinte, qui est une distribution de somme 1.
    """
    factor = THUMBNAIL_SIDE // COLOUR_GRID_SIDE
    grid = thumbnail.reshape(COLOUR_GRID_SIDE, factor, COLOUR_GRID_SIDE, factor, 3).mean(
        axis=(1, 3)
    )
    return (grid / 255.0).astype(np.float32).ravel()


def _hue_histogram(thumbnail: npt.NDArray[np.float32]) -> npt.NDArray[np.float32]:
    """Histogramme de teinte à 16 bins, **pondéré par la saturation**.

    La pondération évite que le bitume et les vitres — des pixels gris, dont la
    teinte est numériquement instable — votent pour un bin arbitraire et noient le
    signal des pixels réellement colorés.
    """
    channels = thumbnail.reshape(-1, 3) / 255.0
    maxc = channels.max(axis=1)
    minc = channels.min(axis=1)
    delta = maxc - minc

    # Saturation au sens HSV ; 0 sur un pixel noir, où la teinte n'existe pas.
    saturation = np.where(maxc > 0, delta / np.maximum(maxc, 1e-6), 0.0)

    hue = _hue_from_channels(channels, maxc, delta)
    bins = np.minimum((hue * HUE_BINS).astype(int), HUE_BINS - 1)

    histogram = np.zeros(HUE_BINS, dtype=np.float32)
    np.add.at(histogram, bins, saturation.astype(np.float32))
    total = float(histogram.sum())
    # Une image entièrement grise donne un histogramme nul : c'est une information
    # valable (« aucune teinte dominante »), pas une division par zéro.
    if total > 0:
        histogram /= total
    return histogram


def _hue_from_channels(
    channels: npt.NDArray[np.floating[Any]],
    maxc: npt.NDArray[np.floating[Any]],
    delta: npt.NDArray[np.floating[Any]],
) -> npt.NDArray[np.floating[Any]]:
    """Teinte dans [0, 1) par la formule HSV à six secteurs, sans OpenCV."""
    first, second, third = channels[:, 0], channels[:, 1], channels[:, 2]
    safe_delta = np.maximum(delta, 1e-6)

    hue = np.where(
        maxc == first,
        ((second - third) / safe_delta) % 6.0,
        np.where(
            maxc == second,
            (third - first) / safe_delta + 2.0,
            (first - second) / safe_delta + 4.0,
        ),
    )
    # Un pixel achromatique n'a pas de teinte : on la fixe à 0 plutôt que de
    # laisser le bruit numérique décider. Sa saturation nulle annule de toute
    # façon sa contribution.
    hue = np.where(delta > 1e-6, hue, 0.0)
    return (hue / 6.0) % 1.0


def _centre_and_normalise(values: npt.NDArray[np.float32]) -> npt.NDArray[np.float32]:
    """Centre puis normalise L2 — dans cet ordre, et c'est tout l'enjeu.

    Sans centrage, toutes les composantes étant positives, deux véhicules sans
    rapport partagent déjà une grande part de leur direction dans l'espace et
    scorent ~0,7.

    Un vecteur de norme nulle après centrage (image parfaitement uniforme sans
    teinte) est rendu tel quel : sa similarité avec n'importe quoi vaudra 0, ce qui
    est le bon comportement — cette apparence ne distingue rien.
    """
    centred = values - float(values.mean())
    norm = float(np.linalg.norm(centred))
    if norm < 1e-9:
        return centred.astype(np.float32)
    return (centred / norm).astype(np.float32)


class IdentityGallery:
    """Attribue et retrouve des identités globales par apparence.

    Deux jeux de compteurs cohabitent, et la distinction est essentielle :

    - `entries` est l'état **vivant** de la galerie, élagué pour borner le coût de
      chaque scan ;
    - `size` et `count_by_class()` sont des compteurs d'**émission** : ils ne
      décroissent jamais. Élaguer une entrée périmée ne doit pas faire baisser le
      nombre de véhicules uniques (piège 17 de prompt/13).
    """

    __slots__ = (
        "_entries",
        "_issued_by_class",
        "_issued_count",
        "_next_global_id",
        "_options",
        "_reid_hits",
    )

    def __init__(self, options: ReidOptions) -> None:
        self._options = options
        self._entries: dict[int, _Entry] = {}
        self._next_global_id = 1
        self._issued_count = 0
        self._issued_by_class: dict[str, int] = {}
        self._reid_hits = 0

    # ── Lectures ─────────────────────────────────────────────────────────────

    @property
    def size(self) -> int:
        """Nombre de véhicules uniques **émis**, élagage compris."""
        return self._issued_count

    @property
    def hits(self) -> int:
        """Nombre de ré-identifications réelles — ce que la carte de l'UI affiche."""
        return self._reid_hits

    def count_by_class(self) -> dict[str, int]:
        """Répartition des identités par classe votée.

        Somme toujours à `size`, y compris après un changement de majorité : c'est
        `_retally` qui déplace le vote unique d'une identité d'un total à l'autre.
        """
        return dict(self._issued_by_class)

    def label_of(self, global_id: int) -> str:
        """Libellé voté d'une identité, `""` si elle a été élaguée."""
        entry = self._entries.get(global_id)
        return entry.label if entry else ""

    def reid_count_of(self, global_id: int) -> int:
        entry = self._entries.get(global_id)
        return entry.reid_count if entry else 0

    def signature_count(self, global_id: int) -> int:
        entry = self._entries.get(global_id)
        return len(entry.signatures) if entry else 0

    # ── Appariement ──────────────────────────────────────────────────────────

    def admit_batch(
        self,
        candidates: Sequence[ReidCandidate],
        now_ms: float,
        frame_diagonal: float,
    ) -> tuple[Admission, ...]:
        """Apparie les candidats aux identités relâchées, en crée pour le reste.

        Glouton best-first : tous les couples au-dessus du seuil sont triés par
        score décroissant, et un candidat comme une entrée ne sont pris qu'une
        fois. Deux arrivées ne peuvent donc pas revendiquer la même identité — sans
        quoi l'une des deux ne serait jamais comptée.
        """
        self._prune(now_ms)

        eligible = [entry for entry in self._entries.values() if self._is_eligible(entry, now_ms)]
        pairs = self._score_pairs(candidates, eligible, now_ms, frame_diagonal)

        matched_tracks: dict[int, int] = {}
        claimed_entries: set[int] = set()
        for _score, track_id, global_id in pairs:
            if track_id in matched_tracks or global_id in claimed_entries:
                continue
            matched_tracks[track_id] = global_id
            claimed_entries.add(global_id)

        admissions: list[Admission] = []
        for candidate in candidates:
            matched = matched_tracks.get(candidate.track_id)
            if matched is not None:
                self._attach(matched, candidate, now_ms, reidentified=True)
                admissions.append(Admission(candidate.track_id, matched, reidentified=True))
            else:
                new_id = self._create(candidate, now_ms)
                admissions.append(Admission(candidate.track_id, new_id, reidentified=False))
        return tuple(admissions)

    def _score_pairs(
        self,
        candidates: Sequence[ReidCandidate],
        eligible: Sequence[_Entry],
        now_ms: float,
        frame_diagonal: float,
    ) -> list[tuple[float, int, int]]:
        """Tous les couples (candidat, entrée) au-dessus du seuil, triés."""
        pairs: list[tuple[float, int, int]] = []
        for candidate in candidates:
            if candidate.signature is None:
                continue
            for entry in eligible:
                # Le gate de déplacement s'applique **avant** tout scoring : c'est
                # lui qui empêche une voiture rouge entrant en haut d'hériter de
                # l'identité d'une voiture rouge sortie en bas.
                if not self._can_reach(entry, candidate.centroid, now_ms, frame_diagonal):
                    continue
                score = self._score(candidate, entry)
                if score >= self._options.min_similarity:
                    pairs.append((score, candidate.track_id, entry.global_id))
        # Tri par score décroissant : le match le plus sûr gagne sa cible, plutôt
        # que le premier candidat de la liste.
        pairs.sort(key=lambda pair: pair[0], reverse=True)
        return pairs

    def _score(self, candidate: ReidCandidate, entry: _Entry) -> float:
        """Similarité pénalisée d'un couple.

        Le **maximum** sur les signatures stockées, pas leur moyenne : un véhicule
        vu de face puis de profil a deux apparences, et la moyenne ne ressemble à
        aucune des deux.
        """
        signature = candidate.signature
        if signature is None or not entry.signatures:
            return -1.0

        best = max(similarity(signature, stored) for stored in entry.signatures)
        if candidate.class_id != entry.class_id:
            best -= self._options.class_mismatch_penalty

        # Écart de forme en échelle logarithmique : un rapport doublé et un rapport
        # divisé par deux doivent être pénalisés identiquement.
        best_aspect_penalty = min(
            abs(math.log(signature.aspect / stored.aspect))
            for stored in entry.signatures
            if stored.aspect > 0
        )
        return best - self._options.aspect_penalty_weight * best_aspect_penalty

    def _is_eligible(self, entry: _Entry, now_ms: float) -> bool:
        """Une identité portée par une piste vivante n'est pas une réapparition.

        Sans cette exclusivité, deux voitures identiques à l'écran deviendraient
        une seule, et la seconde ne serait jamais comptée.
        """
        if entry.active_track_id is not None:
            return False
        gap = now_ms - entry.last_seen_ms
        return self._options.min_gap_ms <= gap <= self._options.max_gap_ms

    def _can_reach(
        self, entry: _Entry, centroid: Point, now_ms: float, frame_diagonal: float
    ) -> bool:
        """Le véhicule a-t-il matériellement pu parcourir cette distance ?

        Le budget croît avec l'écart : un véhicule absent 3 s a pu aller loin, un
        véhicule absent 200 ms non. Un budget fixe serait soit trop serré pour les
        longues occlusions, soit trop large pour les courtes — et c'est sur les
        courtes que les sosies se confondent.
        """
        reference = self._options.travel_reference_ms
        gap = max(now_ms - entry.last_seen_ms, reference)
        budget = frame_diagonal * self._options.max_travel_ratio * (gap / reference)
        return distance(centroid, entry.last_centroid) <= budget

    # ── Cycle de vie d'une identité ──────────────────────────────────────────

    def _create(self, candidate: ReidCandidate, now_ms: float) -> int:
        global_id = self._next_global_id
        self._next_global_id += 1

        self._entries[global_id] = _Entry(
            global_id=global_id,
            votes={candidate.label: (candidate.class_id, 1)},
            class_id=candidate.class_id,
            label=candidate.label,
            signatures=[candidate.signature] if candidate.signature else [],
            active_track_id=candidate.track_id,
            last_seen_ms=now_ms,
            last_centroid=candidate.centroid,
        )
        self._issued_count += 1
        self._issued_by_class[candidate.label] = self._issued_by_class.get(candidate.label, 0) + 1
        return global_id

    def _attach(
        self, global_id: int, candidate: ReidCandidate, now_ms: float, *, reidentified: bool
    ) -> None:
        entry = self._entries[global_id]
        entry.active_track_id = candidate.track_id
        entry.last_seen_ms = now_ms
        entry.last_centroid = candidate.centroid
        if candidate.signature is not None:
            self._store_signature(entry, candidate.signature)
        if reidentified:
            entry.reid_count += 1
            self._reid_hits += 1

    def release(self, global_id: int, now_ms: float, centroid: Point) -> None:
        """Détache une identité de sa piste et la rend appariable.

        **`now_ms` doit être l'instant où le véhicule a réellement été vu pour la
        dernière fois**, jamais celui de la destruction de la piste. La piste ne
        meurt qu'après avoir « planté » `max_lost_ms` : dater le release à
        « maintenant » sous-estime l'écart de jusqu'à 2,5 s, affame le budget de
        déplacement, rejette le retour légitime — qui devient une identité neuve et
        un second comptage (piège 14 de prompt/13).
        """
        entry = self._entries.get(global_id)
        if entry is None:
            return
        entry.active_track_id = None
        entry.last_seen_ms = now_ms
        entry.last_centroid = centroid

    def reacquire(self, global_id: int, track_id: int, now_ms: float, centroid: Point) -> bool:
        """Re-lie une identité à une piste qui la porte encore, reconnue par id.

        Rend `True` **seulement** pour une vraie récupération : identité relâchée,
        non portée. Re-lier une identité déjà vivante est de la tenue de registre,
        pas une ré-identification, et le compter ferait mentir la carte
        « Ré-identifications » de l'interface.
        """
        entry = self._entries.get(global_id)
        if entry is None:
            return False

        recovered = entry.active_track_id is None
        entry.active_track_id = track_id
        entry.last_seen_ms = now_ms
        entry.last_centroid = centroid
        if recovered:
            entry.reid_count += 1
            self._reid_hits += 1
        return recovered

    def refresh(self, global_id: int, signature: Signature) -> None:
        """Ajoute un point de vue à une identité vivante."""
        entry = self._entries.get(global_id)
        if entry is not None:
            self._store_signature(entry, signature)

    def _store_signature(self, entry: _Entry, signature: Signature) -> None:
        """Conserve les `signatures_per_entry` apparences les plus récentes.

        Borné parce que le score parcourt toutes les signatures de toutes les
        entrées éligibles : une liste qui grandit indéfiniment ferait ralentir
        l'analyse au fil du clip.
        """
        entry.signatures.append(signature)
        if len(entry.signatures) > self._options.signatures_per_entry:
            del entry.signatures[0]

    def vote(self, global_id: int, class_id: int, label: str) -> None:
        """Vote majoritaire cumulé pour la classe d'une identité.

        **Une égalité laisse le tenant en place** : une lecture qui alterne
        bus/camion ne doit jamais faire osciller un véhicule entre deux compteurs.
        """
        entry = self._entries.get(global_id)
        if entry is None:
            return

        current_class, current_count = entry.votes.get(label, (class_id, 0))
        entry.votes[label] = (current_class, current_count + 1)

        leader_label, (leader_class, leader_count) = max(
            entry.votes.items(), key=lambda item: item[1][1]
        )
        incumbent_count = entry.votes.get(entry.label, (entry.class_id, 0))[1]
        # `>` strict : à égalité, le tenant garde la place.
        if leader_label != entry.label and leader_count > incumbent_count:
            self._retally(entry.label, leader_label)
            entry.label = leader_label
            entry.class_id = leader_class

    def _retally(self, previous_label: str, new_label: str) -> None:
        """Déplace le vote unique d'une identité d'un total de classe à l'autre.

        Sans ce transfert, `count_by_class()` cesserait de sommer à `size` et la
        répartition par type afficherait plus de véhicules que le total — ce que
        l'utilisateur voit immédiatement.
        """
        if previous_label in self._issued_by_class:
            self._issued_by_class[previous_label] -= 1
            if self._issued_by_class[previous_label] <= 0:
                del self._issued_by_class[previous_label]
        self._issued_by_class[new_label] = self._issued_by_class.get(new_label, 0) + 1

    def _prune(self, now_ms: float) -> None:
        """Retire les entrées non portées et trop vieilles pour matcher.

        Elles ne pouvaient plus être appariées et ne faisaient qu'allonger chaque
        scan. Les compteurs d'émission, eux, ne bougent pas : les véhicules
        élagués restent comptés.
        """
        expired = [
            global_id
            for global_id, entry in self._entries.items()
            if entry.active_track_id is None
            and now_ms - entry.last_seen_ms > self._options.max_gap_ms
        ]
        for global_id in expired:
            del self._entries[global_id]
