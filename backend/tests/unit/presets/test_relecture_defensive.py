"""La relecture d'une ligne de preset depuis sa colonne JSON.

**Un seul preset abîmé ne doit jamais rendre les autres inaccessibles.** La
géométrie vit dans une colonne texte, donc rien n'y est garanti : un preset écrit
par une version antérieure, une colonne bricolée à la main, un rôle rétroporté d'une
version future. `PresetSchema` type les rôles par un `Literal` — une valeur
inattendue ferait échouer la validation de la *réponse*, c'est-à-dire un 500 sur
`GET /presets` qui emporterait toute la liste pour une ligne fautive.

Même doctrine que `_load`, qui rend une liste vide plutôt que de lever sur du JSON
corrompu : dégrader **ce** preset, laisser les autres lisibles.
"""

from __future__ import annotations

from typing import Any

from traffic_analysis.features.presets.infrastructure.sqlalchemy_repository import _read_line


def _raw(**overrides: object) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "id": "l1",
        "name": "Entrée",
        "color": "#38bdf8",
        "zoneId": "z1",
        "a": {"x": 100.0, "y": 400.0},
        "b": {"x": 1180.0, "y": 400.0},
        "positiveName": "Vers le centre",
        "negativeName": "Vers la rocade",
        "positiveRole": "entry",
        "negativeRole": "exit",
    }
    payload.update(overrides)
    return payload


class TestRoles:
    def test_un_role_valide_traverse_inchange(self) -> None:
        line = _read_line(_raw())

        assert line.positive_role == "entry"
        assert line.negative_role == "exit"

    def test_un_role_inconnu_retombe_sur_neutre_sans_lever(self) -> None:
        """Le cas qui protège la liste entière : refuser ici rendrait un 500."""
        line = _read_line(_raw(positiveRole="entrance"))

        assert line.positive_role == "neutral"

    def test_un_role_qui_n_est_pas_une_chaine_retombe_sur_neutre(self) -> None:
        # `raw in (...)` sur une liste ou un dict ne lève pas, mais le repli doit
        # être explicite : une valeur non textuelle atteindrait sinon `Literal`.
        assert _read_line(_raw(positiveRole=None)).positive_role == "neutral"
        assert _read_line(_raw(positiveRole=["entry"])).positive_role == "neutral"

    def test_une_ligne_ecrite_avant_les_roles_est_relue_sans_deviner(self) -> None:
        """`neutral` et non une devinette.

        Deviner « entrée » fausserait un bilan que personne n'a demandé ; `neutral`
        fait afficher le repère « à préciser » du panneau de géométrie, qui force un
        choix explicite au premier contact.
        """
        legacy = {
            key: value
            for key, value in _raw().items()
            if not key.startswith(("positive", "negative"))
        }

        line = _read_line(legacy)

        assert line.positive_role == "neutral"
        assert line.negative_role == "neutral"


class TestLibelles:
    def test_un_libelle_absent_devient_la_chaine_vide_et_non_None(self) -> None:
        """`str(raw.get(...))` rendrait « None », affiché tel quel sur la vidéo.

        La chaîne vide a un sens précis dans le contrat : elle demande à l'interface
        de poser son défaut géométrique, recalculé quand la ligne bouge.
        """
        line = _read_line(_raw(positiveName=None))

        assert line.positive_name == ""

    def test_un_libelle_non_textuel_ne_traverse_pas(self) -> None:
        assert _read_line(_raw(negativeName=42)).negative_name == ""


class TestNouveauxRoles:
    def test_interdit_et_passage_traversent_inchanges(self) -> None:
        """Ils ont rejoint le `Literal` du contrat : les écarter les perdrait.

        Un preset de voie à sens unique relu en `neutral` rendrait une ligne qui ne
        signale plus rien, sans qu'aucun compteur soit faux.
        """
        line = _read_line(_raw(positiveRole="forbidden", negativeRole="transit"))

        assert line.positive_role == "forbidden"
        assert line.negative_role == "transit"


class TestVoieReservee:
    def test_une_liste_valide_traverse_sans_doublon(self) -> None:
        line = _read_line(_raw(allowedClassIds=[5, 7, 5]))

        assert line.allowed_class_ids == (5, 7)

    def test_une_clef_absente_rend_none(self) -> None:
        """Le cas **normal** : un preset écrit avant l'ajout du champ."""
        line = _read_line(_raw())

        assert line.allowed_class_ids is None

    def test_une_valeur_corrompue_rend_none_et_jamais_une_liste_vide(self) -> None:
        """Le repli qui compte : `None` dit « rien n'est restreint ».

        Une liste vide dirait « aucune classe n'a le droit de passer », donc **tout**
        franchissement en infraction. Se tromper de repli fabriquerait ici un écran
        d'alertes entièrement faux, sur une géométrie qui n'a rien restreint.
        """
        assert _read_line(_raw(allowedClassIds="bus")).allowed_class_ids is None
        assert _read_line(_raw(allowedClassIds=[])).allowed_class_ids is None
        assert _read_line(_raw(allowedClassIds=["5", None])).allowed_class_ids is None

    def test_les_booleens_ne_passent_pas_pour_des_identifiants(self) -> None:
        """`True` est un `int` en Python : sans garde, il deviendrait la classe 1."""
        line = _read_line(_raw(allowedClassIds=[True, 5]))

        assert line.allowed_class_ids == (5,)
