"""La re-détection d'un véhicule au franchissement — la galerie interne au clip.

Le cas d'usage qui l'a motivée : une même vidéo doublée sur une seule timeline. Quand
l'analyse atteint la seconde moitié, les franchissements doivent **signaler** que ces
véhicules ont déjà été vus.

Quatre propriétés, et la première est la seule qui rende la fonctionnalité livrable :

1. **elle ne change aucun comptage.** C'est exactement la clause qui la met hors du
   champ d'ADR 0016, dont la galerie supprimée alimentait le compteur. `crossings`,
   `tracked_vehicles`, les `by_line` **et les horodatages** doivent être identiques
   avec et sans galerie ;
2. **elle ne coûte rien quand elle est éteinte.** Pas un encodage de plus, pas un
   objet construit. C'est `vectors_produced` qui le prouve, jamais le contenu du
   registre — un code qui encoderait quand même rendrait le même résultat, plus cher,
   et aucun test portant sur la sortie ne le verrait ;
3. **un véhicule ne se reconnaît jamais lui-même**, ce que garantit l'ordre
   « interroger puis déposer » ;
4. **deux véhicules simultanément à l'écran ne sont jamais le même**, quelle que soit
   leur ressemblance. C'est la garde temporelle, et c'est le faux positif le plus
   visible en trafic dense qu'elle écarte.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import numpy as np
import pytest

from tests.support.builders import CAR, make_line, straight_line, track_path
from tests.support.engine import FakeEngine, FakeVehicleEmbedder
from traffic_analysis.features.counting.application.analysis_service import AnalysisService
from traffic_analysis.features.counting.application.dto import AnalysisJobConfig
from traffic_analysis.features.counting.domain.appearance_gallery import (
    MAX_VIEWS_PER_VEHICLE,
    AppearanceGallery,
)
from traffic_analysis.features.counting.domain.models import BoundingBox, TrackObservation

if TYPE_CHECKING:
    from pathlib import Path

    from traffic_analysis.features.counting.application.dto import AnalysisResultData
    from traffic_analysis.features.counting.domain.models import CountingLineDef


#: Deux tailles de boîte, deux apparences. La doublure dérive son vecteur de la
#: largeur, donc deux véhicules de **même** largeur rendent le même vecteur — c'est
#: ainsi qu'on simule « c'est la même voiture » sans un seul pixel.
SAME_WIDTH = 120.0
OTHER_WIDTH = 200.0


def _appearance_of(box: BoundingBox) -> float:
    """Une apparence par largeur de boîte, et deux largeurs seulement."""
    return 0.90 if box.width == SAME_WIDTH else 0.20


@pytest.fixture
def video(tmp_path: Path) -> Path:
    path = tmp_path / "clip.mp4"
    path.write_bytes(b"\x00" * 16)
    return path


def _crossing(track_id: int, *, width: float = SAME_WIDTH) -> list[TrackObservation]:
    """Une piste qui descend en travers de la ligne par défaut (y = 500)."""
    return track_path(
        track_id,
        CAR,
        straight_line((700.0, 250.0), (700.0, 800.0), steps=8),
        box_size=(width, 60.0),
    )


def _one_after_the_other(*widths: float) -> list[list[TrackObservation]]:
    """Des véhicules qui passent **l'un après l'autre**, jamais ensemble.

    `compose` entrelace les trajectoires, donc il donne des pistes **simultanées** —
    l'inverse exact de ce que la garde temporelle demande à tester. D'où cette
    concaténation à la main : chaque véhicule a le champ pour lui seul, et sa fenêtre
    de présence se referme avant que la suivante ne s'ouvre.

    C'est aussi la forme du cas d'usage réel : une vidéo doublée bout à bout.
    """
    frames: list[list[TrackObservation]] = []
    for index, width in enumerate(widths, start=1):
        frames.extend([observation] for observation in _crossing(index, width=width))
    return frames


def _run(
    video: Path,
    frames: list[list[TrackObservation]],
    *,
    rematch: bool,
    embedder: FakeVehicleEmbedder | None = None,
    floor: float = 0.0,
) -> AnalysisResultData:
    service = AnalysisService(
        FakeEngine(frames),
        vehicle_embedder=embedder,
        reid_rematch_min_similarity=floor,
    )
    config = AnalysisJobConfig(model_id="yolov8n", lines=(make_line(),), vehicle_rematch=rematch)
    return service.run_video("job-1", video, config)


def _by_id(result: AnalysisResultData) -> dict[int, object]:
    return {vehicle.global_id: vehicle for vehicle in result.vehicles}


class TestAucuneRegression:
    """La galerie est un index de consultation. Aucun compteur ne la lit.

    Le test qui rend ADR 0055 livrable au regard d'ADR 0016 — et le seul dont
    l'échec devrait faire retirer la fonctionnalité plutôt que la corriger.
    """

    def test_les_comptages_sont_identiques_avec_et_sans_galerie(self, video: Path) -> None:
        frames = _one_after_the_other(SAME_WIDTH, SAME_WIDTH)
        sans = _run(video, frames, rematch=False)
        avec = _run(
            video,
            frames,
            rematch=True,
            embedder=FakeVehicleEmbedder(similarity_by_box=_appearance_of),
        )

        assert avec.stats.crossings == sans.stats.crossings
        assert avec.stats.tracked_vehicles == sans.stats.tracked_vehicles
        assert avec.stats.by_class == sans.stats.by_class
        # La ventilation **entière**, et pas seulement ses totaux : les sens, leurs
        # premiers et derniers instants, les quasi-franchissements. Comparer les
        # totaux seuls laisserait passer un sens qui bascule.
        assert avec.stats.by_line == sans.stats.by_line

    def test_les_horodatages_sont_identiques(self, video: Path) -> None:
        """Et pas seulement les totaux.

        Un franchissement daté différemment déplacerait la tête de lecture et
        changerait l'ordre du journal, pour des totaux pourtant justes — exactement
        la classe de panne qu'ADR 0038 a corrigée.
        """
        frames = _one_after_the_other(SAME_WIDTH, SAME_WIDTH)
        sans = _run(video, frames, rematch=False)
        avec = _run(
            video,
            frames,
            rematch=True,
            embedder=FakeVehicleEmbedder(similarity_by_box=_appearance_of),
        )

        assert [(c.global_id, c.line_id, c.direction, c.timestamp_ms) for c in avec.crossings] == [
            (c.global_id, c.line_id, c.direction, c.timestamp_ms) for c in sans.crossings
        ]

    def test_un_vehicule_redetecte_reste_un_vehicule_de_plus(self, video: Path) -> None:
        """La re-détection **signale**, elle ne fusionne pas.

        C'est toute la différence avec la galerie qu'ADR 0016 a supprimée : celle-ci
        rendait au second véhicule le numéro du premier, donc un total qui n'avançait
        pas. Ici les deux numéros existent, les deux véhicules sont comptés, les deux
        franchissements aussi — et un troisième champ dit qu'ils se ressemblent.
        """
        result = _run(
            video,
            _one_after_the_other(SAME_WIDTH, SAME_WIDTH),
            rematch=True,
            embedder=FakeVehicleEmbedder(similarity_by_box=_appearance_of),
        )

        assert result.stats.tracked_vehicles == 2
        assert result.stats.crossings == 2
        assert len(result.vehicles) == 2


class TestEteinte:
    def test_sans_interrupteur_aucun_encodage(self, video: Path) -> None:
        """Le coût est nul quand la case est décochée, et c'est vérifié à la dépense.

        Le registre serait identique dans les deux cas : seul le compteur de vecteurs
        distingue « on n'a pas encodé » de « on a encodé pour rien ».
        """
        embedder = FakeVehicleEmbedder(similarity_by_box=_appearance_of)
        result = _run(
            video, _one_after_the_other(SAME_WIDTH, SAME_WIDTH), rematch=False, embedder=embedder
        )

        assert embedder.vectors_produced == 0
        assert all(vehicle.rematch_of is None for vehicle in result.vehicles)

    def test_sans_encodeur_l_analyse_reste_juste(self, video: Path) -> None:
        """Cocher la case sans poids installés n'est pas une erreur fatale.

        Même doctrine que les trois refus de la recherche par image : l'indisponibilité
        d'une option ne fait pas échouer une analyse dont tous les comptages sont
        justes.
        """
        result = _run(video, _one_after_the_other(SAME_WIDTH), rematch=True, embedder=None)

        assert result.stats.crossings == 1
        assert result.vehicles[0].rematch_of is None


class TestRedetection:
    def test_le_second_passage_designe_le_premier(self, video: Path) -> None:
        """Le cas d'usage, réduit à son os : la même voiture repasse.

        Le **second** véhicule porte la re-détection et pointe vers le premier. Jamais
        l'inverse : au moment où le premier franchit, la galerie est vide.
        """
        result = _run(
            video,
            _one_after_the_other(SAME_WIDTH, SAME_WIDTH),
            rematch=True,
            embedder=FakeVehicleEmbedder(similarity_by_box=_appearance_of),
        )
        vehicles = _by_id(result)

        assert vehicles[1].rematch_of is None  # type: ignore[attr-defined]
        assert vehicles[2].rematch_of == 1  # type: ignore[attr-defined]
        assert vehicles[2].rematch_score == pytest.approx(1.0)  # type: ignore[attr-defined]

    def test_un_vehicule_different_n_est_pas_redetecte(self, video: Path) -> None:
        """Le contrôle négatif, sans lequel le test précédent ne prouve rien.

        Le plancher est posé haut exprès : la doublure rend bien une ressemblance
        entre deux apparences distinctes, mais faible. C'est le service qui doit la
        taire, pas la doublure.
        """
        result = _run(
            video,
            _one_after_the_other(SAME_WIDTH, OTHER_WIDTH),
            rematch=True,
            embedder=FakeVehicleEmbedder(similarity_by_box=_appearance_of),
            floor=0.9,
        )
        vehicles = _by_id(result)

        assert vehicles[2].rematch_of is None  # type: ignore[attr-defined]

    def test_le_franchissement_declenche_l_encodage(self, video: Path) -> None:
        """Sans image de requête, **seuls** les franchisseurs sont encodés.

        La règle monotone ne sert que la recherche par image : encoder les plus larges
        sans photo à comparer serait une dépense sans consommateur. Deux véhicules,
        un franchissement chacun, donc deux vecteurs — et non un par image.
        """
        embedder = FakeVehicleEmbedder(similarity_by_box=_appearance_of)
        _run(video, _one_after_the_other(SAME_WIDTH, SAME_WIDTH), rematch=True, embedder=embedder)

        assert embedder.vectors_produced == 2


#: Les trois vues du scénario à deux lignes, et les similarités qu'elles produisent.
#:
#: La doublure fabrique un vecteur unitaire d'angle `arccos(s)` : la ressemblance de
#: deux vues vaut donc `cos(θ₁ − θ₂)`, ce qui permet de choisir les écarts à la main.
#: Ici : `cos(NEAR, NEAR) = 1,00`, `cos(FAR, DECOY) ≈ 0,98`, `cos(FAR, NEAR) ≈ 0,61`.
NEAR_WIDTH = 120.0
FAR_WIDTH = 200.0
DECOY_WIDTH = 160.0

_VIEW_BY_WIDTH = {NEAR_WIDTH: 0.90, FAR_WIDTH: 0.20, DECOY_WIDTH: 0.40}


def _view_of(box: BoundingBox) -> float:
    """Une apparence par largeur de boîte — donc une par vue."""
    return _VIEW_BY_WIDTH.get(box.width, 0.05)


def _two_lines() -> tuple[CountingLineDef, CountingLineDef]:
    """Deux lignes en travers de la route : tout véhicule les franchit toutes deux."""
    return (
        make_line("proche", a=(0.0, 450.0), b=(1920.0, 450.0)),
        make_line("loin", a=(0.0, 750.0), b=(1920.0, 750.0)),
    )


def _descends(track_id: int, *, near: float, far: float) -> list[TrackObservation]:
    """Une piste qui descend et **grossit** : deux vues, une par ligne franchie.

    C'est la forme du cas réel, et elle est le cœur du scénario : la boîte d'un
    véhicule qui approche n'a pas la même largeur au premier trait qu'au second, donc
    les deux franchissements soumettent deux vues **différentes** du même véhicule.
    C'est exactement ce que la première version ne savait pas gérer.
    """
    return [
        TrackObservation(
            track_id=track_id,
            class_id=CAR,
            label="car",
            score=0.9,
            box=BoundingBox(
                x=700.0 - (near if y <= 550.0 else far) / 2,
                y=y,
                width=near if y <= 550.0 else far,
                height=60.0,
            ),
        )
        for y in [100.0 + 75.0 * step for step in range(13)]
    ]


class TestLaMeilleureMesureGagne:
    """Le défaut mesuré sur une vidéo doublée : la **dernière** mesure l'emportait.

    Un véhicule franchit plusieurs lignes, donc interroge la galerie plusieurs fois,
    et chaque interrogation compare une vue **différente**. Deux vues du même véhicule
    ne se ressemblant pas autant qu'on croit (0,387 au plus bas, ADR 0048), la dernière
    mesure est souvent la plus mauvaise — et elle écrasait la bonne.

    Constaté sur une vidéo doublée bout à bout, où la bonne réponse vaut 1,00 par
    construction : trois jumeaux sur sept publiaient 0,42, 0,60 et 0,27, et le dernier
    désignait **un autre véhicule**.
    """

    @staticmethod
    def _scenario() -> list[list[TrackObservation]]:
        """Un antécédent, un leurre, puis le jumeau de l'antécédent.

        Les trois passent l'un après l'autre. Le leurre n'existe que pour porter la
        vue `DECOY`, qui ressemble beaucoup à la vue **lointaine** du jumeau et très
        peu à sa vue proche : au second franchissement du jumeau, c'est donc lui qui
        gagne. Sans la règle du maximum, il devient l'antécédent publié.
        """
        frames: list[list[TrackObservation]] = []
        for track_id, (near, far) in enumerate(
            [
                # L'antécédent : deux vues proches, donc une galerie centrée sur NEAR.
                (NEAR_WIDTH, NEAR_WIDTH),
                # Le leurre.
                (DECOY_WIDTH, DECOY_WIDTH),
                # Le jumeau : vue proche identique à l'antécédent, vue lointaine non.
                (NEAR_WIDTH, FAR_WIDTH),
            ],
            start=1,
        ):
            frames.extend([observation] for observation in _descends(track_id, near=near, far=far))
        return frames

    def _run(self, video: Path) -> AnalysisResultData:
        service = AnalysisService(
            FakeEngine(self._scenario()),
            vehicle_embedder=FakeVehicleEmbedder(similarity_by_box=_view_of),
        )
        config = AnalysisJobConfig(model_id="yolov8n", lines=_two_lines(), vehicle_rematch=True)
        return service.run_video("job-1", video, config)

    def test_le_jumeau_designe_son_antecedent_et_non_le_leurre(self, video: Path) -> None:
        """**Le test qui reproduit la capture.**

        Sans la règle du maximum, le jumeau publie le leurre : sa seconde mesure,
        prise sous un angle qui ne correspond à rien, trouve mieux ailleurs.
        """
        vehicles = _by_id(self._run(video))

        assert vehicles[3].rematch_of == 1  # type: ignore[attr-defined]

    def test_le_score_publie_est_le_meilleur_des_franchissements(self, video: Path) -> None:
        """Et il vaut 1,00 : la vue proche du jumeau est celle de son antécédent.

        C'est la garantie que le cas de la vidéo doublée demande — le métrage étant
        identique, la vue correspondante existe et sa ressemblance est exacte.
        """
        vehicles = _by_id(self._run(video))

        assert vehicles[3].rematch_score == pytest.approx(1.0)  # type: ignore[attr-defined]


class TestGalerie:
    """La galerie seule, sans le service — les deux gardes qui la rendent honnête."""

    @staticmethod
    def _vector(value: float) -> np.ndarray:
        vector = np.zeros(4, dtype=np.float32)
        vector[0] = value
        vector[1] = float(np.sqrt(max(0.0, 1.0 - value * value)))
        return vector

    def test_un_vehicule_ne_se_reconnait_pas_lui_meme(self) -> None:
        gallery = AppearanceGallery()
        gallery.observe(1, 0.0)
        gallery.remember(1, self._vector(0.9), 120.0)
        gallery.observe(1, 100.0)

        assert gallery.lookup(1, self._vector(0.9)) is None

    def test_un_vehicule_encore_a_l_ecran_est_ecarte(self) -> None:
        """Deux véhicules simultanément visibles ne sont pas le même objet physique.

        Quelle que soit leur ressemblance — et deux voitures du même modèle et de la
        même couleur qui se suivent en rendent une très élevée. C'est le faux positif
        le plus visible en trafic dense.
        """
        gallery = AppearanceGallery()
        gallery.observe(1, 0.0)
        gallery.observe(1, 500.0)
        gallery.remember(1, self._vector(0.9), 120.0)
        # Le second apparaît **pendant** que le premier est encore là.
        gallery.observe(2, 300.0)

        assert gallery.lookup(2, self._vector(0.9)) is None

    def test_un_vehicule_disparu_avant_est_eligible(self) -> None:
        """Le pendant positif du test précédent : la garde n'écarte pas tout."""
        gallery = AppearanceGallery()
        gallery.observe(1, 0.0)
        gallery.observe(1, 200.0)
        gallery.remember(1, self._vector(0.9), 120.0)
        gallery.observe(2, 300.0)

        hit = gallery.lookup(2, self._vector(0.9))
        assert hit is not None
        assert hit.global_id == 1
        assert hit.score == pytest.approx(1.0)

    def test_toutes_les_vues_deposees_sont_comparees(self) -> None:
        """**Le correctif du multi-vues.** Chaque franchissement dépose sa vue.

        Une galerie à vue unique ne garderait que la plus large — ici `1.0` — et la
        seconde interrogation, portant sur l'autre vue, ne trouverait plus rien
        d'exact. C'est ce qui faisait dépendre le résultat de la chance que les deux
        vues comparées se correspondent.
        """
        gallery = AppearanceGallery()
        gallery.observe(1, 0.0)
        gallery.remember(1, self._vector(1.0), 200.0)
        gallery.remember(1, self._vector(0.0), 100.0)
        gallery.observe(2, 100.0)

        for value in (1.0, 0.0):
            hit = gallery.lookup(2, self._vector(value))
            assert hit is not None
            assert hit.score == pytest.approx(1.0)

    def test_le_plafond_de_vues_sacrifie_la_plus_etroite(self) -> None:
        """Au-delà du plafond, c'est la vue la plus étroite qui cède, jamais la plus large.

        La largeur reste la seule clé de rang évaluable sans payer un recadrage.
        """
        gallery = AppearanceGallery()
        gallery.observe(1, 0.0)
        # Une vue large qui doit survivre, puis le plafond de vues étroites.
        gallery.remember(1, self._vector(1.0), 400.0)
        for index in range(MAX_VIEWS_PER_VEHICLE):
            gallery.remember(1, self._vector(0.5), 100.0 + index)
        gallery.observe(2, 100.0)

        hit = gallery.lookup(2, self._vector(1.0))
        assert hit is not None
        assert hit.score == pytest.approx(1.0)

    def test_une_vue_plus_etroite_que_toutes_est_ignoree(self) -> None:
        """Le plafond étant atteint, une vue sans mérite n'évince personne."""
        gallery = AppearanceGallery()
        gallery.observe(1, 0.0)
        for index in range(MAX_VIEWS_PER_VEHICLE):
            gallery.remember(1, self._vector(1.0), 300.0 + index)
        gallery.remember(1, self._vector(0.0), 50.0)
        gallery.observe(2, 100.0)

        hit = gallery.lookup(2, self._vector(0.0))
        assert hit is not None
        # `cos(0°, 90°)` : la vue étroite n'a pas été retenue, donc rien ne l'égale.
        assert hit.score == pytest.approx(0.0, abs=1e-6)

    def test_le_meilleur_antecedent_gagne(self) -> None:
        gallery = AppearanceGallery()
        for global_id, value in ((1, 0.2), (2, 0.95)):
            gallery.observe(global_id, 0.0)
            gallery.observe(global_id, 100.0)
            gallery.remember(global_id, self._vector(value), 120.0)
        gallery.observe(3, 200.0)

        hit = gallery.lookup(3, self._vector(0.95))
        assert hit is not None
        assert hit.global_id == 2

    def test_une_galerie_vide_ne_rend_rien(self) -> None:
        """`None` et jamais `0.0` : il n'y a pas eu de mesure, pas une mesure nulle."""
        gallery = AppearanceGallery()
        gallery.observe(1, 0.0)

        assert gallery.lookup(1, self._vector(0.9)) is None
