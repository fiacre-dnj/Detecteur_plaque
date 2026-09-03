"""« Survie d'une piste perdue » atteint enfin le tracker — ADR 0058.

Le curseur `maxLostMs` (200 à 15 000 ms) ne pilotait que la mémoire du domaine.
`track_buffer` est une constante du fichier de suivi versionné, `EngineSpec` ne portait
pas le champ, et la valeur ne *pouvait* donc pas descendre jusqu'à l'adaptateur : le
réglage était écrit, persisté, affiché — et inerte.

Pire, les deux horloges divergeaient. Le domaine compte du **temps de scène**, le
tracker des **images analysées** (`byte_tracker.py`,
`self.max_frames_lost = args.track_buffer`, sans aucune mise à l'échelle). Le
commentaire du fichier de suivi annonçait un « miroir exact » qui n'était vrai qu'à
30 img/s et au pas 1.

Quatre propriétés, et la première est celle qui rend le changement livrable :

1. **le défaut retombe sur la valeur du fichier de base**, donc aucun fichier dérivé,
   donc rien ne change pour qui ne touche pas au curseur ;
2. **la conversion suit la cadence et le pas** — c'est le bug lui-même ;
3. **`track_buffer` est reposé sur les trackers vivants**, et par un mécanisme distinct
   de celui des clés de requête : `reset()` ne le relit pas ;
4. **le direct n'impose rien**, faute de cadence connue.
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest
import yaml

from traffic_analysis.features.counting.application.ports import EngineSpec
from traffic_analysis.features.models_registry.infrastructure.ultralytics_engine import (
    ENGRAVED_TRACKER_ATTRS,
    LIVE_TRACKER_KEYS,
    REQUEST_TRACKER_KEYS,
    TRACKER_CONFIG,
    reset_trackers,
    resolved_tracker_config,
    track_buffer_frames,
)

BASE = yaml.safe_load(TRACKER_CONFIG.read_text(encoding="utf-8"))
BASE_BUFFER = int(BASE["track_buffer"])


class TestLaConversion:
    def test_le_defaut_retombe_exactement_sur_le_fichier_de_base(self) -> None:
        """**La propriété qui rend ADR 0058 livrable.**

        2 500 ms à 30 img/s au pas 1 valent 75 images — la valeur du fichier versionné.
        Si ce test tombait, toutes les analyses au défaut changeraient de tampon sans
        que personne l'ait demandé.
        """
        assert track_buffer_frames(2500.0, 30.0, 1) == BASE_BUFFER

    @pytest.mark.parametrize(
        ("max_lost_ms", "fps", "stride", "expected"),
        [
            # Le bug : à pas 3, le domaine oublie à 2,5 s et le tracker tenait 7,5 s.
            (2500.0, 30.0, 3, 25),
            # Et l'inverse à 60 img/s : le tracker renonçait à 1,25 s.
            (2500.0, 60.0, 1, 150),
            (2500.0, 60.0, 2, 75),
            # Le curseur agit enfin.
            (8000.0, 30.0, 1, 240),
            (200.0, 30.0, 1, 6),
            (15000.0, 30.0, 1, 450),
            # Cadences non entières : 29,97 est le cas courant, et il ne doit pas
            # produire un tampon nul par troncature.
            (2500.0, 29.97, 1, 75),
            # 62,5 exactement : `round` arrondit **au pair** en Python, donc 62 et non
            # 63. Une demi-image n'a aucune conséquence, mais l'écrire évite qu'on
            # « corrige » un jour un arrondi qui n'est pas un bug.
            (2500.0, 25.0, 1, 62),
        ],
    )
    def test_la_conversion_suit_la_cadence_et_le_pas(
        self, max_lost_ms: float, fps: float, stride: int, expected: int
    ) -> None:
        assert track_buffer_frames(max_lost_ms, fps, stride) == expected

    def test_le_tampon_ne_descend_jamais_a_zero(self) -> None:
        """Un tampon nul abandonnerait une piste à l'image même où elle disparaît,
        c'est-à-dire retirerait au tracker la tolérance qui justifie son existence."""
        assert track_buffer_frames(200.0, 1.0, 30) == 1

    def test_une_cadence_inconnue_n_impose_rien(self) -> None:
        """`0` se lit « ne rien imposer » : on ne peut pas convertir sans cadence."""
        assert track_buffer_frames(2500.0, 0.0, 1) == 0
        assert track_buffer_frames(0.0, 30.0, 1) == 0


class TestLeFichierDerive:
    def test_le_defaut_ne_change_pas_le_tampon(self) -> None:
        """Au curseur par défaut, le fichier dérivé porte la valeur du fichier de base.

        Il y a bien un fichier dérivé — le seuil de confiance de la requête, 0,35,
        diffère du 0,25 versionné — mais le tampon, lui, est intact. C'est cette
        propriété qui garantit qu'aucune analyse existante ne change de comportement,
        pas l'absence de fichier.
        """
        derived = resolved_tracker_config("none", 0.35, True, BASE_BUFFER)
        content = yaml.safe_load(Path(derived).read_text(encoding="utf-8"))
        assert content["track_buffer"] == BASE_BUFFER

    def test_une_course_entierement_au_defaut_n_ecrit_toujours_aucun_fichier(self) -> None:
        """Le raccourci d'origine tient encore : quand tout coïncide, on rend le
        fichier versionné lui-même. Ajouter le tampon ne devait pas le casser."""
        assert (
            resolved_tracker_config("none", BASE["track_high_thresh"], True, BASE_BUFFER)
            == TRACKER_CONFIG
        )

    def test_un_tampon_different_est_ecrit_dans_le_derive(self) -> None:
        derived = resolved_tracker_config("none", 0.35, True, 240)
        content = yaml.safe_load(Path(derived).read_text(encoding="utf-8"))
        assert content["track_buffer"] == 240

    def test_zero_laisse_la_valeur_du_fichier_de_base(self) -> None:
        """Le direct, qui n'a pas de cadence : comportement d'avant ADR 0058."""
        derived = resolved_tracker_config("sparseOptFlow", 0.35, True, 0)
        content = yaml.safe_load(Path(derived).read_text(encoding="utf-8"))
        assert content["track_buffer"] == BASE_BUFFER

    def test_deux_tampons_differents_n_ecrivent_pas_dans_le_meme_fichier(self) -> None:
        """Sinon la seconde course emporterait la première pendant qu'elle tourne."""
        assert resolved_tracker_config("none", 0.35, True, 240) != resolved_tracker_config(
            "none", 0.35, True, 25
        )


class TestLeSpecPorteLeReglage:
    def test_engine_spec_porte_max_lost_ms(self) -> None:
        """Sans ce champ, la valeur ne *peut pas* atteindre l'adaptateur — c'était le
        bug, et il n'était pas dans le calcul mais dans l'absence de transport."""
        spec = EngineSpec(
            model_id="yolov8n", confidence=0.35, iou=0.45, class_ids=(2,), max_lost_ms=8000.0
        )
        assert spec.max_lost_ms == 8000.0

    def test_le_defaut_du_spec_est_celui_de_la_requete(self) -> None:
        spec = EngineSpec(model_id="yolov8n", confidence=0.35, iou=0.45, class_ids=(2,))
        assert spec.max_lost_ms == 2500.0


class _FakeTracker:
    """Un tracker au minimum de ce que le vrai expose, y compris la clé gravée."""

    def __init__(self, buffer: int) -> None:
        self.args = SimpleNamespace(
            track_high_thresh=0.25,
            track_low_thresh=0.1,
            new_track_thresh=0.25,
            track_buffer=buffer,
        )
        self.max_frames_lost = buffer
        self.reset_calls = 0

    def reset(self) -> None:
        # Le vrai `reset()` ne relit **pas** `args.track_buffer` : vérifié à
        # l'exécution sur la roue installée. La doublure reproduit cette propriété,
        # sans quoi le test passerait pour la mauvaise raison.
        self.reset_calls += 1


def _model_with(tracker: _FakeTracker) -> SimpleNamespace:
    return SimpleNamespace(predictor=SimpleNamespace(trackers=[tracker]))


class TestLaCleGraveeEstReposee:
    def test_max_frames_lost_suit_le_fichier_derive(self) -> None:
        """**Le patron d'ADR 0035**, sur la clé que `reset()` ne relit pas.

        Écrire la valeur dans le fichier ne suffit pas : Ultralytics ne relit jamais
        le fichier une fois ses trackers en place. Sans ce mécanisme, le réglage serait
        correct à la première analyse d'un processus et inerte à toutes les suivantes.
        """
        tracker = _FakeTracker(BASE_BUFFER)
        config = resolved_tracker_config("none", 0.35, True, 240)

        reset_trackers(_model_with(tracker), config)

        assert tracker.max_frames_lost == 240
        assert tracker.reset_calls == 1

    def test_une_deuxieme_analyse_repose_une_autre_valeur(self) -> None:
        """Deux analyses du même processus, deux curseurs : la seconde doit obéir."""
        tracker = _FakeTracker(BASE_BUFFER)
        model = _model_with(tracker)

        reset_trackers(model, resolved_tracker_config("none", 0.35, True, 240))
        reset_trackers(model, resolved_tracker_config("none", 0.35, True, 25))

        assert tracker.max_frames_lost == 25

    def test_un_fichier_sans_tampon_impose_ne_change_rien(self) -> None:
        tracker = _FakeTracker(BASE_BUFFER)

        reset_trackers(_model_with(tracker), resolved_tracker_config("none", 0.35, True, 0))

        assert tracker.max_frames_lost == BASE_BUFFER

    def test_un_tracker_sans_l_attribut_ne_fait_pas_echouer_l_analyse(self) -> None:
        """Le comportement d'avant plutôt qu'une analyse qui plante — mais journalisé."""
        tracker = SimpleNamespace(args=SimpleNamespace(), reset=lambda: None)
        model = SimpleNamespace(predictor=SimpleNamespace(trackers=[tracker]))

        reset_trackers(model, resolved_tracker_config("none", 0.35, True, 240))

        assert not hasattr(tracker, "max_frames_lost")


class TestLesDeuxCategoriesRestentDistinctes:
    def test_une_cle_gravee_n_est_pas_une_cle_vivante(self) -> None:
        """La garantie `REQUEST_TRACKER_KEYS ⊆ LIVE_TRACKER_KEYS` ne couvre plus tout.

        C'est **le** point à ne pas perdre : il existe désormais deux façons de
        reposer un réglage, et confondre les deux rendrait la clé gravée inerte sans
        qu'aucun test ne le dise.
        """
        assert not (set(ENGRAVED_TRACKER_ATTRS) & LIVE_TRACKER_KEYS)

    def test_la_garantie_historique_tient_toujours_pour_les_cles_de_requete(self) -> None:
        assert REQUEST_TRACKER_KEYS <= LIVE_TRACKER_KEYS

    def test_la_cle_gravee_vise_un_attribut_d_instance_et_non_args(self) -> None:
        assert ENGRAVED_TRACKER_ATTRS == {"track_buffer": "max_frames_lost"}
