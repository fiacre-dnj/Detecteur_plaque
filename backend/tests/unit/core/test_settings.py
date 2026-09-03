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
        assert settings.resolved_plate_model_path == settings.weights_dir / "license-plate.pt"

    def test_un_commentaire_en_fin_de_ligne_ne_devient_pas_un_chemin(self, tmp_path: Path) -> None:
        env_file = tmp_path / ".env"
        env_file.write_text(
            "TRAFFIC_PLATE_MODEL_PATH=              # vide = <weights>/license-plate.pt\n",
            encoding="utf-8",
        )

        settings = Settings(_env_file=env_file)  # type: ignore[call-arg]

        assert settings.plate_model_path is None
        assert settings.resolved_plate_model_path.name == "license-plate.pt"

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

    assert settings.resolved_plate_model_path == Path("/tmp/w/license-plate.pt")  # noqa: S108


def test_un_chemin_de_poids_relatif_ne_depend_pas_du_repertoire_de_lancement(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """**La panne silencieuse de 2.5, en un test.**

    `Path("./.weights")` résolu depuis le répertoire d'exécution faisait paraître
    *tous* les poids absents dès qu'on lançait `uvicorn` ailleurs que dans
    `backend/` — `license-plate.pt` et les deux fichiers d'OCR compris. L'ANPR
    devenait indisponible sans qu'aucun message ne mentionne la cause : le service
    démarre, le catalogue répond, et rien n'a l'air cassé.

    Le verdict porte sur l'**égalité entre deux répertoires courants**, et non sur
    une valeur écrite en dur : c'est exactement la propriété qui manquait, et une
    valeur en dur casserait au premier déplacement du paquet.
    """
    monkeypatch.chdir(tmp_path)
    depuis_tmp = _settings(weights_dir=Path("./.weights"))

    ailleurs = tmp_path / "sous-repertoire"
    ailleurs.mkdir()
    monkeypatch.chdir(ailleurs)
    depuis_ailleurs = _settings(weights_dir=Path("./.weights"))

    assert depuis_tmp.weights_dir == depuis_ailleurs.weights_dir
    assert depuis_tmp.weights_dir.is_absolute()
    # Ancré sur le paquet : le dossier `.weights` est celui où
    # `scripts/fetch_*.py` déposent réellement les fichiers.
    assert depuis_tmp.weights_dir.name == ".weights"
    assert depuis_tmp.weights_dir.parent.name == "backend"


def test_le_repertoire_de_donnees_est_ancre_de_la_meme_facon(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`data_dir` porte les résultats et les vidéos déposées : le déplacer sans
    prévenir ferait disparaître l'historique d'un service relancé ailleurs."""
    monkeypatch.chdir(tmp_path)
    settings = _settings(data_dir=Path("./data"))

    assert settings.data_dir.is_absolute()
    assert settings.data_dir.parent.name == "backend"


def test_un_chemin_de_poids_enracine_traverse_inchange() -> None:
    """La forme d'un déploiement conteneurisé. La réécrire serait une surprise.

    Le critère est la présence d'une racine, **pas** `is_absolute()` : sous
    Windows, `Path("/opt/poids").is_absolute()` est faux faute de lettre de
    lecteur. S'y fier ferait déplacer, sur une machine de développement, le chemin
    qu'un opérateur a écrit explicitement pour la production.
    """
    assert _settings(weights_dir=Path("/opt/poids")).weights_dir == Path("/opt/poids")


class TestAncrageDeLUrlSqlite:
    """`database_url` doit suivre `data_dir`, et ne le suivait pas.

    Les deux réglages décrivent le **même** dépôt de données : la base référence
    des jobs dont les vidéos vivent sous `data_dir`. `data_dir` était ancré, la
    base non — donc lancer `uvicorn` depuis la racine du dépôt plutôt que depuis
    `backend/` ouvrait `<racine>/data/traffic.db` tout en continuant d'écrire les
    vidéos dans `backend/data/jobs/`.

    Relevé sur ce dépôt : deux bases, 19 jobs et 4 presets d'un côté, 5 jobs et
    aucun preset de l'autre, plus 663 Mo de vidéos qu'aucune purge ne pouvait voir
    puisque leur ligne vivait dans l'autre base. Rien ne lève : le service démarre
    et l'historique est simplement vide.
    """

    def test_une_base_relative_ne_depend_pas_du_repertoire_de_lancement(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Même verdict que pour les poids : l'égalité entre deux répertoires
        courants, jamais une valeur écrite en dur."""
        monkeypatch.chdir(tmp_path)
        depuis_tmp = _settings(database_url="sqlite+aiosqlite:///./data/traffic.db")

        ailleurs = tmp_path / "sous-repertoire"
        ailleurs.mkdir()
        monkeypatch.chdir(ailleurs)
        depuis_ailleurs = _settings(database_url="sqlite+aiosqlite:///./data/traffic.db")

        assert depuis_tmp.database_url == depuis_ailleurs.database_url
        assert depuis_tmp.database_url.endswith("/backend/data/traffic.db")

    def test_la_base_et_le_repertoire_de_donnees_atterrissent_au_meme_endroit(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """**La propriété qui compte**, et celle qui manquait : les deux réglages
        décrivent le même dépôt, donc ils doivent désigner le même parent."""
        monkeypatch.chdir(tmp_path)
        settings = _settings()

        assert settings.database_url.endswith(f"{settings.data_dir.as_posix()}/traffic.db")

    def test_une_base_enracinee_traverse_inchangee(self) -> None:
        """La forme d'un déploiement conteneurisé.

        Le piège est dans l'analyse de l'URL : `urlsplit` rend `//opt/data/x.db`
        pour `sqlite:////opt/data/x.db`, et un `lstrip("/")` donnerait
        `opt/data/x.db` — un chemin relatif, donc déplacé sous `backend/`. Une
        seule barre doit être retirée.
        """
        for url in (
            "sqlite+aiosqlite:////opt/data/traffic.db",
            "sqlite+aiosqlite:///D:/donnees/traffic.db",
        ):
            assert _settings(database_url=url).database_url == url

    def test_une_base_en_memoire_et_une_base_non_sqlite_traversent_inchangees(self) -> None:
        """Ni l'une ni l'autre ne décrit un fichier : les ancrer n'aurait aucun
        sens, et casserait la configuration de test comme celle de production."""
        for url in (
            "sqlite+aiosqlite:///:memory:",
            "sqlite+aiosqlite://",
            "postgresql+asyncpg://user:pass@hote/base",
        ):
            assert _settings(database_url=url).database_url == url

    def test_sqlalchemy_relit_l_url_ancree(self) -> None:
        """Le format compte autant que le chemin.

        `urlunsplit` replie `scheme:///chemin` en `scheme:/chemin` quand le netloc
        est vide, et SQLAlchemy ne relit alors plus un chemin de fichier. Le test
        interroge donc la bibliothèque qui consommera réellement l'URL, pas notre
        idée de sa syntaxe.
        """
        from sqlalchemy.engine import make_url

        settings = _settings(database_url="sqlite+aiosqlite:///./data/traffic.db")
        database = make_url(settings.database_url).database

        assert database is not None
        assert Path(database).is_absolute()
        assert Path(database).name == "traffic.db"


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


# ── Étranglement du détecteur de plaques (ADR 0010) ──────────────────────────


def test_la_cadence_du_detecteur_suit_celle_de_l_ocr_par_defaut() -> None:
    """C'était le comportement câblé en dur dans le conteneur ; il devient un repli.

    Détecter plus souvent qu'on ne lit produirait des boîtes que personne ne
    consomme, puisque c'est la lecture qui décide du texte publié.
    """
    settings = _settings(plate_ocr_every_n_frames=5, plate_detect_max_anchor_age=4)

    assert settings.resolved_plate_detect_every_n_frames == 5


def test_la_cadence_du_detecteur_peut_se_desolidariser_de_celle_de_l_ocr() -> None:
    settings = _settings(plate_ocr_every_n_frames=3, plate_detect_every_n_frames=2)

    assert settings.resolved_plate_detect_every_n_frames == 2


def test_une_ancre_trop_courte_pour_la_cadence_est_refusee_au_demarrage() -> None:
    """La panne évitée est purement visuelle : elle n'écrit rien et ne change
    aucun chiffre.

    Entre deux détections espacées de 8 images, les images sautées portent des
    ancres d'âge 1 à 7 ; un `max_anchor_age` de 4 en laisse trois sans rectangle.
    C'est exactement le clignotement qu'ADR 0010 a supprimé, et il se lit comme un
    défaut de détection — donc il se cherche là où il n'est pas.
    """
    with pytest.raises(ValidationError, match="clignoteraient"):
        _settings(plate_detect_every_n_frames=8, plate_detect_max_anchor_age=4)


def test_l_ancre_juste_assez_longue_est_acceptee() -> None:
    """La borne est `every - 1` et non `every` : l'image de la détection suivante
    est mesurée, elle ne reprojette rien."""
    settings = _settings(plate_detect_every_n_frames=5, plate_detect_max_anchor_age=4)

    assert settings.plate_detect_max_anchor_age == 4


def test_les_defauts_du_detecteur_de_plaques_sont_coherents_entre_eux() -> None:
    """Le couple par défaut ne doit pas dépendre du garde-fou pour être juste."""
    settings = _settings()

    assert settings.plate_detect_max_anchor_age >= settings.resolved_plate_detect_every_n_frames - 1


def test_le_plafond_d_echecs_consecutifs_a_un_defaut_de_trois() -> None:
    """Le trou que l'ancre ne bouche pas : une piste sans plaque structurellement
    visible ne doit pas être retentée à chaque image analysée indéfiniment."""
    settings = _settings()

    assert settings.plate_detect_max_consecutive_misses == 3


# ── Budget de threads d'inférence ────────────────────────────────────────────


def test_l_ocr_herite_du_budget_global_de_threads() -> None:
    """Qui borne l'inférence veut la borner **toute**, pas seulement torch."""
    settings = _settings(inference_threads=3)

    assert settings.resolved_plate_ocr_intra_op_threads == 3


def test_le_reglage_specifique_de_l_ocr_reste_prioritaire() -> None:
    """Plusieurs analyses concurrentes : chaque pool intra-op doit être plus
    étroit que le budget de la machine."""
    settings = _settings(inference_threads=8, plate_ocr_intra_op_threads=2)

    assert settings.resolved_plate_ocr_intra_op_threads == 2


def test_sans_budget_personne_ne_borne_rien() -> None:
    """Le défaut `0` laisse chaque bibliothèque décider — le bon choix sur une
    machine dédiée au service."""
    settings = _settings()

    assert settings.inference_threads == 0
    assert settings.resolved_plate_ocr_intra_op_threads == 0


def test_l_autotune_cudnn_est_ferme_par_defaut() -> None:
    """**Un défaut retourné par la mesure** (ADR 0033).

    ADR 0013 l'avait activé sur la prémisse que la forme d'entrée est fixe pour une
    vidéo donnée. Elle l'est pour le détecteur de véhicules ; elle ne l'est pas pour le
    détecteur de plaques, qui reçoit un recadrage par piste. cuDNN réétalonnait donc à
    chaque nouveau rapport d'aspect, une seconde à chaque fois : 1,3× à 2,1× de cadence
    perdue sur une analyse avec plaques, pour un gain nul là où la forme est fixe.
    """
    assert _settings().inference_cudnn_autotune is False
