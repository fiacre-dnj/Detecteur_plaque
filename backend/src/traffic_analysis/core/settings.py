"""Configuration du service — un seul objet, chargé une fois, injecté partout.

Interdiction de lire `os.environ` ailleurs dans le code : une valeur de
configuration lue à deux endroits finit toujours par diverger entre les deux, et
un test ne peut pas la remplacer.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Literal, Self

from pydantic import Field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

Environment = Literal["development", "staging", "test", "production"]
LogFormat = Literal["console", "json"]

#: Racine du dépôt telle que le paquet installé la voit — le `backend/` du projet.
#:
#: `parents[2]` depuis `traffic_analysis/core/settings.py` remonte `core/`, puis
#: `traffic_analysis/`, puis `src/`, et atteint `backend/`. C'est l'ancre des
#: chemins relatifs de configuration : elle ne dépend pas du répertoire depuis
#: lequel on a lancé le service, contrairement à `Path.cwd()`.
_PACKAGE_ROOT = Path(__file__).resolve().parents[3]


class Settings(BaseSettings):
    """Toutes les variables d'environnement du service, préfixées `TRAFFIC_`.

    Les valeurs par défaut sont celles du développement local. Le fichier
    `.env.example` est committé et documente chaque champ ; `.env` est ignoré.
    """

    model_config = SettingsConfigDict(
        env_prefix="TRAFFIC_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="forbid",  # une variable TRAFFIC_ mal orthographiée doit être vue
        frozen=True,  # la configuration ne change pas en cours d'exécution
    )

    # ── Exécution ────────────────────────────────────────────────────────────
    env: Environment = "development"
    host: str = "127.0.0.1"
    port: int = Field(8000, ge=1, le=65535)

    # ── Journalisation ───────────────────────────────────────────────────────
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"] = "INFO"
    log_format: LogFormat = "console"

    # ── CORS et hôtes ────────────────────────────────────────────────────────
    # `localhost` et `127.0.0.1` sont DEUX origines distinctes pour le
    # navigateur : les deux doivent être listées, sinon « ça marche sur l'une et
    # pas sur l'autre » (piège 46 de prompt/13).
    cors_origins: tuple[str, ...] = (
        "http://localhost:5173",
        "http://127.0.0.1:5173",
    )
    cors_origin_regex: str | None = None
    cors_allow_credentials: bool = False
    trusted_hosts: tuple[str, ...] = ("localhost", "127.0.0.1")

    # ── Persistance ──────────────────────────────────────────────────────────
    database_url: str = "sqlite+aiosqlite:///./data/traffic.db"
    data_dir: Path = Path("./data")

    # ── Modèles ──────────────────────────────────────────────────────────────
    weights_dir: Path = Path("./.weights")
    device: str = "auto"  # auto | cpu | 0 | cuda:0
    half: bool = True  # ignoré hors GPU : en fp16 sur CPU, l'inférence ralentit
    #: Compensation de mouvement de caméra du tracker (BoT-SORT).
    #:
    #: **Le poste le plus cher du pipeline, et il ne servait à rien ici.** Mesuré
    #: par `scripts/pipeline_bench.py` sur trois vidéos 720p réelles : `sparseOptFlow`
    #: coûte **20,2 ms par image**, soit 39 % du budget total et davantage que
    #: l'inférence GPU elle-même (17,8 ms). Le passer à `none` fait passer l'analyse
    #: de 19,4 à 34,8 images/s — **1,75×, à comptage identique** sur les trois.
    #:
    #: `none` par défaut parce que la cible du projet est une caméra **fixe** de
    #: circulation : il n'y a alors aucun mouvement global à compenser, et on payait
    #: un flux optique dense pour corriger un déplacement qui n'existe pas.
    #:
    #: **À remettre à `sparseOptFlow` dès que la caméra bouge** — plan embarqué,
    #: drone, mât mal haubané par grand vent. Sans compensation, un mouvement global
    #: se lit comme un mouvement des véhicules : les prédictions de Kalman partent à
    #: côté, les associations se cassent, et les identités se multiplient. Le symptôme
    #: n'est pas une erreur mais un `unique_vehicles` qui gonfle.
    #:
    #: Voir docs/adr/0013-le-cout-du-pipeline-de-comptage.md.
    tracker_gmc: Literal["none", "sparseOptFlow", "orb", "sift", "ecc"] = "none"
    #: Côté de l'entrée du réseau, en pixels. **Multiple de 32 obligatoire.**
    #:
    #: Le coût de l'inférence varie à peu près comme le carré de cette valeur, et
    #: c'est le levier de débit le plus direct qui reste sur cette carte. Il se paie
    #: sur les véhicules **petits et lointains** : ce qui décide qu'un objet est
    #: détecté n'est pas sa taille dans la vidéo mais sa taille **dans l'entrée du
    #: réseau**.
    #:
    #: 640 par défaut, c'est-à-dire la valeur qu'Ultralytics appliquait déjà sans
    #: que personne ne l'écrive. Le rendre explicite ne change donc aucun chiffre —
    #: il rend seulement réglable et mesurable ce qui était subi.
    #:
    #: **L'entrée n'est pas carrée** : `rect=True` est actif en prédiction, donc une
    #: image 16:9 entre en 640×384 et non 640×640. Les gains attendus se calculent
    #: sur cette base.
    #:
    #: À calibrer au banc (`scripts/pipeline_bench.py --imgsz …`), sur ses propres
    #: vidéos, en regardant **débit et comptage** : c'est le seul réglage de cette
    #: section qui peut faire disparaître des véhicules.
    inference_imgsz: int = Field(640, ge=64, le=1920)
    #: Images par inférence en **différé**. Sans effet en direct, où les images
    #: arrivent une par une.
    #:
    #: Un lot amortit le lancement des noyaux et remplit mieux un GPU que le
    #: modèle nano laisse à moitié inoccupé. Le suivi n'en souffre pas : le
    #: chargeur d'Ultralytics remplit un lot d'images **consécutives** de la même
    #: vidéo, et le tracker leur est appliqué une par une, dans l'ordre.
    #:
    #: Mesuré au banc sur 720p, yolov8n, à comptage **strictement identique** :
    #: 1 → 4 gagne 1,16× à 1,37×, et 4 → 8 seulement 1,04× à 1,09×. D'où **4** : le
    #: quatrième doublement ne rapporte presque plus rien et coûte de la mémoire.
    #:
    #: **À redescendre sur les paliers large et xlarge** si la carte n'a que 4 Go :
    #: quatre images d'un yolov8x en vol tiennent moins bien que quatre d'un nano.
    #: L'échec est franc — une erreur CUDA de mémoire, pas une dégradation
    #: silencieuse — mais il fait échouer le job.
    inference_batch: int = Field(4, ge=1, le=32)
    #: Budget de threads d'inférence **CPU**. `0` laisse chaque bibliothèque décider,
    #: c'est-à-dire prendre tous les cœurs.
    #:
    #: Ce défaut est le bon sur une machine dédiée au service, et le mauvais dès que
    #: le navigateur tourne sur la même machine — le cas du développement local. Le
    #: symptôme n'est pas une erreur : c'est la **vidéo qui saccade** pendant
    #: l'analyse, y compris à vitesse normale, parce qu'il ne reste aucun cœur pour
    #: décoder et composer l'image. Le diagnostic naturel est « le lecteur est
    #: mauvais » ; la cause est que le serveur a tout pris.
    #:
    #: Poser un à deux cœurs de moins que la machine rend la lecture fluide, contre
    #: une part de cadence d'analyse. **L'échange se mesure**, il ne se suppose pas :
    #: le banc le chiffre sur ses propres vidéos.
    #:
    #: **Ce qu'il borne, et ce qu'il ne borne pas — mesuré.** Il atteint torch (donc
    #: le détecteur et le suivi des véhicules, qui tournent à *chaque* image) et
    #: l'OCR, dont on a vu la vignette passer de 66 à 85 ms en la ramenant à trois
    #: threads. Il **n'atteint pas le détecteur de plaques** : celui-ci est un
    #: `.onnx` chargé par Ultralytics, qui construit sa session sans jamais passer de
    #: `SessionOptions` (`ultralytics/nn/backends/onnx.py`), donc onnxruntime y garde
    #: son défaut — tous les cœurs. Vérifié plutôt que supposé : à trois threads, la
    #: détection reste à 656 ms contre 702 sans budget, soit l'écart de deux mesures
    #: identiques. Le levier du détecteur n'est pas là : c'est son étranglement.
    #:
    #: Sans effet sur GPU, où l'inférence ne vit pas sur ces threads.
    inference_threads: int = Field(0, ge=0, le=64)
    default_model_id: str = "yolov8n"
    #: Préchauffe le modèle par défaut au démarrage, **si son poids est déjà sur le
    #: disque**. Le premier appel d'un modèle paie son chargement et sa fusion de
    #: couches, ce qui se lit comme un blocage de plusieurs dizaines de secondes.
    #:
    #: La condition « déjà téléchargé » n'est pas négociable : préchauffer un modèle
    #: absent déclencherait un téléchargement de 137 Mo au démarrage, donc un
    #: conteneur qui semble bloqué et un healthcheck qui échoue. Le service ne doit
    #: jamais dépendre du réseau pour démarrer.
    warmup: bool = True
    max_loaded_models: int = Field(2, ge=1, le=8)
    plate_model_path: Path | None = None  # vide = <weights_dir>/license-plate.onnx
    plate_confidence: float = Field(0.25, ge=0.05, le=0.95)
    #: IoU de la suppression des non-maxima du modèle de plaques. Le défaut
    #: d'Ultralytics (0,70) est calibré pour une scène COCO encombrée ; sur une
    #: classe unique et un objet par véhicule, 0,45 supprime les doublons décalés
    #: que 0,70 laissait passer.
    plate_iou: float = Field(0.45, ge=0.1, le=0.9)
    #: Combien de plaques garder par véhicule, les meilleures d'abord. Un véhicule
    #: a une plaque visible ; en garder plus multiplie les rectangles à l'écran et
    #: le coût d'OCR sans rien apprendre.
    plate_max_per_vehicle: int = Field(1, ge=1, le=8)
    #: Côté de la mosaïque : `n²` recadrages de véhicules par inférence.
    #:
    #: **`1` par défaut, c'est-à-dire pas de mosaïque**, parce que l'empaquetage
    #: échange du rappel contre de la vitesse et que l'échange n'est pas gratuit.
    #: Ce qui décide qu'une plaque est trouvée n'est pas l'agrandissement du
    #: recadrage mais la taille de la plaque **dans l'entrée du réseau**, et elle ne
    #: dépend que de la cellule : `plaque ≈ 0,15 × côté_de_cellule`. Mesuré sur 657
    #: véhicules de vraie circulation, à 8,2 véhicules par image :
    #:
    #: | côté | cellule | ms/image | rappel |
    #: |------|---------|----------|--------|
    #: | 1    | 616 px  | 760      | 100 %  |
    #: | 2    | 302 px  | 221      | 84 %   |
    #: | 3    | 197 px  | 116      | 56 %   |
    #:
    #: `2` est l'échange raisonnable quand le débit prime : 3,4× pour 16 % de
    #: détections en moins, largement absorbées par le vote qui agrège plusieurs
    #: images du même véhicule. `3` ne se justifie que sur des plans serrés où les
    #: véhicules sont grands.
    plate_mosaic_side: int = Field(1, ge=1, le=3)

    # ── Étranglement du détecteur de plaques (ADR 0010) ──────────────────────
    # **Le vrai goulot, et de loin.** Mesuré sur cette machine (i5-8350U, sans GPU) :
    # 702 ms par inférence de détection contre 66 ms par vignette d'OCR, soit un
    # rapport de 10,7 à 1. Optimiser l'OCR ne rendrait donc rien de perceptible.
    #
    # Ces trois réglages existaient dans `PlateDetectOptions` sans que personne
    # puisse les atteindre : le conteneur ne passait que `every_n_frames`, repris de
    # celui de l'OCR. Les exposer est ce qui rend l'arbitrage débit/fraîcheur
    # réglable sans recompiler.
    #: Une image analysée sur N par piste. `None` = suit la cadence de l'OCR, ce qui
    #: était le comportement câblé en dur.
    plate_detect_every_n_frames: int | None = Field(None, ge=1, le=30)
    #: Sous cette largeur de **véhicule**, la plaque fera au mieux quelques pixels :
    #: l'inférence coûterait 702 ms sans rien pouvoir trouver d'exploitable.
    #:
    #: Distinct de `plate_ocr_min_width_px`, qui porte sur la plaque. Le rapport
    #: entre les deux dépend de la scène et **ne se déduit pas** : mesuré ici, une
    #: plaque vaut 0,5 à 0,9 de la largeur du véhicule sur un plan serré, et 0,05 à
    #: 0,25 sur une vue de circulation. C'est pourquoi ce seuil est un réglage et non
    #: une fonction de l'autre — à calibrer au banc, sur ses propres vidéos.
    plate_detect_min_vehicle_width_px: float = Field(96.0, ge=0.0, le=4096.0)
    #: Au-delà de cet âge, en images analysées, une ancre n'est plus reprojetée.
    #:
    #: **Lié à `plate_detect_every_n_frames`, et le lien est vérifié au démarrage** :
    #: entre deux détections espacées de N images, les images sautées portent des
    #: ancres d'âge 1 à N−1. Un `max_anchor_age` inférieur à N−1 laisse donc des
    #: images sans rectangle, c'est-à-dire le clignotement qu'ADR 0010 existe pour
    #: supprimer. Monter la cadence sans monter l'âge est le piège de ce couple.
    plate_detect_max_anchor_age: int = Field(4, ge=1, le=60)
    #: Échecs consécutifs (détection soumise, aucune plaque trouvée) au-delà
    #: duquel une piste sans ancre retombe sur la cadence normale.
    #:
    #: **Le trou que l'ancre ne bouche pas.** Une piste dont la plaque n'est
    #: structurellement jamais visible — mauvais angle, trop loin, absente de
    #: l'image — n'a jamais d'ancre, donc la garde « pas d'ancre → toujours
    #: détecter » la retente à *chaque* image analysée sur toute sa vie. Mesuré sur
    #: une vraie vidéo (9 à 13 véhicules simultanés, caméra de circulation) : 24
    #: pistes sur 36 n'ont jamais produit de plaque, certaines pendant 6 à 8 s —
    #: chacune payant ~800 ms par image analysée sans jamais bénéficier de
    #: l'étranglement. Résultat : 1,42 image/s traitée, contre 11 sans ANPR.
    plate_detect_max_consecutive_misses: int = Field(3, ge=1, le=30)

    # Utilisés par scripts/fetch_plate_model.py uniquement. Le service ne
    # télécharge jamais de lui-même : un démarrage ne doit pas dépendre du réseau.
    plate_model_url: str | None = None
    plate_model_sha256: str | None = None

    # ── Lecture du texte de plaque (OCR) ─────────────────────────────────────
    # Deux fichiers, et les deux sont nécessaires : le dictionnaire fait partie du
    # contrat du modèle — l'indice 37 signifie ce que le dictionnaire
    # d'entraînement disait. Un dictionnaire d'une autre taille ne lève rien, il
    # rend des plaques fausses et plausibles (ADR 0007).
    plate_ocr_model_path: Path | None = None
    plate_ocr_charset_path: Path | None = None
    #: Plancher de confiance d'une lecture. Sous ce seuil, la chaîne n'atteint même
    #: pas le vote : une hésitation ne doit pas figurer sur le fil, même étiquetée
    #: comme telle — une chaîne affichée est crue.
    plate_ocr_min_text_score: float = Field(0.50, ge=0.0, le=1.0)
    #: Étranglement : une image analysée sur N par piste.
    plate_ocr_every_n_frames: int = Field(3, ge=1, le=30)
    #: Largeur minimale d'une vignette envoyée à l'OCR — **le plancher de lecture**.
    #:
    #: Mesuré par `scripts/anpr_bench.py --truth-ladder`, sur huit plaques de vérité
    #: terrain rendues aux paliers du tableau (rejouable par commande) :
    #:
    #: | largeur | lectures justes |
    #: |---------|-----------------|
    #: | 320 px  | 8/8             |
    #: | 160 px  | 7/8             |
    #: | 128 px  | 7/8             |
    #: |  96 px  | 7/8             |
    #: |  80 px  | 6/8             |
    #: |  64 px  | 4/8             |
    #: |  48 px  | **0/8**         |
    #:
    #: **64 et non 150**, alors que la lecture ne redevient franchement fiable qu'au
    #: delà : le vote agrège sur toute la vie du véhicule, donc 4/8 par lecture à
    #: 64 px n'est pas rien, et couper à 150 supprimerait toute lecture sur des
    #: scènes où quelque chose passait. 64 est la dernière valeur qui rend encore des
    #: lectures justes ; 48 n'en rend prouvablement aucune.
    #:
    #: **64 et non 32**, la valeur précédente : elle était cinq fois trop permissive
    #: par rapport à la mesure, et dépensait le budget d'inférence sur des vignettes
    #: dont on savait qu'elles ne rendraient rien.
    #:
    #: À ne pas confondre avec `MIN_PLATE_WIDTH_PX` de `plate_reader.py`, qui reste à
    #: 32 : celui-là est le refus de dernier recours de l'adaptateur, pas la politique
    #: de dépense. Les confondre créerait un plancher invisible pour l'opérateur qui
    #: baisse ce réglage.
    plate_ocr_min_width_px: int = Field(64, ge=8, le=512)
    #: Netteté minimale d'une vignette, en variance de laplacien.
    #:
    #: Porte anti-flou de mouvement : une plaque large mais floue est aussi
    #: illisible qu'une plaque nette et minuscule, et seule cette mesure distingue
    #: la première de la seconde. `0` désactive la porte.
    #:
    #: **À calibrer par le banc**, pas au jugé : la variance de laplacien dépend du
    #: contraste de la scène et de la compression du flux, donc sa valeur utile n'est
    #: pas universelle. Le défaut est délibérément bas — on écarte le franchement
    #: flou, pas l'imparfait.
    plate_ocr_min_sharpness: float = Field(8.0, ge=0.0, le=10_000.0)
    #: Facteur d'amélioration exigé pour **relire** une identité déjà lue.
    #:
    #: La qualité est le **produit** largeur × netteté : une vignette large et floue
    #: et une vignette nette et minuscule sont toutes deux illisibles, et seul le
    #: produit écarte les deux. On ne relit que si la nouvelle bat la meilleure déjà
    #: lue de ce facteur ; sous ce seuil, l'inférence rendrait la même chaîne en
    #: moins sûr et **gonflerait la confiance d'un texte peut-être faux**.
    #:
    #: Effet visé : **même nombre d'inférences, meilleures vignettes**. Avant, la
    #: politique dépensait son budget sur la première vignette venue — souvent
    #: minuscule et floue — alors que le véhicule offrirait deux secondes plus tard
    #: une vignette deux fois plus large.
    plate_ocr_quality_improvement: float = Field(1.25, ge=1.0, le=10.0)
    #: Au-dessus de cette IoU avec la dernière boîte lue, on ne relit pas. Protège
    #: surtout la *justesse* du vote : cent recadrages identiques d'un véhicule
    #: arrêté au feu ne feraient que gonfler la confiance d'un texte peut-être faux.
    plate_ocr_skip_iou: float = Field(0.85, ge=0.0, le=1.0)
    #: `0` laisse onnxruntime décider. À baisser si `max_concurrent_jobs` dépasse 1 :
    #: deux analyses créeraient chacune son pool intra-op et se disputeraient les
    #: cœurs.
    plate_ocr_intra_op_threads: int = Field(0, ge=0, le=32)
    #: Lire chaque plaque sous plusieurs prétraitements — redressée, cadre rogné —
    #: et garder la meilleure lecture. Toutes les variantes partent dans le **même**
    #: lot : le surcoût est celui de quelques lignes de tenseur, pas d'une inférence
    #: de plus. À désactiver seulement pour comparer.
    plate_ocr_variants: bool = True
    #: Négocier la largeur du tenseur avec le lot au lieu des 320 px de PP-OCR. Une
    #: plaque européenne tient en 226 px — 30 % de convolutions en moins — et une
    #: plaque très large cesse d'être comprimée. Repli à 320 si un export refusait
    #: une largeur variable.
    plate_ocr_dynamic_width: bool = True
    # Utilisés par scripts/fetch_plate_ocr_model.py uniquement, même règle que le
    # détecteur : le service ne télécharge jamais de lui-même.
    plate_ocr_model_url: str | None = None
    plate_ocr_model_sha256: str | None = None
    plate_ocr_charset_url: str | None = None
    plate_ocr_charset_sha256: str | None = None

    # ── Bornes d'exécution ───────────────────────────────────────────────────
    # Un GPU = une analyse à la fois. Les suivantes attendent en file et sont
    # acceptées en 202 « queued », jamais refusées en 503.
    max_concurrent_jobs: int = Field(1, ge=1, le=8)
    max_realtime_sessions: int = Field(1, ge=1, le=4)
    max_upload_mb: int = Field(800, ge=1, le=8192)
    #: Intervalle minimal entre deux aperçus d'une analyse en cours, en
    #: millisecondes. `0` désactive l'aperçu : le flux SSE ne transporte alors que
    #: la progression, comme avant qu'il existe.
    #:
    #: Échantillonné en temps et non en images : la cadence d'analyse varie d'un
    #: facteur dix entre un CPU et un GPU, alors que ce qu'on borne — le débit du
    #: flux et le travail du navigateur — se mesure en secondes.
    preview_interval_ms: int = Field(200, ge=0, le=5000)
    job_ttl_minutes: int = Field(1440, ge=1)
    # La vidéo d'entrée est la donnée la plus lourde et la plus sensible, et elle
    # n'est plus nécessaire une fois le résultat produit : elle part plus tôt.
    input_ttl_minutes: int = Field(60, ge=1)

    # ── Limitation de débit, par adresse IP ──────────────────────────────────
    #: Limite globale. `0` la désactive entièrement — utile pour un déploiement
    #: derrière une passerelle qui limite déjà, où compter deux fois n'aiderait
    #: personne.
    rate_limit_per_minute: int = Field(60, ge=0)
    #: Dépôts d'analyse par minute. Beaucoup plus strict que la limite globale :
    #: chaque dépôt écrit un fichier de plusieurs centaines de mégaoctets sur le
    #: disque **avant** toute borne de concurrence, donc une rafale remplit le
    #: volume sans jamais saturer le GPU.
    rate_limit_jobs_per_minute: int = Field(10, ge=0)
    #: Benchmarks par heure. Un run mesure jusqu'à vingt modèles et les télécharge
    #: au besoin : c'est l'opération la plus coûteuse du service, et de loin.
    rate_limit_benchmark_per_hour: int = Field(2, ge=0)
    #: Handshakes WebSocket par minute. Le middleware CORS ne voit jamais passer un
    #: handshake, donc cette limite est la seule protection de cette porte.
    rate_limit_realtime_per_minute: int = Field(10, ge=0)

    # ── Documentation ────────────────────────────────────────────────────────
    docs_enabled: bool = True
    #: Autorise la documentation ouverte **en production**, où elle est refusée par
    #: défaut. Un second réglage plutôt qu'un simple `docs_enabled=true` : publier
    #: le schéma OpenAPI d'un service exposé est un choix qui mérite d'être écrit
    #: quelque part, pas hérité d'un `.env` de développement copié en production.
    docs_public: bool = False
    static_dir: Path | None = None  # build frontend servi par le backend

    # ── Champs dérivés ───────────────────────────────────────────────────────

    @property
    def is_production(self) -> bool:
        return self.env == "production"

    @property
    def max_upload_bytes(self) -> int:
        return self.max_upload_mb * 1024 * 1024

    @property
    def resolved_plate_model_path(self) -> Path:
        """Chemin effectif du modèle de plaques.

        Vide dans l'environnement signifie « à l'emplacement par défaut », pas
        « pas de modèle » : l'absence du fichier se constate au chargement, elle
        ne se déduit pas d'une configuration vide.
        """
        return self.plate_model_path or self.weights_dir / "license-plate.onnx"

    @property
    def resolved_plate_detect_every_n_frames(self) -> int:
        """Cadence effective du **détecteur** de plaques.

        Le repli sur la cadence de l'OCR n'est pas un défaut arbitraire : détecter
        plus souvent qu'on ne lit produirait des boîtes que personne ne consomme,
        puisque c'est la lecture qui décide du texte publié. C'est le comportement
        qui était câblé en dur dans le conteneur ; il devient le repli.
        """
        return self.plate_detect_every_n_frames or self.plate_ocr_every_n_frames

    @property
    def resolved_plate_ocr_intra_op_threads(self) -> int:
        """Threads intra-op d'onnxruntime pour l'OCR.

        Repli sur le budget global : un opérateur qui pose `TRAFFIC_INFERENCE_THREADS`
        veut borner **toute** l'inférence, pas seulement torch. Le réglage spécifique
        reste prioritaire, parce qu'il existe un cas où les deux diffèrent
        légitimement — plusieurs analyses concurrentes, où chaque pool intra-op doit
        être plus étroit que le budget de la machine.
        """
        return self.plate_ocr_intra_op_threads or self.inference_threads

    @property
    def resolved_plate_ocr_model_path(self) -> Path:
        """Chemin effectif du modèle de lecture. Même règle « vide ⇒ défaut »."""
        return self.plate_ocr_model_path or self.weights_dir / "license-plate-ocr.onnx"

    @property
    def resolved_plate_ocr_charset_path(self) -> Path:
        """Chemin effectif du dictionnaire de caractères.

        Séparé du modèle parce que ce sont deux fichiers distincts, mais **jamais
        indépendants** : le dictionnaire dit ce que veut dire chaque indice de sortie.
        `available` exige les deux, et l'adaptateur refuse de charger si leurs tailles
        ne correspondent pas.
        """
        return self.plate_ocr_charset_path or self.weights_dir / "license-plate-ocr.charset.txt"

    # ── Validation ───────────────────────────────────────────────────────────

    # Seuls les champs `Path | None` et `str | None` sont candidats à ce validateur :
    # il rend `None` pour une valeur vide, et `None` sur un `float`/`int` non
    # optionnel produirait une erreur de démarrage dont le message ne dirait rien de
    # la vraie cause. Les seuils OCR n'y figurent donc pas, à dessein.
    @field_validator(
        "plate_model_path",
        "static_dir",
        "cors_origin_regex",
        "plate_model_url",
        "plate_model_sha256",
        "plate_ocr_model_path",
        "plate_ocr_charset_path",
        "plate_ocr_model_url",
        "plate_ocr_model_sha256",
        "plate_ocr_charset_url",
        "plate_ocr_charset_sha256",
        mode="before",
    )
    @classmethod
    def _blank_means_unset(cls, value: object) -> object:
        """« Rien » veut dire « pas de valeur », pas « une valeur bizarre ».

        Deux formes de « rien » arrivent réellement dans un `.env` :

        - `TRAFFIC_STATIC_DIR=` — vide. Sans ce validateur, pydantic en fait
          `Path("")`, c'est-à-dire `Path(".")`, qui est **vrai** : le repli
          « vide ⇒ défaut » ne se déclenche jamais et le service sert le
          répertoire courant au lieu de rien ;
        - `TRAFFIC_PLATE_MODEL_PATH=  # vide = <weights>/license-plate.onnx` —
          un commentaire en fin de ligne après une valeur vide. Il **devient** la
          valeur, et le service cherche alors son modèle de plaques à un chemin
          nommé « # vide = … ». C'est exactement ce qui est arrivé ici : l'ANPR
          est restée indisponible pendant tout le projet, avec le bon fichier
          présent au bon endroit, et aucun message ne mentionnant la cause.

        Le second cas est traité parce qu'une valeur qui commence par `#` ne peut
        être ni un chemin, ni une URL, ni une empreinte : c'est un commentaire mal
        placé, et l'interpréter littéralement ne peut produire qu'une panne
        silencieuse. La ligne fautive est corrigée dans `.env.example` ; ce
        validateur protège les `.env` déjà écrits d'après lui.
        """
        if not isinstance(value, str):
            return value
        trimmed = value.strip()
        if not trimmed or trimmed.startswith("#"):
            return None
        return trimmed

    @field_validator("inference_imgsz")
    @classmethod
    def _require_stride_multiple(cls, value: int) -> int:
        """Le côté doit être un multiple de 32, le pas du réseau.

        Refusé plutôt qu'arrondi. Ultralytics, lui, arrondit **en silence** vers le
        haut et poursuit : un opérateur qui pose 500 pour gagner du temps mesurerait
        en réalité 512, comparerait deux courses en croyant les avoir séparées, et
        le rapport du banc afficherait une valeur que l'inférence n'a pas utilisée.
        Une erreur au démarrage coûte dix secondes ; une mesure fausse peut coûter
        une décision.
        """
        if value % 32:
            msg = (
                f"TRAFFIC_INFERENCE_IMGSZ={value} n'est pas un multiple de 32, le pas "
                f"du réseau. Prenez {value // 32 * 32} ou {(value // 32 + 1) * 32}."
            )
            raise ValueError(msg)
        return value

    @field_validator("weights_dir", "data_dir")
    @classmethod
    def _anchor_to_package_root(cls, value: Path) -> Path:
        """Un chemin relatif est ancré sur le dépôt, **jamais sur le CWD**.

        La panne évitée est silencieuse, et c'est la même famille que le
        commentaire en fin de ligne du `.env` : lancer `uvicorn` depuis la racine
        du dépôt plutôt que depuis `backend/` faisait résoudre `./.weights` en
        `<racine>/.weights`, un dossier qui n'existe pas. **Tous** les poids
        paraissaient alors absents — `license-plate.onnx` et les deux fichiers
        d'OCR compris — donc l'ANPR devenait indisponible sans qu'aucun message ne
        mentionne le répertoire de lancement. Le service démarre, le catalogue
        répond, et rien n'a l'air cassé.

        L'ancrage se fait sur la racine du paquet installé
        (`backend/`, deux niveaux au-dessus de `traffic_analysis/`), c'est-à-dire
        l'endroit où `scripts/fetch_*.py` déposent réellement les fichiers.

        Un chemin **enraciné** traverse inchangé : c'est la forme qu'utilise un
        déploiement conteneurisé, et la réécrire serait une surprise.

        Le critère est « porte une racine ou une lettre de lecteur », et **non**
        `is_absolute()`. La nuance est propre à Windows et elle compte : là-bas,
        `Path("/opt/poids").is_absolute()` est **faux** — un chemin enraciné sans
        lettre de lecteur n'est pas complet au sens de l'API. S'y fier ferait
        réécrire `/app/.weights` en `<backend>/app/.weights` sur une machine de
        développement Windows, c'est-à-dire déplacer silencieusement le chemin
        qu'un opérateur a écrit explicitement — précisément le mode de panne que
        ce validateur existe pour supprimer.

        À ne pas confondre avec `_tidy_downloaded_weights` du registre, qui garde
        délibérément son `Path.cwd()` : Ultralytics dépose ses téléchargements
        dans le répertoire courant, ce qui n'est pas le même chemin ni le même
        besoin.
        """
        if value.is_absolute() or value.root or value.drive:
            return value
        return (_PACKAGE_ROOT / value).resolve()

    @field_validator("cors_origins", "trusted_hosts", mode="before")
    @classmethod
    def _split_comma_separated(cls, value: object) -> object:
        """Accepte aussi bien `["a","b"]` (JSON) que `a,b` (liste simple).

        La forme JSON est celle de `.env.example`, mais une variable posée à la
        main dans un shell ou un `docker run -e` prend presque toujours la forme
        séparée par des virgules. Refuser la seconde ne protège de rien.
        """
        if isinstance(value, str) and not value.lstrip().startswith("["):
            return tuple(part.strip() for part in value.split(",") if part.strip())
        return value

    @field_validator("cors_origins")
    @classmethod
    def _reject_wildcard_origin(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        """`*` n'est jamais une origine acceptable ici.

        La liste est explicite en production comme en développement. En
        développement la voie normale est le proxy Vite (donc same-origin), et
        CORS n'est que le filet pour les appels directs.
        """
        if "*" in value:
            msg = (
                "TRAFFIC_CORS_ORIGINS ne doit jamais contenir '*' : "
                "listez les origines explicitement (voir prompt/06 §2)."
            )
            raise ValueError(msg)
        return value

    @field_validator("cors_origin_regex")
    @classmethod
    def _require_anchored_regex(cls, value: str | None) -> str | None:
        """La regex d'origine doit être ancrée aux DEUX bouts.

        Sans ancrage, `https://evil.com/#mon-domaine.dev` satisfait une regex
        censée n'autoriser que `*.mon-domaine.dev`.
        """
        if not value:
            return None
        if not (value.startswith("^") and value.endswith("$")):
            msg = (
                "TRAFFIC_CORS_ORIGIN_REGEX doit être ancrée par ^ et $ : sans cela "
                "une origine hostile peut la satisfaire par son fragment."
            )
            raise ValueError(msg)
        return value

    @model_validator(mode="after")
    def _reject_credentials_with_open_cors(self) -> Self:
        """`allow_credentials` avec une origine ouverte est refusé au démarrage.

        Le navigateur refuse déjà la combinaison `Allow-Credentials: true` +
        `Allow-Origin: *`. Échouer au boot vaut mieux qu'un comportement
        inexplicable en production.
        """
        if self.cors_allow_credentials and not self.cors_origins and not self.cors_origin_regex:
            msg = (
                "TRAFFIC_CORS_ALLOW_CREDENTIALS=true exige une liste d'origines "
                "explicite ou une regex ancrée."
            )
            raise ValueError(msg)
        return self

    @model_validator(mode="after")
    def _require_anchor_to_outlive_the_detector_gap(self) -> Self:
        """L'ancre doit survivre jusqu'à la détection suivante. Refusé au démarrage.

        Entre deux détections espacées de N images analysées, les images sautées
        portent des ancres d'âge 1 à N−1 ; `_project_anchor` cesse de reprojeter
        au-delà de `max_anchor_age`. Un âge trop court laisse donc des images **sans
        aucun rectangle**, ce qui est exactement le clignotement qu'ADR 0010 a
        supprimé et la raison pour laquelle `plate_policy` interdisait jusque-là
        d'étrangler le détecteur.

        Refusé, et non simplement signalé : la panne est purement visuelle, elle
        n'écrit rien dans les journaux et ne change aucun chiffre. Elle se lit comme
        un défaut de détection, jamais comme un défaut de configuration — donc elle
        se cherche là où elle n'est pas. Le message dit les deux issues.
        """
        gap = self.resolved_plate_detect_every_n_frames - 1
        if self.plate_detect_max_anchor_age < gap:
            msg = (
                f"TRAFFIC_PLATE_DETECT_MAX_ANCHOR_AGE={self.plate_detect_max_anchor_age} "
                f"est trop court pour une détection une image sur "
                f"{self.resolved_plate_detect_every_n_frames} : les images sautées "
                f"portent des ancres d'âge 1 à {gap}, donc les rectangles de plaque "
                f"clignoteraient. Posez au moins {gap}, ou baissez la cadence de "
                "détection (voir ADR 0010)."
            )
            raise ValueError(msg)
        return self

    @model_validator(mode="after")
    def _require_json_logs_in_production(self) -> Self:
        """En production, les journaux vont à un collecteur, pas à un terminal.

        Séparé de la règle sur les docs depuis le lot 14. Les deux vivaient dans un
        seul validateur nommé `_warn_free_docs_in_production` dont le corps testait
        `is_production and docs_enabled and log_format != "json"` : la contrainte
        sur les journaux **disparaissait** dès qu'on fermait les docs, ce qui est
        exactement l'inverse du lien que le nom suggérait. Une règle qui dépend
        d'une autre sans raison est une règle qu'on finit par violer sans le voir.
        """
        if self.is_production and self.log_format != "json":
            msg = (
                "En production, TRAFFIC_LOG_FORMAT doit valoir 'json' "
                "(les journaux sont destinés à un collecteur, pas à un terminal)."
            )
            raise ValueError(msg)
        return self

    @model_validator(mode="after")
    def _refuse_public_docs_in_production(self) -> Self:
        """Un `openapi.json` public expose la surface d'attaque complète.

        Refusé, et non simplement signalé. Le défaut `docs_enabled = True` sert le
        développement, où il est juste ; le laisser passer en production
        publierait chaque route, chaque schéma et chaque borne de validation à qui
        demande — une carte du service offerte à qui cherche par où entrer.

        Ce n'est pas irrévocable : exposer sa documentation est un choix légitime
        pour une API publique. Mais il doit être **explicite**, et
        `TRAFFIC_DOCS_ENABLED=true` posé à la main en production l'est ; le défaut
        hérité d'un fichier `.env` de développement ne l'est pas. Le message dit
        les deux issues.
        """
        if self.is_production and self.docs_enabled and not self.docs_public:
            msg = (
                "En production, la documentation de l'API est fermée par défaut. "
                "Posez TRAFFIC_DOCS_ENABLED=false, ou TRAFFIC_DOCS_PUBLIC=true si "
                "vous voulez délibérément publier le schéma OpenAPI."
            )
            raise ValueError(msg)
        return self


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Configuration du processus, construite une seule fois.

    Le cache est ce qui garantit qu'il n'existe qu'un objet `Settings` : les
    tests le vident (`get_settings.cache_clear()`) ou passent leur propre
    instance à `create_app()`, ils ne rechargent jamais l'environnement.
    """
    return Settings()
