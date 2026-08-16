"""Le bridage de l'analyse sur le temps de la scène.

Il existe pour une raison d'affichage, pas de comptage : l'aperçu live cale la
vidéo du client sur le temps de scène analysé, donc un serveur plus rapide que la
scène produit un aperçu accéléré du même facteur. Ces tests vérifient donc deux
choses de nature différente — que l'attente a bien lieu, et qu'elle **ne change
aucun chiffre**.

Aucune assertion ne borne l'attente par un nombre d'itérations ni ne suppose une
machine rapide : les seules bornes temporelles sont des **minorants** sur du temps
déjà dormi, qu'une machine lente ne peut que dépasser.
"""

from __future__ import annotations

from time import perf_counter
from typing import TYPE_CHECKING

import pytest

from tests.support.builders import CAR, TRUCK, compose, make_line, straight_line, track_path
from tests.support.engine import FakeEngine
from traffic_analysis.features.counting.application.analysis_service import AnalysisService
from traffic_analysis.features.counting.application.dto import (
    AnalysisCancelled,
    AnalysisJobConfig,
)
from traffic_analysis.features.counting.domain.models import VideoInfo
from traffic_analysis.features.counting.domain.pacing import ScenePacer

if TYPE_CHECKING:
    from pathlib import Path

    from traffic_analysis.features.counting.application.dto import PreviewSample
    from traffic_analysis.features.counting.domain.models import TrackObservation

#: Une cadence de source élevée rend la période courte, donc le test rapide, sans
#: rien changer à l'arithmétique : ce qui est cadencé est le temps de scène.
FAST_FPS = 200.0
STEPS = 20
#: Temps de scène couvert par le clip de test, à `FAST_FPS`.
SCENE_S = STEPS / FAST_FPS

#: Un intervalle plus long que le test : seul l'aperçu final est publié.
NEVER = 3600.0


def _frames() -> list[list[TrackObservation]]:
    """Deux véhicules qui franchissent la ligne en sens opposés."""
    return compose(
        track_path(1, CAR, straight_line((700.0, 250.0), (700.0, 800.0), steps=STEPS)),
        track_path(2, TRUCK, straight_line((1200.0, 800.0), (1200.0, 250.0), steps=STEPS)),
    )


def _engine(*, fps: float = FAST_FPS) -> FakeEngine:
    frames = _frames()
    return FakeEngine(
        frames,
        info=VideoInfo(width=1920, height=1080, fps=fps, frame_count=len(frames)),
    )


def _config(
    speed: float | None, *, frame_stride: int = 1, max_fps: float | None = None
) -> AnalysisJobConfig:
    return AnalysisJobConfig(
        model_id="yolov8n",
        lines=(make_line(),),
        analysis_speed=speed,
        frame_stride=frame_stride,
        max_analysis_fps=max_fps,
    )


@pytest.fixture
def video(tmp_path: Path) -> Path:
    path = tmp_path / "clip.mp4"
    path.write_bytes(b"\x00" * 16)
    return path


class TestScenePacer:
    """Le cadenceur seul — pur, donc testable sans vidéo ni horloge."""

    def test_sans_cadence_demandee_il_n_y_a_pas_de_cadenceur(self) -> None:
        assert ScenePacer.for_video(25.0, 1, None) is None

    def test_une_source_sans_cadence_ne_peut_pas_etre_bridee(self) -> None:
        """`fps = 0` ne dit pas ce que « temps réel » voudrait dire pour elle.

        Rendre `None` plutôt que lever : une cadence inconnue n'empêche pas de
        compter, et un conteneur mal formé n'est pas une erreur de l'utilisateur.
        """
        assert ScenePacer.for_video(0.0, 1, 1.0) is None

    def test_la_periode_est_le_temps_de_scene_d_une_image(self) -> None:
        pacer = ScenePacer.for_video(25.0, 1, 1.0)
        assert pacer is not None
        assert pacer.period_s == pytest.approx(0.04)

    def test_le_pas_d_analyse_allonge_la_periode(self) -> None:
        """Une image analysée sur trois fait avancer la scène de trois images.

        Cadencer sur le nombre d'images analysées brimerait l'analyse au tiers de
        la vitesse demandée.
        """
        pacer = ScenePacer.for_video(25.0, 3, 1.0)
        assert pacer is not None
        assert pacer.period_s == pytest.approx(0.12)

    def test_la_cadence_divise_la_periode(self) -> None:
        pacer = ScenePacer.for_video(25.0, 1, 2.0)
        assert pacer is not None
        assert pacer.period_s == pytest.approx(0.02)

    def test_la_premiere_image_est_deja_cadencee(self) -> None:
        """Sinon les deux premières images partiraient à la suite, sans attendre."""
        pacer = ScenePacer(period_s=0.04)
        assert pacer.wait_s(0.005) == pytest.approx(0.035)

    def test_l_attente_comble_exactement_le_retard(self) -> None:
        pacer = ScenePacer(period_s=0.04)
        assert pacer.wait_s(0.0) == pytest.approx(0.04)
        # L'attente a été honorée : on est à l'échéance.
        assert pacer.wait_s(0.04) == pytest.approx(0.04)
        assert pacer.wait_s(0.08) == pytest.approx(0.04)

    def test_l_attente_n_est_jamais_negative(self) -> None:
        pacer = ScenePacer(period_s=0.04)
        assert pacer.wait_s(10.0) == 0.0


class TestPlafondAbsolu:
    """`max_fps` — un débit, pas une vitesse relative à la scène.

    Indépendant de `speed` : il ne connaît ni la cadence de la source ni
    `frame_stride`, seulement le nombre d'images analysées par seconde réelle.
    """

    def test_un_plafond_seul_bride_sans_connaitre_la_source(self) -> None:
        # `fps = 0.0` — une source qui ne déclare pas sa cadence — n'empêche pas
        # le plafond absolu, contrairement à `speed`.
        pacer = ScenePacer.for_video(0.0, 1, None, 30.0)
        assert pacer is not None
        assert pacer.period_s == pytest.approx(1.0 / 30.0)

    def test_le_plafond_ignore_le_pas_d_analyse(self) -> None:
        """Il compte des images analysées, pas du temps de scène couvert."""
        pacer = ScenePacer.for_video(25.0, 3, None, 30.0)
        assert pacer is not None
        assert pacer.period_s == pytest.approx(1.0 / 30.0)

    def test_le_plus_restrictif_des_deux_bridages_l_emporte(self) -> None:
        # Cadence relative : 1× à 25 fps → période 0,04 s (25 img/s).
        # Plafond absolu à 60 img/s → période plus courte (0,0167 s) : ne
        # contraint rien de plus que la cadence relative.
        pacer = ScenePacer.for_video(25.0, 1, 1.0, 60.0)
        assert pacer is not None
        assert pacer.period_s == pytest.approx(0.04)

        # Plafond absolu à 10 img/s → période plus longue (0,1 s) : c'est lui qui
        # gagne, même si la cadence relative demandait 25 img/s.
        pacer = ScenePacer.for_video(25.0, 1, 1.0, 10.0)
        assert pacer is not None
        assert pacer.period_s == pytest.approx(0.1)

    def test_aucun_des_deux_ne_bride(self) -> None:
        assert ScenePacer.for_video(25.0, 1, None, None) is None


#: Une période de 40 ms — 25 images par seconde bridées à 1×.
PERIOD = 0.04


def _simulate(costs: list[float], period: float = PERIOD) -> float:
    """Rejoue la boucle d'analyse et rend le temps total écoulé.

    L'arithmétique de la vraie boucle, sans dormir : chaque image coûte son temps de
    travail, puis l'attente que le cadenceur réclame. C'est ce qui permet de tester
    la propriété qui compte — **la durée totale** — sans faire dépendre le verdict de
    la vitesse de la machine.
    """
    pacer = ScenePacer(period_s=period)
    elapsed = 0.0
    for cost in costs:
        elapsed += cost
        elapsed += pacer.wait_s(elapsed)
    return elapsed


class TestDureeTotale:
    """La propriété que le bridage promet : la durée, pas l'attente image par image.

    Ces tests sont écrits contre un bug réel. La première version du cadenceur
    n'autorisait aucun rattrapage, et un bridage à 1× rendait **0,82×** : mesuré
    contre le vrai serveur, 240 images dont 60 dépassaient leur période, et chaque
    dépassement repoussait définitivement l'échéance.
    """

    def test_des_images_bon_marche_donnent_exactement_le_temps_de_la_scene(self) -> None:
        elapsed = _simulate([0.005] * 100)

        assert elapsed == pytest.approx(100 * PERIOD)

    def test_des_pointes_de_cout_ne_derivent_pas(self) -> None:
        """Une image sur cinq coûte une période et demie : la durée ne bouge pas.

        C'est le test du bug mesuré. Sans rattrapage, ces vingt pointes ajoutaient
        chacune leur dépassement à la durée totale.
        """
        costs = [0.06 if index % 5 == 0 else 0.005 for index in range(100)]

        elapsed = _simulate(costs)

        assert elapsed == pytest.approx(100 * PERIOD, rel=0.01)

    def test_un_decrochage_franc_n_est_pas_rattrape(self) -> None:
        """L'autre bord : le temps perdu par un vrai décrochage est perdu.

        Le rattraper demanderait une rafale d'images sans attente, donc une
        accélération visible de l'aperçu — exactement ce que le bridage corrige. La
        seconde perdue se retrouve donc dans la durée totale, et c'est voulu.
        """
        costs = [0.005] * 100
        costs[50] = 1.0

        elapsed = _simulate(costs)

        assert elapsed == pytest.approx(100 * PERIOD + 1.0 - PERIOD, rel=0.02)

    def test_une_machine_plus_lente_que_la_scene_n_attend_jamais(self) -> None:
        """Le bridage ne peut pas accélérer : il ne sait que ralentir.

        Sur un CPU à 10 images par seconde, un bridage à 1× sur une source à 25 fps
        n'ajoute rien — et surtout n'accumule aucune dette qui produirait une rafale.
        """
        costs = [0.1] * 50

        elapsed = _simulate(costs)

        assert elapsed == pytest.approx(sum(costs))


class TestBridageDeLAnalyse:
    def test_une_analyse_bridee_dure_au_moins_le_temps_de_la_scene(self, video: Path) -> None:
        """Le minorant, seule borne temporelle honnête : on ne mesure que du sommeil.

        Une machine lente ne peut que dépasser ce seuil ; une machine rapide ne peut
        pas descendre en dessous, puisque `sleep` ne rend jamais la main en avance.
        """
        service = AnalysisService(_engine())
        started = perf_counter()
        service.run_video("job-1", video, _config(1.0))
        elapsed = perf_counter() - started

        # Une période de tolérance : la dernière image est suivie d'une attente, mais
        # la première ne l'est pas précédée.
        assert elapsed >= SCENE_S - 1.0 / FAST_FPS

    def test_un_plafond_absolu_bride_meme_sans_cadence_relative(self, video: Path) -> None:
        """`max_analysis_fps` seul bride, sans passer par `analysis_speed`."""
        max_fps = 50.0
        period = 1.0 / max_fps
        service = AnalysisService(_engine())
        started = perf_counter()
        service.run_video("job-1", video, _config(None, max_fps=max_fps))
        elapsed = perf_counter() - started

        assert elapsed >= (STEPS - 1) * period

    def test_une_cadence_double_bride_deux_fois_moins(self, video: Path) -> None:
        service = AnalysisService(_engine())
        started = perf_counter()
        service.run_video("job-1", video, _config(2.0))
        elapsed = perf_counter() - started

        assert elapsed >= SCENE_S / 2 - 1.0 / FAST_FPS

    def test_le_bridage_ne_change_aucun_chiffre(self, video: Path) -> None:
        """L'invariant qui compte : brider est un réglage d'affichage.

        Deux analyses du même clip, l'une bridée, l'autre pas, doivent rendre les
        mêmes compteurs — sinon le réglage cesserait d'être gratuit et deviendrait
        un paramètre de comptage.
        """
        libre = AnalysisService(_engine()).run_video("job-1", video, _config(None))
        bridee = AnalysisService(_engine()).run_video("job-2", video, _config(1.0))

        assert bridee.stats.tracked_vehicles == libre.stats.tracked_vehicles
        assert bridee.stats.crossings == libre.stats.crossings
        assert len(bridee.timeline) == len(libre.timeline)
        assert [row.timestamp_ms for row in bridee.timeline] == [
            row.timestamp_ms for row in libre.timeline
        ]

    # Pas de test de bout en bout du cas « cadence inconnue » : `probe()` de
    # l'adaptateur réel retombe sur `DEFAULT_FPS` dès que la cadence est nulle ou
    # aberrante, donc `VideoInfo.fps == 0` n'atteint jamais `run_video` en
    # production. Le garde de `for_video` reste vérifié unitairement ci-dessus, et
    # il reste utile : `VideoInfo` autorise cette valeur, et `duration_ms` s'en
    # protège de la même façon.

    def test_l_annulation_est_prise_en_compte_pendant_le_bridage(self, video: Path) -> None:
        """Une analyse bridée reste interruptible : l'attente est en fin d'itération.

        Le compte est en images analysées, jamais en tours d'attente : c'est la
        cadence de la scène qui est bridée, et le verdict ne doit pas dépendre de la
        vitesse de la machine.
        """
        seen = 0

        def is_cancelled() -> bool:
            nonlocal seen
            seen += 1
            return seen > 3

        service = AnalysisService(_engine())
        with pytest.raises(AnalysisCancelled):
            service.run_video("job-1", video, _config(1.0), is_cancelled=is_cancelled)


class TestIntervalleDApercu:
    """Le bridage resserre l'aperçu, sans jamais l'élargir."""

    def _run(self, video: Path, *, paced_interval: float) -> list[PreviewSample]:
        samples: list[PreviewSample] = []
        AnalysisService(_engine()).run_video(
            "job-1",
            video,
            _config(1.0),
            on_preview=samples.append,
            preview_interval_s=NEVER,
            paced_preview_interval_s=paced_interval,
        )
        return samples

    def test_une_analyse_bridee_resserre_son_apercu(self, video: Path) -> None:
        """Minorant, comme les mesures de durée : une machine lente en publie plus.

        L'analyse dort au moins `SCENE_S`, donc un aperçu toutes les 5 ms en publie
        au moins une vingtaine ; le seuil est volontairement bas.
        """
        samples = self._run(video, paced_interval=0.005)

        assert len(samples) >= 5

    def test_un_intervalle_bride_nul_ne_resserre_rien(self, video: Path) -> None:
        """Zéro signifie « ne pas resserrer », **pas** « publier chaque image ».

        Un déploiement qui met ce champ à zéro ne doit pas se retrouver avec des
        dizaines de trames par seconde sur le flux : seul `preview_interval_ms`
        décide de l'existence de l'aperçu.
        """
        samples = self._run(video, paced_interval=0.0)

        # Le seul aperçu publié est l'aperçu final, obligatoire.
        assert len(samples) == 1
