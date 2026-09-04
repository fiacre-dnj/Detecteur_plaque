"""Moteurs factices — le cœur du dispositif de test.

C'est ce qui permet à la CI de tourner **sans GPU, sans poids et sans
ultralytics**. Un test qui a besoin de télécharger 40 Mo est un test mal conçu.

Les images sont des `np.zeros` : les tests du comptage ne dépendent d'aucun pixel.
Les seuls tests qui en dépendent sont ceux de la ré-identification, qui
construisent des crops de couleurs contrôlées.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import numpy as np

from traffic_analysis.features.counting.application.ports import (
    EngineFrame,
    PlateText,
    VehicleAppearance,
    VehicleSnapshot,
)
from traffic_analysis.features.counting.domain.models import (
    BoundingBox,
    PlateDetection,
    TrackObservation,
    VideoInfo,
)

if TYPE_CHECKING:
    from collections.abc import Callable, Iterator, Sequence
    from pathlib import Path

    import numpy.typing as npt

    from traffic_analysis.features.counting.application.ports import EngineSpec

DEFAULT_INFO = VideoInfo(width=1920, height=1080, fps=25.0, frame_count=0)


class FakeEngine:
    """Rejoue une liste de frames préparée à la main.

    Satisfait `DetectionTrackingEngine` sans en hériter : c'est tout l'intérêt des
    `Protocol`.
    """

    def __init__(
        self,
        frames: Sequence[Sequence[TrackObservation]],
        *,
        info: VideoInfo | None = None,
        texture: int = 40,
        fail_with: Exception | None = None,
    ) -> None:
        self._frames = [tuple(frame) for frame in frames]
        self._info = info or VideoInfo(
            width=DEFAULT_INFO.width,
            height=DEFAULT_INFO.height,
            fps=DEFAULT_INFO.fps,
            frame_count=len(self._frames),
        )
        self._texture = texture
        # Permet de tester le chemin d'échec d'un job sans provoquer un vrai bug.
        self._fail_with = fail_with
        self.probe_calls = 0
        self.iterated_frames = 0

    def probe(self, video_path: Path) -> VideoInfo:  # noqa: ARG002
        self.probe_calls += 1
        return self._info

    def iter_video(self, video_path: Path, spec: EngineSpec) -> Iterator[EngineFrame]:  # noqa: ARG002
        """Parcourt les frames préparées, en respectant le pas d'analyse.

        Le pas est appliqué ici comme le ferait `vid_stride` d'Ultralytics, et
        `frame_index = position × stride` : sans cela, les horodatages du test ne
        correspondraient pas à ceux de la production et la progression serait
        testée sur une unité différente de celle qui est servie.
        """
        if self._fail_with is not None:
            raise self._fail_with

        stride = max(1, spec.frame_stride)
        image = self.image()
        for position, tracks in enumerate(self._frames[::stride]):
            frame_index = position * stride
            self.iterated_frames += 1
            yield EngineFrame(
                frame_index=frame_index,
                timestamp_ms=frame_index / self._info.fps * 1000.0,
                image=image,
                tracks=tracks,
            )

    def open_stream(self, spec: EngineSpec) -> FakeStream:  # noqa: ARG002
        return FakeStream(self._frames, self.image())

    def image(self) -> npt.NDArray[np.uint8]:
        """Image texturée : la ré-identification a besoin d'apparence.

        Une image parfaitement noire donnerait un descripteur de norme nulle, donc
        des similarités toutes égales à zéro — les tests d'identité passeraient
        pour de mauvaises raisons.
        """
        image = np.zeros((self._info.height, self._info.width, 3), dtype=np.uint8)
        if self._texture:
            image[:, :] = (self._texture, 90, 200 - self._texture)
            image[::5, :] = (240, 240, 240)
        return image


class FakeStream:
    """Flux de suivi factice, pour le temps réel."""

    def __init__(
        self,
        frames: Sequence[Sequence[TrackObservation]],
        image: npt.NDArray[np.uint8],
    ) -> None:
        self._frames = [tuple(frame) for frame in frames]
        self._image = image
        self._position = 0
        self.closed = False

    def track(
        self,
        image: npt.NDArray[np.uint8],  # noqa: ARG002
        timestamp_ms: float,  # noqa: ARG002
    ) -> tuple[TrackObservation, ...]:
        """Rend la frame suivante, puis boucle sur la dernière.

        Boucler plutôt que s'épuiser : une session temps réel dure aussi longtemps
        que l'utilisateur le veut, et un test ne doit pas avoir à préparer mille
        frames.
        """
        if not self._frames:
            return ()
        tracks = self._frames[min(self._position, len(self._frames) - 1)]
        self._position += 1
        return tracks

    def close(self) -> None:
        self.closed = True


class FakePlateDetector:
    """Détecteur de plaques factice, à disponibilité contrôlable.

    Deux compteurs et non un, pour la même raison que `FakePlateReader` : `calls`
    compte les **lots**, donc il prouve que les pistes d'une frame partent en un seul
    appel — c'est toute la raison d'être de la mosaïque ; `crops` compte les
    **recadrages**, donc il reste proportionnel au travail réellement demandé.
    """

    def __init__(
        self,
        *,
        available: bool = True,
        loadable: bool | None = None,
        score: float = 0.71,
        plates_for: Callable[[BoundingBox], Sequence[tuple[BoundingBox, float]]] | None = None,
    ) -> None:
        self._available = available
        #: Verdict rendu par `probe()`. `None` suit `available`, ce qui est le cas
        #: sain ; le poser explicitement à `False` reproduit **l'état qui compte** —
        #: des poids présents et illisibles, donc un drapeau vert et une ANPR muette.
        #: Aucune doublure ne pouvait exprimer cet état avant ADR 0015.
        self._loadable = available if loadable is None else loadable
        self._score = score
        #: Rend la main sur **ce que le détecteur trouve**, boîte par boîte.
        #:
        #: Ce qui devient possible : la boîte « véhicule entier » à 0,87 de
        #: confiance — le cas qui a motivé l'ADR 0008 et qu'aucun test ne
        #: traversait, parce que la doublure ne savait rendre qu'une plaque
        #: parfaitement plausible. `None` garde ce comportement par défaut.
        self._plates_for = plates_for
        self.calls = 0
        self.crops = 0
        #: Dernier seuil reçu, ou `None`. C'est ce qui permet à un test d'affirmer
        #: qu'un `plateConfidence` de requête atteint réellement l'adaptateur — le
        #: réglage est resté mort tout un lot sans que rien ne le signale.
        self.last_confidence: float | None = None
        #: Les boîtes **réellement soumises**, image par image.
        #:
        #: Un compteur dit *combien* d'inférences ont eu lieu ; ce journal dit
        #: *lesquelles*, et c'est ce qu'il faut pour prouver qu'un étranglement
        #: écarte les bonnes pistes — et surtout qu'il ne laisse aucun trou dans
        #: les snapshots des images qu'il saute.
        self.submitted: list[tuple[BoundingBox, ...]] = []
        #: Combien de fois l'auto-test a tourné. Il doit tourner **une** fois, au
        #: démarrage : le rappeler par requête coûterait des secondes.
        self.probes = 0

    @property
    def available(self) -> bool:
        return self._available

    def probe(self) -> bool:
        self.probes += 1
        return self._loadable

    def detect(
        self,
        image: npt.NDArray[np.uint8],
        box: BoundingBox,
        confidence: float | None = None,
    ) -> tuple[PlateDetection, ...]:
        """Cherche une plaque dans une seule boîte."""
        return self.detect_many(image, (box,), confidence)[0]

    def detect_many(
        self,
        image: npt.NDArray[np.uint8],  # noqa: ARG002
        boxes: Sequence[BoundingBox],
        confidence: float | None = None,
    ) -> tuple[tuple[PlateDetection, ...], ...]:
        """Rend une plaque plausible par boîte, en coordonnées de l'image **complète**.

        Les coordonnées absolues et non relatives au crop : c'est le contrat du
        port, et un test qui accepterait des coordonnées relatives laisserait
        passer un adaptateur qui oublie de les réexprimer.
        """
        if not boxes:
            return ()
        self.calls += 1
        self.crops += len(boxes)
        self.last_confidence = confidence
        self.submitted.append(tuple(boxes))
        if not self._available:
            return tuple(() for _ in boxes)
        if self._plates_for is not None:
            return tuple(
                tuple(
                    PlateDetection(box=plate, score=score) for plate, score in self._plates_for(box)
                )
                for box in boxes
            )
        # **Trois nombres se répondent, et rien ne le dit ailleurs.** Les scénarios
        # ANPR utilisent `VEHICLE_SIZE = (160, 120)` et cette plaque vaut
        # `largeur × 0,4`, soit **exactement 64,0 px** — c'est-à-dire pile la valeur
        # de `PlateOcrOptions.min_width_px`, donc pile le plancher que la porte de
        # lisibilité (ADR 0039) compare. Les deux comparaisons étant strictes, tout
        # passe aujourd'hui ; mais changer l'un des trois — la taille de véhicule
        # des tests, ce `0.4`, ou le plancher de lecture — ferait basculer plusieurs
        # tests d'un coup, sans qu'aucun message ne mentionne la cause.
        return tuple(
            (
                PlateDetection(
                    box=BoundingBox(
                        x=box.x + box.width * 0.3,
                        y=box.y + box.height * 0.65,
                        width=box.width * 0.4,
                        height=box.height * 0.15,
                    ),
                    score=self._score,
                ),
            )
            for box in boxes
        )


class FakePlateReader:
    """Lecteur de plaques factice, à disponibilité contrôlable.

    **Rend délibérément du texte non normalisé et en minuscules.** C'est ce qui fait
    qu'un test aboutissant à `AB-123-CD` *prouve* que la normalisation du domaine a
    tourné. Une doublure qui normaliserait ferait le travail de la production, et les
    tests cesseraient de démontrer quoi que ce soit — c'est le mécanisme exact par
    lequel deux vrais bugs ont traversé 500 tests verts.

    Deux compteurs et non un : `calls` compte les **lots**, donc il prouve que les
    plaques d'une frame partent en un seul appel ; `crops` compte les **plaques**,
    donc il prouve que l'étranglement en écarte.
    """

    def __init__(
        self,
        *,
        available: bool = True,
        text: str = "ab-123-cd",
        score: float = 0.93,
        is_readable: Callable[[BoundingBox], bool] | None = None,
        bad_length: bool = False,
        text_for: Callable[[BoundingBox], str] | None = None,
        score_for: Callable[[], float] | None = None,
    ) -> None:
        self._available = available
        self._text = text
        self._score = score
        #: Permet à un test de faire **varier** la confiance d'une image à l'autre,
        #: ce qu'aucune valeur fixe ne sait exprimer. C'est ce dont la règle de
        #: capture a besoin : « 0,80 puis 0,90 puis 0,85 » est une suite, pas un
        #: réglage. Sans argument, pour que l'appelant n'ait pas à connaître la boîte
        #: — il compte les appels, il ne les identifie pas.
        self._score_for = score_for
        #: Permet à un test — et au script de génération des fixtures — de produire
        #: l'état « plaque vue mais illisible », que l'interface rate le plus
        #: facilement. `None` signifie « tout est lisible ».
        self._is_readable = is_readable
        #: Simule un lecteur qui viole le contrat d'alignement positionnel du port.
        #: Le service doit alors renoncer au texte de la frame, pas échouer.
        self._bad_length = bad_length
        #: Décide le texte **à partir de la boîte**, au lieu du seul `text` fixe.
        #: C'est ce qui permet de simuler des lectures discordantes pour une même
        #: piste — donc un vote qui n'atteint jamais le consensus — sans quoi cette
        #: doublure ne peut produire que « jamais lu » ou « toujours la même chaîne ».
        #: Une rotation par **compteur global** ne le ferait pas : plusieurs pistes
        #: lisibles partageant un même appel `read()` recevraient chacune toujours
        #: la même valeur, jamais un désaccord en leur sein.
        #: `None` garde le comportement historique : `text` pour toute lecture réussie.
        self._text_for = text_for
        self.calls = 0
        self.crops = 0
        #: Les boîtes **réellement lues**, dans l'ordre.
        #:
        #: C'est ce journal qui permet de prouver qu'une sélection par qualité a
        #: retenu la meilleure vignette et non la troisième venue — un compteur
        #: dirait seulement qu'il y a eu autant de lectures.
        self.read_boxes: list[BoundingBox] = []
        #: Les planchers de lecture **reçus**, un par appel.
        #:
        #: La doublure les applique au lieu de les ignorer, et c'est délibéré : un
        #: réglage de requête que le port accepte sans effet est le pire état d'un
        #: réglage, et c'est exactement par là que `plate_confidence` était resté
        #: mort jusqu'à ADR 0007. Une doublure qui obéit rend le câblage vérifiable
        #: sans onnxruntime.
        self.min_scores: list[float | None] = []

    @property
    def available(self) -> bool:
        return self._available

    def read(
        self,
        image: npt.NDArray[np.uint8],  # noqa: ARG002
        boxes: Sequence[BoundingBox],
        min_score: float | None = None,
    ) -> tuple[PlateText | None, ...]:
        """Rend **exactement** un élément par boîte, dans le même ordre."""
        self.calls += 1
        self.crops += len(boxes)
        self.read_boxes.extend(boxes)
        self.min_scores.append(min_score)
        if not self._available:
            return (None,) * len(boxes)
        if self._bad_length:
            return ()
        # Le plancher est appliqué comme le ferait le vrai lecteur : la lecture ne
        # devient pas un `PlateText`, elle ne traverse pas le port, donc elle ne vote
        # pas. Un refus, jamais un texte étiqueté « peu sûr ».
        if min_score is not None and self._score < min_score:
            return (None,) * len(boxes)
        return tuple(
            PlateText(
                text=self._text_for(box) if self._text_for is not None else self._text,
                score=self._score_for() if self._score_for is not None else self._score,
            )
            if self._is_readable is None or self._is_readable(box)
            else None
            for box in boxes
        )


class FakeSnapshotEncoder:
    """Encodeur de captures factice — des octets quelconques, jamais des pixels.

    La CI n'a pas d'images utiles, et la règle qu'on teste ici n'en a pas besoin :
    « la meilleure lecture gagne » est une comparaison de nombres, pas de pixels. La
    doublure rend donc des octets reconnaissables, et compte ses appels — c'est ce
    comptage qui **prouve** l'optimisation : une lecture moins bonne que la
    précédente ne doit déclencher aucun encodage, pas seulement aucun remplacement.

    `fails` couvre l'autre moitié du contrat : un encodeur qui refuse ne doit laisser
    aucun score derrière lui, sinon un véhicule annoncerait une capture sans fichier.
    """

    def __init__(self, *, fails: bool = False) -> None:
        self._fails = fails
        #: Nombre d'encodages **réellement demandés**. Le chiffre qui dit si la règle
        #: monotone protège bien le chemin critique.
        self.calls = 0
        #: Les boîtes reçues, dans l'ordre — pour vérifier qu'on recadre le véhicule
        #: et sa plaque, et pas deux fois la même chose. La plaque vaut `None` sur une
        #: capture retenue pour la ressemblance du véhicule (ADR 0051).
        self.boxes: list[tuple[BoundingBox, BoundingBox | None]] = []

    def encode(
        self,
        image: npt.NDArray[np.uint8],
        vehicle: BoundingBox,
        plate: BoundingBox | None,
    ) -> VehicleSnapshot | None:
        del image
        self.calls += 1
        self.boxes.append((vehicle, plate))
        if self._fails:
            return None
        return VehicleSnapshot(
            vehicle_jpeg=b"vehicle-jpeg",
            plate_jpeg=None if plate is None else b"plate-jpeg",
        )


class FakeVehicleEmbedder:
    """Encodeur d'apparence factice — des vecteurs choisis, jamais des pixels.

    La CI n'a ni poids ni images utiles, et ce qu'on teste ici ne les demande pas : la
    règle monotone est une comparaison de nombres, et l'alignement positionnel une
    propriété de liste.

    `calls` compte les appels à `embed`, et `vectors_produced` les vecteurs réellement
    rendus. C'est ce second chiffre qui **prouve** que la règle monotone protège le
    chemin critique : un code qui encoderait chaque véhicule à chaque image rendrait
    exactement le même `matchScore`, deux ordres de grandeur plus cher, et aucun test
    portant seulement sur le résultat ne le verrait. Même raison d'être que
    `FakeSnapshotEncoder.calls`.

    `similarity_for` permet de faire ressembler un véhicule et pas un autre : la
    doublure fabrique deux vecteurs unitaires dont le produit scalaire vaut exactement
    la similarité demandée, de sorte que `cosine_similarity` — la vraie, celle du
    domaine — rende ce nombre. On teste ainsi la chaîne complète sans modèle.
    """

    def __init__(
        self,
        *,
        similarity_for: Callable[[int], float] | None = None,
        similarity_by_box: Callable[[BoundingBox], float] | None = None,
        min_width_px: float = 0.0,
        available: bool = True,
        query_fails: bool = False,
    ) -> None:
        self._similarity_for = similarity_for or (lambda _global_id: 0.9)
        # `similarity_for` est indexé sur la **position dans le lot**, ce qui suffit
        # tant que les véhicules à distinguer sont dans la même image. La galerie
        # d'ADR 0055 teste l'inverse — des véhicules qui passent l'un **après**
        # l'autre —, où cet index vaut toujours zéro et ne distingue donc rien. La
        # boîte, elle, reste discriminante d'une image à l'autre.
        #
        # Deux véhicules qui reçoivent la même valeur produisent le **même** vecteur,
        # donc une similarité de 1 entre eux : c'est ainsi qu'on simule « c'est le
        # même véhicule » sans un seul pixel.
        self._similarity_by_box = similarity_by_box
        self._min_width_px = min_width_px
        self._available = available
        self._query_fails = query_fails
        self.calls = 0
        self.vectors_produced = 0
        self.query_calls = 0

    @property
    def available(self) -> bool:
        return self._available

    def probe(self) -> bool:
        return self._available

    def embed_query(self, payload: bytes) -> VehicleAppearance | None:
        del payload
        self.query_calls += 1
        if self._query_fails:
            return None
        # Le vecteur de requête est l'axe 0 : la similarité d'un véhicule se règle
        # alors par sa seule première composante.
        vector = np.zeros(4, dtype=np.float32)
        vector[0] = 1.0
        return VehicleAppearance(vector=vector)

    def embed(
        self,
        image: npt.NDArray[np.uint8],
        boxes: Sequence[BoundingBox],
    ) -> tuple[VehicleAppearance | None, ...]:
        del image
        self.calls += 1
        out: list[VehicleAppearance | None] = []
        for index, box in enumerate(boxes):
            if box.width < self._min_width_px:
                # Le trou reste **à sa place** : c'est le contrat d'alignement
                # positionnel, et un décalage d'un cran attribuerait l'apparence d'un
                # véhicule à son voisin.
                out.append(None)
                continue
            self.vectors_produced += 1
            similarity = (
                self._similarity_for(index)
                if self._similarity_by_box is None
                else self._similarity_by_box(box)
            )
            vector = np.zeros(4, dtype=np.float32)
            vector[0] = similarity
            # Norme 1 par construction, comme le fait le vrai adaptateur : la
            # similarité cosinus n'est un produit scalaire que sur des vecteurs
            # normalisés.
            vector[1] = float(np.sqrt(max(0.0, 1.0 - similarity * similarity)))
            out.append(VehicleAppearance(vector=vector))
        return tuple(out)
