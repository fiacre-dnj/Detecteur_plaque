"""L'aperçu d'une analyse en cours — ce que le serveur publie pendant qu'il compte.

L'aperçu existe pour une seule raison : **valider** une analyse pendant qu'elle
tourne. Un aperçu qui montrerait autre chose que ce que le résultat contiendra
serait pire qu'aucun aperçu — il ferait douter de chiffres justes, ou rassurerait
sur des chiffres faux. Ces tests vérifient donc surtout des égalités entre
l'aperçu et le résultat.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from tests.support.builders import CAR, TRUCK, compose, make_line, straight_line, track_path
from tests.support.engine import FakeEngine
from traffic_analysis.features.counting.application.analysis_service import AnalysisService
from traffic_analysis.features.counting.application.dto import AnalysisJobConfig

if TYPE_CHECKING:
    from pathlib import Path

    from traffic_analysis.features.counting.application.dto import (
        AnalysisResultData,
        PreviewSample,
    )
    from traffic_analysis.features.counting.domain.models import TrackObservation

#: Un intervalle nul publie chaque frame : c'est le seul mode déterministe, donc
#: le seul qu'un test puisse utiliser. Compter les aperçus d'une analyse
#: échantillonnée en temps ferait dépendre le verdict de la vitesse de la machine.
EVERY_FRAME = 0.0

#: Un intervalle plus long que le test lui-même : seul l'aperçu final est publié.
#: Utile pour vérifier ce que porte un aperçu qui « rattrape » tout un segment.
NEVER = 3600.0

CONFIG = AnalysisJobConfig(model_id="yolov8n", lines=(make_line(),))


def _frames(steps: int = 12) -> list[list[TrackObservation]]:
    """Deux véhicules qui franchissent la ligne en sens opposés."""
    return compose(
        track_path(1, CAR, straight_line((700.0, 250.0), (700.0, 800.0), steps=steps)),
        track_path(2, TRUCK, straight_line((1200.0, 800.0), (1200.0, 250.0), steps=steps)),
    )


@pytest.fixture
def video(tmp_path: Path) -> Path:
    path = tmp_path / "clip.mp4"
    path.write_bytes(b"\x00" * 16)
    return path


def _run(
    video: Path,
    *,
    interval: float = EVERY_FRAME,
    steps: int = 12,
    vehicles_interval: float | None = EVERY_FRAME,
) -> tuple[list[PreviewSample], AnalysisResultData]:
    samples: list[PreviewSample] = []
    service = AnalysisService(FakeEngine(_frames(steps)))
    result = service.run_video(
        "job-1",
        video,
        CONFIG,
        on_preview=samples.append,
        preview_interval_s=interval,
        # Comme `preview_interval_s` : la valeur nulle est le seul mode
        # déterministe, donc le seul qu'un test puisse utiliser sans faire dépendre
        # son verdict de la vitesse de la machine.
        preview_vehicles_interval_s=vehicles_interval,
    )
    return samples, result


class TestPublication:
    def test_un_intervalle_nul_publie_chaque_image_plus_l_apercu_final(self, video: Path) -> None:
        samples, result = _run(video)

        assert len(samples) == len(result.timeline) + 1

    def test_un_apercu_final_est_publie_meme_si_l_intervalle_n_est_jamais_atteint(
        self, video: Path
    ) -> None:
        """Sans lui, une analyse courte n'afficherait **jamais** rien.

        Et sur une analyse longue, la dernière image affichée serait celle d'un
        échantillon quelconque, dont les compteurs ne correspondent pas au
        résultat : l'écart se lit comme un bug de comptage.
        """
        samples, _ = _run(video, interval=NEVER)

        assert len(samples) == 1

    def test_sans_callback_le_resultat_est_identique(self, video: Path) -> None:
        """L'aperçu observe l'analyse, il ne la modifie pas."""
        nu = AnalysisService(FakeEngine(_frames())).run_video("job-1", video, CONFIG)
        _, observe = _run(video)

        assert nu.stats is not None
        assert observe.stats is not None
        assert nu.stats.crossings == observe.stats.crossings
        assert nu.stats.tracked_vehicles == observe.stats.tracked_vehicles
        assert len(nu.timeline) == len(observe.timeline)


class TestCeQueLApercuPorte:
    def test_les_evenements_sont_cumules_depuis_l_apercu_precedent(self, video: Path) -> None:
        """Aucun franchissement perdu, aucun compté deux fois.

        C'est la propriété qui rend le journal d'événements crédible : sa somme
        doit être exactement celle du résultat. Ne publier que les événements de
        l'image échantillonnée en perdrait la plupart, alors que les compteurs,
        eux, resteraient justes — un journal en désaccord avec son total est pire
        qu'un journal absent.
        """
        samples, result = _run(video, interval=NEVER)

        cumulated = [crossing for sample in samples for crossing in sample.crossings]
        assert len(cumulated) == len(result.crossings)
        assert [c.global_id for c in cumulated] == [c.global_id for c in result.crossings]

    def test_le_dernier_apercu_annonce_les_memes_chiffres_que_le_resultat(
        self, video: Path
    ) -> None:
        """L'égalité qui valide tout le dispositif.

        Si elle tombe, c'est que l'aperçu observe autre chose que la timeline
        écrite — et l'utilisateur validerait alors une analyse qu'il n'a pas vue.
        """
        samples, result = _run(video)

        final = samples[-1].stats
        assert result.stats is not None
        assert final.crossings == result.stats.crossings
        assert final.tracked_vehicles == result.stats.tracked_vehicles
        assert final.by_line == result.stats.by_line

    def test_les_dimensions_publiees_sont_celles_sondees_par_le_serveur(self, video: Path) -> None:
        """Elles sont le filet contre une géométrie mal ancrée côté client.

        Le serveur ne peut pas savoir ce que la balise `<video>` du navigateur
        rapporte ; il annonce donc ce qu'il a décodé, et le client refuse de
        dessiner en cas de désaccord plutôt que d'afficher des boîtes décalées
        que rien n'expliquerait.
        """
        samples, _ = _run(video)

        assert {(s.frame_width, s.frame_height) for s in samples} == {(1920, 1080)}

    def test_les_pistes_publiees_sont_des_snapshots(self, video: Path) -> None:
        """Sinon toutes les images convergeraient vers l'état final.

        Le même piège que pour la timeline : la référence vivante d'une piste
        continue de bouger après publication, et l'aperçu montrerait la position
        finale du véhicule sur chacune des images précédentes.
        """
        samples, _ = _run(video)

        premiere = next(track for track in samples[0].tracks if track.track_id == 1)
        derniere = next(track for track in samples[-1].tracks if track.track_id == 1)
        assert premiere.box.y != derniere.box.y

    def test_les_compteurs_d_un_apercu_sont_figes_a_l_instant_de_sa_publication(
        self, video: Path
    ) -> None:
        """Un bloc de statistiques est une **photographie**, pas une vue.

        `stats()` recopiait le dictionnaire `by_line` mais pas ses tallies : ceux-ci
        continuaient de grossir dans l'objet déjà rendu, tandis que le scalaire
        `crossings`, lui, restait figé. Un aperçu conservé quelques millisecondes
        avant sérialisation violait donc son propre invariant —
        `crossings == Σ by_line[*].total` — sur des données pourtant justes.
        C'est la fixture du contrat frontend qui l'a révélé.
        """
        samples, _ = _run(video)

        for sample in samples:
            derived = sum(tally.total for tally in sample.stats.by_line.values())
            assert sample.stats.crossings == derived

    def test_le_dernier_apercu_porte_le_meme_registre_que_le_resultat(self, video: Path) -> None:
        """L'égalité qui rend le tableau des véhicules affichable **pendant** l'analyse.

        Le registre publié par l'aperçu est celui du résultat, aux véhicules sans
        franchissement près — que l'écran n'affiche pas (ADR 0023). S'il s'en
        écartait, le tableau changerait sous les yeux de l'utilisateur à la seconde
        où l'analyse se termine, et l'écart se lirait comme un bug de comptage.
        """
        samples, result = _run(video)

        published = samples[-1].vehicles
        assert published is not None
        expected = tuple(record for record in result.vehicles if record.crossed_lines)
        assert published == expected
        # La restriction est réelle sur cette scène : les deux véhicules franchissent,
        # donc l'égalité ci-dessus ne serait pas une tautologie si elle échouait.
        assert [record.global_id for record in published] == [1, 2]

    def test_un_intervalle_de_registre_jamais_atteint_ne_publie_que_le_final(
        self, video: Path
    ) -> None:
        """`None` veut dire « inchangé », et l'aperçu final fait exception.

        Deux propriétés en une, parce qu'elles se tiennent : le registre n'est pas
        republié à la cadence des boîtes — il grossit avec l'analyse — mais la
        dernière liste affichée doit être exacte, sinon elle reste en retard de
        quelques véhicules sur les compteurs posés juste à côté.

        `None` **n'est pas** une liste vide : celle-là dirait « aucun véhicule n'a
        franchi de ligne », que le client afficherait comme telle au lieu de garder
        ce qu'il sait déjà.
        """
        samples, _ = _run(video, vehicles_interval=NEVER)

        # Le premier le porte : sinon l'écran resterait vide pendant tout
        # l'intervalle, au moment précis où l'on regarde si quelque chose se passe.
        assert samples[0].vehicles is not None
        assert samples[-1].vehicles is not None
        assert all(sample.vehicles is None for sample in samples[1:-1])

    def test_un_registre_desactive_n_enleve_pas_l_apercu(self, video: Path) -> None:
        """Les deux réglages sont indépendants.

        Couper le registre allège le flux sans toucher aux boîtes : confondre les
        deux ferait disparaître le canvas en croyant n'alléger que le tableau.

        `None` désactive, `0.0` publie à chaque aperçu — la même convention que
        `preview_interval_s`, où le zéro publie aussi chaque image. Deux paramètres
        voisins où le zéro voudrait dire deux choses opposées seraient un piège.
        """
        samples, _ = _run(video, vehicles_interval=None)

        assert len(samples) > 1
        assert all(sample.tracks != () for sample in samples[:-1])
        # L'aperçu final garde son registre même ici, sinon la fin d'analyse
        # afficherait un tableau vide sous des compteurs remplis.
        assert samples[-1].vehicles is not None
        assert all(sample.vehicles is None for sample in samples[:-1])

    def test_l_horodatage_est_du_temps_de_scene(self, video: Path) -> None:
        """`frame_index / fps`, jamais l'horloge murale (invariant 1).

        C'est ce qui permet au navigateur de caler la vidéo locale sur l'image
        analysée : un temps mural n'y correspondrait à rien.
        """
        samples, _ = _run(video)

        # 25 images par seconde dans le moteur factice : une image toutes les 40 ms.
        assert samples[0].timestamp_ms == 0.0
        assert samples[1].timestamp_ms == pytest.approx(40.0)
        # L'aperçu final rejoue la dernière image analysée, il n'en invente pas une.
        assert samples[-1].frame_index == samples[-2].frame_index
