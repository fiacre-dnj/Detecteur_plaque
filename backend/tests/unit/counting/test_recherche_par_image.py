"""La recherche d'un véhicule par image de requête.

Trois propriétés, et la première est la seule qui rende cette fonctionnalité
livrable :

1. **elle ne change aucun comptage.** ADR 0016 a supprimé la galerie
   d'apparence parce qu'elle était branchée sur le compteur : un véhicule
   ré-identifié réapparaissait au milieu d'une vidéo et faussait le total. La
   recherche par image est un index de consultation, donc `crossings`,
   `tracked_vehicles` et tous les `by_line` doivent être **identiques** avec et sans
   encodeur. C'est ce que `TestAucuneRegression` vérifie sur le même clip ;
2. **elle encode une fois par véhicule, pas une fois par image.**
   `FakeVehicleEmbedder.vectors_produced` compte les vecteurs réellement produits.
   C'est ce chiffre, et non le contenu du registre, qui prouve que la règle monotone
   protège le chemin critique — un code qui encoderait à chaque image rendrait
   exactement les mêmes scores, deux ordres de grandeur plus cher, et aucun test
   portant seulement sur le résultat ne le verrait. Même raison d'être que le
   comptage d'appels d'ADR 0042 ;
3. **elle ne dépend pas de l'ANPR.** Un utilisateur qui cherche une voiture n'a
   aucune raison d'activer la lecture de plaques.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import numpy as np
import pytest

from tests.support.builders import CAR, compose, make_line, straight_line, track_path
from tests.support.engine import FakeEngine, FakeVehicleEmbedder
from traffic_analysis.features.counting.application.analysis_service import AnalysisService
from traffic_analysis.features.counting.application.dto import AnalysisJobConfig
from traffic_analysis.features.counting.domain.appearance import cosine_similarity
from traffic_analysis.features.counting.domain.models import BoundingBox, TrackObservation

if TYPE_CHECKING:
    from pathlib import Path

    from traffic_analysis.features.counting.application.dto import AnalysisResultData


CONFIG = AnalysisJobConfig(model_id="yolov8n", lines=(make_line(),))

#: Des octets quelconques : la doublure ne les décode pas, et le vrai adaptateur est
#: le seul à toucher un pixel.
QUERY = b"jpeg-de-requete"


def _frames(steps: int = 8) -> list[list[TrackObservation]]:
    """Un véhicule qui traverse la ligne."""
    return compose(track_path(1, CAR, straight_line((700.0, 250.0), (700.0, 800.0), steps=steps)))


@pytest.fixture
def video(tmp_path: Path) -> Path:
    path = tmp_path / "clip.mp4"
    path.write_bytes(b"\x00" * 16)
    return path


def _run(
    video: Path,
    *,
    embedder: FakeVehicleEmbedder | None,
    query: bytes | None = QUERY,
    min_similarity: float = 0.0,
    steps: int = 8,
) -> AnalysisResultData:
    service = AnalysisService(
        FakeEngine(_frames(steps)),
        vehicle_embedder=embedder,
        reid_min_similarity=min_similarity,
    )
    return service.run_video("job-1", video, CONFIG, query_image=query)


def _growing(steps: int = 8) -> list[list[TrackObservation]]:
    """Un véhicule qui **s'approche** : 60, 80, 100 … px de large.

    Construit à la main parce que `track_path` n'accepte qu'une taille de boîte
    **fixe**, et c'est justement l'élargissement qui est en jeu. C'est le profil qui
    rend la règle monotone seule inopérante : chaque image bat la précédente, donc
    « plus large que la meilleure vue » est vrai à chaque image.
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
                    y=250.0 + index * 80.0,
                    width=60.0 + index * 20.0,
                    height=60.0,
                ),
            )
        ]
        for index in range(steps)
    ]


def _run_growing(
    video: Path,
    *,
    improvement: float,
    steps: int = 8,
) -> FakeVehicleEmbedder:
    """Fait passer le véhicule qui s'approche, et rend la doublure pour la compter."""
    embedder = FakeVehicleEmbedder()
    service = AnalysisService(
        FakeEngine(_growing(steps)),
        vehicle_embedder=embedder,
        reid_min_similarity=0.0,
        reid_appearance_improvement=improvement,
    )
    service.run_video("job-1", video, CONFIG, query_image=QUERY)
    return embedder


class TestAucuneRegression:
    """**La propriété qui rend la fonctionnalité livrable.** ADR 0048.

    Le grief central d'ADR 0016 était l'apparence branchée sur le compteur. Ces tests
    verrouillent qu'elle ne l'est pas : à clip identique, les chiffres publiés ne
    dépendent pas de la présence d'un encodeur.
    """

    def test_les_comptages_sont_identiques_avec_et_sans_encodeur(self, video: Path) -> None:
        avec = _run(video, embedder=FakeVehicleEmbedder())
        sans = _run(video, embedder=None, query=None)

        assert avec.stats.crossings == sans.stats.crossings
        assert avec.stats.tracked_vehicles == sans.stats.tracked_vehicles
        assert avec.stats.crossed_unique == sans.stats.crossed_unique
        assert avec.stats.by_class == sans.stats.by_class
        # Les totaux **et** leur ventilation par ligne et par sens : un décalage qui
        # ne toucherait que la ventilation laisserait les totaux d'accord.
        assert {key: tally.total for key, tally in avec.stats.by_line.items()} == {
            key: tally.total for key, tally in sans.stats.by_line.items()
        }

    def test_les_horodatages_de_franchissement_ne_bougent_pas(self, video: Path) -> None:
        """Ni les comptages **ni leurs dates** : ADR 0038 date un passage de son
        intersection, et une passe supplémentaire dans la boucle ne doit pas décaler
        cet instant.
        """
        avec = _run(video, embedder=FakeVehicleEmbedder())
        sans = _run(video, embedder=None, query=None)

        assert [crossing.timestamp_ms for crossing in avec.crossings] == [
            crossing.timestamp_ms for crossing in sans.crossings
        ]

    def test_un_encodeur_sans_image_de_requete_ne_fait_rien(self, video: Path) -> None:
        """Pas de requête ⇒ pas un seul encodage. L'étage entier reste éteint.

        C'est ce qui rend l'encodeur installable sans coût : sa seule présence ne
        ralentit aucune analyse.
        """
        embedder = FakeVehicleEmbedder()
        result = _run(video, embedder=embedder, query=None)

        assert embedder.calls == 0
        assert embedder.query_calls == 0
        assert all(vehicle.match_score is None for vehicle in result.vehicles)


class TestRegleMonotone:
    """Une vue encodée n'est remplacée que par une meilleure — jamais l'inverse."""

    def test_on_encode_bien_moins_souvent_qu_on_analyse(self, video: Path) -> None:
        """**Le test qui prouve l'optimisation**, et il porte sur un compteur d'appels.

        La doublure fait croître la qualité avec la largeur de la boîte ; le clip garde
        une largeur constante, donc la première vue gagne et aucune autre ne la bat. Un
        code sans règle monotone produirait un vecteur à chaque image.
        """
        embedder = FakeVehicleEmbedder()
        _run(video, embedder=embedder, steps=8)

        # Un seul véhicule, une seule vue retenue : le vecteur de la première image
        # analysée où la piste existe. Les images suivantes ne battent pas sa qualité.
        assert embedder.vectors_produced == 1

    def test_une_meilleure_vue_remplace_la_precedente(self, video: Path) -> None:
        """Une boîte qui grandit — le véhicule s'approche — doit être réencodée.

        C'est la contrepartie de la règle : elle *suspend*, elle n'abandonne pas. Sans
        cela, un véhicule vu de loin garderait à jamais l'embedding le plus flou de sa
        vie, ce qui est exactement le contraire du but.
        """
        # Marge neutralisée : c'est la règle monotone seule qu'on éprouve ici.
        embedder = _run_growing(video, improvement=1.0)

        # Une vue de plus à chaque élargissement : la règle est strictement croissante,
        # donc chaque image bat la précédente sur ce trajet-là.
        assert embedder.vectors_produced > 1


class TestMargeDeLargeur:
    """La règle monotone **seule** ne bornait rien. ADR 0050.

    « Strictement plus large que la meilleure vue » est vrai à presque chaque image
    d'un véhicule qui approche : on payait donc jusqu'à un encodage par image
    analysée — 21,8 ms de CPU mesurés par vignette — pour un étage que la docstring
    de l'adaptateur annonçait comme « une fois par véhicule ». Ce que la mesure
    d'ADR 0048 comptait (« 8 suivis, 2 encodés ») était un nombre de *véhicules*,
    pas d'*encodages*.
    """

    def test_la_marge_borne_les_encodages_sur_la_vie_d_une_piste(self, video: Path) -> None:
        """**Le test qui prouve l'optimisation**, et il porte sur un compteur d'appels.

        Le clip va de 60 à 200 px par pas de 20. Sans marge, chaque image bat la
        précédente : huit encodages. À 1,15, la marge écarte 160 (qui ne bat pas
        140 × 1,15 = 161) et 200 (qui ne bat pas 180 × 1,15 = 207) : six.

        Le bornage est **logarithmique** en largeur, ce qui est la propriété qui
        distingue la marge d'une cadence : elle borne le *total* sur la vie d'une
        piste, indépendamment de la cadence de la vidéo.
        """
        assert _run_growing(video, improvement=1.0).vectors_produced == 8
        assert _run_growing(video, improvement=1.15).vectors_produced == 6

    def test_la_marge_par_defaut_du_service_ne_change_rien(self, video: Path) -> None:
        """`1.0` reproduit ADR 0048 au bit près : `w > best * 1.0` ≡ `w > best`.

        C'est ce qui rend le réglage strictement additif — un appelant qui ne le
        passe pas obtient exactement l'ancien comportement.
        """
        embedder = FakeVehicleEmbedder()
        service = AnalysisService(
            FakeEngine(_growing()), vehicle_embedder=embedder, reid_min_similarity=0.0
        )
        service.run_video("job-1", video, CONFIG, query_image=QUERY)

        assert embedder.vectors_produced == _run_growing(video, improvement=1.0).vectors_produced

    def test_la_premiere_vue_est_toujours_encodee(self, video: Path) -> None:
        """**Aucun véhicule candidat ne perd son score.**

        C'est ce qui sépare cette marge du mode de panne d'ADR 0029 : là-bas le
        consommateur était un *vote* qu'on affamait jusqu'à ce qu'aucun texte
        n'existe ; ici c'est un *remplacement*, et la première vue reste
        inconditionnelle. Une marge absurde ne peut refuser qu'une amélioration.
        """
        embedder = _run_growing(video, improvement=4.0)

        assert embedder.vectors_produced == 1

    def test_une_marge_absurde_ne_prive_personne_de_ressemblance(self, video: Path) -> None:
        """Le corollaire publié : le registre porte toujours un `matchScore`."""
        embedder = FakeVehicleEmbedder(similarity_for=lambda _index: 0.83)
        service = AnalysisService(
            FakeEngine(_growing()),
            vehicle_embedder=embedder,
            reid_min_similarity=0.0,
            reid_appearance_improvement=4.0,
        )

        result = service.run_video("job-1", video, CONFIG, query_image=QUERY)

        assert result.vehicles[0].match_score == pytest.approx(0.83, abs=1e-4)

    def test_une_marge_sous_un_est_ramenee_a_un(self, video: Path) -> None:
        """`max(1.0, improvement)` : une marge < 1 ferait réencoder sur une vue *pire*.

        Le champ `Settings` borne déjà à `ge=1.0`, mais le domaine ne dépend pas de
        la validation d'une couche au-dessus de lui.
        """
        assert _run_growing(video, improvement=0.5).vectors_produced == 8


class TestScorePublie:
    def test_le_score_traverse_jusqu_au_registre(self, video: Path) -> None:
        result = _run(video, embedder=FakeVehicleEmbedder(similarity_for=lambda _index: 0.83))

        assert result.vehicles[0].match_score == pytest.approx(0.83, abs=1e-4)

    def test_le_plancher_de_deploiement_tait_un_score_trop_bas(self, video: Path) -> None:
        """Le plancher **ne publie pas** au lieu de publier et laisser filtrer.

        Il ne remplace pas le seuil de l'utilisateur, qui vit côté client sur le score
        brut : il évite seulement de transporter des nombres dont on sait qu'ils ne
        veulent rien dire.
        """
        result = _run(
            video,
            embedder=FakeVehicleEmbedder(similarity_for=lambda _index: 0.10),
            min_similarity=0.5,
        )

        assert result.vehicles[0].match_score is None

    def test_une_image_de_requete_illisible_ne_fait_pas_echouer_l_analyse(
        self, video: Path
    ) -> None:
        """Une requête refusée laisse une analyse **complète et sans score**.

        Une recherche indisponible n'est pas une analyse ratée : c'est la doctrine des
        deux étages de plaques, appliquée ici.
        """
        embedder = FakeVehicleEmbedder(query_fails=True)
        result = _run(video, embedder=embedder)

        assert result.stats.crossings > 0
        assert all(vehicle.match_score is None for vehicle in result.vehicles)
        # L'étage n'est même pas entré dans la boucle : sans vecteur de requête, il n'y
        # a rien à comparer.
        assert embedder.calls == 0

    def test_un_vehicule_trop_petit_reste_sans_score_sans_decaler_les_autres(
        self, video: Path
    ) -> None:
        """Le contrat d'alignement positionnel, vu du résultat.

        Un recadrage refusé laisse un trou **à sa place**. Un décalage d'un cran
        attribuerait l'apparence d'un véhicule à son voisin — un score plausible et
        faux, sans rien qui lève.
        """
        # Deux pistes, dont une trop étroite pour être encodée.
        frames = compose(
            track_path(
                1,
                CAR,
                straight_line((300.0, 250.0), (300.0, 800.0), steps=8),
                box_size=(40.0, 60.0),
            ),
            track_path(
                2,
                CAR,
                straight_line((900.0, 250.0), (900.0, 800.0), steps=8),
                box_size=(200.0, 120.0),
            ),
        )
        embedder = FakeVehicleEmbedder(min_width_px=100.0, similarity_for=lambda _index: 0.77)
        service = AnalysisService(
            FakeEngine(frames), vehicle_embedder=embedder, reid_min_similarity=0.0
        )
        result = service.run_video("job-1", video, CONFIG, query_image=QUERY)

        by_id = {vehicle.global_id: vehicle for vehicle in result.vehicles}
        narrow = next(vehicle for vehicle in by_id.values() if vehicle.match_score is None)
        wide = next(vehicle for vehicle in by_id.values() if vehicle.match_score is not None)
        assert narrow.global_id != wide.global_id
        assert wide.match_score == pytest.approx(0.77, abs=1e-4)


class TestSimilariteCosinus:
    """`cosine_similarity` — la seule définition de « se ressembler »."""

    def test_un_vecteur_est_identique_a_lui_meme(self) -> None:
        vector = np.asarray([0.6, 0.8, 0.0, 0.0], dtype=np.float32)
        assert cosine_similarity(vector, vector) == pytest.approx(1.0)

    def test_le_resultat_ne_depasse_jamais_un(self) -> None:
        """**Le bornage n'est pas de la coquetterie.**

        L'arithmétique flottante rend régulièrement 1,0000001 pour un vecteur comparé à
        lui-même, et un score au-dessus de 1 affiché en pourcentage donnerait
        « 100,00001 % de ressemblance ».
        """
        vector = np.asarray([1.0, 0.0, 0.0, 0.0], dtype=np.float32)
        assert cosine_similarity(vector, vector) <= 1.0
        assert cosine_similarity(vector, -vector) >= -1.0

    def test_deux_vecteurs_orthogonaux_ne_se_ressemblent_pas(self) -> None:
        left = np.asarray([1.0, 0.0, 0.0, 0.0], dtype=np.float32)
        right = np.asarray([0.0, 1.0, 0.0, 0.0], dtype=np.float32)
        assert cosine_similarity(left, right) == pytest.approx(0.0)
