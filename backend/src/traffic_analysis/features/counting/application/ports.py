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


@dataclass(frozen=True, slots=True)
class VehicleSnapshot:
    """La capture d'un véhicule : lui, et sa plaque.

    **Deux JPEG et non une image composite.** La mise en page — la plaque sous la
    voiture — est faite par l'interface, en CSS. Composer ici figerait une décision
    d'affichage dans la donnée stockée, alors que la vignette de plaque a sa propre
    vie : c'est elle qui valide une alerte de plaque recherchée, et on veut pouvoir
    la montrer seule, plus grande, ou à côté du texte cherché.

    Des octets déjà encodés et non des pixels : l'encodage a lieu dans la boucle
    d'analyse, au moment où l'image est valide, et ce qui traverse ensuite est
    ~15 Ko au lieu des mégaoctets d'un recadrage brut.
    """

    vehicle_jpeg: bytes
    #: La vignette de plaque, ou `None` — **il n'y avait aucune plaque à recadrer**.
    #:
    #: `None` ne dit pas que l'encodage a échoué : il dit que cette capture a été
    #: retenue pour la ressemblance du véhicule à une image de requête (ADR 0051), et
    #: qu'aucune plaque n'y entre. Un échec de recadrage de plaque, quand une plaque
    #: était demandée, refuse la capture **entière** — sans quoi une capture annoncée
    #: « plaque lue » n'aurait pas de plaque à montrer.
    #:
    #: Pas de valeur par défaut : les deux faces sont passées nommément, pour qu'un
    #: futur appelant ne produise pas une capture sans plaque en croyant le contraire.
    plate_jpeg: bytes | None


@runtime_checkable
class VehicleSnapshotEncoder(Protocol):
    """Recadre un véhicule et, s'il y en a une, sa plaque.

    Un port et non un appel direct à OpenCV, pour la raison qui vaut pour tous les
    autres ici : `cv2` est interdit dans `application/**` comme dans `domain/**`, et
    la CI doit pouvoir tourner sans pixels. La doublure de test rend des octets
    quelconques, et les tests de la règle de capture n'en demandent pas plus.
    """

    def encode(
        self,
        image: npt.NDArray[np.uint8],
        vehicle: BoundingBox,
        plate: BoundingBox | None,
    ) -> VehicleSnapshot | None:
        """Rend la capture, ou `None` s'il n'y a rien d'exploitable à recadrer.

        Les boîtes sont en coordonnées de l'image **complète**, comme partout
        ailleurs dans ces ports. `plate` à `None` demande une capture **sans vignette
        de plaque** — c'est le cas d'une photo retenue pour la ressemblance du
        véhicule, où aucune plaque n'a été localisée (ADR 0051). Ce n'est pas une
        dégradation : quand une plaque est fournie et que son recadrage échoue, la
        capture entière est refusée.

        **Ne lève jamais.** Une capture ratée n'est pas une analyse ratée : le
        véhicule reste compté, son texte reste publié, il n'a simplement pas de
        photo. `None` est donc un refus honnête — recadrage vide, boîte hors image,
        encodeur en panne — et l'appelant n'enregistre alors aucun score.
        """
        ...


@dataclass(frozen=True, slots=True)
class VehicleAppearance:
    """L'apparence d'un véhicule, réduite à un vecteur comparable.

    `vector` est **déjà normalisé L2** par l'adaptateur, et c'est ce qui rend la
    similarité cosinus un simple produit scalaire. Normaliser à la production plutôt
    qu'à la comparaison évite que deux consommateurs le fassent différemment — ou
    qu'un seul l'oublie, ce qui rendrait des scores hors de [-1, 1] parfaitement
    plausibles à l'œil.

    **Il n'y a que le vecteur.** Une version antérieure portait ici une « qualité »
    (largeur × netteté) censée servir de clé à la règle monotone. C'était une erreur de
    conception : cette clé n'est connue qu'*après* le recadrage, alors que la règle doit
    être interrogée **avant** de payer quoi que ce soit. Le rang se joue donc sur la
    largeur de la boîte, que le domaine connaît seul, et la netteté reste un plancher
    dans l'adaptateur. Un champ dont personne ne décide rien serait un champ de trop.
    """

    vector: npt.NDArray[np.float32]


@runtime_checkable
class VehicleEmbedder(Protocol):
    """Encode l'apparence d'un véhicule en vecteur, pour une recherche par image.

    **N'entre dans aucun compteur.** Cette frontière ne sert qu'à la recherche par
    image de requête : ni `crossings`, ni `tracked_vehicles`, ni aucun `by_line` ne la
    lisent, et une analyse sans encodeur rend exactement les mêmes chiffres. C'est ce
    qui met cette fonctionnalité hors du champ d'ADR 0016, qui a supprimé la galerie
    d'identités précisément parce qu'elle était branchée sur le comptage.
    """

    def embed(
        self,
        image: npt.NDArray[np.uint8],
        boxes: Sequence[BoundingBox],
    ) -> tuple[VehicleAppearance | None, ...]:
        """Rend **exactement** un élément par boîte, dans le même ordre.

        Le contrat d'alignement positionnel est le même que celui de `detect_many` et
        de `read`, et pour la même raison : un recadrage trop petit ou trop flou laisse
        un `None` **à sa place**, il ne décale pas les suivants. Un décalage d'un cran
        attribuerait l'apparence d'un véhicule à son voisin — des scores plausibles et
        faux, sans rien qui lève.

        Les boîtes sont en coordonnées de l'image **complète**, comme partout ailleurs
        dans ces ports.

        **Ne lève jamais.** Un échec rend un tuple de `None` de la bonne longueur et
        journalise. Sans encodeur utilisable, la recherche par image est indisponible ;
        elle ne fait pas échouer l'analyse.
        """
        ...

    @property
    def available(self) -> bool:
        """Les poids sont-ils **là** ? Présence du fichier, jamais chargement.

        `/health` est interrogé en permanence : y charger 8,8 Mo d'ONNX en ferait un
        point de contention. Même règle que `PlateDetector.available`, et même
        complément — `probe()` répond à l'autre question.
        """
        ...

    def probe(self) -> bool:
        """Charge et fait **une** inférence à vide. Rend `False` sans jamais lever.

        C'est ce qui sépare `reidAvailable` de `reidLoadable` : un `.pt` déposé sous un
        nom en `.onnx`, un fichier tronqué, un graphe dont la sortie n'a pas la
        dimension attendue — tout cela passe `available` et échoue ici. « Poids
        présents, recherche muette, tout vert par ailleurs » est l'état qu'on refuse,
        et ce projet a déjà passé un projet entier dedans avec l'ANPR.
        """
        ...

    def embed_query(self, payload: bytes) -> VehicleAppearance | None:
        """Encode l'image de requête, fournie **en octets** encodés (JPEG, PNG).

        Des octets et non un tableau de pixels, et c'est structurel : `cv2` est
        interdit dans `application/**`, donc le service ne peut pas décoder. Faire
        voyager les octets jusqu'ici garde tout le travail sur les pixels dans
        l'adaptateur, du décodage au redimensionnement.

        **Aucun plancher de taille ne s'applique.** Les planchers de largeur et de
        netteté existent pour ne pas payer une inférence sur un véhicule lointain de
        la vidéo (ADR 0039) ; l'image de requête est fournie exprès, et la refuser
        parce qu'elle est petite laisserait l'utilisateur devant une recherche qui ne
        démarre pas sans savoir que c'est sa photo qui est en cause.

        Le **cadrage**, en revanche, doit être le même des deux côtés de la
        comparaison : c'est `vehicle_crop` qui définit « la vignette d'un véhicule ».
        L'appelant est censé avoir déjà réduit l'image au véhicule cherché — le
        client le fait avant l'envoi — donc l'adaptateur ne redécoupe pas.

        `None` si les octets ne sont pas une image exploitable.
        """
        ...
