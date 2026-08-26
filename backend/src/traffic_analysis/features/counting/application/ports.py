"""Ports du comptage : ce dont l'orchestration a besoin, sans savoir qui le fournit.

C'est **la** décision qui rend tout le projet testable. Les tests injectent un
`FakeEngine` et n'ont donc besoin ni de GPU, ni de poids, ni d'ultralytics ; la
CI tourne en moins de cinq minutes sur une machine sans carte graphique.

Des `Protocol` et non des classes de base abstraites : une implémentation n'a
rien à hériter ni à importer pour satisfaire le contrat, et le port peut donc
vivre ici pendant que l'adaptateur vit dans une autre feature.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Protocol, runtime_checkable

if TYPE_CHECKING:
    from collections.abc import Iterator, Sequence
    from pathlib import Path

    import numpy as np
    import numpy.typing as npt

    from traffic_analysis.features.counting.domain.models import (
        BoundingBox,
        PlateDetection,
        TrackObservation,
        VideoInfo,
    )


@dataclass(frozen=True, slots=True)
class EngineSpec:
    """Ce que l'orchestration demande au moteur pour une course donnée.

    Les seuils viennent de la requête de l'utilisateur, jamais du catalogue :
    c'est ce qui garantit que les chiffres affichés correspondent aux réglages
    visibles à l'écran.
    """

    model_id: str
    confidence: float
    iou: float
    class_ids: tuple[int, ...]
    frame_stride: int = 1
    #: Temps de scène (ms) avant lequel il est **inutile** de décoder.
    #:
    #: C'est un indice de performance, **jamais la règle de comptage**. La fenêtre
    #: analysée est tranchée par `AnalysisService` sur les horodatages qu'un moteur
    #: rapporte, donc un adaptateur qui ignore ce champ — le `FakeEngine` de la CI,
    #: par exemple — produit exactement les mêmes chiffres, simplement plus
    #: lentement. Un adaptateur qui l'honore ne doit **pas** décaler ses
    #: horodatages : ils restent absolus depuis le début du fichier.
    #:
    #: Il n'y a pas de `end_ms` en face, et l'asymétrie est voulue : la fin s'obtient
    #: en refermant le générateur, ce que la boucle d'analyse fait déjà en sortant.
    start_ms: float = 0.0


@dataclass(frozen=True, slots=True)
class EngineFrame:
    """Une frame analysée, telle que le moteur la rapporte.

    `timestamp_ms` est du **temps de scène** (`frame_index / fps × 1000`), calculé
    par l'adaptateur. Il n'y a pas d'horloge murale dans ce flux.
    """

    frame_index: int
    timestamp_ms: float
    image: npt.NDArray[np.uint8]
    tracks: tuple[TrackObservation, ...]


@runtime_checkable
class TrackingStream(Protocol):
    """Flux de suivi ouvert, pour le temps réel.

    Un flux et non des images indépendantes : c'est `persist=True` côté
    Ultralytics qui fait qu'une suite de frames partage un état de suivi. Le bail
    du modèle reste ouvert jusqu'à `close()`.
    """

    def track(
        self, image: npt.NDArray[np.uint8], timestamp_ms: float
    ) -> tuple[TrackObservation, ...]:
        """Suit les objets d'une frame et rend les observations."""
        ...

    def close(self) -> None:
        """Ferme le flux et **rend le bail du modèle**.

        Appelée depuis un `finally` : un bail non rendu immobilise une instance de
        modèle jusqu'au redémarrage du service.
        """
        ...


@runtime_checkable
class DetectionTrackingEngine(Protocol):
    """Détection et suivi. Ultralytics aujourd'hui, un autre moteur demain."""

    def probe(self, video_path: Path) -> VideoInfo:
        """Dimensions, cadence et nombre d'images d'une vidéo.

        Sert aussi de **validation de format** : une vidéo qu'on ne peut pas
        sonder n'est pas une vidéo, quoi qu'en dise son `content-type`.
        """
        ...

    def iter_video(self, video_path: Path, spec: EngineSpec) -> Iterator[EngineFrame]:
        """Parcourt la vidéo image par image, sous un **unique bail** de modèle.

        Un bail pour toute l'itération : deux `track()` simultanés sur la même
        instance partagent l'état de suivi et mélangent deux vidéos — des chiffres
        plausibles et complètement faux.
        """
        ...

    def open_stream(self, spec: EngineSpec) -> TrackingStream:
        """Ouvre un flux de suivi persistant pour le temps réel."""
        ...


@runtime_checkable
class PlateDetector(Protocol):
    """Localisation de plaques sur le recadrage d'un véhicule suivi.

    Deux étages, pour une raison mesurée : une plaque fait ~15 px de large sur un
    plan large 1920×1080, et ~240 px une fois recadrée sur son véhicule. Le modèle
    plein cadre ne la voit pas.
    """

    def detect(
        self, image: npt.NDArray[np.uint8], box: BoundingBox, confidence: float | None = None
    ) -> tuple[PlateDetection, ...]:
        """Cherche une plaque dans `box`, en coordonnées de l'image **complète**.

        `confidence` remplace le seuil de l'adaptateur pour cet appel. `None` — le
        cas courant — garde celui de la configuration du service.

        Ne lève jamais : une passe ANPR ratée rend une liste vide et journalise.
        Un comptage ne doit pas échouer parce qu'une plaque était illisible.
        """
        ...

    def detect_many(
        self,
        image: npt.NDArray[np.uint8],
        boxes: Sequence[BoundingBox],
        confidence: float | None = None,
    ) -> tuple[tuple[PlateDetection, ...], ...]:
        """Cherche une plaque dans **chaque** boîte, et rend un tuple par boîte.

        Un lot et non un recadrage, pour la même raison que `PlateReader.read` : c'est
        à l'adaptateur de décider comment amortir ses inférences, et il ne peut le
        faire que s'il voit toute la frame d'un coup. L'implémentation Ultralytics sait
        empaqueter plusieurs recadrages dans une seule entrée de réseau — un échange
        rappel/vitesse qu'elle documente et que le déploiement arbitre.

        Rend **exactement** un tuple par boîte, dans le même ordre : c'est l'appelant
        qui sait à quelle piste appartient quel recadrage. Un recadrage trop petit
        rend un tuple vide, il ne décale pas les suivants.

        Ne lève jamais.
        """
        ...

    @property
    def available(self) -> bool:
        """Les poids sont-ils présents ?

        Distinct de « l'objet existe » : les poids sont chargés paresseusement, et
        leur absence ne doit pas empêcher le service de démarrer — l'option est
        simplement signalée indisponible dans `/health` et désactivée dans l'UI.

        Distinct aussi de `probe()` : celui-ci répond « le fichier est là », pas
        « le fichier est utilisable ». Un poids corrompu ou d'un format que son
        suffixe contredit rend `True` ici et échoue au chargement.
        """
        ...

    def probe(self) -> bool:
        """Charge les poids et lance **une** inférence à vide. Ne lève jamais.

        Appelé une fois au démarrage, dans un thread worker, et **jamais** depuis
        une route : c'est une opération de plusieurs secondes.

        Sépare deux états que `available` confondait, et cette confusion a un
        historique ici — trois pannes silencieuses de la même famille, où un
        drapeau vert accompagnait un pipeline muet. Un `available: true` avec un
        `probe()` faux nomme la panne au lieu de la laisser deviner.
        """
        ...


@dataclass(frozen=True, slots=True)
class PlateText:
    """Un texte de plaque lu, tel que le moteur d'OCR le rapporte.

    **Brut** : ni normalisé, ni filtré. La forme canonique est décidée par le domaine
    (`normalise_plate_text`) et pas par l'adaptateur — sinon deux adaptateurs, ou un
    adaptateur et sa doublure de test, voteraient sur des chaînes différentes et les
    tests ne prouveraient plus rien de la normalisation.
    """

    text: str
    #: Moyenne des probabilités maximales des pas de temps **retenus** par le
    #: décodage. Jamais la moyenne sur tous les pas : une plaque de sept caractères
    #: occupe une dizaine de pas sur les quarante que rend le modèle, et la longue
    #: traîne de blancs — dont la probabilité frôle 1,0 — tirerait toute confiance
    #: vers 0,95 en rendant n'importe quel seuil inopérant.
    score: float
    #: Confiance de **chaque** caractère, alignée sur `text`. Le consensus par
    #: caractère du vote en a besoin : une moyenne dit qu'une lecture hésitait, elle
    #: ne dit pas *où*, et c'est précisément la position litigieuse qu'il faut
    #: trancher entre `AB123CD` et `AB123CO`.
    #:
    #: Vide par défaut, et le vote sait faire sans : un lecteur d'une autre
    #: implémentation, ou une doublure de test, n'a pas à fabriquer des confiances
    #: qu'il ne mesure pas. Le vote retombe alors sur la confiance de la lecture
    #: entière — moins fin, jamais faux.
    char_scores: tuple[float, ...] = ()


@runtime_checkable
class PlateReader(Protocol):
    """Lecture des caractères d'une plaque **déjà localisée**.

    Étage **trois** et non deux : le modèle plein cadre ne voit pas la plaque, le
    détecteur de plaques ne lit pas les caractères. Chaque étage recadre plus près.

    **Un lot et non un recadrage.** La tête de reconnaissance a une entrée fixe
    48×320 : sur un tenseur si petit, le coût fixe d'un appel d'inférence — traversée
    de la frontière pybind11, réveil du pool de threads, allocation de l'arène — pèse
    autant que le calcul lui-même. Quatre plaques en quatre appels le paient quatre
    fois ; en un appel, une fois. Les GEMM du backbone, eux, sortent enfin du régime
    où leur synchronisation coûte plus que leur travail.
    """

    def read(
        self,
        image: npt.NDArray[np.uint8],
        boxes: Sequence[BoundingBox],
        min_score: float | None = None,
    ) -> tuple[PlateText | None, ...]:
        """Lit les plaques de `boxes`, en coordonnées de l'image **complète**.

        Rend **exactement** un élément par boîte, dans le même ordre : c'est
        l'appelant qui sait à quelle détection appartient quelle boîte, et lui rendre
        une liste plus courte l'obligerait à deviner. `None` signifie « rien de
        lisible ici » — un refus honnête, pas une erreur.

        `min_score` est le plancher de confiance de **cette** course, `None` gardant
        celui du déploiement (`plate_ocr_min_text_score`). Il voyage par appel et non
        par construction, exactement comme le `confidence` de
        `PlateDetector.detect_many`, et pour la même raison : c'est une question que
        seul l'utilisateur peut trancher devant sa vidéo — « des plaques fausses, ou
        pas de plaques ». Une lecture sous ce plancher n'atteint pas le vote, donc ne
        peut rien publier.

        Ne lève **jamais** : une lecture ratée rend `(None, …)` et journalise. Un
        comptage ne doit pas échouer parce qu'une plaque était sale.
        """
        ...

    @property
    def available(self) -> bool:
        """Les poids **et** le dictionnaire de caractères sont-ils présents ?

        Les deux, et c'est le piège propre à ce port : un `argmax` qui indexe un
        dictionnaire absent — ou d'une autre taille que celle du modèle — ne lève pas
        forcément. Il rend une chaîne fausse et parfaitement plausible. Répondre
        « disponible » avec un seul des deux fichiers produirait des plaques
        inventées.

        Une vérification de présence et non de chargement, comme
        `PlateDetector.available` : l'interface interroge `/health` en permanence.
        """
        ...
