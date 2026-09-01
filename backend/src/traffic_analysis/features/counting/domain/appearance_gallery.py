"""La galerie des apparences déjà vues — « ce véhicule est-il repassé ? ».

Chaque véhicule qui franchit une ligne y dépose l'apparence de **cette** vue, et chaque
nouveau franchisseur est comparé à **toutes** celles des déposants. Un véhicule qui
ressemble franchement à un franchisseur antérieur est **signalé**, jamais fusionné.

**Plusieurs vues et non une seule, et c'est le correctif de la première version.**
Elle ne gardait que la plus large : le candidat comparait sa vue courante à cette
unique référence, et le résultat dépendait de la chance que les deux se
correspondent. Deux vues d'un même véhicule ne se ressemblent pas autant qu'on croit
— 0,387 au plus bas (ADR 0048), parce que le prétraitement étire la vignette au carré
et que la déformation suit le rapport d'aspect de la boîte, lequel change avec la
distance et l'angle. Mesuré sur une vidéo doublée bout à bout, où la bonne réponse
vaut 1,00 par construction : trois jumeaux sur sept sortaient à 0,42, 0,60 et 0,27, et
le dernier désignait **un autre véhicule**.

**Ceci n'abroge pas ADR 0016**, et la distinction est toute la raison d'être de ce
module. La galerie d'identités qu'ADR 0016 a supprimée était **branchée sur le
comptage** : elle relâchait une identité puis la ré-attachait, donc le même `#1`
réapparaissait au milieu d'une vidéo et faussait les totaux. Celle-ci est un
**index de consultation** : aucun compteur ne la lit, un véhicule re-détecté reste
un véhicule de plus dans `tracked_vehicles`, et son franchissement compte comme
n'importe quel autre. C'est exactement la dérogation qu'ADR 0048 a déjà obtenue
pour la recherche par image, et elle se prouve de la même façon — un test qui
compare comptages, ventilations **et** horodatages avec et sans galerie.

**La comparaison n'est pas écrite ici.** `cosine_similarity` et `best_similarity`
vivent dans `domain/appearance.py`, seul juge de « se ressembler », lu par
l'adaptateur, par le service, par le banc et par ce module. Un `views @ vector` écrit
séparément finirait par différer sur la normalisation ou sur les bornes, et l'écart
serait invisible — des scores plausibles qui ne veulent pas dire la même chose.

**Ce que ce module ne fait pas : trancher.** Mesuré (ADR 0048), les distributions
se recouvrent — deux vues du même véhicule descendent à 0,387, deux véhicules
différents montent à 0,891. `lookup` rend donc le meilleur score **brut** et son
porteur ; c'est le client qui décide, sur la capture, avec un curseur qu'il peut
déplacer sans réanalyser.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

import numpy as np

from traffic_analysis.features.counting.domain.appearance import best_similarity

if TYPE_CHECKING:
    import numpy.typing as npt


#: Vues retenues par véhicule. Le rang est la largeur : au-delà, la plus étroite cède.
#:
#: **Pourquoi plusieurs, et pourquoi si peu.** Une seule vue ne suffit pas — le
#: candidat compare la sienne à celle-là, et rien ne garantit que les deux se
#: correspondent (voir `best_similarity`). Une par franchissement suffit largement :
#: un véhicule franchit une ou deux lignes, trois sur un carrefour complexe. `4`
#: laisse de la marge sans faire croître le coût de `lookup`, qui est linéaire en
#: `déposants × vues`.
MAX_VIEWS_PER_VEHICLE = 4


@dataclass(frozen=True, slots=True)
class GalleryHit:
    """Le meilleur antécédent trouvé, et à quel point il ressemble."""

    global_id: int
    score: float


@dataclass(slots=True)
class _Window:
    """Quand ce véhicule a été vu, du premier au dernier instant.

    Tenue par la galerie elle-même plutôt que lue sur la session, et ce n'est pas
    de la duplication : la session ne connaît que les véhicules **numérotés**, et
    surtout la faire interroger ici lierait un index de consultation au cœur du
    comptage. La galerie observe le temps qui passe, la session compte — les deux
    n'ont pas à se connaître.
    """

    first_ms: float
    last_ms: float


@dataclass(slots=True)
class _Entry:
    """Les apparences retenues pour un véhicule, et la largeur de chacune.

    **Plusieurs vues et non une seule**, et c'est le correctif de la première version.
    Elle ne gardait que la plus large : le candidat comparait alors sa vue courante à
    cette unique référence, et le score dépendait entièrement de la chance que les
    deux se correspondent. Mesuré sur une vidéo doublée bout à bout — où la bonne
    réponse est 1,00 par construction —, trois jumeaux sur sept sortaient à 0,42, 0,60
    et 0,27, et le dernier désignait même **un autre véhicule**.

    Les largeurs sont conservées en parallèle des vecteurs parce qu'elles sont la clé
    d'éviction, jamais de comparaison — même règle et même raison que
    `appearance_width_px`.
    """

    #: Matrice `(k, d)` des vues, prête pour `best_similarity`. Empilée à l'écriture
    #: plutôt qu'à la lecture : `lookup` est appelé une fois par franchissement et par
    #: déposant, `remember` une fois par franchissement tout court.
    views: npt.NDArray[np.float32]
    widths: list[float] = field(default_factory=list)


class AppearanceGallery:
    """Les apparences déjà déposées, interrogeables par ressemblance.

    Le cycle d'utilisation est **`observe` à chaque image, `lookup` puis `remember`
    au franchissement**, et l'ordre des deux derniers est la seule chose qui
    empêche un véhicule de se reconnaître lui-même. `lookup` exclut bien son propre
    identifiant, mais s'appuyer là-dessus seul serait fragile : déposer avant
    d'interroger ferait aussi remonter la vue précédente du **même** véhicule à
    chaque franchissement suivant, avec un score proche de 1.
    """

    __slots__ = ("_entries", "_windows")

    def __init__(self) -> None:
        self._entries: dict[int, _Entry] = {}
        self._windows: dict[int, _Window] = {}

    def observe(self, global_id: int, timestamp_ms: float) -> None:
        """Note que ce véhicule est à l'écran à cet instant.

        À appeler pour **toute piste visible**, encodée ou non : c'est ce qui rend
        la garde temporelle de `lookup` exacte. Un véhicule dont on n'observerait
        que les franchissements aurait une fenêtre réduite à ceux-ci, et deux
        voitures côte à côte pendant dix secondes paraîtraient ne s'être jamais
        croisées.

        Coût : deux comparaisons de flottants par piste et par image.
        """
        window = self._windows.get(global_id)
        if window is None:
            self._windows[global_id] = _Window(timestamp_ms, timestamp_ms)
            return
        window.first_ms = min(window.first_ms, timestamp_ms)
        window.last_ms = max(window.last_ms, timestamp_ms)

    def remember(self, global_id: int, vector: npt.NDArray[np.float32], width_px: float) -> None:
        """Ajoute une vue de ce véhicule à la galerie.

        **Accumulation et non remplacement**, contrairement à la première version.
        Chaque franchissement dépose sa vue, et les `MAX_VIEWS_PER_VEHICLE` plus
        larges sont conservées. Ce n'est pas un vote pour autant — les vues ne
        s'additionnent pas, elles sont autant de références indépendantes dont
        `lookup` retient la meilleure. Il n'y a donc rien à affamer, et le mode de
        panne d'ADR 0029 ne s'y rejoue pas.

        Au-delà du plafond, c'est la vue la plus **étroite** qui cède : la largeur
        reste la seule clé de rang disponible sans payer un recadrage, la netteté
        étant un plancher dans l'adaptateur et jamais un critère de classement.

        Une vue plus étroite que toutes les gardées, quand le plafond est atteint, est
        simplement ignorée.
        """
        current = self._entries.get(global_id)
        if current is None:
            self._entries[global_id] = _Entry(views=vector.reshape(1, -1).copy(), widths=[width_px])
            return

        if len(current.widths) < MAX_VIEWS_PER_VEHICLE:
            current.views = np.vstack((current.views, vector.reshape(1, -1)))
            current.widths.append(width_px)
            return

        narrowest = min(range(len(current.widths)), key=current.widths.__getitem__)
        if width_px <= current.widths[narrowest]:
            return
        current.views[narrowest] = vector
        current.widths[narrowest] = width_px

    def lookup(self, global_id: int, vector: npt.NDArray[np.float32]) -> GalleryHit | None:
        """Le déposant qui ressemble le plus à ce vecteur, ou `None`.

        Deux exclusions, et la seconde est celle qui ne se devine pas :

        - **soi-même**, évidemment ;
        - **tout véhicule qui était à l'écran en même temps que celui-ci.** Deux
          véhicules simultanément visibles ne peuvent pas être le même objet
          physique, quelle que soit leur ressemblance — et c'est précisément le
          faux positif le plus visible en trafic dense, où deux voitures du même
          modèle et de la même couleur se suivent. La garde est stricte : un
          déposant n'est éligible que s'il avait **disparu** avant que le candidat
          n'apparaisse.

        Rend `None` quand rien n'est éligible — galerie vide, ou tous les
        déposants encore à l'écran. Jamais un score par défaut : un `0.0` se
        lirait comme « mesuré, et sans ressemblance », alors qu'il n'y a rien eu à
        mesurer.

        **Le meilleur sur toutes les vues d'un déposant**, et c'est ce qui rend le
        résultat indépendant de la vue que le hasard avait fait retenir. Coût :
        `déposants × vues` produits scalaires de 512 flottants — quelques
        millisecondes, contre 21,8 ms pour un **seul** encodage.
        """
        window = self._windows.get(global_id)
        if window is None:
            return None

        best: GalleryHit | None = None
        for other_id, entry in self._entries.items():
            if other_id == global_id:
                continue
            other = self._windows.get(other_id)
            if other is None or other.last_ms >= window.first_ms:
                continue
            score = best_similarity(vector, entry.views)
            if best is None or score > best.score:
                best = GalleryHit(other_id, score)
        return best
