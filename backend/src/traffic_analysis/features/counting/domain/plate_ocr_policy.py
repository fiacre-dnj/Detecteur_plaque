"""Quelles plaques valent une inférence d'OCR.

**Le type vit dans le domaine, la décision appartient au service.** Le domaine n'a
pas à savoir que l'OCR coûte cher ; mais la politique doit être unitairement
testable, donc pure — exactement le statut de `SessionConfig`.

**Le coût, dit franchement.** La détection de plaques coûte ~880 ms par frame avec
trois pistes, soit ~290 ms par piste ; une tête de reconnaissance sur
`(N, 3, 48, 320)` est deux ordres de grandeur en dessous. **L'OCR n'est pas le
goulot, la détection l'est.** Cette politique existe donc d'abord pour la *justesse*
du vote — ne pas voter quarante fois sur le même recadrage figé d'un véhicule arrêté
au feu, ce qui gonflerait la confiance d'un texte peut-être faux — et pour rendre le
surcoût invisible.

Corollaire : personne ne doit « optimiser » en étranglant le **détecteur**. Ses
boîtes sont dessinées à l'écran ; les produire une frame sur trois ferait clignoter
des rectangles que l'utilisateur lit comme un défaut de détection. On étrangle ce qui
ne se voit pas.
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

    #: Sous cette largeur, ~4 px par caractère : l'inférence coûterait sans jamais
    #: rien lire.
    min_width_px: float = 32.0

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

    def should_read(
        self,
        global_id: int,
        ordinal: int,
        box: BoundingBox,
        *,
        vote_is_confident: bool,
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

        # 2. Trop petit : gratuit à évaluer, garanti sans résultat.
        if box.width < self.options.min_width_px:
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

    def record(self, global_id: int, ordinal: int, box: BoundingBox) -> None:
        """Note qu'une inférence a eu lieu — **même si elle n'a rien lu**.

        Sinon une plaque durablement illisible serait relue à chaque frame, c'est-à-
        dire exactement le coût qu'on cherche à éviter.
        """
        self.last_ordinal[global_id] = ordinal
        self.last_box[global_id] = box
