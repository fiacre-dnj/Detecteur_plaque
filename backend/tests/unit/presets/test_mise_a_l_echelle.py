"""La mise à l'échelle d'un preset, et pourquoi elle déforme volontairement.

Le seul calcul du domaine des presets, donc le seul endroit où un test unitaire a
quelque chose à prouver. Le reste de la feature est de la persistance et du transport.
"""

from __future__ import annotations

from traffic_analysis.features.presets.domain.records import (
    Preset,
    PresetLine,
    PresetPoint,
    PresetZone,
)


def _preset(width: int = 1280, height: int = 720) -> Preset:
    return Preset(
        id="p1",
        name="Carrefour nord",
        description="",
        source_width=width,
        source_height=height,
        mask_outside_zones=False,
        lines=(
            PresetLine(
                id="l1",
                name="Entrée",
                color="#38bdf8",
                zone_id="z1",
                a=PresetPoint(x=100.0, y=400.0),
                b=PresetPoint(x=1180.0, y=400.0),
            ),
        ),
        zones=(
            PresetZone(
                id="z1",
                name="Carrefour",
                color="#f59e0b",
                points=(
                    PresetPoint(x=0.0, y=0.0),
                    PresetPoint(x=640.0, y=0.0),
                    PresetPoint(x=640.0, y=360.0),
                ),
            ),
        ),
    )


class TestMiseALEchelle:
    def test_une_reduction_de_moitie_divise_les_coordonnees_par_deux(self) -> None:
        scaled = _preset().scaled_to(640, 360)

        assert scaled.lines[0].a == PresetPoint(x=50.0, y=200.0)
        assert scaled.lines[0].b == PresetPoint(x=590.0, y=200.0)

    def test_tous_les_sommets_de_zone_suivent(self) -> None:
        scaled = _preset().scaled_to(640, 360)

        assert scaled.zones[0].points == (
            PresetPoint(x=0.0, y=0.0),
            PresetPoint(x=320.0, y=0.0),
            PresetPoint(x=320.0, y=180.0),
        )

    def test_les_dimensions_du_preset_rendu_sont_les_nouvelles(self) -> None:
        # Sinon un second appel remettrait à l'échelle depuis l'ancienne résolution
        # et diviserait les coordonnées deux fois.
        scaled = _preset().scaled_to(640, 360)

        assert (scaled.source_width, scaled.source_height) == (640, 360)
        assert scaled.scaled_to(640, 360) is scaled

    def test_un_changement_de_rapport_d_aspect_deforme_volontairement(self) -> None:
        """Deux facteurs indépendants, pas une homothétie.

        Passer d'un 16/9 à un 4/3 déforme l'image elle-même : la géométrie doit
        suivre la même déformation, sinon les lignes ne recouvrent plus la route.
        Une homothétie laisserait une bande morte ou déborderait du cadre.
        """
        scaled = _preset(1280, 720).scaled_to(640, 480)

        # x divisé par 2, y multiplié par 2/3 — des facteurs différents.
        assert scaled.lines[0].a.x == 50.0
        assert scaled.lines[0].a.y == 400.0 * (480 / 720)

    def test_l_identite_rend_le_meme_objet(self) -> None:
        # Pas seulement égal : le même. Recréer des milliers de points pour rien
        # rendrait le cas courant — recharger sur la même vidéo — coûteux.
        preset = _preset()

        assert preset.scaled_to(1280, 720) is preset

    def test_un_preset_sans_dimensions_est_rendu_tel_quel(self) -> None:
        # Deviner un facteur serait pire que ne rien faire : les lignes seraient
        # déplacées vers un endroit arbitraire sans que rien ne l'explique.
        orphan = _preset(0, 0)

        assert orphan.scaled_to(1920, 1080) is orphan

    def test_les_noms_couleurs_et_rattachements_survivent(self) -> None:
        # Un preset qui rendrait des lignes grises et anonymes obligerait à tout
        # renommer, ce qui annule l'intérêt de l'enregistrer.
        scaled = _preset().scaled_to(640, 360)

        assert scaled.lines[0].name == "Entrée"
        assert scaled.lines[0].color == "#38bdf8"
        assert scaled.lines[0].zone_id == "z1"
        assert scaled.zones[0].name == "Carrefour"

    def test_le_preset_d_origine_n_est_pas_mute(self) -> None:
        preset = _preset()

        preset.scaled_to(640, 360)

        assert preset.lines[0].a == PresetPoint(x=100.0, y=400.0)


class TestBesoinDeMiseALEchelle:
    def test_faux_quand_les_dimensions_coincident(self) -> None:
        assert _preset().needs_scaling_for(1280, 720) is False

    def test_vrai_des_qu_une_dimension_differe(self) -> None:
        assert _preset().needs_scaling_for(1920, 720) is True
        assert _preset().needs_scaling_for(1280, 1080) is True

    def test_vrai_pour_un_ecart_d_un_seul_pixel(self) -> None:
        # Un pixel déplace déjà toutes les lignes proportionnellement. Prétendre
        # que « c'est la même chose » serait faux, et l'utilisateur découvrirait
        # l'écart en constatant des comptages différents.
        assert _preset().needs_scaling_for(1281, 720) is True
