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
from typing import TYPE_CHECKING

from traffic_analysis.features.counting.domain.models import BoundingBox

if TYPE_CHECKING:
    from collections.abc import Sequence


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

    #: Recadrages soumis au détecteur par image analysée, au plus. `0` = illimité.
    #:
    #: **C'est le seul plafond qui rende le coût de l'ANPR indépendant de la scène.**
    #: Mesuré sur une scène dense réelle (1920×1080, 6 à 14 véhicules par image) :
    #: l'étage de plaques coûte 76 ms par image analysée, soit **73 %** du budget,
    #: contre 0,4 ms pour l'OCR — et ce coût est **linéaire en nombre de recadrages**,
    #: chaque véhicule payant une inférence complète. Sans plafond, la cadence suit
    #: donc la circulation : une intersection chargée coûte trois fois une rue calme,
    #: et une source plus définie fait franchir le seuil de largeur à plus de
    #: véhicules, donc paie encore davantage.
    #:
    #: Ce qui n'est pas servi cette image l'est à la suivante, et c'est ce qui rend le
    #: plafond peu coûteux en justesse : le texte publié est un **vote sur la vie du
    #: véhicule** (invariant 4), pas la lecture d'une image. Le budget va d'abord aux
    #: pistes **jamais mesurées** — sinon un véhicule pourrait traverser tout le champ
    #: sans jamais recevoir de rectangle — puis aux **plus larges**, dont la plaque a
    #: le plus de chances de dépasser le plancher de lecture.
    #:
    #: **Il coûte tout de même des plaques localisées**, à peu près proportionnellement
    #: aux recadrages écartés : 180 sur la scène dense sans plafond, 137 à `2`, 76 à
    #: `1`. Et son gain de cadence, une fois corrigée la vraie cause des pauses
    #: (ADR 0033), est bien plus faible qu'il n'a d'abord paru. Il **borne** le coût
    #: quand le trafic monte ; il ne l'améliore pas dans le cas général.
    max_per_frame: int = 0

    #: La porte de lisibilité est-elle armée ? Réglage de déploiement.
    #:
    #: Distinct de `readable_min_plate_width_px`, qui est la **valeur** du plancher et
    #: vient de l'OCR : celui-ci est l'interrupteur, celui-là le seuil. Les confondre
    #: obligerait le service à connaître un nombre pour dire « non ».
    readable_gate: bool = True

    #: Plancher de **lecture** de l'OCR, en pixels de **plaque**. `0` désactive.
    #:
    #: **La porte qui manquait, et c'est le plus gros levier de cadence de l'ANPR.**
    #: Mesuré sur une vue de circulation réelle (ADR 0032) : la détection de plaques
    #: pèse 73 % du budget, son coût est **linéaire en recadrages** — 21,5 ms pour un,
    #: 139,7 pour huit — et **aucune plaque n'y est publiable**, parce qu'elles font
    #: moins de 48 px pour un plancher de lecture à 64 (invariant 12). Les deux tiers
    #: du budget partaient donc dans des inférences dont on pouvait *prouver*, mesure
    #: en main, qu'elles ne rendraient jamais de texte.
    #:
    #: Dès qu'une piste a reçu **une seule** détection réelle, on connaît le rapport
    #: `largeur_plaque / largeur_véhicule` **de cette piste-là** — mesuré sur elle, pas
    #: estimé sur la scène. On sait donc quelle largeur de véhicule il faudrait pour
    #: atteindre le plancher, et on peut se taire tant qu'elle n'est pas atteinte.
    #:
    #: **Ce qui distingue cette porte d'un abandon, et ce qui la rend sûre** :
    #: `largeur_véhicule × rapport ≥ plancher` redevient vrai **tout seul** quand le
    #: véhicule s'approche. Pas de facteur de croissance à régler, pas d'hystérésis,
    #: pas de compteur à faire expirer — la porte **suspend**, elle n'abandonne pas.
    #: C'est ce qui répond à l'objection décisive : on ne perd pas la plaque qu'une
    #: piste publiera dans trois secondes, à dix mètres d'ici.
    #:
    #: **Aucun texte ne peut être perdu, par construction et pas en moyenne** : le
    #: nombre comparé est le **même** que celui dont `PlateOcrOptions.min_width_px` se
    #: sert déjà pour refuser de lire. Une plaque écartée ici est une plaque que l'OCR
    #: aurait refusée de toute façon. Ce qui est réellement payé est ailleurs, et il
    #: faut le dire : le **rectangle** disparaît sur ces véhicules, après les
    #: `max_anchor_age` images de reprojection.
    #:
    #: Posé par le service, et **seulement quand l'OCR tourne vraiment** : sans
    #: lecture, un rectangle sur une plaque de 20 px est exactement ce que
    #: l'utilisateur a demandé, et le couper serait lui retirer sa fonctionnalité au
    #: nom d'un texte qu'il n'attend pas.
    readable_min_plate_width_px: float = 0.0

    #: Mesures consécutives sous le plancher avant de suspendre la piste.
    #:
    #: `2` et non `1` : une plaque à moitié occultée ou vue de biais rend une mesure
    #: courte qui ne décrit pas la piste. Deux mesures basses de suite décrivent une
    #: situation, une seule décrit un instant.
    readable_min_samples: int = 2

    #: Réarmement d'office toutes les N images analysées. `0` = jamais.
    #:
    #: Quota d'exploration, désactivé par défaut : la porte se rouvre déjà seule
    #: quand le véhicule grandit, donc ce réglage n'existe que pour le cas — non
    #: observé à ce jour — d'une piste réellement lisible qui ne grandirait pas.
    readable_retry_every: int = 0

    #: Nombre d'échecs consécutifs (détection soumise, aucune plaque trouvée)
    #: au-delà duquel une piste sans ancre retombe sur la cadence normale au lieu
    #: d'être retentée à chaque image analysée.
    #:
    #: **Le trou que l'ancre ne bouche pas.** « Aucune ancre à reprojeter → on
    #: préfère payer » est correct pour une piste qui vient d'apparaître ou dont la
    #: plaque est passée hors champ un instant. Il devient un gouffre pour une piste
    #: dont la plaque n'est **structurellement** jamais visible — mauvais angle,
    #: trop loin, plaque absente de l'image : cette piste n'a jamais d'ancre à
    #: aucun moment de sa vie, donc la garde « pas d'ancre → toujours vrai » la
    #: retente à *chaque* image analysée, sans jamais bénéficier de
    #: l'étranglement. Mesuré sur une vraie vidéo : des pistes de ce type vivent 6
    #: à 8 s sans jamais produire de plaque, chacune payant ~800 ms par image
    #: analysée pendant toute leur vie.
    #:
    #: Après `max_consecutive_misses` échecs, continuer à payer n'achète plus rien
    #: de nouveau : le détecteur vient de répondre « rien » plusieurs fois de
    #: suite sur la même piste. Retomber sur la cadence économise sans changer le
    #: contrat visible — une piste sans ancre ne dessine toujours rien pendant les
    #: images sautées (`_project_anchor` rend `()` sans ancre), donc rien ne se met
    #: à clignoter : il n'y avait rien à faire clignoter.
    max_consecutive_misses: int = 3


@dataclass(frozen=True, slots=True)
class DetectionCandidate:
    """Une piste qui a passé les gardes de `should_detect`, prête à être classée.

    Trois champs et pas la piste entière : le classement est une règle de dépense, il
    n'a aucune raison de connaître une `SessionTrack` — et cette séparation est ce qui
    le rend testable sur des tuples.
    """

    global_id: int
    width: float
    #: Aucune détection n'a **jamais** été soumise pour cette piste.
    never_detected: bool


def select_within_budget(candidates: Sequence[DetectionCandidate], budget: int) -> frozenset[int]:
    """Les `budget` pistes qui méritent l'inférence de cette image.

    Rend un ensemble d'identités et non une liste : l'appelant garde **son** ordre,
    qui est celui du suivi. Un budget nul ou supérieur au nombre de candidates ne
    retire rien — c'est le comportement historique, et le plafond reste donc
    strictement additif tant que personne ne le pose.

    Le classement, dans cet ordre :

    1. **jamais mesurée d'abord.** Sans cette priorité, un véhicule qui apparaît au
       milieu d'un embouteillage pourrait traverser tout le champ sans jamais recevoir
       une seule mesure, donc sans jamais afficher de rectangle — un silence qui se
       lit comme une panne de détection, pas comme une économie ;
    2. **la plus large ensuite.** La largeur du véhicule est le meilleur prédicteur
       disponible de la largeur de la plaque, donc de sa lisibilité : le plancher de
       lecture est mesuré à 64 px (invariant 12), et dépenser sur une piste dont la
       plaque fera 20 px achète une boîte que l'OCR refusera de lire ;
    3. **l'identité, à égalité stricte**, pour que deux courses du même clip
       dépensent au même endroit. Un `set` d'itération non déterministe rendrait deux
       analyses du même fichier légèrement différentes, ce qui est exactement le
       genre d'écart qu'on passe des jours à ne pas comprendre.
    """
    if budget <= 0 or len(candidates) <= budget:
        return frozenset(candidate.global_id for candidate in candidates)
    ranked = sorted(
        candidates,
        key=lambda candidate: (not candidate.never_detected, -candidate.width, candidate.global_id),
    )
    return frozenset(candidate.global_id for candidate in ranked[:budget])


@dataclass(slots=True)
class PlateDetectPolicy:
    """Décide quelles pistes valent une inférence de **détection**. Pur, donc testable.

    Une instance **par appel à `run_video`**, comme `PlateOcrPolicy` : aucun état
    d'étranglement partagé entre jobs.
    """

    options: PlateDetectOptions
    #: Identité → ordinal de la dernière détection réellement soumise.
    last_ordinal: dict[int, int] = field(default_factory=dict)
    #: Identité → nombre d'échecs consécutifs (détection soumise, rien trouvé).
    #: Remis à zéro par tout succès ; absent tant qu'aucune détection n'a été
    #: soumise.
    misses: dict[int, int] = field(default_factory=dict)
    #: Identité → **meilleur** rapport largeur-plaque / largeur-véhicule mesuré.
    #:
    #: Un maximum, jamais la dernière valeur vue — même convention que
    #: `PlateOcrPolicy.record`, et elle penche du bon côté : un maximum rouvre la
    #: porte plus facilement qu'il ne la ferme.
    best_ratio: dict[int, float] = field(default_factory=dict)
    #: Identité → mesures consécutives dont la plaque était sous le plancher.
    unreadable: dict[int, int] = field(default_factory=dict)
    #: Identité → ordinal auquel la porte de lisibilité l'a suspendue.
    suspended_at: dict[int, int] = field(default_factory=dict)

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

        # 1 bis. Lisibilité projetée : cette piste a été mesurée, on connaît le
        #    rapport plaque/véhicule **de cette piste**, et il dit que sa plaque
        #    n'atteindra pas le plancher de lecture à la taille où le véhicule est.
        #    Payer achèterait une boîte que l'OCR refusera de lire — pas une plaque
        #    de moins. **La porte se rouvre seule quand le véhicule grandit** : c'est
        #    ce qui la distingue d'un abandon, et ce qui la rend sûre sur un véhicule
        #    qui approche.
        #
        #    **Impérativement AVANT la garde 3**, et c'est le seul détail
        #    d'implémentation qui peut faire échouer tout ce mécanisme en silence :
        #    une piste suspendue ne mesure plus, donc son ancre vieillit et disparaît
        #    à `max_anchor_age` ; la garde 3 (« pas d'ancre » → vrai inconditionnel)
        #    la relancerait alors à chaque image et la porte n'économiserait **rien**.
        if self._is_projected_unreadable(global_id, vehicle, ordinal):
            return False

        last = self.last_ordinal.get(global_id)

        # 2. Jamais détectée : on ne diffère pas la première mesure. Sans cette
        #    garde, une piste apparue juste après son tour de rôle attendrait
        #    `every_n_frames` images avant d'exister à l'écran.
        if last is None:
            return True

        # 3. Aucune ancre à reprojeter : sauter cette image ne produirait **rien**
        #    du tout, c'est-à-dire précisément le clignotement que l'ancre existe
        #    pour supprimer. On préfère payer — mais seulement tant que les
        #    tentatives récentes ont pu échouer par hasard plutôt que
        #    structurellement (voir `max_consecutive_misses`).
        if not has_anchor and self.misses.get(global_id, 0) < self.options.max_consecutive_misses:
            return True

        # 4. Cadence, décalée par identité pour que la charge reste plate.
        every = max(1, self.options.every_n_frames)
        if self.options.stagger:
            return (ordinal - global_id) % every == 0
        return ordinal - last >= every

    def record(self, global_id: int, ordinal: int, *, found: bool = True) -> None:
        """Note qu'une détection a été soumise pour cette identité.

        `found` distingue une détection qui a localisé une plaque de celle qui
        n'a rien trouvé — c'est ce compte d'échecs **consécutifs** qui permet à une
        piste structurellement sans plaque de retomber sur la cadence normale au
        lieu d'être retentée à chaque image (voir `max_consecutive_misses`).
        """
        self.last_ordinal[global_id] = ordinal
        if found:
            self.misses[global_id] = 0
        else:
            self.misses[global_id] = self.misses.get(global_id, 0) + 1

    def observe_plate(self, global_id: int, vehicle_width: float, plate_width: float) -> None:
        """Note ce qu'une détection **réelle** a mesuré sur cette piste.

        Jamais une reprojection : une ancre reprojetée n'est pas une observation, et
        la faire entrer ici ferait décider la porte sur une estimation d'estimation.
        L'appelant garantit cette propriété en ne l'appelant que sur `measured`.

        Le rapport retenu est un **maximum** : si la plaque a déjà été vue large une
        fois sur cette piste, c'est qu'elle *peut* l'être, et la porte doit s'ouvrir
        dès que le véhicule retrouve cette taille. Retenir la dernière mesure
        laisserait une vue de biais fermer la porte pour de bon.

        Le compteur d'illisibilité est remis à zéro par toute mesure au-dessus du
        plancher, comme `misses` l'est par tout succès : ce sont des échecs
        **consécutifs** qui décrivent une situation, pas un cumul sur la vie.
        """
        if vehicle_width <= 0.0 or plate_width <= 0.0:
            return
        ratio = plate_width / vehicle_width
        self.best_ratio[global_id] = max(self.best_ratio.get(global_id, 0.0), ratio)
        if plate_width >= self.options.readable_min_plate_width_px:
            self.unreadable[global_id] = 0
        else:
            self.unreadable[global_id] = self.unreadable.get(global_id, 0) + 1

    def _is_projected_unreadable(self, global_id: int, vehicle: BoundingBox, ordinal: int) -> bool:
        """La plaque de cette piste sera-t-elle **certainement** illisible ici ?

        « Certainement » au sens de ce qu'on a mesuré sur elle : on ne suspend
        jamais une piste qu'on n'a pas soi-même vue rendre des plaques trop petites,
        `readable_min_samples` fois de suite.
        """
        floor = self.options.readable_min_plate_width_px
        if floor <= 0.0:
            return False
        if self.unreadable.get(global_id, 0) < max(1, self.options.readable_min_samples):
            return False
        ratio = self.best_ratio.get(global_id)
        if ratio is None or ratio <= 0.0:
            return False

        # Le réarmement qui n'a besoin d'aucun réglage : le véhicule a grandi assez
        # pour que sa plaque franchisse le plancher. C'est une mesure, pas un délai.
        if vehicle.width * ratio >= floor:
            return False

        # Le quota d'exploration, désactivé par défaut. Il ne rouvre la porte que le
        # temps d'une image : sans nouvelle mesure au-dessus du plancher, la piste
        # est resuspendue aussitôt.
        every = self.options.readable_retry_every
        since = self.suspended_at.get(global_id)
        if every > 0:
            if since is None:
                self.suspended_at[global_id] = ordinal
            elif ordinal - since >= every:
                self.suspended_at[global_id] = ordinal
                return False
        return True
