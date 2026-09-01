"""Les règles de ligne décrivent, elles ne comptent pas.

**Le test qui protège la doctrine.** Depuis ADR 0016, un rôle de sens voyage de la
requête au `config_json` et revient, sans qu'aucun compteur le lise : c'est ce qui
permet de corriger un libellé après coup sans réanalyser. « Interdit », « Passage »
et les classes autorisées d'une voie réservée rejoignent cette famille — et ce
fichier vérifie qu'ils n'en sortent jamais.

Le mode de panne évité est **silencieux et grave** : si le domaine venait un jour à
lire ces champs pour écarter un franchissement, l'invariant 3
(`crossings == Σ by_line[*].total`) tomberait sans qu'aucune exception ne soit levée,
et deux analyses de la même vidéo rendraient des chiffres différents selon les mots
que l'utilisateur a choisis.

Une infraction est un **passage qualifié**, jamais un passage retiré.
"""

from __future__ import annotations

from dataclasses import replace
from typing import TYPE_CHECKING

import pytest

from tests.support.builders import CAR, TRUCK, compose, make_line, straight_line, track_path
from tests.support.engine import FakeEngine
from traffic_analysis.features.counting.application.analysis_service import AnalysisService
from traffic_analysis.features.counting.application.dto import AnalysisJobConfig

if TYPE_CHECKING:
    from pathlib import Path

    from traffic_analysis.features.counting.application.dto import AnalysisResultData
    from traffic_analysis.features.counting.domain.models import TrackObservation

#: La même ligne, décrite de quatre façons. Seuls les mots changent.
ORDINAIRE = make_line()
SENS_UNIQUE = replace(ORDINAIRE, positive_role="entry", negative_role="forbidden")
INFRANCHISSABLE = replace(ORDINAIRE, positive_role="forbidden", negative_role="forbidden")
VOIE_RESERVEE = replace(
    ORDINAIRE, positive_role="entry", negative_role="exit", allowed_class_ids=(5,)
)
COMPTAGE_SEUL = replace(ORDINAIRE, positive_role="transit", negative_role="transit")


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


def _run(video: Path, line: object) -> AnalysisResultData:
    service = AnalysisService(FakeEngine(_frames()))
    config = AnalysisJobConfig(model_id="yolov8n", lines=(line,))  # type: ignore[arg-type]
    return service.run_video("job-1", video, config)


def _figures(result: AnalysisResultData) -> dict[str, object]:
    """Tout ce qu'un mot ne doit **jamais** changer."""
    stats = result.stats
    assert stats is not None
    tally = stats.by_line["l1"]
    return {
        "crossings": stats.crossings,
        "tracked_vehicles": stats.tracked_vehicles,
        "crossed_unique": stats.crossed_unique,
        "by_class": dict(stats.by_class),
        "positive": tally.positive.total,
        "negative": tally.negative.total,
        "instants": [event.timestamp_ms for event in result.crossings],
    }


class TestUnMotNeChangePasUnChiffre:
    @pytest.mark.parametrize(
        "line",
        [SENS_UNIQUE, INFRANCHISSABLE, VOIE_RESERVEE, COMPTAGE_SEUL],
        ids=["sens-unique", "infranchissable", "voie-reservee", "comptage-seul"],
    )
    def test_aucune_regle_ne_change_les_totaux(self, video: Path, line: object) -> None:
        """Les quatre descriptions rendent **exactement** les mêmes chiffres.

        Y compris les horodatages : une règle ne déplace pas non plus un
        franchissement dans le temps.
        """
        assert _figures(_run(video, line)) == _figures(_run(video, ORDINAIRE))

    def test_un_franchissement_interdit_reste_compte(self, video: Path) -> None:
        """L'invariant 3 en dépend, et c'est ce qui rend l'infraction dérivable.

        Le sens négatif est marqué « Interdit » : son franchissement doit rester dans
        `by_line`, sinon l'interface ne pourrait pas le qualifier — elle ne compte
        rien elle-même, elle relit ce que le serveur publie.
        """
        result = _run(video, SENS_UNIQUE)
        stats = result.stats
        assert stats is not None

        assert stats.by_line["l1"].negative.total == 1
        assert stats.crossings == sum(tally.total for tally in stats.by_line.values())

    def test_une_classe_non_autorisee_est_comptee_comme_les_autres(self, video: Path) -> None:
        """La voie réservée n'autorise que le bus ; le camion et la voiture passent.

        Les deux sont comptés : c'est l'interface qui les qualifie d'infraction, à
        partir de `by_class` que le serveur publie par sens.
        """
        result = _run(video, VOIE_RESERVEE)
        stats = result.stats
        assert stats is not None

        assert stats.by_line["l1"].positive.by_class == {"car": 1}
        assert stats.by_line["l1"].negative.by_class == {"truck": 1}
