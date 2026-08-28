"""La forme exacte du fil.

Ce que ces tests protègent : **une divergence silencieuse avec le frontend**. Le
résultat sérialisé est le seul payload que pydantic ne revalide pas, donc rien côté
serveur ne signale un renommage — c'est `frontend/src/shared/api/contracts.ts` et sa
fixture committée qui s'en chargent, et le test frontend échoue alors *après* coup,
loin de la cause.

Les assertions portent donc sur le **jeu de clés complet** et non sur la présence de
telle clé : c'est ce qui fait échouer un renommage ici, à côté de la ligne fautive.
"""

from __future__ import annotations

import pytest

from traffic_analysis.features.counting.application.serializers import (
    serialise_crossing,
    serialise_track,
    serialise_vehicle,
)
from traffic_analysis.features.counting.domain.geometry import Point
from traffic_analysis.features.counting.domain.models import (
    BoundingBox,
    CrossingEvent,
    PlateDetection,
    SessionTrack,
    VehicleRecord,
)

BOX = BoundingBox(100.0, 200.0, 80.0, 60.0)
PLATE_BOX = BoundingBox(124.0, 239.0, 32.0, 9.0)


def _track(*, plates: tuple[PlateDetection, ...] = (), plate_text: str = "") -> SessionTrack:
    return SessionTrack(
        track_id=3,
        class_id=2,
        label="car",
        score=0.87,
        box=BOX,
        centroid=Point(140.0, 230.0),
        global_id=7,
        identity_label="car",
        plates=list(plates),
        plate_text=plate_text,
        plate_text_score=0.8812 if plate_text else 0.0,
    )


def _vehicle(**overrides: object) -> VehicleRecord:
    base: dict[str, object] = {
        "global_id": 7,
        "label": "car",
        "first_seen_ms": 0.0,
        "last_seen_ms": 480.0,
        "crossed_lines": (),
        "zones_visited": (),
        "best_plate_score": 0.71,
    }
    base.update(overrides)
    return VehicleRecord(**base)  # type: ignore[arg-type]


def _crossing(**overrides: object) -> CrossingEvent:
    base: dict[str, object] = {
        "line_id": "l1",
        "global_id": 7,
        "track_id": 3,
        "label": "car",
        "direction": 1,
        "timestamp_ms": 480.0,
        "frame_index": 12,
    }
    base.update(overrides)
    return CrossingEvent(**base)  # type: ignore[arg-type]


class TestSerialiseTrack:
    def test_le_jeu_de_cles_d_une_piste(self) -> None:
        assert sorted(serialise_track(_track())) == [
            "box",
            "classId",
            "counted",
            "globalId",
            "hits",
            "identityLabel",
            "label",
            "plateText",
            "plateTextScore",
            "plates",
            "score",
            "trackId",
        ]

    def test_le_jeu_de_cles_d_une_plaque(self) -> None:
        plate = PlateDetection(box=PLATE_BOX, score=0.71, text="AB-123-CD", text_score=0.88)
        payload = serialise_track(_track(plates=(plate,)))
        assert sorted(payload["plates"][0]) == ["box", "score", "text", "textScore"]

    def test_une_plaque_lue_porte_son_texte_et_sa_confiance(self) -> None:
        plate = PlateDetection(box=PLATE_BOX, score=0.71, text="AB-123-CD", text_score=0.881234)
        serialised = serialise_track(_track(plates=(plate,)))["plates"][0]
        assert serialised["text"] == "AB-123-CD"
        assert serialised["textScore"] == pytest.approx(0.8812)

    def test_une_plaque_vue_mais_illisible_rend_null_et_non_zero(self) -> None:
        """`0` dirait « lu, sans aucune confiance » — ce n'est pas la même chose.

        L'état à préserver est « une plaque a bien été vue » : le `score` de détection
        reste réel, seul le couple de lecture est absent.
        """
        plate = PlateDetection(box=PLATE_BOX, score=0.71)
        serialised = serialise_track(_track(plates=(plate,)))["plates"][0]
        assert serialised["text"] is None
        assert serialised["textScore"] is None
        assert serialised["score"] == pytest.approx(0.71)

    def test_le_texte_vote_est_publie_au_niveau_de_la_piste(self) -> None:
        """C'est ce champ que le canvas étiquette, pas `plates[].text`."""
        payload = serialise_track(_track(plate_text="AB-123-CD"))
        assert payload["plateText"] == "AB-123-CD"
        assert payload["plateTextScore"] == pytest.approx(0.8812)

    def test_un_vote_non_concluant_rend_null_et_non_une_chaine_vide(self) -> None:
        payload = serialise_track(_track())
        assert payload["plateText"] is None
        assert payload["plateTextScore"] is None


class TestSerialiseCrossing:
    def test_le_jeu_de_cles_d_un_franchissement(self) -> None:
        assert sorted(serialise_crossing(_crossing())) == [
            "category",
            "direction",
            "frameIndex",
            "globalId",
            "label",
            "lineId",
            "plateText",
            "plateTextScore",
            "timestampMs",
            "trackId",
        ]

    def test_un_franchissement_porte_sa_categorie(self) -> None:
        """Véhicule ou personne, décidé **par le serveur** et transporté.

        C'est ce qui permet à la relecture côté navigateur de ventiler les
        franchissements par catégorie sans recopier la table des classes : deux
        copies d'une règle de classement finissent par diverger, et un
        franchissement changerait de colonne selon l'écran qui le montre.
        """
        assert serialise_crossing(_crossing())["category"] == "vehicle"
        assert serialise_crossing(_crossing(label="person"))["category"] == "person"

    def test_un_franchissement_sans_plaque_rend_deux_null(self) -> None:
        payload = serialise_crossing(_crossing())
        assert payload["plateText"] is None
        assert payload["plateTextScore"] is None

    def test_un_franchissement_avec_plaque_arrondit_sa_confiance(self) -> None:
        payload = serialise_crossing(_crossing(plate_text="AB-123-CD", plate_text_score=0.881234))
        assert payload["plateText"] == "AB-123-CD"
        assert payload["plateTextScore"] == pytest.approx(0.8812)


class TestSerialiseVehicle:
    def test_le_jeu_de_cles_du_registre(self) -> None:
        assert sorted(serialise_vehicle(_vehicle())) == [
            "bestPlateScore",
            "crossedLines",
            "firstSeenMs",
            "globalId",
            "label",
            "lastSeenMs",
            "matchScore",
            "plateBestGuess",
            "plateBestGuessScore",
            "plateBestWidthPx",
            "plateText",
            "plateTextScore",
            "plateUnreadReason",
            "snapshotMs",
            "snapshotScore",
            "zonesVisited",
        ]

    def test_un_vehicule_sans_recherche_par_image_rend_un_score_nul(self) -> None:
        """`matchScore` à `null` couvre **deux** causes, et c'est assumé.

        Aucune image de requête fournie, ou véhicule jamais assez grand ni assez net
        pour être encodé. Les distinguer côté serveur demanderait un second champ pour
        une différence que l'écran n'a pas à faire : dans les deux cas il n'y a rien à
        classer. Le tiroir d'alertes, lui, sait s'il a une requête — c'est lui qui
        décide s'il faut afficher une colonne.
        """
        assert serialise_vehicle(_vehicle())["matchScore"] is None

    def test_une_ressemblance_est_arrondie_comme_les_autres_scores(self) -> None:
        """Même arrondi que toutes les confiances : quatre décimales (ADR 0026).

        Un score de ressemblance non arrondi porterait dix-sept chiffres dans chaque
        aperçu SSE, pour une précision que rien n'affiche.
        """
        payload = serialise_vehicle(_vehicle(match_score=0.8812345))
        assert payload["matchScore"] == pytest.approx(0.8812)

    def test_un_vehicule_sans_capture_rend_deux_null(self) -> None:
        """La non-nullité de `snapshotScore` **est** le drapeau « il y a une photo ».

        Pas de booléen en plus, et surtout pas d'URL : le serveur ne fabrique pas les
        adresses du client, qui les construit depuis l'identifiant du job et le numéro
        du véhicule — même convention que la vidéo déposée.
        """
        payload = serialise_vehicle(_vehicle())
        assert payload["snapshotScore"] is None
        assert payload["snapshotMs"] is None

    def test_un_vehicule_capture_porte_sa_confiance_et_son_instant(self) -> None:
        payload = serialise_vehicle(_vehicle(snapshot_score=0.921234, snapshot_ms=12_400.0))
        assert payload["snapshotScore"] == pytest.approx(0.9212)
        assert payload["snapshotMs"] == pytest.approx(12_400.0)

    def test_une_plaque_vue_mais_illisible_garde_son_score_de_detection(self) -> None:
        """L'état que l'interface rate le plus facilement, et qui doit rester lisible.

        `plateText` nul avec un `bestPlateScore` réel n'est pas « aucune plaque » :
        c'est « une plaque vue, aucune lecture concluante ». Une colonne vide en face
        d'un rectangle visible à l'écran serait une contradiction.
        """
        payload = serialise_vehicle(_vehicle())
        assert payload["plateText"] is None
        assert payload["plateTextScore"] is None
        assert payload["bestPlateScore"] == pytest.approx(0.71)

    def test_un_vehicule_lu_porte_les_deux_confiances(self) -> None:
        payload = serialise_vehicle(_vehicle(plate_text="AB-123-CD", plate_text_score=0.881234))
        assert payload["plateText"] == "AB-123-CD"
        assert payload["plateTextScore"] == pytest.approx(0.8812)
        assert payload["bestPlateScore"] == pytest.approx(0.71)
