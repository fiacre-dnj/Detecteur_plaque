"""Ce que la configuration refuse au démarrage.

Échouer au boot avec un message précis vaut mieux qu'un comportement
inexplicable en production. Chaque test ici correspond à une erreur de
configuration réellement commise.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import ValidationError

from traffic_analysis.core.settings import Settings


def _settings(**overrides: object) -> Settings:
    """Configuration minimale, sans lire le `.env` de la machine."""
    return Settings(_env_file=None, **overrides)  # type: ignore[call-arg,arg-type]


def test_les_defauts_conviennent_au_developpement_local() -> None:
    settings = _settings()

    assert settings.env == "development"
    # Les deux formes de l'hôte local sont deux origines distinctes pour le
    # navigateur : les deux doivent être présentes.
    assert "http://localhost:5173" in settings.cors_origins
    assert "http://127.0.0.1:5173" in settings.cors_origins


def test_une_origine_joker_est_refusee() -> None:
    with pytest.raises(ValidationError, match="jamais contenir"):
        _settings(cors_origins=["*"])


def test_une_regex_d_origine_non_ancree_est_refusee() -> None:
    """`https://evil.com/#mon-domaine.dev` satisferait une regex non ancrée."""
    with pytest.raises(ValidationError, match="ancrée"):
        _settings(cors_origin_regex=r"https://.*\.mon-domaine\.dev")


def test_une_regex_ancree_est_acceptee() -> None:
    settings = _settings(cors_origin_regex=r"^https://.*\.mon-domaine\.dev$")

    assert settings.cors_origin_regex == r"^https://.*\.mon-domaine\.dev$"


def test_une_regex_vide_devient_none() -> None:
    """`TRAFFIC_CORS_ORIGIN_REGEX=` dans un `.env` arrive comme chaîne vide.

    La laisser telle quelle ferait passer `allow_origin_regex=""` à Starlette,
    dont la compilation réussit et qui ne correspond alors à rien de façon
    silencieuse.
    """
    assert _settings(cors_origin_regex="").cors_origin_regex is None


class TestValeursVidesEtCommentaires:
    """Le piège qui a tenu l'ANPR hors service pendant tout le projet.

    `.env.example` portait `TRAFFIC_PLATE_MODEL_PATH=  # vide = <weights>/…`. Le
    commentaire en fin de ligne **devient la valeur** : le service cherchait son
    modèle de plaques à un chemin nommé « # vide = … », ne le trouvait jamais, et
    signalait l'ANPR indisponible — avec le bon fichier au bon endroit, et sans
    qu'aucun message ne mentionne la cause.

    Le fichier d'exemple est corrigé ; ces tests protègent les `.env` déjà écrits
    d'après lui, qui vivent sur les machines et que personne ne relira.
    """

    def test_un_chemin_vide_retombe_sur_le_defaut(self) -> None:
        settings = _settings(plate_model_path="")

        assert settings.plate_model_path is None
        # Le repli documenté fonctionne : sans cela, `Path("")` vaut `Path(".")`,
        # qui est **vrai**, et le repli ne se déclencherait jamais.
        assert settings.resolved_plate_model_path == settings.weights_dir / "license-plate.onnx"

    def test_un_commentaire_en_fin_de_ligne_ne_devient_pas_un_chemin(self, tmp_path: Path) -> None:
        env_file = tmp_path / ".env"
        env_file.write_text(
            "TRAFFIC_PLATE_MODEL_PATH=              # vide = <weights>/license-plate.onnx\n",
            encoding="utf-8",
        )

        settings = Settings(_env_file=env_file)  # type: ignore[call-arg]

        assert settings.plate_model_path is None
        assert settings.resolved_plate_model_path.name == "license-plate.onnx"

    def test_un_repertoire_statique_vide_ne_sert_pas_le_repertoire_courant(self) -> None:
        # `Path("")` vaut `Path(".")` : sans garde, un `TRAFFIC_STATIC_DIR=` vide
        # ferait servir le répertoire de travail du serveur — c'est-à-dire le code
        # source, `.env` compris.
        assert _settings(static_dir="").static_dir is None

    def test_les_chemins_d_ocr_retombent_aussi_sur_leurs_defauts(self) -> None:
        """Le même piège, sur les deux nouveaux chemins.

        Six réglages d'OCR sont des `Path | None` ou `str | None` et rejoignent donc le
        validateur. Les seuils numériques, eux, n'y sont **pas** : le validateur rend
        `None`, et `None` sur un `float` non optionnel produirait une erreur de
        démarrage dont le message ne dirait rien de la vraie cause.
        """
        settings = _settings(plate_ocr_model_path="", plate_ocr_charset_path="")

        assert settings.plate_ocr_model_path is None
        assert settings.plate_ocr_charset_path is None
        assert (
            settings.resolved_plate_ocr_model_path
            == settings.weights_dir / "license-plate-ocr.onnx"
        )
        assert (
            settings.resolved_plate_ocr_charset_path
            == settings.weights_dir / "license-plate-ocr.charset.txt"
        )

    def test_un_commentaire_ne_devient_pas_un_chemin_d_ocr(self, tmp_path: Path) -> None:
        """La même protection, pour les `.env` écrits d'après le nouvel exemple."""
        env_file = tmp_path / ".env"
        env_file.write_text(
            "TRAFFIC_PLATE_OCR_MODEL_PATH=    # vide = <weights>/license-plate-ocr.onnx\n"
            "TRAFFIC_PLATE_OCR_CHARSET_URL=   # à renseigner\n",
            encoding="utf-8",
        )

        settings = Settings(_env_file=env_file)  # type: ignore[call-arg]

        assert settings.plate_ocr_model_path is None
        assert settings.plate_ocr_charset_url is None
        assert settings.resolved_plate_ocr_model_path.name == "license-plate-ocr.onnx"

    def test_les_chemins_d_ocr_explicites_sont_respectes(self, tmp_path: Path) -> None:
        settings = _settings(
            plate_ocr_model_path=str(tmp_path / "autre.onnx"),
            plate_ocr_charset_path=str(tmp_path / "autre.txt"),
        )

        assert settings.resolved_plate_ocr_model_path == tmp_path / "autre.onnx"
        assert settings.resolved_plate_ocr_charset_path == tmp_path / "autre.txt"


def test_une_liste_separee_par_des_virgules_est_acceptee() -> None:
    """`docker run -e TRAFFIC_CORS_ORIGINS=a,b` est la forme la plus courante
    posée à la main ; refuser cette syntaxe ne protège de rien."""
    settings = _settings(cors_origins="http://a.test, http://b.test")

    assert settings.cors_origins == ("http://a.test", "http://b.test")


def test_une_cle_inconnue_du_fichier_env_fait_echouer_le_demarrage(tmp_path: Path) -> None:
    """`TRAFFIC_MAX_UPLOD_MB` (faute de frappe) dans `.env` doit être vue.

    C'est le cas qui compte : on copie `.env.example`, on modifie une ligne, et
    une faute de frappe rendrait la valeur silencieusement ignorée — donc la
    limite d'upload resterait à 800 Mo en croyant l'avoir baissée.

    Noter la portée : `extra="forbid"` couvre les clés du fichier `.env`, que
    pydantic-settings lit intégralement. Une **variable d'environnement**
    inconnue, elle, n'est pas détectable — la source d'environnement ne cherche
    que les noms de champs qu'elle connaît, sans énumérer le reste.
    """
    env_file = tmp_path / ".env"
    env_file.write_text("TRAFFIC_MAX_UPLOD_MB=50\n", encoding="utf-8")

    with pytest.raises(ValidationError, match="max_uplod_mb"):
        Settings(_env_file=env_file)  # type: ignore[call-arg]


def test_une_cle_correcte_du_fichier_env_est_lue(tmp_path: Path) -> None:
    env_file = tmp_path / ".env"
    env_file.write_text("TRAFFIC_MAX_UPLOAD_MB=50\n", encoding="utf-8")

    assert Settings(_env_file=env_file).max_upload_mb == 50  # type: ignore[call-arg]


def test_le_chemin_du_modele_de_plaques_a_un_defaut_derive() -> None:
    """Vide dans l'environnement signifie « à l'emplacement par défaut ».

    Pas « pas de modèle » : l'absence se constate au chargement du fichier, elle
    ne se déduit pas d'une configuration vide.
    """
    settings = _settings(weights_dir=Path("/tmp/w"))  # noqa: S108

    assert settings.resolved_plate_model_path == Path("/tmp/w/license-plate.onnx")  # noqa: S108


def test_un_chemin_explicite_gagne_sur_le_defaut() -> None:
    settings = _settings(
        weights_dir=Path("/tmp/w"),  # noqa: S108
        plate_model_path=Path("/ailleurs/plaques.onnx"),
    )

    assert settings.resolved_plate_model_path == Path("/ailleurs/plaques.onnx")


def test_la_limite_d_upload_est_exposee_en_octets() -> None:
    """Le middleware de limite de corps compare des octets : la conversion vit
    dans la configuration, pas recopiée à chaque appelant."""
    assert _settings(max_upload_mb=8).max_upload_bytes == 8 * 1024 * 1024


def test_la_production_exige_des_journaux_json() -> None:
    """Les journaux de production partent vers un collecteur, pas un terminal :
    le rendu console y perdrait toute la structure."""
    with pytest.raises(ValidationError, match="json"):
        _settings(env="production", log_format="console", docs_enabled=False)


def test_l_exigence_de_journaux_json_ne_depend_pas_des_docs() -> None:
    """Le bug corrigé au lot 14, en un test.

    Les deux règles vivaient dans un seul validateur dont la condition était
    `is_production and docs_enabled and log_format != "json"` : fermer les docs
    faisait **disparaître** l'exigence sur les journaux. Deux règles sans rapport
    conflées en une, et celle qui sautait était silencieuse.
    """
    with pytest.raises(ValidationError, match="json"):
        _settings(env="production", log_format="console", docs_enabled=True, docs_public=True)


def test_la_production_refuse_une_documentation_ouverte_par_defaut() -> None:
    """Un `openapi.json` public est une carte du service offerte à qui cherche
    par où entrer. Le défaut `docs_enabled=True` sert le développement ; l'hériter
    en production publierait chaque route et chaque borne de validation."""
    with pytest.raises(ValidationError, match="TRAFFIC_DOCS_ENABLED"):
        _settings(env="production", log_format="json")


def test_la_documentation_publique_reste_possible_si_elle_est_explicite() -> None:
    """Exposer sa documentation est un choix légitime pour une API publique — il
    doit seulement être écrit, et non hérité d'un `.env` de développement."""
    settings = _settings(env="production", log_format="json", docs_public=True)

    assert settings.docs_enabled is True


def test_fermer_les_docs_suffit_a_demarrer_en_production() -> None:
    settings = _settings(env="production", log_format="json", docs_enabled=False)

    assert settings.is_production


def test_la_configuration_est_immuable() -> None:
    """Une valeur de configuration qui change en cours d'exécution rend le
    service impossible à raisonner."""
    settings = _settings()

    with pytest.raises(ValidationError):
        settings.port = 9000  # type: ignore[misc]
