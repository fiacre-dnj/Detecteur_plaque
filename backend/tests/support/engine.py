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

from traffic_analysis.features.counting.application.ports import EngineFrame, PlateText
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
    ) -> None:
        self._available = available
        self._text = text
        self._score = score
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
                score=self._score,
            )
            if self._is_readable is None or self._is_readable(box)
            else None
            for box in boxes
        )
