"""La passe ANPR et la passe OCR, pilotées par le service.

**Aucun test ne pilotait jusqu'ici `run_video` avec `detect_plates=True`.** Ce fichier
comble le trou, et il couvre les trois choses que ni le domaine ni l'adaptateur ne
peuvent démontrer seuls :

- l'**invariant 8** — le snapshot est pris après les deux passes. Testé par sa
  conséquence observable : du texte présent dans la timeline. Un snapshot est une
  copie, donc du texte dedans ne peut venir que d'une OCR exécutée *avant* la copie ;
- la **dégradation indépendante** — un lecteur absent ne doit pas emporter la
  détection avec lui. C'est le mode de panne d'un déploiement neuf, où seul le modèle
  de détection est présent ;
- l'**étranglement** — mesuré en nombre d'inférences, jamais en durée. Un test dont le
  verdict dépend de la vitesse de la machine ne prouve rien.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from tests.support.builders import CAR, TRUCK, compose, make_line, straight_line, track_path
from tests.support.engine import FakeEngine, FakePlateDetector, FakePlateReader
from traffic_analysis.features.counting.application.analysis_service import AnalysisService
from traffic_analysis.features.counting.application.dto import (
    AnalysisJobConfig,
    AnalysisResultData,
    BoundingBox,
    PlateDetectOptions,
    PlateOcrOptions,
)

VIDEO = Path("/inexistant.mp4")  # `FakeEngine` ne lit jamais le disque.


#: Taille de véhicule de ces scénarios : **au-dessus de `min_vehicle_width_px`**.
#:
#: 160 px et non les 80 px par défaut des constructeurs, parce que
#: `PlateDetectPolicy` écarte les pistes trop étroites — sur un véhicule de 80 px,
#: la plaque ferait une douzaine de pixels et l'inférence coûterait pour rien. Ces
#: tests-ci portent sur l'orchestration des deux passes, pas sur cette garde : les
#: laisser sous le seuil ferait passer chaque scénario par le chemin « rien à
#: faire », et ils ne prouveraient plus rien. La garde a son propre test.
VEHICLE_SIZE = (160.0, 120.0)


def _frames(steps: int = 16) -> list[list[object]]:
    return compose(
        track_path(
            1,
            CAR,
            straight_line((700.0, 250.0), (700.0, 800.0), steps=steps),
            box_size=VEHICLE_SIZE,
        ),
        track_path(
            2,
            TRUCK,
            straight_line((1200.0, 800.0), (1200.0, 250.0), steps=steps),
            box_size=VEHICLE_SIZE,
        ),
    )


def _wide_and_narrow(steps: int = 12) -> list[list[object]]:
    """Deux pistes de largeurs **différentes**, toutes deux au-dessus du plancher.

    Le classement du budget départage par la largeur : deux pistes identiques
    rendraient le test aveugle à l'ordre, qui est précisément ce qui décide de la
    justesse quand on plafonne.
    """
    return compose(
        track_path(
            1,
            CAR,
            straight_line((700.0, 250.0), (700.0, 800.0), steps=steps),
            box_size=(400.0, 220.0),
        ),
        track_path(
            2,
            TRUCK,
            straight_line((1200.0, 800.0), (1200.0, 250.0), steps=steps),
            box_size=(120.0, 100.0),
        ),
    )


def _run(
    *,
    detect_plates: bool = True,
    read_plate_text: bool = True,
    detector: FakePlateDetector | None = None,
    reader: FakePlateReader | None = None,
    ocr: PlateOcrOptions | None = None,
    detect: PlateDetectOptions | None = None,
    steps: int = 16,
    plate_confidence: float | None = None,
    plate_text_confidence: float | None = None,
) -> AnalysisResultData:
    service = AnalysisService(
        FakeEngine(_frames(steps)),  # type: ignore[arg-type]
        detector if detector is not None else FakePlateDetector(),
        reader,
        ocr,
        detect,
    )
    config = AnalysisJobConfig(
        model_id="yolov8n",
        lines=(make_line(),),
        detect_plates=detect_plates,
        read_plate_text=read_plate_text,
        plate_confidence=plate_confidence,
        plate_text_confidence=plate_text_confidence,
    )
    return service.run_video("job-anpr", VIDEO, config)


def _texts(result: AnalysisResultData) -> list[str]:
    return [
        plate.text
        for row in result.timeline
        for track in row.tracks
        for plate in track.plates
        if plate.text is not None
    ]


class TestPasseComplete:
    def test_les_deux_passes_tournent(self) -> None:
        detector, reader = FakePlateDetector(), FakePlateReader()
        _run(detector=detector, reader=reader)

        assert detector.calls > 0
        assert reader.calls > 0

    def test_la_timeline_porte_le_texte_normalise(self) -> None:
        """L'invariant 8, testé par sa conséquence observable.

        Un snapshot est une **copie** : du texte dedans ne peut venir que d'une OCR
        exécutée avant la copie. Et que ce texte soit `AB-123-CD` alors que le lecteur
        rend `ab-123-cd` prouve du même coup que la normalisation du domaine a tourné.
        """
        result = _run(reader=FakePlateReader(text="ab-123-cd"))

        assert _texts(result)
        assert set(_texts(result)) == {"AB-123-CD"}

    def test_le_registre_porte_le_texte_vote(self) -> None:
        result = _run(reader=FakePlateReader(text="ab-123-cd"))

        assert result.vehicles
        assert all(record.plate_text == "AB-123-CD" for record in result.vehicles)
        assert all(record.plate_text_score == pytest.approx(0.93) for record in result.vehicles)

    def test_le_lot_regroupe_les_plaques_d_une_frame(self) -> None:
        """`crops >= calls` : la preuve que plusieurs plaques partent en un appel.

        Le détecteur factice rend une plaque par piste, donc l'égalité stricte est
        attendue ici — mais l'assertion porte sur l'inégalité, qui est ce que le port
        promet réellement.
        """
        reader = FakePlateReader()
        _run(reader=reader)

        assert reader.crops >= reader.calls

    def test_le_lot_regroupe_les_pistes_d_une_frame_pour_la_detection(self) -> None:
        """La mosaïque, mesurée là où elle compte : **une inférence par frame**.

        Deux pistes traversent ces images ; sans empaquetage le détecteur serait
        appelé deux fois par frame. `crops == 2 × calls` prouve que les deux
        recadrages sont partis ensemble — et c'était le poste dominant du coût de
        l'ANPR, une inférence de 640×640 par piste et par frame.

        Mesuré **sans décalage** (`stagger=False`), parce que le décalage répartit
        délibérément les identités sur des images différentes : avec lui, deux
        pistes qui ne partent pas ensemble sont le comportement voulu, et
        l'égalité ne dirait plus rien de l'empaquetage.
        """
        detector = FakePlateDetector()
        _run(
            detector=detector,
            detect=PlateDetectOptions(every_n_frames=1, stagger=False, stop_when_confident=False),
        )

        assert detector.calls > 0
        assert detector.crops == 2 * detector.calls

    def test_le_seuil_de_la_requete_atteint_l_adaptateur(self) -> None:
        """`plateConfidence` a été annoncé dans l'API et ignoré pendant tout un lot.

        Un réglage qui figure au contrat et ne fait rien est pire qu'un réglage
        absent : l'utilisateur le déplace, les chiffres ne bougent pas, et il conclut
        que la détection est mauvaise. Rien ne le signalait — d'où ce test.
        """
        detector = FakePlateDetector()
        _run(detector=detector, plate_confidence=0.6)

        assert detector.last_confidence == pytest.approx(0.6)

    def test_sans_seuil_de_requete_l_adaptateur_garde_le_sien(self) -> None:
        """`None` signifie « garde ta configuration », pas « seuil zéro »."""
        detector = FakePlateDetector()
        _run(detector=detector, plate_confidence=None)

        assert detector.last_confidence is None


class TestDegradationGracieuse:
    def test_sans_lecteur_la_detection_continue(self) -> None:
        detector = FakePlateDetector()
        result = _run(detector=detector, reader=None)

        assert detector.calls > 0
        assert _texts(result) == []
        # Les rectangles sont bien là : c'est l'option de l'option qui manque.
        assert any(track.plates for row in result.timeline for track in row.tracks)

    def test_un_lecteur_indisponible_n_emporte_pas_la_detection(self) -> None:
        """Le mode de panne d'un déploiement neuf : détecteur présent, lecteur absent.

        L'OCR est une option **de** l'option. Si son absence désactivait la détection,
        un serveur sans modèle de lecture perdrait aussi les boîtes qu'il sait
        produire — une régression pour tout le monde au profit de personne.
        """
        detector, reader = FakePlateDetector(), FakePlateReader(available=False)
        result = _run(detector=detector, reader=reader)

        assert detector.calls > 0
        # Jamais appelé : le garde de disponibilité écarte le lecteur en amont.
        assert reader.calls == 0
        assert _texts(result) == []
        assert any(track.plates for row in result.timeline for track in row.tracks)

    def test_sans_read_plate_text_le_lecteur_n_est_pas_appele(self) -> None:
        detector, reader = FakePlateDetector(), FakePlateReader()
        result = _run(detector=detector, reader=reader, read_plate_text=False)

        assert detector.calls > 0
        assert reader.calls == 0
        assert any(track.plates for row in result.timeline for track in row.tracks)

    def test_sans_detect_plates_rien_ne_tourne(self) -> None:
        """Lire sans détecter n'a pas de sens : il n'y aurait aucune boîte."""
        detector, reader = FakePlateDetector(), FakePlateReader()
        _run(detector=detector, reader=reader, detect_plates=False, read_plate_text=True)

        assert detector.calls == 0
        assert reader.calls == 0

    def test_un_lecteur_qui_viole_son_contrat_ne_casse_pas_l_analyse(self) -> None:
        """Longueur de retour inattendue : on renonce au texte, pas au comptage."""
        result = _run(reader=FakePlateReader(bad_length=True))

        assert _texts(result) == []
        assert result.stats.crossings == 2
        assert any(track.plates for row in result.timeline for track in row.tracks)

    def test_une_plaque_illisible_garde_sa_boite(self) -> None:
        """« Vue mais illisible » : l'état que l'interface rate le plus facilement."""
        result = _run(reader=FakePlateReader(is_readable=lambda _box: False))

        assert _texts(result) == []
        assert any(track.plates for row in result.timeline for track in row.tracks)
        assert all(record.plate_text is None for record in result.vehicles)
        assert all(record.best_plate_score is not None for record in result.vehicles)


class TestEtranglement:
    def test_un_vote_etabli_arrete_les_inferences(self) -> None:
        """La plus grosse économie du dispositif, mesurée.

        16 frames × 2 pistes = 32 occasions. La cadence en écarte les deux tiers, et
        l'arrêt sur confiance le reste dès que chaque véhicule a trois lectures
        concordantes. La borne est un **compte**, jamais une durée.
        """
        reader = FakePlateReader()
        _run(reader=reader, steps=16)

        assert reader.crops <= 8

    def test_la_cadence_seule_ecarte_deja_des_inferences(self) -> None:
        reader = FakePlateReader()
        _run(
            reader=reader,
            ocr=PlateOcrOptions(every_n_frames=4, stop_when_confident=False, skip_above_iou=1.0),
            steps=16,
        )

        assert 0 < reader.crops < 32

    def test_sans_etranglement_chaque_piste_est_lue_a_chaque_frame(self) -> None:
        """Le témoin : il donne son sens aux bornes des deux tests précédents.

        **Les deux étranglements doivent être désarmés**, et pas seulement celui de
        l'OCR : le lecteur ne voit que des boîtes *mesurées*, donc étrangler le
        détecteur borne mécaniquement les lectures. Ne désarmer que l'OCR mesurerait
        la cadence du détecteur en croyant mesurer l'absence d'étranglement.
        """
        reader = FakePlateReader()
        _run(
            reader=reader,
            ocr=PlateOcrOptions(every_n_frames=1, stop_when_confident=False, skip_above_iou=1.0),
            detect=PlateDetectOptions(every_n_frames=1, stop_when_confident=False),
            steps=16,
        )

        assert reader.crops > 20


class TestEtranglementDuDetecteur:
    """L'étranglement du détecteur, et l'ancre qui le rend invisible.

    Le détecteur tournait une fois par piste et par image analysée : une inférence
    640×640 chacune, soit le poste dominant du coût de l'ANPR. L'objection qui
    l'interdisait — les rectangles clignoteraient — tombe dès lors que les images
    sautées reçoivent une reprojection plutôt que rien. Ces trois tests vérifient
    les trois moitiés de cette phrase : l'économie, l'absence de clignotement, et
    le fait qu'une extrapolation ne vote jamais.
    """

    def test_le_detecteur_tourne_environ_une_image_sur_trois(self) -> None:
        """L'économie, mesurée en **appels** et jamais en durée."""
        detector = FakePlateDetector()
        _run(detector=detector, reader=None, steps=30)

        # 30 images × 2 pistes = 60 recadrages sans étranglement. À une image sur
        # trois, on en attend environ le tiers.
        assert 0 < detector.crops <= 60 / 3 + 4

    def test_chaque_image_porte_une_boite_pour_chaque_piste(self) -> None:
        """**Le non-clignotement, qui est tout l'objet de l'ancre.**

        C'est la propriété qui autorisait l'étranglement : une image sautée doit
        porter une boîte reprojetée, pas un trou. Un seul trou et le rectangle
        disparaît à l'écran une image sur trois — ce que l'utilisateur lit comme un
        défaut de détection.

        Les toutes premières images sont exclues : une piste n'a pas encore d'ancre
        avant sa première détection réelle, et il n'y a alors rien à reprojeter.
        """
        result = _run(reader=None, steps=30)

        rows = result.timeline[3:]
        assert rows
        for row in rows:
            for track in row.tracks:
                assert track.plates, (
                    f"image {row.frame_index}, piste {track.track_id} : aucune plaque — "
                    "un rectangle clignoterait ici"
                )

    def test_l_ocr_ne_lit_jamais_une_boite_reprojetee(self) -> None:
        """**L'invariant qui protège le vote.**

        Une reprojection n'est pas une mesure : la faire voter fabriquerait de la
        confiance à partir de rien, et deux relectures du même clip pourraient
        publier deux plaques (invariant 4). Le journal du lecteur dit *quelles*
        boîtes il a vues ; aucune ne doit être `stale`.
        """
        reader = FakePlateReader()
        result = _run(reader=reader, steps=30)

        stale_boxes = {
            (plate.box.x, plate.box.y)
            for row in result.timeline
            for track in row.tracks
            for plate in track.plates
            if plate.stale
        }
        assert stale_boxes, "aucune reprojection : le scénario ne teste rien"
        assert reader.read_boxes, "aucune lecture : le scénario ne teste rien"
        for box in reader.read_boxes:
            assert (box.x, box.y) not in stale_boxes

    def test_les_boites_reprojetees_sont_marquees_stale(self) -> None:
        """Le drapeau doit traverser jusqu'à la timeline : c'est lui qui permet au
        canvas de dessiner une estimation d'un trait plus fin qu'une mesure."""
        result = _run(reader=None, steps=30)

        plates = [
            plate for row in result.timeline for track in row.tracks for plate in track.plates
        ]
        assert any(plate.stale for plate in plates)
        assert any(not plate.stale for plate in plates)

    def test_une_piste_trop_etroite_ne_coute_aucune_inference(self) -> None:
        """La garde de taille, vue depuis le service.

        Un véhicule de 80 px porte une plaque d'une douzaine de pixels : la
        détecter coûterait sans rien pouvoir trouver.
        """
        detector = FakePlateDetector()
        service = AnalysisService(
            FakeEngine(  # type: ignore[arg-type]
                compose(
                    track_path(
                        1,
                        CAR,
                        straight_line((700.0, 250.0), (700.0, 800.0), steps=16),
                        box_size=(80.0, 60.0),
                    )
                )
            ),
            detector,
        )
        service.run_video(
            "job-etroit",
            VIDEO,
            AnalysisJobConfig(model_id="yolov8n", lines=(make_line(),), detect_plates=True),
        )

        assert detector.calls == 0


class TestPlafondParImage:
    """Le plafond de dépense, vu du service : combien de recadrages partent vraiment.

    Le classement lui-même est testé dans le domaine (`test_plate_detect_policy.py`).
    Ce qui ne peut se vérifier qu'ici est le **câblage** : que le plafond s'applique
    après les gardes, que les pistes écartées reçoivent quand même leur rectangle, et
    qu'un plafond non posé ne change rien.
    """

    @staticmethod
    def _service(detector: FakePlateDetector, budget: int) -> AnalysisResultData:
        service = AnalysisService(
            FakeEngine(_wide_and_narrow()),  # type: ignore[arg-type]
            detector,
            None,
            None,
            PlateDetectOptions(max_per_frame=budget),
        )
        return service.run_video(
            "job-budget",
            VIDEO,
            AnalysisJobConfig(model_id="yolov8n", lines=(make_line(),), detect_plates=True),
        )

    def test_sans_plafond_une_image_peut_soumettre_les_deux_pistes(self) -> None:
        """Le témoin. Sans lui, le test suivant pourrait passer parce que la scène ne
        soumet jamais deux recadrages, et non parce que le plafond travaille."""
        detector = FakePlateDetector()

        self._service(detector, 0)

        assert max(len(boxes) for boxes in detector.submitted) == 2

    def test_un_plafond_de_un_ne_soumet_jamais_deux_recadrages(self) -> None:
        """Le coût de l'étage est linéaire en recadrages — 21,5 ms pour un, 139,7 pour
        huit sur une vraie carte. Plafonner le nombre est donc plafonner le coût."""
        detector = FakePlateDetector()

        self._service(detector, 1)

        assert detector.submitted
        assert max(len(boxes) for boxes in detector.submitted) == 1

    def test_une_piste_ecartee_garde_son_rectangle(self) -> None:
        """**Ce qui est écarté n'est pas perdu.** La piste reçoit l'ancre reprojetée,
        exactement comme sur une image sautée par la cadence : sans cela, plafonner
        ferait clignoter les rectangles, ce qu'ADR 0010 existe pour supprimer.

        Les deux pistes sont mesurées dans les deux premières images — une piste jamais
        mesurée passe avant une plus large — puis chacune vit sur son ancre les images
        où elle n'est pas servie.
        """
        result = self._service(FakePlateDetector(), 1)

        muettes = [
            (row.frame_index, track.global_id)
            for row in result.timeline[2:]
            for track in row.tracks
            if not track.plates
        ]
        assert muettes == []


class TestPlancherDeLecture:
    """« Confiance lecture » : le plancher de confiance d'une **lecture**.

    Il existait déjà, mais seulement comme réglage de **déploiement**
    (`plate_ocr_min_text_score`) : l'utilisateur devant sa vidéo ne pouvait pas
    arbitrer « des plaques fausses, ou pas de plaques ». Il voyage désormais par
    requête, exactement comme `plate_confidence`, et descend jusqu'à l'adaptateur en
    argument de `read`.

    Ces tests portent sur le **câblage**, qui est ce qui manquait : le seuil doit
    arriver au lecteur, et un lecteur qui le refuse doit laisser le véhicule sans
    plaque plutôt qu'avec une plaque incertaine.
    """

    def test_le_plancher_de_la_requete_arrive_au_lecteur(self) -> None:
        """Le mode de panne visé : un réglage accepté au contrat et sans effet.

        C'est l'état où `plate_confidence` est resté jusqu'à ADR 0007, et il ne se
        voit d'aucune façon — l'écran affiche le curseur, le serveur accepte la
        requête, et rien ne change dans les chiffres.
        """
        reader = FakePlateReader()
        _run(reader=reader, plate_text_confidence=0.80)

        assert reader.min_scores
        assert set(reader.min_scores) == {0.80}

    def test_sans_plancher_de_requete_le_lecteur_garde_celui_du_deploiement(self) -> None:
        """`None` n'est pas `0` : il veut dire « garde ton réglage », pas « accepte tout »."""
        reader = FakePlateReader()
        _run(reader=reader)

        assert reader.min_scores
        assert set(reader.min_scores) == {None}

    def test_une_lecture_sous_le_plancher_ne_publie_aucune_plaque(self) -> None:
        """Un refus, jamais un texte étiqueté « peu sûr » : une chaîne affichée est crue.

        Le lecteur rend 0,93 ; à 0,95 exigés, plus rien ne traverse le port, donc
        rien ne vote — et le registre reste muet au lieu d'afficher une hésitation.
        """
        result = _run(reader=FakePlateReader(text="ab-123-cd"), plate_text_confidence=0.95)

        assert result.vehicles
        assert all(record.plate_text is None for record in result.vehicles)
        assert not _texts(result)

    def test_au_plancher_exact_la_lecture_passe(self) -> None:
        """Comparaison **inclusive**, comme celle du vrai lecteur (`>=`).

        Un seuil exclusif ferait qu'un curseur posé sur la valeur affichée par le
        registre rejetterait précisément la lecture qu'on cherchait à garder.
        """
        result = _run(reader=FakePlateReader(text="ab-123-cd"), plate_text_confidence=0.93)

        assert result.vehicles
        assert all(record.plate_text == "AB-123-CD" for record in result.vehicles)


class TestPorteDeLisibilite:
    """La porte qui refuse de payer pour une plaque prouvée illisible — ADR 0039.

    Mesuré sur une vue de circulation réelle : la détection de plaques pèse 73 % du
    budget et **aucune plaque n'y est publiable**, les plaques faisant moins de
    48 px pour un plancher de lecture à 64. Ces tests vérifient les deux moitiés de
    la promesse — l'économie est réelle, et elle ne coûte aucun texte.
    """

    #: Une plaque de 20 px sur un véhicule de 160 : rapport 0,125, donc il faudrait
    #: 512 px de véhicule pour atteindre le plancher de lecture de 64.
    @staticmethod
    def _narrow(box: BoundingBox) -> tuple[tuple[BoundingBox, float], ...]:
        return (
            (
                BoundingBox(
                    x=box.x + 20.0,
                    y=box.y + box.height * 0.6,
                    width=20.0,
                    height=8.0,
                ),
                0.8,
            ),
        )

    def _crops(self, *, gate: bool) -> tuple[int, list[str]]:
        detector = FakePlateDetector(plates_for=self._narrow)
        result = _run(
            detector=detector,
            reader=FakePlateReader(),
            # La cadence et l'arrêt sur vote désarmés : la porte doit être la
            # **seule** chose qui écarte des inférences, sinon le test mesurerait
            # un étranglement pour un autre.
            detect=PlateDetectOptions(
                every_n_frames=1,
                stop_when_confident=False,
                max_consecutive_misses=99,
                readable_gate=gate,
            ),
            ocr=PlateOcrOptions(every_n_frames=1, stop_when_confident=False, skip_above_iou=1.0),
            steps=16,
        )
        return detector.crops, _texts(result)

    def test_la_porte_effondre_le_nombre_d_inferences(self) -> None:
        with_gate, _ = self._crops(gate=True)
        without_gate, _ = self._crops(gate=False)

        assert with_gate < without_gate

    def test_et_elle_ne_coute_aucun_texte(self) -> None:
        """**La moitié qui rend la porte livrable.**

        Le plancher comparé est celui-là même dont `PlateOcrPolicy.should_read` se
        sert pour refuser de lire : une plaque écartée par la porte est une plaque
        que l'OCR aurait refusée. Les deux courses doivent donc publier exactement
        les mêmes textes — ici aucun, puisque 20 px est très en dessous de 64.
        """
        _, with_gate = self._crops(gate=True)
        _, without_gate = self._crops(gate=False)

        assert with_gate == without_gate

    def test_la_porte_reste_inerte_sans_ocr(self) -> None:
        """Sans lecture, un rectangle sur une plaque de 20 px est ce qui est demandé.

        Le service ne pose le plancher que si un lecteur tourne réellement : couper
        la détection au nom d'un texte que personne n'attend retirerait à
        l'utilisateur la fonctionnalité qu'il a cochée.
        """
        detector = FakePlateDetector(plates_for=self._narrow)
        _run(
            detector=detector,
            read_plate_text=False,
            detect=PlateDetectOptions(
                every_n_frames=1, stop_when_confident=False, max_consecutive_misses=99
            ),
            steps=16,
        )

        without_gate = FakePlateDetector(plates_for=self._narrow)
        _run(
            detector=without_gate,
            read_plate_text=False,
            detect=PlateDetectOptions(
                every_n_frames=1,
                stop_when_confident=False,
                max_consecutive_misses=99,
                readable_gate=False,
            ),
            steps=16,
        )

        assert detector.crops == without_gate.crops
