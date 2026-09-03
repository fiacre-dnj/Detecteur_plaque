"""Le diagnostic sait enfin dire « ce type n'a jamais été détecté » — ADR 0059.

Deux défauts distincts du panneau « Comptage », et le second est le plus trompeur :

1. **tout était global.** Six chiffres qui additionnent toutes les classes ne peuvent
   pas distinguer « 3 000 voitures détectées et zéro moto » de « tout va bien ». Or
   c'est exactement la question qu'on pose en ouvrant ce panneau ;
2. **« Pistes provisoires » est un instantané au milieu de cumuls.** Il compte les
   pistes vivantes à la dernière image, c'est-à-dire les ~2,5 dernières secondes — donc
   il vaut `0` alors même que douze motos viennent d'être abandonnées. Son aide
   promettait pourtant « baisser Images avant comptage les compterait ».

Le compteur qui répond existait déjà, sans consommateur : `TrackNumbering.issued − size`.
"""

from __future__ import annotations

from tests.support.builders import CAR, MOTORCYCLE, PERSON, make_line, track_path
from traffic_analysis.features.counting.domain.models import BoundingBox, TrackObservation
from traffic_analysis.features.counting.domain.tracking_session import (
    AnalysisSession,
    SessionConfig,
)

FRAME_WIDTH = 1920
FRAME_HEIGHT = 1080
FRAME_MS = 40.0

CLASS_LABELS = {PERSON: "person", CAR: "car", MOTORCYCLE: "motorcycle"}


def _session(**overrides: object) -> AnalysisSession:
    config = SessionConfig(
        lines=(make_line("l1", a=(960.0, 0.0), b=(960.0, 1080.0)),),
        min_hits=2,
        confidence_threshold=0.35,
        **overrides,  # type: ignore[arg-type]
    )
    return AnalysisSession(config, FRAME_WIDTH, FRAME_HEIGHT)


def _observation(track_id: int, class_id: int, score: float, x: float) -> TrackObservation:
    return TrackObservation(
        track_id=track_id,
        class_id=class_id,
        label=CLASS_LABELS[class_id],
        score=score,
        box=BoundingBox(x, 500.0, 60.0, 60.0),
    )


class TestVentilationParClasse:
    def test_une_classe_cochee_et_jamais_vue_porte_une_rangee_a_zero(self) -> None:
        """**L'absence est l'information.** Omettre la clé se lirait « pas mesuré »."""
        session = _session(class_ids=(CAR, MOTORCYCLE, PERSON))
        session.feed(0, 0.0, [_observation(1, CAR, 0.90, 100.0)])

        by_class = session.stats().diagnostics.by_class

        assert set(by_class) == {"car", "motorcycle", "person"}
        assert by_class["motorcycle"].high_detections == 0
        assert by_class["motorcycle"].rescued_by_low_score == 0
        assert by_class["car"].high_detections == 1

    def test_les_classes_non_cochees_n_apparaissent_pas(self) -> None:
        """Une rangée pour une classe jamais cherchée serait le mensonge symétrique."""
        session = _session(class_ids=(CAR,))
        session.feed(0, 0.0, [_observation(1, CAR, 0.90, 100.0)])

        assert set(session.stats().diagnostics.by_class) == {"car"}

    def test_le_detail_somme_exactement_aux_deux_totaux(self) -> None:
        """L'égalité, et pas les valeurs : c'est elle qui empêche deux compteurs de
        diverger et d'afficher deux vérités sur le même écran (invariant 3)."""
        session = _session(class_ids=(CAR, MOTORCYCLE))
        session.feed(
            0,
            0.0,
            [
                _observation(1, CAR, 0.90, 100.0),
                _observation(2, CAR, 0.20, 300.0),
                _observation(3, MOTORCYCLE, 0.80, 500.0),
                _observation(4, MOTORCYCLE, 0.10, 700.0),
            ],
        )

        diagnostics = session.stats().diagnostics
        rows = diagnostics.by_class.values()
        assert sum(row.high_detections for row in rows) == diagnostics.high_detections
        assert sum(row.rescued_by_low_score for row in rows) == diagnostics.rescued_by_low_score

    def test_la_bande_basse_est_rangee_sous_sa_propre_classe(self) -> None:
        session = _session(class_ids=(CAR, MOTORCYCLE))
        session.feed(0, 0.0, [_observation(1, MOTORCYCLE, 0.20, 100.0)])

        by_class = session.stats().diagnostics.by_class
        assert by_class["motorcycle"].high_detections == 0
        assert by_class["motorcycle"].rescued_by_low_score == 1
        assert by_class["car"].rescued_by_low_score == 0


#: Motos scintillantes, une image chacune.
FLICKERS = 12

#: Images « calmes » ensuite. `max_lost_ms` vaut 2 500 ms et une image dure 40 ms :
#: il en faut plus de 63 pour que le dernier scintillement soit **relâché**, c'est-à-dire
#: pour que l'instantané ait fini de le voir. C'est tout le sujet de ce bloc.
QUIET_FRAMES = 80


def _run_flickers(session: AnalysisSession) -> None:
    """Une voiture continue, douze motos vues une image chacune, puis le silence."""
    for index in range(FLICKERS):
        voiture = _observation(1, CAR, 0.90, 100.0 + index * 5)
        scintillement = _observation(100 + index, MOTORCYCLE, 0.60, 400.0 + index * 5)
        session.feed(index, index * FRAME_MS, [voiture, scintillement])
    for offset in range(QUIET_FRAMES):
        index = FLICKERS + offset
        session.feed(index, index * FRAME_MS, [_observation(1, CAR, 0.90, 160.0 + offset * 5)])


class TestPistesJamaisConfirmees:
    def test_douze_scintillements_sont_comptes_alors_que_l_instantane_dit_zero(self) -> None:
        """**Le cas mesuré qui a motivé le champ.**

        Douze motos vues une image chacune, au-dessus du seuil : chacune est
        numérotée, suivie, et abandonnée avant `min_hits`. Au moment où l'on lit le
        panneau elles ont quitté `self._tracks` depuis longtemps, donc « Pistes
        provisoires » vaut `0` — sous une aide qui promet de les compter.
        """
        session = _session(class_ids=(CAR, MOTORCYCLE))
        _run_flickers(session)

        diagnostics = session.stats().diagnostics
        assert diagnostics.tentative_tracks == 0
        assert diagnostics.unconfirmed_tracks == FLICKERS

    def test_la_ventilation_montre_les_motos_que_le_total_cache(self) -> None:
        """Les deux correctifs se répondent : le cumul dit « douze abandonnées », la
        ventilation dit **de quel type**. Séparément, aucun des deux ne suffit."""
        session = _session(class_ids=(CAR, MOTORCYCLE))
        _run_flickers(session)

        stats = session.stats()
        assert stats.tracked_by_class == {"car": 1}
        assert stats.diagnostics.by_class["motorcycle"].high_detections == FLICKERS

    def test_l_egalite_qui_empeche_le_chiffre_de_deriver(self) -> None:
        """`unconfirmed_tracks + tracked_vehicles == issued`, par construction.

        C'est un **dérivé** d'un état déjà tenu et jamais un second compteur : cette
        égalité est ce qui le garantit. Sans elle, le nouveau chiffre finirait par
        contredire le registre (invariant 3).
        """
        session = _session(class_ids=(CAR, MOTORCYCLE))
        _run_flickers(session)

        stats = session.stats()
        assert stats.diagnostics.unconfirmed_tracks + stats.tracked_vehicles == FLICKERS + 1

    def test_une_analyse_sans_scintillement_rend_zero(self) -> None:
        session = _session(class_ids=(CAR,))
        for index, position in enumerate(
            track_path(1, CAR, [(100.0, 500.0), (880.0, 500.0)], box_size=(60.0, 60.0))
        ):
            session.feed(index, index * FRAME_MS, [position])

        assert session.stats().diagnostics.unconfirmed_tracks == 0
