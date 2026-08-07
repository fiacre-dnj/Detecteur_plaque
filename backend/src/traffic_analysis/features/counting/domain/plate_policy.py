"""Quelles plaques valent une inférence — **détection** et **lecture**.

**Les types vivent dans le domaine, la décision appartient au service.** Le
domaine n'a pas à savoir ce qu'une inférence coûte ; mais les politiques doivent
être unitairement testables, donc pures — exactement le statut de `SessionConfig`.

**Le coût, dit franchement.** La détection de plaques coûte ~880 ms par frame avec
trois pistes, soit ~290 ms par piste ; une tête de reconnaissance sur
`(N, 3, 48, 320)` est deux ordres de grandeur en dessous. **L'OCR n'est pas le
goulot, la détection l'est.** `PlateOcrPolicy` existe donc d'abord pour la
*justesse* du vote — ne pas voter quarante fois sur le même recadrage figé d'un
véhicule arrêté au feu, ce qui gonflerait la confiance d'un texte peut-être faux —
et pour rendre le surcoût invisible.

**Ce module portait l'interdiction inverse, et elle est levée — pas contournée.**
Il posait que personne ne doit étrangler le *détecteur*, parce que ses boîtes sont
dessinées à l'écran et que les produire une image sur trois ferait clignoter des
rectangles que l'utilisateur lit comme un défaut de détection. Le raisonnement
était juste, et sa conclusion valable **tant qu'on se contentait de ne rien
produire les images sautées**. `plate_anchor` produit désormais une estimation
continue à la place : la condition qui fondait l'interdiction n'existe plus, et
`PlateDetectPolicy` peut étrangler ce qui était jusqu'ici le vrai goulot.

Ce qui demeure absolument : **l'OCR ne lit jamais une boîte reprojetée.** Une
extrapolation n'est pas une mesure, et la faire voter fabriquerait de la confiance
à partir de rien.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from traffic_analysis.features.counting.domain.models import BoundingBox


@dataclass(frozen=True, slots=True)
class PlateOcrOptions:
    """Réglages de l'étranglement. Chaque défaut a une raison."""

    #: Une image analysée sur N par piste. 3 : à 25 fps avec un pas de 1, cela fait
    #: ~8 occasions par seconde, largement assez pour réunir les deux lectures
    #: concordantes du vote pendant qu'un véhicule traverse le champ.
    every_n_frames: int = 3

    #: Au-dessus de cette IoU avec la dernière boîte lue, on ne relit pas. Un
    #: véhicule arrêté au feu produit cent recadrages identiques : les relire rend
    #: cent fois la même chaîne et ne fait que gonfler la confiance d'un texte
    #: peut-être faux. 0,85 laisse passer un changement d'échelle de ~15 %,
    #: c'est-à-dire un véhicule qui s'approche — un point de vue réellement neuf.
    skip_above_iou: float = 0.85

    #: Largeur minimale d'une vignette — **le plancher de lecture mesuré**.
    #:
    #: 64 px : l'échelle de vérité terrain (`scripts/anpr_bench.py --truth-ladder`)
    #: donne 4/8 lectures justes à cette largeur et **0/8 à 48 px**. La valeur
    #: précédente, 32, était cinq fois trop permissive par rapport à la mesure et
    #: dépensait le budget sur des vignettes dont on savait qu'elles ne rendraient
    #: rien. Couper plus haut supprimerait en revanche toute lecture sur des scènes
    #: où quelque chose passait : le vote agrège sur la vie du véhicule, donc 4/8
    #: par lecture n'est pas rien.
    min_width_px: float = 64.0

    #: Netteté minimale, en variance de laplacien. `0` désactive la porte.
    #:
    #: Anti-flou de mouvement : une plaque large mais floue est aussi illisible
    #: qu'une plaque nette et minuscule. La largeur seule ne les distingue pas.
    min_sharpness: float = 0.0

    #: Facteur d'amélioration exigé pour relire une identité déjà lue.
    #:
    #: `1.0` désactive la sélection par qualité. Au-dessus, on ne relit que si la
    #: nouvelle vignette bat la meilleure déjà lue de ce facteur : sous ce seuil,
    #: l'inférence rendrait la même chaîne en moins sûr et gonflerait la confiance
    #: d'un texte peut-être faux.
    quality_improvement: float = 1.0

    #: Cesser l'OCR d'une identité dont le vote est établi. **La plus grosse
    #: économie du dispositif**, et de loin : un véhicule passe de quarante
    #: inférences à trois sur sa vie.
    stop_when_confident: bool = True


def _iou(first: BoundingBox, second: BoundingBox) -> float:
    """Intersection sur union. `0` si l'une des deux boîtes est dégénérée.

    Fonction de module et **pas** une méthode de `BoundingBox`, délibérément :
    `containment` existe justement parce que l'IoU est le mauvais outil pour le cas
    cabine/camion, et poser les deux côte à côte sur le même objet inviterait à
    choisir le mauvais.
    """
    union = first.area + second.area - first.intersection_area(second)
    if union <= 0:
        return 0.0
    return first.intersection_area(second) / union


@dataclass(slots=True)
class PlateOcrPolicy:
    """Décide quelles plaques valent une inférence. Pur, donc testable.

    Une instance **par appel à `run_video`** : aucun état partagé entre jobs.

    Les deux dictionnaires croissent avec le nombre d'identités — quelques milliers
    d'entrées légères sur un clip de trente minutes. Borne acceptée sans purge : il
    n'existe aucun crochet propre pour purger, et en inventer un pour économiser
    quelques centaines de kilo-octets serait un mauvais échange.
    """

    options: PlateOcrOptions
    #: Identité → ordinal de la dernière inférence tentée.
    last_ordinal: dict[int, int] = field(default_factory=dict)
    #: Identité → boîte de plaque de la dernière inférence tentée.
    last_box: dict[int, BoundingBox] = field(default_factory=dict)
    #: Identité → meilleure **qualité** déjà lue (largeur × netteté).
    best_quality: dict[int, float] = field(default_factory=dict)

    def should_read(
        self,
        global_id: int,
        ordinal: int,
        box: BoundingBox,
        *,
        vote_is_confident: bool,
        sharpness: float = 0.0,
    ) -> bool:
        """Faut-il dépenser une inférence sur cette plaque ?

        `ordinal` est un compte d'images **analysées**, pas un `frame_index`. Avec
        `frame_stride = 3`, `frame_index` avance de 3 en 3 : comparer des index
        rendrait `every_n_frames` vrai à chaque image analysée, et l'étranglement ne
        servirait à rien. C'est le genre d'erreur qui ne se voit que sur une mesure
        de cadence.

        Les quatre gardes sont dans l'ordre du meilleur rapport économie/coût.
        """
        # 0. Pas d'identité : la lecture n'aurait aucun agrégat où voter, donc elle
        #    serait jetée. Dépenser pour jeter est le pire des échanges.
        if global_id == 0:
            return False

        # 1. Vote établi : plus rien à apprendre.
        if self.options.stop_when_confident and vote_is_confident:
            return False

        # 2. Trop petit : gratuit à évaluer, garanti sans résultat. Le plancher est
        #    **mesuré** — 0/8 lectures justes à 48 px.
        if box.width < self.options.min_width_px:
            return False

        # 2 bis. Trop flou. Une plaque large mais floue est aussi illisible qu'une
        #    plaque nette et minuscule, et la largeur seule ne les distingue pas.
        if self.options.min_sharpness > 0.0 and sharpness < self.options.min_sharpness:
            return False

        # 2 ter. Pas meilleure que ce qu'on a déjà lu de cette identité.
        #
        #    La qualité est le **produit** largeur × netteté : les deux façons d'être
        #    illisible se compensent sinon, et une vignette large et floue passerait
        #    pour meilleure qu'une vignette nette un peu plus petite.
        #
        #    Relire une vignette équivalente rendrait la même chaîne en moins sûr et
        #    gonflerait la confiance d'un texte peut-être faux. Le budget doit aller
        #    aux **meilleures** vignettes, pas à la troisième venue.
        if self.options.quality_improvement > 1.0:
            best = self.best_quality.get(global_id)
            if best is not None and self._quality(box, sharpness) < best * (
                self.options.quality_improvement
            ):
                return False

        # 3. Cadence : une image analysée sur N.
        last = self.last_ordinal.get(global_id)
        if last is not None and ordinal - last < self.options.every_n_frames:
            return False

        # 4. Déplacement : IoU et non distance du centroïde. L'IoU capte **aussi** le
        #    changement d'échelle, et une plaque qui a grandi de 40 % est un point de
        #    vue plus net qui vaut d'être relu — ce qu'un garde de distance ne
        #    verrait pas sur un véhicule venant droit sur la caméra.
        previous = self.last_box.get(global_id)
        return previous is None or _iou(previous, box) <= self.options.skip_above_iou

    @staticmethod
    def _quality(box: BoundingBox, sharpness: float) -> float:
        """Qualité d'une vignette : **le produit** largeur × netteté.

        Le produit et non l'une des deux : une vignette large et floue et une
        vignette nette et minuscule sont toutes deux illisibles, et seul le produit
        écarte les deux. Une netteté nulle — porte désactivée, ou mesure absente —
        rend la largeur seule, ce qui garde la sélection utilisable sans mesure.
        """
        return box.width * (sharpness if sharpness > 0.0 else 1.0)

    def record(
        self, global_id: int, ordinal: int, box: BoundingBox, sharpness: float = 0.0
    ) -> None:
        """Note qu'une inférence a eu lieu — **même si elle n'a rien lu**.

        Sinon une plaque durablement illisible serait relue à chaque frame, c'est-à-
        dire exactement le coût qu'on cherche à éviter.

        La qualité retenue est un **maximum**, jamais la dernière vue : sinon une
        vignette médiocre succédant à une bonne rabaisserait la barre, et la
        sélection par qualité perdrait tout son sens dès la deuxième lecture.
        """
        self.last_ordinal[global_id] = ordinal
        self.last_box[global_id] = box
        quality = self._quality(box, sharpness)
        previous = self.best_quality.get(global_id)
        if previous is None or quality > previous:
            self.best_quality[global_id] = quality


@dataclass(frozen=True, slots=True)
class PlateDetectOptions:
    """Réglages de l'étranglement du **détecteur**. Chaque défaut a une raison."""

    #: Une image analysée sur N par piste. **Aligné sur celui de l'OCR** : détecter
    #: plus souvent qu'on ne lit produirait des boîtes que personne ne consomme,
    #: puisque c'est la lecture qui décide du texte publié.
    every_n_frames: int = 3

    #: Décale la cadence par identité (`global_id % every_n_frames`).
    #:
    #: **Sans ce décalage, la charge oscille** : les huit pistes d'une image
    #: partiraient toutes ensemble une image sur trois, donnant 8 inférences puis
    #: 0 puis 0. Le débit moyen serait le même et l'expérience bien pire — une
    #: image sur trois prend trois fois plus longtemps que les autres, ce qui se
    #: voit dans la cadence affichée. Décalées, les inférences s'étalent.
    stagger: bool = True

    #: Cesser de détecter pour une identité dont le vote de texte est acquis.
    #:
    #: Sur les vidéos où aucun vote ne s'établit — plaques sous le plancher de
    #: lecture — cette garde n'apporte rien, et c'est attendu : elle économise ce
    #: qui alimentait un consommateur qui n'écoute plus.
    stop_when_confident: bool = True

    #: Sous cette largeur de **véhicule**, la plaque fera au mieux quelques pixels :
    #: l'inférence coûterait sans rien pouvoir trouver. Distinct du
    #: `min_width_px` de l'OCR, qui porte sur la plaque et non sur le véhicule.
    min_vehicle_width_px: float = 96.0

    #: Au-delà de cet âge, une ancre n'est plus reprojetée.
    #:
    #: Une plaque solidaire de son véhicule le reste sur deux ou trois images ; au
    #: bout de quatre, le véhicule a pu tourner, et reprojeter promènerait un
    #: rectangle qui ne décrit plus rien. Ne rien dessiner est alors plus honnête.
    max_anchor_age: int = 4


@dataclass(slots=True)
class PlateDetectPolicy:
    """Décide quelles pistes valent une inférence de **détection**. Pur, donc testable.

    Une instance **par appel à `run_video`**, comme `PlateOcrPolicy` : aucun état
    d'étranglement partagé entre jobs.
    """

    options: PlateDetectOptions
    #: Identité → ordinal de la dernière détection réellement soumise.
    last_ordinal: dict[int, int] = field(default_factory=dict)

    def should_detect(
        self,
        global_id: int,
        ordinal: int,
        vehicle: BoundingBox,
        *,
        vote_is_confident: bool,
        has_anchor: bool,
    ) -> bool:
        """Faut-il dépenser une inférence de détection sur cette piste ?

        `ordinal` est un compte d'images **analysées**, pas un `frame_index` — même
        raison que pour l'OCR : avec `frame_stride = 3`, comparer des index rendrait
        la garde de cadence vraie à chaque image analysée et l'étranglement ne
        servirait à rien.

        Les gardes sont dans l'ordre du meilleur rapport économie/coût.
        """
        # 0. Piste trop petite : la plaque y ferait quelques pixels. Gratuit à
        #    évaluer, garanti sans résultat exploitable.
        if vehicle.width < self.options.min_vehicle_width_px:
            return False

        # 1. Vote acquis : on payait le goulot pour alimenter un consommateur qui
        #    n'écoute plus. **La plus grosse économie quand des plaques sont lues.**
        if self.options.stop_when_confident and vote_is_confident:
            return False

        last = self.last_ordinal.get(global_id)

        # 2. Jamais détectée : on ne diffère pas la première mesure. Sans cette
        #    garde, une piste apparue juste après son tour de rôle attendrait
        #    `every_n_frames` images avant d'exister à l'écran.
        if last is None:
            return True

        # 3. Aucune ancre à reprojeter : sauter cette image ne produirait **rien**
        #    du tout, c'est-à-dire précisément le clignotement que l'ancre existe
        #    pour supprimer. On préfère payer.
        if not has_anchor:
            return True

        # 4. Cadence, décalée par identité pour que la charge reste plate.
        every = max(1, self.options.every_n_frames)
        if self.options.stagger:
            return (ordinal - global_id) % every == 0
        return ordinal - last >= every

    def record(self, global_id: int, ordinal: int) -> None:
        """Note qu'une détection a été soumise pour cette identité."""
        self.last_ordinal[global_id] = ordinal
