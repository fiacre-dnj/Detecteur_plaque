"""Ré-identification longue durée — prompt/03 §5.

BoT-SORT maintient l'identité à travers les occlusions **courtes**. Au-delà, l'id
de piste change et le véhicule serait compté comme neuf. La galerie donne une
identité globale qui survit à la disparition : c'est elle qui distingue
« véhicules uniques » de « passages ».

Quatre tests portent chacun un bug déjà payé :

- `test_deux_vehicules_sans_rapport_ont_une_similarite_proche_de_zero` : sans
  centrage avant normalisation, deux véhicules **sans rapport** scorent ~0,7 et la
  plage utile du cosinus s'écrase ;
- `test_un_saut_impossible_est_refuse_avant_tout_scoring` : sans gate de
  déplacement, une voiture rouge entrant en haut hérite de l'identité d'une
  voiture rouge sortie en bas, et le vrai second véhicule n'est jamais compté ;
- `test_une_moto_n_herite_pas_de_l_identite_d_une_voiture` : c'est la pénalité de
  **forme** qui sépare les classes, pas la pénalité de classe ;
- `test_l_elagage_ne_fait_pas_baisser_le_nombre_de_vehicules_uniques` : les
  compteurs sont des compteurs d'émission, pas une vue de la galerie.
"""

from __future__ import annotations

import numpy as np
import pytest

from tests.support.builders import CAR, MOTORCYCLE, TRUCK
from traffic_analysis.features.counting.domain.geometry import Point
from traffic_analysis.features.counting.domain.models import BoundingBox
from traffic_analysis.features.counting.domain.reid import (
    IdentityGallery,
    ReidCandidate,
    ReidOptions,
    build_signature,
    similarity,
)

FRAME_DIAGONAL = 2203.0  # 1920×1080


def _image(
    colour: tuple[int, int, int],
    *,
    size: tuple[int, int] = (200, 300),
    noise: int = 0,
) -> np.ndarray:
    """Image unie, éventuellement bruitée, aux dimensions (hauteur, largeur)."""
    height, width = size
    image = np.zeros((height, width, 3), dtype=np.uint8)
    image[:, :] = colour
    if noise:
        rng = np.random.default_rng(seed=1234)
        jitter = rng.integers(-noise, noise + 1, size=image.shape, dtype=np.int16)
        image = np.clip(image.astype(np.int16) + jitter, 0, 255).astype(np.uint8)
    return image


def _textured_image(base: tuple[int, int, int], *, stripe: tuple[int, int, int]) -> np.ndarray:
    """Image à bandes : deux véhicules de teinte proche mais de motif différent."""
    image = _image(base)
    image[::4, :] = stripe
    return image


BOX = BoundingBox(10.0, 10.0, 120.0, 80.0)


def _candidate(
    track_id: int,
    class_id: int,
    label: str,
    image: np.ndarray,
    centroid: tuple[float, float],
    *,
    box: BoundingBox = BOX,
) -> ReidCandidate:
    return ReidCandidate(
        track_id=track_id,
        class_id=class_id,
        label=label,
        centroid=Point(*centroid),
        signature=build_signature(image, box),
    )


class TestDescripteur:
    def test_le_meme_objet_score_un(self) -> None:
        signature = build_signature(_image((30, 60, 200)), BOX)

        assert signature is not None
        assert similarity(signature, signature) == pytest.approx(1.0, abs=1e-5)

    def test_deux_vehicules_sans_rapport_ont_une_similarite_proche_de_zero(self) -> None:
        """LE test du centrage.

        Toutes les composantes du descripteur étant des intensités positives,
        deux véhicules **sans rapport** scoraient ~0,7 sans centrage : la plage
        utile du cosinus s'écrasait, et il devenait impossible de choisir un seuil.
        Mesuré après centrage : même objet 1,00, objets différents ≈ 0,01.
        """
        rouge = build_signature(_textured_image((20, 20, 200), stripe=(240, 240, 240)), BOX)
        vert = build_signature(_textured_image((20, 200, 20), stripe=(10, 10, 10)), BOX)

        assert rouge is not None
        assert vert is not None
        assert similarity(rouge, vert) < 0.5

    def test_le_meme_vehicule_legerement_bruite_reste_tres_similaire(self) -> None:
        """Le cas réel : le même véhicule sur deux frames voisines.

        Compression, éclairage et tremblement de boîte bougent les pixels ; le
        descripteur doit y résister, sinon chaque retour légitime devient une
        identité neuve et un second franchissement.
        """
        propre = build_signature(_textured_image((40, 90, 180), stripe=(230, 230, 230)), BOX)
        bruite = build_signature(
            _textured_image((45, 95, 185), stripe=(225, 228, 232)),
            BOX,
        )

        assert propre is not None
        assert bruite is not None
        assert similarity(propre, bruite) > 0.8

    def test_le_descripteur_fait_soixante_quatre_valeurs(self) -> None:
        """48 valeurs de grille RGB 4×4 + 16 bins de teinte."""
        signature = build_signature(_image((100, 100, 100)), BOX)

        assert signature is not None
        assert signature.values.shape == (64,)

    def test_le_descripteur_est_norme(self) -> None:
        signature = build_signature(_textured_image((10, 120, 240), stripe=(0, 0, 0)), BOX)

        assert signature is not None
        assert float(np.linalg.norm(signature.values)) == pytest.approx(1.0, abs=1e-5)

    def test_une_boite_trop_petite_ne_donne_pas_de_signature(self) -> None:
        """Sous 20 px de côté, il n'y a pas assez de pixels pour décrire quoi que
        ce soit. Deviner sur du bruit est pire que créer une identité neuve."""
        assert build_signature(_image((50, 50, 50)), BoundingBox(0.0, 0.0, 19.0, 80.0)) is None
        assert build_signature(_image((50, 50, 50)), BoundingBox(0.0, 0.0, 80.0, 19.0)) is None

    def test_une_boite_hors_de_l_image_ne_donne_pas_de_signature(self) -> None:
        """Le suivi extrapole parfois une boîte au-delà du bord de l'image."""
        assert (
            build_signature(_image((50, 50, 50)), BoundingBox(5000.0, 5000.0, 80.0, 80.0)) is None
        )

    def test_le_rapport_de_forme_est_conserve_a_cote_du_descripteur(self) -> None:
        signature = build_signature(_image((50, 50, 50)), BoundingBox(0.0, 0.0, 150.0, 50.0))

        assert signature is not None
        assert signature.aspect == pytest.approx(3.0)


class TestAdmission:
    def test_un_candidat_inconnu_recoit_une_identite_neuve(self) -> None:
        gallery = IdentityGallery(ReidOptions())
        candidate = _candidate(1, CAR, "car", _image((200, 30, 30)), (500.0, 500.0))

        admissions = gallery.admit_batch((candidate,), 0.0, FRAME_DIAGONAL)

        assert len(admissions) == 1
        assert admissions[0].global_id == 1
        assert admissions[0].reidentified is False
        assert gallery.size == 1

    def test_un_candidat_sans_signature_recoit_aussi_une_identite_neuve(self) -> None:
        """Deviner sur du bruit est pire que créer une identité.

        Une petite boîte non appariable devient un véhicule de plus — au pire on
        surcompte d'un, alors qu'un mauvais appariement perdrait *deux* véhicules :
        celui qui hérite à tort, et le vrai.
        """
        gallery = IdentityGallery(ReidOptions())
        candidate = ReidCandidate(
            track_id=1, class_id=CAR, label="car", centroid=Point(0.0, 0.0), signature=None
        )

        admissions = gallery.admit_batch((candidate,), 0.0, FRAME_DIAGONAL)

        assert admissions[0].global_id == 1
        assert admissions[0].reidentified is False

    def test_une_identite_portee_par_une_piste_vivante_est_ineligible(self) -> None:
        """Deux voitures identiques à l'écran restent deux voitures.

        Sans exclusivité, la seconde hériterait de l'identité de la première et ne
        serait jamais comptée.
        """
        gallery = IdentityGallery(ReidOptions())
        image = _textured_image((200, 30, 30), stripe=(255, 255, 255))
        premiere = _candidate(1, CAR, "car", image, (500.0, 500.0))
        gallery.admit_batch((premiere,), 0.0, FRAME_DIAGONAL)

        # Piste 2, apparence identique, alors que la piste 1 est toujours vivante.
        seconde = _candidate(2, CAR, "car", image, (520.0, 500.0))
        admissions = gallery.admit_batch((seconde,), 40.0, FRAME_DIAGONAL)

        assert admissions[0].global_id == 2
        assert admissions[0].reidentified is False
        assert gallery.size == 2

    def test_une_identite_relachee_est_retrouvee_par_apparence(self) -> None:
        """Le cas nominal : véhicule occulté, piste détruite, retour reconnu."""
        gallery = IdentityGallery(ReidOptions())
        image = _textured_image((200, 30, 30), stripe=(255, 255, 255))
        gallery.admit_batch(
            (_candidate(1, CAR, "car", image, (500.0, 500.0)),), 0.0, FRAME_DIAGONAL
        )
        gallery.release(1, 0.0, Point(500.0, 500.0))

        retour = _candidate(9, CAR, "car", image, (560.0, 520.0))
        admissions = gallery.admit_batch((retour,), 300.0, FRAME_DIAGONAL)

        assert admissions[0].global_id == 1
        assert admissions[0].reidentified is True
        assert gallery.size == 1
        assert gallery.hits == 1

    def test_min_gap_ms_vaut_zero_pour_permettre_le_match_dans_le_meme_appel(self) -> None:
        """Le tracker détruit une piste morte et crée sa remplaçante dans le
        *même* appel : un écart minimum non nul refuserait le match légitime
        (piège 4 de prompt/13)."""
        assert ReidOptions().min_gap_ms == 0.0

        gallery = IdentityGallery(ReidOptions())
        image = _textured_image((200, 30, 30), stripe=(255, 255, 255))
        gallery.admit_batch(
            (_candidate(1, CAR, "car", image, (500.0, 500.0)),), 100.0, FRAME_DIAGONAL
        )
        gallery.release(1, 100.0, Point(500.0, 500.0))

        # Même horodatage : écart nul.
        admissions = gallery.admit_batch(
            (_candidate(2, CAR, "car", image, (510.0, 505.0)),), 100.0, FRAME_DIAGONAL
        )

        assert admissions[0].global_id == 1

    def test_un_retour_trop_tardif_devient_une_identite_neuve(self) -> None:
        gallery = IdentityGallery(ReidOptions())
        image = _textured_image((200, 30, 30), stripe=(255, 255, 255))
        gallery.admit_batch(
            (_candidate(1, CAR, "car", image, (500.0, 500.0)),), 0.0, FRAME_DIAGONAL
        )
        gallery.release(1, 0.0, Point(500.0, 500.0))

        tardif = _candidate(9, CAR, "car", image, (500.0, 500.0))
        admissions = gallery.admit_batch((tardif,), 60_000.0, FRAME_DIAGONAL)

        assert admissions[0].global_id == 2
        assert gallery.size == 2


class TestGateDeDeplacement:
    def test_un_saut_impossible_est_refuse_avant_tout_scoring(self) -> None:
        """Le bug des sosies.

        Une voiture rouge sort en bas de l'image ; 200 ms plus tard une voiture
        rouge entre en haut. Sans gate, la seconde hérite de l'identité de la
        première — et le vrai second véhicule n'est jamais compté.
        """
        gallery = IdentityGallery(ReidOptions())
        image = _textured_image((200, 30, 30), stripe=(255, 255, 255))
        gallery.admit_batch(
            (_candidate(1, CAR, "car", image, (900.0, 1000.0)),), 0.0, FRAME_DIAGONAL
        )
        gallery.release(1, 0.0, Point(900.0, 1000.0))

        # Apparence identique, mais à l'autre bout de l'image en 200 ms.
        arrivee = _candidate(2, CAR, "car", image, (900.0, 40.0))
        admissions = gallery.admit_batch((arrivee,), 200.0, FRAME_DIAGONAL)

        assert admissions[0].global_id == 2
        assert admissions[0].reidentified is False

    def test_le_budget_de_deplacement_croit_avec_le_temps_ecoule(self) -> None:
        """Un véhicule absent 3 s a pu aller loin ; absent 200 ms, non.

        Un budget fixe serait soit trop serré pour les longues occlusions, soit
        trop large pour les courtes — et c'est sur les courtes que les sosies se
        confondent.
        """
        options = ReidOptions()
        image = _textured_image((200, 30, 30), stripe=(255, 255, 255))

        gallery = IdentityGallery(options)
        gallery.admit_batch(
            (_candidate(1, CAR, "car", image, (900.0, 1000.0)),), 0.0, FRAME_DIAGONAL
        )
        gallery.release(1, 0.0, Point(900.0, 1000.0))

        # Même saut, mais 3 secondes plus tard : le budget suffit désormais.
        admissions = gallery.admit_batch(
            (_candidate(2, CAR, "car", image, (900.0, 40.0)),), 3000.0, FRAME_DIAGONAL
        )

        assert admissions[0].global_id == 1
        assert admissions[0].reidentified is True


class TestPenalites:
    def test_une_moto_n_herite_pas_de_l_identite_d_une_voiture(self) -> None:
        """C'est la pénalité de **forme** qui sépare les classes.

        La pénalité de classe reste volontairement petite parce que car, bus et
        truck sont réellement confondus par le détecteur et doivent rester
        appariables. Une moto (~0,7 de rapport) et une voiture (~1,5) donnent en
        revanche une pénalité de forme d'environ 0,25 : assez pour mettre
        l'identité d'une voiture hors de portée.
        """
        gallery = IdentityGallery(ReidOptions())
        image = _textured_image((200, 30, 30), stripe=(255, 255, 255))
        voiture_box = BoundingBox(10.0, 10.0, 150.0, 100.0)  # rapport 1,5
        moto_box = BoundingBox(10.0, 10.0, 56.0, 80.0)  # rapport 0,7

        gallery.admit_batch(
            (_candidate(1, CAR, "car", image, (900.0, 500.0), box=voiture_box),),
            0.0,
            FRAME_DIAGONAL,
        )
        gallery.release(1, 0.0, Point(900.0, 500.0))

        moto = _candidate(2, MOTORCYCLE, "motorcycle", image, (910.0, 505.0), box=moto_box)
        admissions = gallery.admit_batch((moto,), 200.0, FRAME_DIAGONAL)

        assert admissions[0].global_id == 2
        assert admissions[0].reidentified is False

    def test_un_camion_relu_comme_voiture_retrouve_son_identite(self) -> None:
        """Le pendant du test précédent.

        car/bus/truck sont réellement confondus par le détecteur : la pénalité de
        classe est petite exprès. Refuser ce match ferait compter deux fois chaque
        camion dont la classe vacille.
        """
        gallery = IdentityGallery(ReidOptions())
        image = _textured_image((90, 90, 200), stripe=(240, 240, 240))
        box = BoundingBox(10.0, 10.0, 150.0, 100.0)

        gallery.admit_batch(
            (_candidate(1, TRUCK, "truck", image, (900.0, 500.0), box=box),), 0.0, FRAME_DIAGONAL
        )
        gallery.release(1, 0.0, Point(900.0, 500.0))

        relu = _candidate(2, CAR, "car", image, (930.0, 510.0), box=box)
        admissions = gallery.admit_batch((relu,), 200.0, FRAME_DIAGONAL)

        assert admissions[0].global_id == 1
        assert admissions[0].reidentified is True

    def test_la_penalite_de_classe_est_petite_et_celle_de_forme_dominante(self) -> None:
        """Les deux valeurs qui font tenir les deux tests précédents ensemble."""
        options = ReidOptions()

        assert options.class_mismatch_penalty == pytest.approx(0.12)
        assert options.aspect_penalty_weight == pytest.approx(0.30)


class TestGloutonBestFirst:
    def test_deux_arrivees_ne_revendiquent_pas_la_meme_identite(self) -> None:
        """Un candidat et une entrée ne sont pris qu'une fois.

        Sans exclusivité mutuelle, deux véhicules qui se ressemblent hériteraient
        tous deux de la même identité, et l'un des deux ne serait jamais compté.
        """
        gallery = IdentityGallery(ReidOptions())
        rouge = _textured_image((200, 30, 30), stripe=(255, 255, 255))
        bleu = _textured_image((30, 30, 200), stripe=(0, 0, 0))

        gallery.admit_batch(
            (
                _candidate(1, CAR, "car", rouge, (600.0, 500.0)),
                _candidate(2, CAR, "car", bleu, (700.0, 500.0)),
            ),
            0.0,
            FRAME_DIAGONAL,
        )
        gallery.release(1, 0.0, Point(600.0, 500.0))
        gallery.release(2, 0.0, Point(700.0, 500.0))

        admissions = gallery.admit_batch(
            (
                _candidate(11, CAR, "car", rouge, (610.0, 505.0)),
                _candidate(12, CAR, "car", rouge, (620.0, 510.0)),
            ),
            200.0,
            FRAME_DIAGONAL,
        )

        assigned = {admission.global_id for admission in admissions}
        assert len(assigned) == 2, "deux candidats ont reçu la même identité"

    def test_le_meilleur_couple_est_apparie_en_premier(self) -> None:
        """Tri par score décroissant : le match le plus sûr gagne sa cible.

        Un appariement dans l'ordre d'arrivée donnerait l'identité au premier
        candidat venu, même si un suivant lui ressemble bien davantage.
        """
        gallery = IdentityGallery(ReidOptions())
        rouge = _textured_image((200, 30, 30), stripe=(255, 255, 255))
        bleu = _textured_image((30, 30, 200), stripe=(0, 0, 0))

        gallery.admit_batch((_candidate(1, CAR, "car", bleu, (600.0, 500.0)),), 0.0, FRAME_DIAGONAL)
        gallery.release(1, 0.0, Point(600.0, 500.0))

        # Le rouge arrive d'abord, le bleu ensuite : c'est le bleu qui doit
        # récupérer l'identité 1.
        admissions = gallery.admit_batch(
            (
                _candidate(11, CAR, "car", rouge, (605.0, 502.0)),
                _candidate(12, CAR, "car", bleu, (610.0, 505.0)),
            ),
            200.0,
            FRAME_DIAGONAL,
        )

        by_track = {admission.track_id: admission for admission in admissions}
        assert by_track[12].global_id == 1
        assert by_track[12].reidentified is True
        assert by_track[11].reidentified is False


class TestVoteDeClasse:
    def test_la_majorite_determine_le_libelle(self) -> None:
        gallery = IdentityGallery(ReidOptions())
        image = _image((200, 30, 30))
        gallery.admit_batch(
            (_candidate(1, CAR, "car", image, (500.0, 500.0)),), 0.0, FRAME_DIAGONAL
        )

        gallery.vote(1, TRUCK, "truck")
        gallery.vote(1, TRUCK, "truck")

        assert gallery.label_of(1) == "truck"

    def test_une_egalite_laisse_le_tenant_en_place(self) -> None:
        """Une lecture qui alterne bus/camion ne doit jamais faire osciller un
        véhicule entre deux compteurs."""
        gallery = IdentityGallery(ReidOptions())
        image = _image((200, 30, 30))
        gallery.admit_batch(
            (_candidate(1, BUS := 5, "bus", image, (500.0, 500.0)),), 0.0, FRAME_DIAGONAL
        )
        assert BUS == 5

        gallery.vote(1, TRUCK, "truck")  # 1 voix chacun

        assert gallery.label_of(1) == "bus"

    def test_la_repartition_par_classe_somme_toujours_au_nombre_d_uniques(self) -> None:
        """Quand la majorité change, le vote unique de l'identité **déménage**.

        Sans ce transfert, la répartition par type afficherait plus de véhicules
        que le total, ce que l'utilisateur voit immédiatement.
        """
        gallery = IdentityGallery(ReidOptions())
        image = _textured_image((200, 30, 30), stripe=(255, 255, 255))
        autre = _textured_image((30, 200, 30), stripe=(0, 0, 0))
        gallery.admit_batch(
            (
                _candidate(1, CAR, "car", image, (400.0, 400.0)),
                _candidate(2, CAR, "car", autre, (900.0, 900.0)),
            ),
            0.0,
            FRAME_DIAGONAL,
        )
        assert sum(gallery.count_by_class().values()) == gallery.size

        for _ in range(3):
            gallery.vote(1, TRUCK, "truck")

        assert gallery.label_of(1) == "truck"
        assert gallery.count_by_class() == {"car": 1, "truck": 1}
        assert sum(gallery.count_by_class().values()) == gallery.size


class TestReacquisitionEtRelease:
    def test_reacquerir_une_identite_relachee_compte_comme_une_reidentification(self) -> None:
        """BoT-SORT peut ressusciter un id de piste : c'est une vraie récupération."""
        gallery = IdentityGallery(ReidOptions())
        image = _image((200, 30, 30))
        gallery.admit_batch(
            (_candidate(1, CAR, "car", image, (500.0, 500.0)),), 0.0, FRAME_DIAGONAL
        )
        gallery.release(1, 0.0, Point(500.0, 500.0))

        recovered = gallery.reacquire(1, track_id=1, now_ms=200.0, centroid=Point(510.0, 505.0))

        assert recovered is True
        assert gallery.hits == 1

    def test_relier_une_identite_deja_vivante_ne_compte_pas(self) -> None:
        """C'est de la tenue de registre, pas une ré-identification.

        Le compter ferait mentir la carte « Ré-identifications » de l'interface.
        """
        gallery = IdentityGallery(ReidOptions())
        image = _image((200, 30, 30))
        gallery.admit_batch(
            (_candidate(1, CAR, "car", image, (500.0, 500.0)),), 0.0, FRAME_DIAGONAL
        )

        recovered = gallery.reacquire(1, track_id=1, now_ms=40.0, centroid=Point(505.0, 500.0))

        assert recovered is False
        assert gallery.hits == 0

    def test_release_date_du_dernier_instant_vu_et_non_de_la_mort_de_la_piste(self) -> None:
        """Piège 14 de prompt/13, et il est subtil.

        La piste ne meurt qu'après avoir « planté » `max_lost_ms`. Dater le release
        à « maintenant » sous-estime l'écart de jusqu'à 2,5 s, affame le budget de
        déplacement, rejette le retour légitime — qui devient une identité neuve et
        un second comptage.

        Ici le véhicule est vu à t=0 puis relâché à t=0 (son dernier instant vu)
        alors que la session est à t=2500. Le budget est calculé depuis l'écart
        réel, et le retour est accepté.
        """
        gallery = IdentityGallery(ReidOptions())
        image = _textured_image((200, 30, 30), stripe=(255, 255, 255))
        gallery.admit_batch(
            (_candidate(1, CAR, "car", image, (900.0, 900.0)),), 0.0, FRAME_DIAGONAL
        )

        gallery.release(1, 0.0, Point(900.0, 900.0))  # daté du dernier instant vu
        admissions = gallery.admit_batch(
            (_candidate(2, CAR, "car", image, (900.0, 200.0)),), 2600.0, FRAME_DIAGONAL
        )

        assert admissions[0].global_id == 1


class TestElagage:
    def test_l_elagage_ne_fait_pas_baisser_le_nombre_de_vehicules_uniques(self) -> None:
        """`size` et `count_by_class()` sont des compteurs d'**émission**.

        Les entrées trop vieilles sont retirées de la galerie — elles ne pouvaient
        plus matcher et ne faisaient qu'allonger chaque scan — mais les véhicules
        qu'elles représentaient restent comptés.
        """
        gallery = IdentityGallery(ReidOptions())
        image = _textured_image((200, 30, 30), stripe=(255, 255, 255))
        gallery.admit_batch(
            (_candidate(1, CAR, "car", image, (500.0, 500.0)),), 0.0, FRAME_DIAGONAL
        )
        gallery.release(1, 0.0, Point(500.0, 500.0))
        assert gallery.size == 1

        # Une admission bien plus tard déclenche l'élagage de l'entrée périmée.
        autre = _textured_image((30, 200, 30), stripe=(0, 0, 0))
        gallery.admit_batch(
            (_candidate(2, CAR, "car", autre, (500.0, 500.0)),), 90_000.0, FRAME_DIAGONAL
        )

        assert gallery.size == 2
        assert sum(gallery.count_by_class().values()) == 2

    def test_une_entree_encore_portee_n_est_jamais_elaguee(self) -> None:
        """Une piste vivante depuis longtemps ne doit pas perdre son identité.

        Un véhicule à l'arrêt dans le champ pendant deux minutes reste le même
        véhicule.
        """
        gallery = IdentityGallery(ReidOptions())
        image = _textured_image((200, 30, 30), stripe=(255, 255, 255))
        gallery.admit_batch(
            (_candidate(1, CAR, "car", image, (500.0, 500.0)),), 0.0, FRAME_DIAGONAL
        )

        gallery.admit_batch(
            (_candidate(2, CAR, "car", _image((10, 10, 10)), (100.0, 100.0)),),
            120_000.0,
            FRAME_DIAGONAL,
        )

        assert gallery.label_of(1) == "car"


class TestRafraichissementDApparence:
    def test_plusieurs_points_de_vue_sont_conserves_par_identite(self) -> None:
        """Le score retient le **meilleur** point de vue, pas leur moyenne.

        Un véhicule vu de face puis de profil a deux apparences ; les moyenner
        produirait un descripteur qui ne ressemble à aucune des deux.
        """
        options = ReidOptions()
        assert options.signatures_per_entry == 5

        gallery = IdentityGallery(options)
        de_face = _textured_image((200, 30, 30), stripe=(255, 255, 255))
        de_profil = _textured_image((30, 200, 30), stripe=(0, 0, 0))
        gallery.admit_batch(
            (_candidate(1, CAR, "car", de_face, (500.0, 500.0)),), 0.0, FRAME_DIAGONAL
        )

        profil_signature = build_signature(de_profil, BOX)
        assert profil_signature is not None
        gallery.refresh(1, profil_signature)
        gallery.release(1, 100.0, Point(500.0, 500.0))

        # Le retour ressemble au profil, pas à la face.
        admissions = gallery.admit_batch(
            (_candidate(2, CAR, "car", de_profil, (510.0, 505.0)),), 300.0, FRAME_DIAGONAL
        )

        assert admissions[0].global_id == 1

    def test_le_nombre_de_signatures_par_identite_est_borne(self) -> None:
        """Sinon chaque scan de la galerie s'allonge indéfiniment sur un clip long."""
        options = ReidOptions()
        gallery = IdentityGallery(options)
        gallery.admit_batch(
            (_candidate(1, CAR, "car", _image((200, 30, 30)), (500.0, 500.0)),), 0.0, FRAME_DIAGONAL
        )

        for shade in range(20):
            signature = build_signature(_image((shade * 10, 30, 30)), BOX)
            assert signature is not None
            gallery.refresh(1, signature)

        assert gallery.signature_count(1) == options.signatures_per_entry
