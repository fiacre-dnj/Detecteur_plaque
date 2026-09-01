"""La galerie des apparences déjà vues — « ce véhicule est-il repassé ? ».

Chaque véhicule qui franchit une ligne y dépose l'apparence de sa meilleure vue, et
chaque nouveau franchisseur y est comparé. Un véhicule qui ressemble franchement à
un franchisseur antérieur est **signalé**, jamais fusionné avec lui.

**Ceci n'abroge pas ADR 0016**, et la distinction est toute la raison d'être de ce
module. La galerie d'identités qu'ADR 0016 a supprimée était **branchée sur le
comptage** : elle relâchait une identité puis la ré-attachait, donc le même `#1`
réapparaissait au milieu d'une vidéo et faussait les totaux. Celle-ci est un
**index de consultation** : aucun compteur ne la lit, un véhicule re-détecté reste
un véhicule de plus dans `tracked_vehicles`, et son franchissement compte comme
n'importe quel autre. C'est exactement la dérogation qu'ADR 0048 a déjà obtenue
pour la recherche par image, et elle se prouve de la même façon — un test qui
compare comptages, ventilations **et** horodatages avec et sans galerie.

**La comparaison n'est pas écrite ici.** `cosine_similarity` vit dans
`domain/appearance.py` et reste le seul juge de « se ressembler », lu par
l'adaptateur, par le service, par le banc et maintenant par ce module. Quatre
produits scalaires écrits séparément finiraient par différer sur la normalisation
ou sur les bornes, et l'écart serait invisible — des scores plausibles qui ne
veulent pas dire la même chose.

**Ce que ce module ne fait pas : trancher.** Mesuré (ADR 0048), les distributions
se recouvrent — deux vues du même véhicule descendent à 0,387, deux véhicules
différents montent à 0,891. `lookup` rend donc le meilleur score **brut** et son
porteur ; c'est le client qui décide, sur la capture, avec un curseur qu'il peut
déplacer sans réanalyser.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from traffic_analysis.features.counting.domain.appearance import cosine_similarity

if TYPE_CHECKING:
    import numpy as np
    import numpy.typing as npt


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
    """L'apparence retenue pour un véhicule, et la vue dont elle vient."""

    vector: npt.NDArray[np.float32]
    #: Largeur de la boîte dont ce vecteur est tiré. Clé de remplacement, jamais de
    #: comparaison — même règle et même raison que `appearance_width_px`.
    width_px: float


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
        """Dépose l'apparence de ce véhicule, ou remplace celle qu'il avait déjà.

        Sémantique de **remplacement** et non de vote, exactement comme
        `record_embedding` : la meilleure vue écrase la précédente. Il n'y a donc
        aucun vote à affamer, et c'est ce qui distingue cet étage de l'OCR, où
        raréfier les lectures empêche un texte d'exister (ADR 0029).

        Une vue plus étroite ne remplace rien. La largeur est la seule clé de rang
        disponible sans payer un recadrage — la netteté reste un plancher dans
        l'adaptateur, jamais un critère de classement.
        """
        current = self._entries.get(global_id)
        if current is not None and width_px <= current.width_px:
            return
        self._entries[global_id] = _Entry(vector, width_px)

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
            score = cosine_similarity(vector, entry.vector)
            if best is None or score > best.score:
                best = GalleryHit(other_id, score)
        return best
