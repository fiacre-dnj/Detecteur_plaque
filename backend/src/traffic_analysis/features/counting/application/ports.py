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

    #: Silence au-delà duquel une piste est abandonnée, en **ms de temps de scène**.
    #:
    #: Le même réglage que `SessionConfig.max_lost_ms` — une seule source, la requête,
    #: et deux consommateurs. Le domaine oublie l'identité d'un véhicule au bout de ce
    #: délai ; le tracker, lui, doit renoncer **au même moment**, sinon l'un rend un
    #: `track_id` que l'autre ne reconnaît plus et le véhicule reçoit un numéro neuf.
    #:
    #: **Il n'atteignait pas le tracker du tout**, et le curseur de l'écran était
    #: inerte : `track_buffer` est une constante du fichier de suivi versionné, et
    #: `EngineSpec` ne portait pas ce champ, donc la valeur ne *pouvait pas* descendre
    #: jusqu'à l'adaptateur. Voir `track_buffer_frames` et ADR 0058.
    #:
    #: **Un moteur qui l'ignore reste correct** : c'est la même doctrine que
    #: `start_ms` — un indice, jamais la règle. Le domaine applique `max_lost_ms` de
    #: son côté quoi qu'il arrive, donc le `FakeEngine` de la CI produit les mêmes
    #: chiffres. Le respecter aligne seulement les deux horloges.
    max_lost_ms: float = 2500.0

    #: Côté d'entrée du réseau demandé, ou `None` pour suivre le déploiement.
    #:
    #: **Ce n'est pas la taille d'un objet dans la vidéo qui décide qu'il est détecté,
    #: c'est sa taille ici.** En 16:9 le letterbox rend 640×384 : une moto de 60 px sur
    #: du 1080p n'en fait plus que 20, soit moins de trois cellules de la grille P3.
    #: C'est la cause qu'ADR 0037 a nommée sans pouvoir la corriger, le réglage
    #: n'existant nulle part dans la requête.
    #:
    #: Contrairement à `start_ms` et `max_lost_ms`, ce n'est **pas** un simple indice :
    #: un moteur qui l'ignore rendra d'autres détections, donc d'autres chiffres. Il n'y
    #: a pas de règle équivalente ailleurs qui le rattraperait — c'est le seul champ de
    #: cette classe dans ce cas, et le `FakeEngine` de la CI n'en produit aucune image.
    imgsz: int | None = None

    #: Plancher de confiance des **petits objets** — moto, vélo, personne.
    #:
    #: `None` (le défaut) rend le comportement d'avant ADR 0062 : un seul seuil pour
    #: toutes les classes. Voir `class_confidence_floors`, seul juge de la dérivation.
    small_confidence: float | None = None


def nms_class_groups(class_ids: Sequence[int]) -> tuple[tuple[int, ...], ...]:
    """Partitionne les classes demandées en groupes de suppression pour le moteur.

    Le juge unique de la façon dont le moteur découpe sa suppression des doublons,
    publié ici parce que l'adaptateur vit dans une autre feature et ne peut lire que
    le contrat (`features/models_registry` → `counting/application`).

    **Pourquoi le moteur en a besoin.** Le NMS d'Ultralytics ne connaît que deux
    régimes : *class-aware*, qui ne compare jamais deux classes — donc laisse une
    camionnette survivre comme `car 0.52` **et** `truck 0.41`, le piège 5 — et
    *agnostique*, qui compare tout — donc supprime la moto sous son pilote dès que
    leur recouvrement dépasse le seuil IoU. Aucun des deux n'est ce qu'on veut. La
    bonne règle est « agnostique **dans** un groupe, jamais **entre** deux », et elle
    s'obtient en découpant l'appel.

    **Le groupe est la CATÉGORIE, et surtout pas `class_group`.** Les deux tables
    existent, elles se ressemblent, et les confondre est le piège de ce module — un
    test verrouille l'écart. Elles répondent à deux questions différentes :

    - `class_group` sert à la **containment** (`_drop_contained`, ADR 0056) : « cet
      objet peut-il être *à l'intérieur* de l'autre en restant un objet distinct ? »
      Une moto **devant** un camion est contenue à 1,0 dans sa boîte et reste une
      moto, d'où trois familles ;
    - ici la question est l'**IoU** : « ces deux boîtes, qui *coïncident*, peuvent-elles
      décrire le même objet ? » Deux boîtes de classes véhicule qui se recouvrent
      au-delà de 0,45 ont la même taille et la même place — c'est un objet scoré deux
      fois, exactement le piège 5. La moto **devant** le camion, elle, n'atteint jamais
      cette IoU : les tailles sont trop différentes.

    La seule classe dont la boîte coïncide légitimement avec celle d'un **autre** objet
    est `person` : un pilote occupe la boîte de sa machine. D'où deux groupes, et pas
    trois.

    Trois propriétés, et la première est celle qui rend le changement livrable :

    - **une seule catégorie ⇒ une seule partie**, donc un seul appel au NMS, donc le
      comportement d'aujourd'hui au bit près. C'est le cas du jeu de classes par défaut
      (`car`, `motorcycle`, `bus`, `truck`) : aucune analyse existante ne change de
      chiffre, et c'est vérifié sur la sortie du NMS lui-même ;
    - **l'ordre est déterministe** — les catégories par leur nom, les identifiants
      croissants à l'intérieur. Deux courses identiques doivent soumettre les mêmes
      lots dans le même ordre, sinon le NMS glouton pourrait départager autrement ;
    - **une classe hors catalogue est un véhicule**, comme partout ailleurs
      (`category_of`) : elle continue donc d'être dédupliquée avec eux.
    """
    from traffic_analysis.features.counting.domain.models import CATEGORY_OF_ID

    groups: dict[str, list[int]] = {}
    for class_id in sorted(set(class_ids)):
        category = CATEGORY_OF_ID.get(class_id, "vehicle")
        groups.setdefault(category, []).append(class_id)
    return tuple(tuple(ids) for _, ids in sorted(groups.items()))


def class_confidence_floors(
    class_ids: Sequence[int], confidence: float, small_confidence: float | None
) -> tuple[tuple[int, float], ...]:
    """Le plancher de confiance **par classe**, ordonné et déterministe.

    `small_confidence` à `None` rend le même plancher pour tout le monde, c'est-à-dire
    exactement le comportement d'avant ADR 0062 : un no-op strict.

    **Pourquoi un plancher par classe.** Mesuré sur une vidéo réelle, descendre le
    curseur global de 0,35 à 0,20 fait passer le rappel des voitures de 0,484 à 0,790 —
    et fait **inventer dix-sept observations de `bus`** sur un clip qui n'en contient
    aucun. Le curseur unique force donc à choisir entre « rater les petits objets » et
    « compter des véhicules fantômes », alors que les deux effets ne portent pas sur les
    mêmes classes.

    Trois points qui ne se devinent pas :

    - **le minimum de ces planchers va au tracker**, jamais celui de l'utilisateur : le
      seuil de requête part sur `track_high_thresh` / `new_track_thresh` (ADR 0024), et
      s'il restait à 0,35 une moto à 0,25 n'ouvrirait aucune piste — le plancher par
      classe n'aurait alors aucun effet. C'est `minimum_floor` qui le garantit ;
    - **le filtre par classe vit donc APRÈS le NMS et AVANT le tracker**, dans le
      `postprocess` du prédicteur. Le tracker ne doit jamais voir une voiture à 0,25 :
      s'il la voyait, elle ouvrirait une piste que rien en aval ne saurait retirer — le
      score publié d'une piste vient de sa dernière détection et oscille ;
    - **jamais dans `_to_observations` ni dans le domaine.** Les deux sont en aval du
      tracker : filtrer là tuerait une piste en cours de vie au lieu d'empêcher sa
      naissance, et `counting/domain/models.py` documente déjà qu'une détection non
      associée n'existe plus à ce stade.
    """
    from traffic_analysis.features.counting.domain.models import SMALL_CLASS_IDS

    if small_confidence is None:
        return tuple((class_id, confidence) for class_id in sorted(set(class_ids)))
    return tuple(
        (class_id, small_confidence if class_id in SMALL_CLASS_IDS else confidence)
        for class_id in sorted(set(class_ids))
    )


def minimum_floor(floors: Sequence[tuple[int, float]], fallback: float) -> float:
    """Le plus bas des planchers — **ce qui doit partir au tracker**.

    `fallback` sert quand aucune classe n'est demandée, cas que le schéma de requête
    refuse déjà mais que le port ne peut pas supposer.
    """
    return min((floor for _, floor in floors), default=fallback)


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
