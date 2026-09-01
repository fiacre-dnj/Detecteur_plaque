"""Une capture par véhicule, et c'est la meilleure lecture qui gagne.

La règle demandée tient en une phrase : à 0,80 on capture, à 0,90 on remplace, à
0,85 ensuite on ne touche plus à rien. Elle est **monotone stricte**, et ces tests
la verrouillent dans les deux sens — ce qui doit capturer, et surtout ce qui ne doit
**pas** déclencher d'encodage.

Le second point est le plus important : `FakeSnapshotEncoder.calls` compte les
encodages réellement demandés. C'est ce chiffre, et non le contenu du registre, qui
prouve que la règle protège le chemin critique. Un code qui encoderait à chaque image
puis jetterait le résultat rendrait exactement les mêmes captures, deux ordres de
grandeur plus cher — et aucun test portant seulement sur le résultat ne le verrait.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from tests.support.builders import CAR, compose, make_line, straight_line, track_path
from tests.support.engine import (
    FakeEngine,
    FakePlateDetector,
    FakePlateReader,
    FakeSnapshotEncoder,
    FakeVehicleEmbedder,
)
from traffic_analysis.features.counting.application.analysis_service import AnalysisService
from traffic_analysis.features.counting.application.dto import (
    AnalysisJobConfig,
    PlateDetectOptions,
    PlateOcrOptions,
)
from traffic_analysis.features.counting.domain.models import BoundingBox, TrackObservation

#: Détection et lecture **à chaque image**, pour que la suite de confiances soit
#: consommée image par image et que le test reste déterministe.
#:
#: Les étranglements ont leurs propres tests ; les mêler à celui-ci ferait dépendre
#: le verdict de deux règles à la fois, et un échec ne dirait plus laquelle est en
#: cause.
EVERY_FRAME_OCR = PlateOcrOptions(
    every_n_frames=1,
    skip_above_iou=1.0,
    min_width_px=0.0,
    min_sharpness=0.0,
    stop_when_confident=False,
)
EVERY_FRAME_DETECT = PlateDetectOptions(
    every_n_frames=1, min_vehicle_width_px=0.0, readable_gate=False, stop_when_confident=False
)

if TYPE_CHECKING:
    from pathlib import Path

    from traffic_analysis.features.counting.application.analysis_service import SnapshotCallback
    from traffic_analysis.features.counting.application.dto import AnalysisResultData

CONFIG = AnalysisJobConfig(
    model_id="yolov8n", lines=(make_line(),), detect_plates=True, read_plate_text=True
)

#: Ni ANPR ni OCR demandés : la configuration des causes qui ne les concernent pas.
CONFIG_SANS_OCR = AnalysisJobConfig(model_id="yolov8n", lines=(make_line(),))

#: L'ANPR sans la lecture — le cas de « Repérer les plaques » cochée, OCR décochée.
#: C'est là que la cause `plate_box` est la seule qui puisse produire une photo.
CONFIG_SANS_LECTURE = AnalysisJobConfig(
    model_id="yolov8n", lines=(make_line(),), detect_plates=True, read_plate_text=False
)


def _frames(steps: int = 6) -> list[list[TrackObservation]]:
    """Un véhicule qui traverse la ligne, sans se presser."""
    return compose(track_path(1, CAR, straight_line((700.0, 250.0), (700.0, 800.0), steps=steps)))


def _growing_vehicle(steps: int = 10) -> list[list[TrackObservation]]:
    """Un véhicule qui **s'approche** : 60, 80, 100 … px de large.

    Construit à la main parce que `track_path` n'accepte qu'une taille de boîte
    **fixe**, et c'est justement l'élargissement qui est en jeu ici. C'est le profil
    qui rend la règle monotone seule inopérante — chaque image bat la précédente, donc
    « plus large que la meilleure vue » est vrai à chaque image, et la plaque que le
    détecteur factice y trouve grandit dans la même proportion.

    Le jumeau de `_growing` dans `test_recherche_par_image.py`, dupliqué exprès :
    partager ce profil ferait dépendre les deux fichiers d'une même géométrie, et
    l'ajuster pour l'un casserait les seuils de l'autre.
    """
    return [
        [
            TrackObservation(
                track_id=1,
                class_id=CAR,
                label="car",
                score=0.9,
                box=BoundingBox(
                    x=700.0 - (60.0 + index * 20.0) / 2,
                    y=250.0 + index * 40.0,
                    width=60.0 + index * 20.0,
                    height=60.0,
                ),
            )
        ]
        for index in range(steps)
    ]


@pytest.fixture
def video(tmp_path: Path) -> Path:
    path = tmp_path / "clip.mp4"
    path.write_bytes(b"\x00" * 16)
    return path


def _run(
    video: Path,
    scores: list[float],
    *,
    read: bool = True,
    fails: bool = False,
    steps: int | None = None,
    on_snapshot: SnapshotCallback | None = None,
    plate_box: bool = False,
    improvement: float = 1.0,
) -> tuple[AnalysisResultData, FakeSnapshotEncoder]:
    """Analyse un clip où l'OCR rend une confiance **différente à chaque image**.

    `scores` est consommé image par image : c'est ce qui permet d'écrire la
    progression 0,80 → 0,90 → 0,85 telle que l'utilisateur l'a décrite.

    `plate_box` et `improvement` valent par défaut ce que le service pose lui-même,
    c'est-à-dire **le régime d'ADR 0042** : les tests de la cause `plate_text` restent
    donc mot pour mot ceux d'avant ADR 0051, et tout test des nouvelles causes dit
    explicitement qu'il les allume.
    """
    remaining = list(scores)

    def next_score() -> float:
        return remaining.pop(0) if remaining else 0.0

    encoder = FakeSnapshotEncoder(fails=fails)
    service = AnalysisService(
        # Deux images de plus que de confiances : la piste doit être **confirmée**
        # (`min_hits`) pour entrer dans le registre, et les confiances épuisées
        # rendent 0,0 — qui ne bat jamais rien.
        FakeEngine(_frames(steps if steps is not None else len(scores) + 3)),
        FakePlateDetector(),
        FakePlateReader(score_for=next_score) if read else None,
        plate_ocr=EVERY_FRAME_OCR,
        plate_detect=EVERY_FRAME_DETECT,
        snapshot_encoder=encoder,
        snapshot_on_plate_box=plate_box,
        snapshot_width_improvement=improvement,
    )
    config = AnalysisJobConfig(
        model_id="yolov8n",
        lines=(make_line(),),
        detect_plates=True,
        read_plate_text=read,
    )
    return service.run_video("job-1", video, config, on_snapshot=on_snapshot), encoder


def _captured(result: AnalysisResultData) -> tuple[float | None, float | None]:
    """La confiance et l'instant de la capture du premier véhicule."""
    vehicle = result.vehicles[0]
    return vehicle.snapshot_score, vehicle.snapshot_ms


def _kind(result: AnalysisResultData) -> str | None:
    """**Pourquoi** le premier véhicule a une photo, ou `None` — il n'en a pas."""
    return result.vehicles[0].snapshot_kind


class TestLaMeilleureLectureGagne:
    def test_la_premiere_lecture_declenche_une_capture(self, video: Path) -> None:
        result, encoder = _run(video, [0.80])

        assert encoder.calls == 1
        assert _captured(result)[0] == pytest.approx(0.80)

    def test_une_lecture_meilleure_remplace_la_capture(self, video: Path) -> None:
        result, encoder = _run(video, [0.80, 0.90])

        assert encoder.calls == 2
        assert _captured(result)[0] == pytest.approx(0.90)

    def test_une_lecture_moins_bonne_ne_declenche_aucun_encodage(self, video: Path) -> None:
        """**Le test qui prouve l'optimisation**, pas seulement le résultat.

        Après 0,90, la lecture à 0,85 ne doit pas seulement perdre : elle ne doit pas
        coûter un encodage. Encoder puis jeter rendrait le même registre pour un coût
        sans rapport, et un test portant sur le seul résultat ne le verrait jamais.
        """
        result, encoder = _run(video, [0.80, 0.90, 0.85, 0.70])

        assert encoder.calls == 2
        assert _captured(result)[0] == pytest.approx(0.90)

    def test_il_n_y_a_jamais_qu_une_capture_par_vehicule(self, video: Path) -> None:
        result, _ = _run(video, [0.70, 0.80, 0.90])

        assert len(result.snapshots) == 1
        assert set(result.snapshots) == {result.vehicles[0].global_id}

    def test_la_capture_porte_l_instant_de_l_image_retenue(self, video: Path) -> None:
        """L'instant est celui de l'image gagnante, pas de la dernière lue.

        C'est lui qui dit où regarder dans la vidéo : le dater à la fin ferait chercher
        le véhicule là où il n'est déjà plus.
        """
        result, _ = _run(video, [0.80, 0.95, 0.60, 0.60])
        score, timestamp = _captured(result)

        assert score == pytest.approx(0.95)
        assert timestamp is not None
        # Deuxième image analysée, à 25 images par seconde.
        assert timestamp == pytest.approx(40.0)


class TestCeQuiNeCapturePas:
    def test_sans_ocr_et_sans_la_cause_plaque_reperee_aucune_capture(self, video: Path) -> None:
        """La cause `plate_box` est un **commutateur**, pas un comportement câblé.

        Éteinte, le régime d'ADR 0042 est intact : la capture suit la lecture, et un
        rectangle sans texte ne déclenche rien. C'est ce que vérifie ce test, et c'est
        ce qui garantit qu'un déploiement peut revenir en arrière sans toucher au code.
        """
        result, encoder = _run(video, [0.80, 0.90], read=False)

        assert encoder.calls == 0
        assert result.snapshots == {}
        assert _captured(result) == (None, None)
        assert _kind(result) is None

    def test_sans_ocr_une_plaque_reperee_donne_quand_meme_une_photo(self, video: Path) -> None:
        """Le trou qu'ADR 0051 comble, et le cas dominant sur une vue large.

        Une plaque localisée sans texte — trop petite, trop floue, lecture refusée —
        n'avait aucune photo, alors que c'est précisément là qu'elle sert le plus :
        elle est la seule chose qui permette de lire ce que le serveur a refusé
        d'affirmer.

        La photo porte alors une cause et un instant, mais **aucune** confiance de
        lecture : il n'y a rien eu à lire.
        """
        result, encoder = _run(video, [0.80, 0.90], read=False, plate_box=True)

        assert encoder.calls >= 1
        assert _kind(result) == "plate_box"
        score, timestamp = _captured(result)
        assert score is None
        assert timestamp is not None
        # Et la vignette de plaque existe : une plaque a bien été localisée.
        assert encoder.boxes[0][1] is not None

    def test_un_encodeur_absent_ne_change_rien_d_autre(self, video: Path) -> None:
        """Le comptage, les plaques et le registre sont identiques sans encodeur."""
        service = AnalysisService(
            FakeEngine(_frames()),
            FakePlateDetector(),
            FakePlateReader(),
            plate_ocr=EVERY_FRAME_OCR,
            plate_detect=EVERY_FRAME_DETECT,
        )
        result = service.run_video("job-1", video, CONFIG)

        assert result.snapshots == {}
        assert result.vehicles[0].plate_text == "AB-123-CD"
        assert result.stats is not None
        assert result.stats.crossings == 1

    def test_un_encodage_rate_ne_laisse_pas_de_score_orphelin(self, video: Path) -> None:
        """Sinon un véhicule annoncerait une photo qui n'existe pas.

        L'interface afficherait une image cassée, et la seule façon de comprendre
        serait d'aller lire le disque. C'est pourquoi `should_capture` et
        `record_snapshot` sont deux appels et non un.
        """
        result, encoder = _run(video, [0.80, 0.90], fails=True)

        assert encoder.calls > 0
        assert result.snapshots == {}
        assert _captured(result) == (None, None)

    def test_un_encodeur_qui_refuse_est_redemande(self, video: Path) -> None:
        """Et c'est voulu : un refus décrit **cette image**, pas le véhicule.

        `encode` rend `None` quand il n'y a rien d'exploitable à recadrer — une boîte
        de quelques pixels, un véhicule à moitié hors champ. Deux images plus tard, le
        même véhicule peut très bien être recadrable. Mémoriser l'échec le priverait
        d'une photo pour un état passager, et c'est un mode de panne bien pire que
        quelques appels perdus sur un encodeur durablement en panne — appels que
        l'étranglement de l'OCR borne déjà.
        """
        _, encoder = _run(video, [0.80, 0.90, 0.95], fails=True)

        assert encoder.calls >= 3

    def test_la_capture_recadre_le_vehicule_et_sa_plaque(self, video: Path) -> None:
        """Deux boîtes distinctes, et la plaque est **dans** le véhicule.

        Recadrer deux fois la même chose rendrait deux vignettes identiques, ce qui
        ne se verrait qu'à l'écran — jamais dans un compteur.
        """
        _, encoder = _run(video, [0.80])
        vehicle, plate = encoder.boxes[0]

        assert plate.width < vehicle.width
        assert vehicle.x <= plate.x
        assert plate.x + plate.width <= vehicle.x + vehicle.width


class TestLaCaptureEstPubliableAvantLaFin:
    """Le rappel qui rend la vignette lisible **pendant** l'analyse (ADR 0046).

    Les octets étaient tenus en mémoire jusqu'à la fin du job : la colonne
    « Capture » du registre restait donc vide pendant tout le temps où on la
    regarde se remplir, et une alerte de plaque arrivait sans la photo qui permet
    de la valider.
    """

    def test_chaque_capture_retenue_est_publiee_tout_de_suite(self, video: Path) -> None:
        published: list[tuple[int, bytes]] = []
        result, encoder = _run(
            video,
            [0.80, 0.90],
            on_snapshot=lambda gid, snap: published.append((gid, snap.vehicle_jpeg)),
        )

        # Une publication par **amélioration**, exactement comme un encodage : le
        # rappel est posé juste après, sur les octets qui viennent d'être produits.
        assert encoder.calls == 2
        assert len(published) == 2
        assert {gid for gid, _ in published} == {result.vehicles[0].global_id}

    def test_une_lecture_moins_bonne_ne_republie_rien(self, video: Path) -> None:
        """Le rappel suit la règle monotone, il ne la double pas.

        S'il était appelé à chaque lecture plutôt qu'à chaque capture retenue, il
        réécrirait le fichier avec les octets d'une image moins bonne — et le
        registre annoncerait un score que la photo ne porte pas.
        """
        published: list[int] = []
        _run(video, [0.80, 0.90, 0.85, 0.70], on_snapshot=lambda gid, _: published.append(gid))

        assert len(published) == 2

    def test_les_octets_restent_aussi_en_memoire(self, video: Path) -> None:
        """Le rappel est un canal **de plus**, jamais un remplacement.

        L'écriture finale reste et réécrit les mêmes octets : c'est elle qui
        rattrape un rappel qu'une erreur disque passagère aurait fait échouer.
        """
        result, _ = _run(video, [0.80], on_snapshot=lambda _gid, _snap: None)

        assert len(result.snapshots) == 1

    def test_sans_rappel_rien_ne_change(self, video: Path) -> None:
        """La propriété qui rend le changement livrable.

        Le banc, les tests et tout appelant qui ignore le rappel obtiennent
        exactement le résultat d'avant.
        """
        with_callback, _ = _run(video, [0.80, 0.90], on_snapshot=lambda _gid, _snap: None)
        without, _ = _run(video, [0.80, 0.90])

        assert with_callback.snapshots.keys() == without.snapshots.keys()
        assert _captured(with_callback) == _captured(without)

    def test_un_encodage_rate_ne_publie_rien(self, video: Path) -> None:
        """Sinon le rappel écrirait un fichier vide sous un véhicule sans score."""
        published: list[int] = []
        _run(video, [0.80, 0.90], fails=True, on_snapshot=lambda gid, _: published.append(gid))

        assert published == []


class TestLEchelleDePriorite:
    """Trois causes, une seule photo, et c'est la cause qui tranche avant le rang.

    Le rang n'est comparable qu'à l'intérieur d'un tier : une confiance de lecture
    pour `plate_text`, une largeur de boîte pour les deux autres. Les comparer entre
    tiers serait une erreur d'unité invisible — 0,95 de confiance perdrait contre
    n'importe quelle boîte de 40 px, et le chiffre resterait plausible.
    """

    def test_une_plaque_lue_remplace_une_plaque_reperee(self, video: Path) -> None:
        """Et son rang est numériquement **plus petit** : 0,80 contre ~64 px.

        C'est exactement le cas qu'une comparaison de rangs entre tiers raterait.
        """
        result, encoder = _run(video, [0.0, 0.80, 0.0], read=True, plate_box=True)

        assert _kind(result) == "plate_text"
        assert _captured(result)[0] == pytest.approx(0.80)
        # Deux encodages : la plaque repérée de la première image, puis la lecture.
        assert encoder.calls >= 2

    def test_une_plaque_reperee_ne_remplace_jamais_une_plaque_lue(self, video: Path) -> None:
        """L'assertion porte sur `calls`, pas sur le registre.

        Un code qui encoderait puis jetterait rendrait le même registre pour un coût
        sans rapport : c'est la doctrine de tout ce fichier. Les images qui suivent la
        lecture n'ont plus de confiance à consommer — `next_score` rend 0,0 — et leurs
        plaques restent localisées : aucune ne doit redescendre l'échelle.
        """
        _, encoder = _run(video, [0.90], read=True, plate_box=True, steps=8)

        assert encoder.calls <= 2

    def test_une_ressemblance_ne_remplace_ni_l_une_ni_l_autre(self, video: Path) -> None:
        encoder = FakeSnapshotEncoder()
        service = AnalysisService(
            FakeEngine(_frames(6)),
            FakePlateDetector(),
            FakePlateReader(score_for=lambda: 0.90),
            plate_ocr=EVERY_FRAME_OCR,
            plate_detect=EVERY_FRAME_DETECT,
            snapshot_encoder=encoder,
            vehicle_embedder=FakeVehicleEmbedder(),
            snapshot_on_plate_box=True,
            snapshot_on_appearance=True,
            snapshot_width_improvement=1.15,
        )
        result = service.run_video("job-1", video, CONFIG, query_image=b"query")

        assert _kind(result) == "plate_text"
        # La plaque lue reste la photo, et sa vignette de plaque avec elle.
        assert result.snapshots[result.vehicles[0].global_id].plate_jpeg is not None

    def test_a_priorite_egale_la_regle_monotone_tranche(self, video: Path) -> None:
        """Le comportement d'ADR 0042, inchangé, et vérifié sur les deux tiers.

        Sur `plate_text` c'est la confiance qui monte ; sur `plate_box` c'est la
        largeur. Dans les deux cas une valeur qui ne bat pas la précédente ne coûte
        aucun encodage.
        """
        _, lu = _run(video, [0.80, 0.90, 0.85, 0.70])
        assert lu.calls == 2

        _, repere = _run(video, [0.0, 0.0, 0.0, 0.0], read=False, plate_box=True)
        # La largeur de plaque est constante ici, la boîte de véhicule l'étant : une
        # seule capture, jamais une par image.
        assert repere.calls == 1


class TestLaMargeBorneLesTiersEnLargeur:
    """**Le test qui empêche ADR 0050 de se rejouer**, sur la largeur de plaque.

    « Strictement plus large » est vrai à presque chaque image d'un véhicule qui
    approche. L'étranglement du détecteur de plaques ne divise le problème que par
    trois ; la marge, elle, borne le total sur la vie d'une piste.
    """

    @staticmethod
    def _run_growing(video: Path, *, improvement: float, steps: int = 10) -> FakeSnapshotEncoder:
        encoder = FakeSnapshotEncoder()
        service = AnalysisService(
            FakeEngine(_growing_vehicle(steps)),
            FakePlateDetector(),
            None,
            plate_ocr=EVERY_FRAME_OCR,
            plate_detect=EVERY_FRAME_DETECT,
            snapshot_encoder=encoder,
            snapshot_on_plate_box=True,
            snapshot_width_improvement=improvement,
        )
        service.run_video("job-1", video, CONFIG_SANS_LECTURE)
        return encoder

    def test_une_plaque_qui_s_elargit_ne_recapture_pas_a_chaque_image(self, video: Path) -> None:
        """Dix images, une plaque plus large à chaque : bien moins de dix captures.

        La marge autorise au plus autant de captures que de crans de 15 % entre la
        première largeur et la dernière, quelle que soit la cadence de la vidéo. Sans
        elle, c'est une capture par image — le piège d'ADR 0050, à l'identique.
        """
        borne = self._run_growing(video, improvement=1.15)
        sans_marge = self._run_growing(video, improvement=1.0)

        assert sans_marge.calls == 10
        assert borne.calls < sans_marge.calls
        assert borne.calls <= 7

    def test_une_marge_ne_touche_pas_le_tier_lu(self, video: Path) -> None:
        """Son rang est une confiance, qui ne croît pas avec l'approche du véhicule.

        Le service impose donc `1.0` sur ce tier, et une marge de déploiement absurde
        ne peut pas l'affamer : 0,80 puis 0,90 capturent toutes les deux.
        """
        _, encoder = _run(video, [0.80, 0.90, 0.85], improvement=4.0)

        assert encoder.calls == 2


class TestLaCaptureParRessemblance:
    """Une photo pour ce que la recherche par image propose. ADR 0051, sur ADR 0048.

    L'écran promet « à vérifier sur la capture » ; sans cela il n'y en avait aucune,
    l'ANPR étant la seule cause de capture.
    """

    @staticmethod
    def _run(
        video: Path,
        *,
        query: bytes | None = b"query",
        embedder: FakeVehicleEmbedder | None = None,
        min_similarity: float = 0.0,
        appearance: bool = True,
        steps: int = 6,
    ) -> tuple[AnalysisResultData, FakeSnapshotEncoder]:
        """**Aucune ANPR du tout** : ni détecteur, ni lecteur, ni options de plaque."""
        encoder = FakeSnapshotEncoder()
        service = AnalysisService(
            FakeEngine(_growing_vehicle(steps)),
            snapshot_encoder=encoder,
            vehicle_embedder=embedder if embedder is not None else FakeVehicleEmbedder(),
            reid_min_similarity=min_similarity,
            snapshot_on_appearance=appearance,
            snapshot_width_improvement=1.15,
        )
        return service.run_video("job-1", video, CONFIG_SANS_OCR, query_image=query), encoder

    def test_tout_vehicule_encode_recoit_une_photo(self, video: Path) -> None:
        result, encoder = self._run(video)

        assert encoder.calls >= 1
        assert _kind(result) == "appearance"
        assert _captured(result)[1] is not None
        assert result.vehicles[0].match_score is not None

    def test_une_photo_de_ressemblance_n_a_pas_de_vignette_de_plaque(self, video: Path) -> None:
        """Il n'y a pas de plaque à recadrer, et ce n'est pas un échec.

        L'encodeur reçoit `None` et rend une capture à une seule face ; la modale du
        client explique au lieu d'afficher un repère d'erreur.
        """
        result, encoder = self._run(video)

        assert all(plate is None for _vehicle, plate in encoder.boxes)
        assert result.snapshots[result.vehicles[0].global_id].plate_jpeg is None

    def test_un_vehicule_refuse_par_l_adaptateur_n_est_pas_photographie(self, video: Path) -> None:
        """On ne photographie que les vues **réellement encodées**.

        Les planchers de l'adaptateur — largeur, netteté — viennent d'accepter le
        recadrage : c'est exactement la barre qu'on veut pour une photo, et elle est
        déjà payée. Capturer les refusés donnerait des vignettes trop petites ou
        floues de mouvement.
        """
        result, encoder = self._run(video, embedder=FakeVehicleEmbedder(min_width_px=10_000.0))

        assert encoder.calls == 0
        assert _kind(result) is None

    def test_un_score_sous_le_plancher_de_deploiement_garde_sa_photo(self, video: Path) -> None:
        """**La propriété qui rend le curseur client déplaçable.**

        Le seuil d'affichage vit côté client (ADR 0048/0041). Une photo qui n'existerait
        qu'au-dessus d'un seuil serveur manquerait exactement au moment où l'on descend
        le curseur pour la regarder.
        """
        result, encoder = self._run(video, min_similarity=0.99)

        assert result.vehicles[0].match_score is None
        assert encoder.calls >= 1
        assert _kind(result) == "appearance"

    def test_sans_image_de_requete_aucune_photo_de_ressemblance(self, video: Path) -> None:
        """L'étage entier est éteint : la capture ne coûte alors rien du tout."""
        result, encoder = self._run(video, query=None)

        assert encoder.calls == 0
        assert _kind(result) is None

    def test_la_cause_ressemblance_est_un_commutateur(self, video: Path) -> None:
        result, encoder = self._run(video, appearance=False)

        assert encoder.calls == 0
        assert _kind(result) is None
        # Et la recherche par image continue de fonctionner, sans photo.
        assert result.vehicles[0].match_score is not None


class TestLeNoConsensusGardeSaPhoto:
    """Un vote qui refuse de publier n'efface pas la preuve. ADR 0042, garanti ici.

    C'est le cas où la photo compte le plus : le serveur se tait sur le texte, et la
    seule façon de savoir ce qui était écrit est de regarder l'image. Des lectures
    individuelles ont bien eu lieu, donc la cause reste `plate_text`.
    """

    def test_des_lectures_discordantes_gardent_leur_capture(self, video: Path) -> None:
        encoder = FakeSnapshotEncoder()
        # Trois graphies de **longueurs différentes**, comme dans
        # `test_plate_reasons.py` : à longueur égale, le consensus par caractère
        # publierait là où le vote par chaîne refuse, et le test ne verrouillerait
        # plus le cas qu'il vise.
        rotation = ["ab-123-cd", "xy-78-zw", "mn-4567-op"]
        calls = iter(range(1_000))
        service = AnalysisService(
            FakeEngine(_frames(6)),
            FakePlateDetector(),
            FakePlateReader(text_for=lambda _box: rotation[next(calls) % len(rotation)]),
            plate_ocr=EVERY_FRAME_OCR,
            plate_detect=EVERY_FRAME_DETECT,
            snapshot_encoder=encoder,
        )
        result = service.run_video("job-1", video, CONFIG)
        vehicle = result.vehicles[0]

        assert vehicle.plate_text is None
        assert vehicle.plate_unread_reason == "no_consensus"
        assert vehicle.snapshot_kind == "plate_text"
        assert vehicle.snapshot_score is not None


def test_la_capture_ne_coute_rien_quand_aucune_cause_n_est_armee(video: Path) -> None:
    """Les trois commutateurs allumés, ni ANPR ni requête : zéro encodage.

    Le coût de la capture est **conditionné aux étages qui la portent** — la passe
    plaques et la passe apparence — et aucun des deux ne tourne ici. Une ligne de trop
    dans le corps de la boucle se verrait dans ce test.
    """
    encoder = FakeSnapshotEncoder()
    service = AnalysisService(
        FakeEngine(_frames(6)),
        snapshot_encoder=encoder,
        snapshot_on_plate_box=True,
        snapshot_on_appearance=True,
        snapshot_width_improvement=1.15,
    )
    result = service.run_video("job-1", video, CONFIG_SANS_OCR)

    assert encoder.calls == 0
    assert result.snapshots == {}
    assert result.vehicles[0].snapshot_kind is None
