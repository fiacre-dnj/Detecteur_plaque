"""La fenêtre d'analyse — analyser un morceau de la vidéo, et lui seul.

Trois propriétés portent tout le reste, et chacune correspond à une façon dont
cette fonctionnalité pouvait mentir sans lever :

1. **les horodatages restent absolus.** Une analyse lancée à 00:34 date son
   premier franchissement à 00:34, jamais à 00:00. Sans cela, la vidéo locale ne
   pourrait pas se caler sur l'aperçu, et deux analyses de fenêtres différentes ne
   seraient pas comparables ;
2. **la borne de fin est exclue.** Deux fenêtres adjacentes ne partagent aucune
   image, donc ne comptent pas deux fois ce qui se passe à leur jointure ;
3. **la progression compte les images de la fenêtre.** Sans cela, une analyse
   bornée à un dixième d'un fichier s'arrêterait à 10 % en annonçant « terminé »,
   ce qui se lit comme une analyse tronquée par une panne.

Ces tests passent par le `FakeEngine`, qui **ignore** `EngineSpec.start_ms` : c'est
volontaire, et c'est ce qui prouve que la fenêtre est tranchée par l'application et
non par l'adaptateur. Un moteur qui honore le déplacement ne fait qu'aller plus
vite ; s'il changeait un chiffre, la fenêtre serait devenue une divergence que la
CI ne traverse jamais.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from tests.support.builders import CAR, compose, make_line, straight_line, track_path
from tests.support.engine import FakeEngine
from traffic_analysis.core.errors import ValidationAppError
from traffic_analysis.features.counting.application.analysis_service import AnalysisService
from traffic_analysis.features.counting.application.dto import AnalysisJobConfig, Progress
from traffic_analysis.features.counting.domain.models import VideoInfo

if TYPE_CHECKING:
    from pathlib import Path

    from traffic_analysis.features.counting.application.dto import AnalysisResultData
    from traffic_analysis.features.counting.domain.models import TrackObservation

#: 25 images par seconde : une image dure exactement 40 ms, donc les bornes des
#: tests tombent sur des frontières d'image sans arrondi à discuter.
FPS = 25.0
FRAME_MS = 1000.0 / FPS

#: Vingt images, soit 800 ms de scène, aux horodatages 0, 40, …, 760.
STEPS = 20


def _frames() -> list[list[TrackObservation]]:
    """Une voiture qui descend et franchit la ligne au milieu du parcours."""
    return compose(track_path(1, CAR, straight_line((700.0, 250.0), (700.0, 800.0), steps=STEPS)))


def _engine() -> FakeEngine:
    return FakeEngine(
        _frames(),
        info=VideoInfo(width=1920, height=1080, fps=FPS, frame_count=STEPS),
    )


@pytest.fixture
def video(tmp_path: Path) -> Path:
    path = tmp_path / "clip.mp4"
    path.write_bytes(b"\x00" * 16)
    return path


def _run(
    video: Path,
    *,
    start_ms: float = 0.0,
    end_ms: float | None = None,
    frame_stride: int = 1,
) -> tuple[AnalysisResultData, list[Progress]]:
    progress: list[Progress] = []
    service = AnalysisService(_engine())
    config = AnalysisJobConfig(
        model_id="yolov8n",
        lines=(make_line(),),
        start_ms=start_ms,
        end_ms=end_ms,
        frame_stride=frame_stride,
        # Le comptage doit voir naître la piste dans la fenêtre : `1` évite qu'un
        # test parle d'une confirmation quand il veut parler d'une borne.
        min_hits=1,
    )
    return service.run_video("job-1", video, config, on_progress=progress.append), progress


def test_sans_fenetre_toutes_les_images_sont_analysees(video: Path) -> None:
    """Le cas de référence : les défauts ne changent rien au comportement d'avant."""
    result, _ = _run(video)
    assert len(result.timeline) == STEPS
    assert result.timeline[0].frame_index == 0


def test_un_debut_saute_les_images_qui_le_precedent(video: Path) -> None:
    """Cinq images sautées, quinze analysées — et la première est bien la sixième."""
    result, _ = _run(video, start_ms=5 * FRAME_MS)
    assert len(result.timeline) == STEPS - 5
    assert result.timeline[0].frame_index == 5


def test_les_horodatages_restent_absolus(video: Path) -> None:
    """**La propriété 1**, celle qui casserait l'aperçu sans rien lever.

    Un décalage à zéro paraîtrait même plus « logique » à la lecture du code. Il
    ferait pourtant sauter la vidéo locale au mauvais endroit pendant toute
    l'analyse, et daterait les franchissements d'un temps qui n'existe nulle part
    ailleurs — ni dans le fichier, ni dans une autre analyse du même clip.
    """
    result, _ = _run(video, start_ms=5 * FRAME_MS)
    assert result.timeline[0].timestamp_ms == pytest.approx(5 * FRAME_MS)
    assert all(row.timestamp_ms >= 5 * FRAME_MS for row in result.timeline)


def test_la_borne_de_fin_est_exclue(video: Path) -> None:
    """**La propriété 2.** L'image qui tombe pile sur la fin n'est pas analysée."""
    result, _ = _run(video, end_ms=10 * FRAME_MS)
    assert len(result.timeline) == 10
    assert result.timeline[-1].frame_index == 9


def test_deux_fenetres_adjacentes_se_partagent_exactement_la_video(video: Path) -> None:
    """Le corollaire qui donne son sens à l'exclusion de la borne.

    `[0 ; 400[` puis `[400 ; fin[` doivent couvrir toutes les images, chacune une
    seule fois. Avec une borne incluse, l'image de 400 ms tomberait dans les deux
    fenêtres — et un véhicule qui franchit à cet instant serait compté deux fois
    par qui découpe une longue vidéo en tranches.
    """
    premiere, _ = _run(video, end_ms=400.0)
    seconde, _ = _run(video, start_ms=400.0)

    indices = [row.frame_index for row in premiere.timeline]
    indices += [row.frame_index for row in seconde.timeline]
    assert indices == list(range(STEPS))


def test_la_fenetre_s_aligne_sur_le_pas_d_analyse(video: Path) -> None:
    """Avec un pas de 3, seules les images d'index multiple de 3 existent.

    La fenêtre ne doit donc pas les décaler : elle retient celles qui tombent
    dedans, elle n'en fabrique aucune. C'est la même règle que suit
    `_first_analysed_index` côté adaptateur pour choisir où se déplacer, et les
    deux doivent rester d'accord — sinon l'adaptateur sauterait une image que
    l'application aurait gardée, ou l'inverse.
    """
    result, _ = _run(video, start_ms=4 * FRAME_MS, frame_stride=3)
    # Multiples de 3 dont l'horodatage atteint 160 ms : 6, 9, 12, 15, 18.
    assert [row.frame_index for row in result.timeline] == [6, 9, 12, 15, 18]


def test_la_progression_compte_les_images_de_la_fenetre(video: Path) -> None:
    """**La propriété 3.** La barre atteint 100 %, pas 50 %."""
    result, progress = _run(video, start_ms=10 * FRAME_MS)
    final = progress[-1]
    assert final.processed_frames == len(result.timeline) == 10
    assert final.total_frames == 10
    assert final.ratio == 1.0


def test_une_fenetre_hors_de_la_video_est_refusee_avant_d_analyser(video: Path) -> None:
    """Refusée, et non rendue en compteurs à zéro.

    C'est le seul contrôle de fenêtre qui ne peut pas vivre dans le schéma de
    requête : lui ne connaît pas la durée du fichier. Un job « terminé » et vide
    serait indiscernable d'une panne de détection, et enverrait chercher le défaut
    dans la vidéo ou le modèle.
    """
    with pytest.raises(ValidationAppError) as raised:
        _run(video, start_ms=60_000.0)
    assert raised.value.code == "empty_analysis_range"
    # Le message donne la durée réelle : sans elle, l'utilisateur ne sait pas de
    # combien il s'est trompé.
    assert "0.8 s" in raised.value.detail
