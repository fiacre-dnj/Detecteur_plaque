"""Configuration du service — un seul objet, chargé une fois, injecté partout.

Interdiction de lire `os.environ` ailleurs dans le code : une valeur de
configuration lue à deux endroits finit toujours par diverger entre les deux, et
un test ne peut pas la remplacer.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Literal, Self

from pydantic import Field, ValidationInfo, field_validator, model_validator
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
    #: n'est pas une erreur mais un `tracked_vehicles` qui gonfle.
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
    #: **Ce qu'il borne, et ce qu'il ne borne pas.** Il atteint tout ce qui passe par
    #: torch : le détecteur et le suivi des véhicules, qui tournent à *chaque* image,
    #: et **désormais le détecteur de plaques** — depuis son passage en `.pt`
    #: ([ADR 0015](../../../docs/adr/0015-le-detecteur-de-plaques-en-pt.md)), il vit
    #: sur les mêmes threads que le reste. Ce n'était pas le cas de l'export `.onnx`
    #: qu'il remplace : Ultralytics construisait sa session onnxruntime sans jamais
    #: passer de `SessionOptions`, donc ce budget lui était invisible — mesuré à
    #: l'époque, 656 ms à trois threads contre 702 sans budget, soit deux fois la
    #: même chose.
    #:
    #: Il atteint aussi l'OCR, dont on a vu la vignette passer de 66 à 85 ms en la
    #: ramenant à trois threads. L'OCR, elle, reste en onnxruntime, mais son
    #: adaptateur passe ses `SessionOptions` explicitement (`plate_reader.py`).
    #:
    #: Sans effet sur GPU, où l'inférence ne vit pas sur ces threads.
    inference_threads: int = Field(0, ge=0, le=64)
    #: Threads du `parallel_for_` d'**OpenCV**. `0` ne fait rien.
    #:
    #: Un second robinet, parce qu'`inference_threads` n'atteint qu'OpenCV via torch
    #: — c'est-à-dire jamais. Au repos, OpenCV prend *tous* les processeurs logiques
    #: (12 mesurés ici) quand torch en prend 6, et rien ne les arbitrait. Or le
    #: prétraitement d'Ultralytics est du pur OpenCV et tourne **dans le fil qui
    #: attend le GPU**, pendant que le fil de décodage d'ADR 0031 en veut autant :
    #: c'est nommément la contention qu'ADR 0031 désigne comme la cause de son gain
    #: non réalisé en 720p et 1080p, restée sans réglage jusqu'ici.
    #:
    #: **`0` par défaut, et c'est mesuré, pas prudent.** Trois mesures, et la
    #: troisième est celle qui décide :
    #:
    #: - micro-banc, machine libre, OpenCV à 3 fils au lieu de 12 : *perd* 3,4 % ;
    #: - micro-banc avec un fil OpenCV concurrent : *gagne* 9,7 puis 10,2 % ;
    #: - **pipeline réel** (`pipeline_bench --anpr --ocr`, courses alternées) :
    #:   20,92 → 20,97 puis 21,20 → 21,10 img/s. **Aucun effet**, et l'écart change
    #:   de signe d'une passe à l'autre.
    #:
    #: Le fil concurrent du micro-banc était un substitut ; dans le vrai pipeline, le
    #: décodage vit dans son propre fil depuis ADR 0031 et le détecteur de plaques
    #: domine le budget, donc la contention que ce réglage vise ne se produit pas sur
    #: ce profil. Il reste utile là où elle se produit — un navigateur qui lit la
    #: vidéo sur la même machine, plusieurs analyses concurrentes — et c'est
    #: précisément pourquoi il est réglable et non posé. Même doctrine
    #: qu'`inference_threads` : l'échange se mesure, il ne se suppose pas.
    #:
    #: Ne borne **pas** le pool du décodeur FFmpeg, qui se pose par capture. Le
    #: décodage vivant dans son propre fil depuis ADR 0031, il est hors du chemin
    #: critique, et son effet n'a pas été mesuré ici.
    opencv_threads: int = Field(0, ge=0, le=64)
    #: Laisser cuDNN choisir ses algorithmes de convolution **par la mesure**.
    #:
    #: **`false` par défaut, et c'est un correctif, pas un renoncement.** ADR 0013
    #: l'avait activé sans jamais chiffrer ce qu'il apportait, sur la prémisse que
    #: « notre forme d'entrée est fixe pour une vidéo donnée ». Cette prémisse est
    #: vraie du détecteur de véhicules et **fausse du détecteur de plaques**, qui reçoit
    #: un recadrage différent par piste : Ultralytics impose `rect=True` en prédiction,
    #: donc un recadrage soumis seul produit une forme d'entrée qui dépend de son
    #: rapport d'aspect. cuDNN réétalonne à **chaque nouvelle forme**, et cet
    #: étalonnage coûte environ une seconde.
    #:
    #: Mesuré sur deux scènes réelles, ANPR et OCR actives, à détections et plaques
    #: publiées **strictement identiques** :
    #:
    #: | scène | autotune actif | coupé | gain |
    #: |---|---|---|---|
    #: | clairsemée (1 recadrage par appel) | 8,4 img/s | **18,2** | **2,17×** |
    #: | dense (2,3 recadrages par image) | 8,0 img/s | **11,0** | **1,38×** |
    #:
    #: Sur la scène clairsemée, **six appels sur 124 dépassaient la seconde et pesaient
    #: 73 %** du temps de l'étage de plaques. Après, plus aucun au-dessus de 100 ms.
    #:
    #: Et ce que l'autotune rendait au chemin dont la forme *est* fixe : **rien de
    #: mesurable** — inférence véhicules 7,92 ms avec, 8,00 ms sans, soit le bruit.
    #:
    #: Le réglage existe donc pour une machine où la mesure dirait autre chose — une
    #: carte plus récente, un déploiement sans ANPR. `scripts/pipeline_bench.py --cudnn`
    #: la refait sans toucher à l'environnement. Voir ADR 0033.
    inference_cudnn_autotune: bool = False
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
    plate_model_path: Path | None = None  # vide = <weights_dir>/license-plate.pt
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
    #: Côté de l'entrée du **détecteur de plaques**, en pixels. Multiple de 32.
    #:
    #: **C'est le premier poste du budget dès que l'ANPR est active, et de loin.**
    #: Mesuré sur une scène dense réelle (1920×1080, 6 à 14 véhicules par image,
    #: `--anpr --ocr`) : l'étage de plaques coûte **76 ms par image analysée, soit
    #: 73 % du total**, contre 0,4 ms pour l'OCR. Le coût est **linéaire en nombre de
    #: recadrages** — 21,5 ms pour un, 139,7 pour huit — parce que chaque recadrage de
    #: véhicule paie une inférence complète, exactement comme une image entière.
    #:
    #: Le côté de l'entrée est donc le seul levier qui n'exige pas d'en détecter
    #: moins. Mesuré sur les mêmes huit recadrages, plaques trouvées à l'identique :
    #:
    #: | côté | ms/appel | ms/recadrage |
    #: |------|----------|--------------|
    #: | 640  | 141,1    | 17,6         |
    #: | 448  | 77,8     | 9,7          |
    #: | 320  | 56,8     | 7,1          |
    #:
    #: **640 reste le défaut**, parce que c'est la résolution d'entraînement du modèle
    #: et qu'on ne troque pas du rappel contre du débit sans que quelqu'un le demande
    #: (même règle que la mosaïque, ADR 0008). Ce qui décide qu'une plaque est trouvée
    #: est sa taille **dans l'entrée du réseau** : le recadrage étant agrandi jusqu'à
    #: ce côté, une plaque y occupe ~0,15 × côté, soit ~96 px à 640 et ~48 px à 320.
    #: Descendre se paie donc d'abord sur les **véhicules lointains**, dont la plaque
    #: était de toute façon sous le plancher de lecture de l'OCR (64 px, invariant 12).
    #:
    #: À calibrer sur ses propres vidéos avec `scripts/anpr_bench.py --net-size …`, en
    #: regardant les plaques **détectées** et les textes **publiés**, jamais la seule
    #: cadence.
    plate_net_size: int = Field(640, ge=64, le=1280)

    # ── Étranglement du détecteur de plaques (ADR 0010) ──────────────────────
    # **Le vrai goulot, et de loin.** Sur une vue de circulation réelle, l'étage de
    # plaques pèse 73 % du budget par image (ADR 0032), à 17,5 ms par recadrage sur
    # GPU — chaque véhicule payant une inférence entière.
    #
    # Le rapport « 702 ms contre 66 ms, soit 10,7 à 1 » qui vivait ici est **périmé**
    # et ADR 0030 l'a explicitement déclaré faux : il datait d'une mesure CPU
    # (i5-8350U) d'avant le passage du détecteur en `.pt` sur GPU (ADR 0015, 45,2 ms
    # par inférence) et d'avant le lot d'ADR 0030. Sa conclusion — « optimiser l'OCR
    # ne rend rien » — reste vraie sur une vue large où aucune plaque n'est lisible,
    # et fausse dès que des plaques sont lues : mesuré ici, OCR 18,9 % du budget.
    #
    # Ces trois réglages existaient dans `PlateDetectOptions` sans que personne
    # puisse les atteindre : le conteneur ne passait que `every_n_frames`, repris de
    # celui de l'OCR. Les exposer est ce qui rend l'arbitrage débit/fraîcheur
    # réglable sans recompiler.
    #: Une image analysée sur N par piste. `None` = suit la cadence de l'OCR, ce qui
    #: était le comportement câblé en dur.
    plate_detect_every_n_frames: int | None = Field(None, ge=1, le=30)
    #: Sous cette largeur de **véhicule**, la plaque fera au mieux quelques pixels :
    #: l'inférence coûterait une passe entière sans rien pouvoir trouver
    #: d'exploitable — 17,5 ms par recadrage sur cette carte (ADR 0032).
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
    #: Suspendre une piste dont les plaques mesurées restent sous le plancher de lecture.
    #:
    #: **Le plus gros levier de cadence de l'ANPR, et il ne coûte aucun texte.** Sur une
    #: vue de circulation réelle (ADR 0032), la détection de plaques pèse 73 % du budget
    #: et **aucune plaque n'y est publiable** — elles font moins de 48 px pour un plancher
    #: de lecture à 64 (invariant 12). La porte compare la largeur **mesurée sur cette
    #: piste-là** au *même* nombre que l'OCR utilise déjà pour refuser de lire : une
    #: plaque écartée est une plaque qui aurait été refusée de toute façon.
    #:
    #: Ce qui est réellement payé, et c'est pourquoi le réglage existe : le **rectangle**
    #: disparaît sur ces véhicules, après les `max_anchor_age` images de reprojection. Le
    #: service dit déjà pourquoi par `plate_unread_reason = too_small`. Mettre `false`
    #: rend tous les rectangles, au prix de la cadence.
    #:
    #: Sans OCR, la porte ne s'arme **jamais** : le service ne la pose que si un lecteur
    #: tourne réellement.
    plate_detect_readable_gate: bool = True
    #: Mesures consécutives sous le plancher avant de suspendre la piste.
    plate_detect_readable_min_samples: int = Field(2, ge=1, le=10)
    #: Réarmement d'office toutes les N images analysées. `0` = jamais, le défaut.
    #:
    #: La porte se rouvre déjà **seule** quand le véhicule s'approche — c'est une mesure,
    #: pas un délai. Ce quota n'existe que pour le cas, non observé à ce jour, d'une piste
    #: réellement lisible qui ne grandirait pas.
    plate_detect_readable_retry_every: int = Field(0, ge=0, le=300)
    #: Recadrages soumis au détecteur par image analysée, au plus. `0` = illimité.
    #:
    #: **Le seul plafond qui rende le coût de l'ANPR indépendant de la scène.** Sans
    #: lui, la cadence suit la circulation : mesuré sur une scène dense réelle
    #: (1920×1080, 6 à 14 véhicules par image), l'étage de plaques coûte 76 ms par
    #: image analysée — 73 % du budget, contre 0,4 ms pour l'OCR — et ce coût est
    #: **linéaire en nombre de recadrages**, chaque véhicule payant une inférence
    #: entière (21,5 ms pour un recadrage, 139,7 pour huit).
    #:
    #: `0` par défaut, c'est-à-dire le comportement historique : plafonner écarte des
    #: mesures, donc des plaques possibles, et cet arbitrage ne se prend pas à la place
    #: de l'exploitant. Ce qui n'est pas servi cette image l'est à la suivante — le
    #: texte publié est un vote sur la vie du véhicule (invariant 4) — et le budget va
    #: d'abord aux pistes jamais mesurées, puis aux plus larges.
    #:
    #: **Son gain est bien plus faible qu'annoncé d'abord, et son prix est réel.** Le
    #: 1,27× qui lui était attribué venait surtout de ce qu'il évitait les appels à un
    #: seul recadrage, donc les pauses d'étalonnage cuDNN d'ADR 0033. Cette cause
    #: corrigée, sur la scène dense, à comptages identiques :
    #:
    #: | plafond | img/s | recadrages/image | plaques **localisées** |
    #: |---|---|---|---|
    #: | 0 (illimité) | 11,0 | 2,28 | **180** |
    #: | 2 | 9,0 | 1,74 | 137 |
    #: | 1 | 13,8 | 1,00 | 76 |
    #:
    #: Le plafond **coûte des plaques localisées**, à peu près proportionnellement aux
    #: recadrages écartés, et sa cadence ne s'ordonne pas proprement (`2` plus lent que
    #: `0` sur cette passe, à coût d'étage quasi égal). Il **borne** le coût quand le
    #: trafic monte ; il ne l'améliore pas dans le cas général.
    #:
    #: À mesurer avec `scripts/pipeline_bench.py --anpr --ocr` : la cadence d'un côté,
    #: les **plaques publiées** de l'autre. Un plafond qui double la cadence en
    #: publiant une plaque de moins n'est pas un réglage, c'est une perte.
    plate_detect_max_per_frame: int = Field(0, ge=0, le=32)

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
    #:
    #: **`1.0` — donc désactivé — depuis ADR 0029, et c'est une mesure qui l'a
    #: décidé.** À `1.25`, ce garde *affamait le vote* : sur une fenêtre de vraie
    #: circulation, le serveur publiait `R606` pour une plaque `苏A·R606L`, ou plus
    #: rien du tout. La raison est arithmétique — `PlateTextVote` exige deux lectures
    #: concordantes, une confiance cumulée de 1,2 et une domination de 1,5, et une
    #: exigence d'amélioration de 25 % à chaque relecture ne laissait que deux ou
    #: trois lectures sur toute la vie d'un véhicule. Réparties sur quatre graphies
    #: voisines, aucune ne pouvait dominer. À `1.0`, la même fenêtre publie
    #: `AR606L`, la vérité terrain.
    #:
    #: Le raisonnement d'origine n'était pas faux, il était **déjà couvert** :
    #: `plate_ocr_skip_iou` interdit déjà de relire le recadrage figé d'un véhicule
    #: arrêté au feu, qui est le cas où la confiance se gonflerait pour rien.
    #:
    #: **Et cela ne coûte pas plus cher.** L'analyse de la même fenêtre n'a pas
    #: ralenti — la mesure la donne même plus rapide, parce qu'un vote qui converge
    #: déclenche `stop_when_confident`, lequel arrête le *détecteur* de plaques,
    #: c'est-à-dire le vrai goulot (ADR 0015).
    plate_ocr_quality_improvement: float = Field(1.0, ge=1.0, le=10.0)
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
    #: Fractions rognées **à gauche**, une variante de lecture par valeur.
    #:
    #: Elles existent pour un caractère de tête absent de l'alphabet du modèle — un
    #: idéogramme de province chinois, un blason régional : le CTC doit émettre
    #: quelque chose pour ces pas de temps, et ce quelque chose mange la lettre
    #: voisine. Mesuré sur 40 vignettes de vraie circulation, la chaîne rendait la
    #: plaque **moins sa première lettre** (`96886` pour `苏A·96886`) à 0,90 de
    #: confiance ; le même recadrage privé de son bord gauche rend `A96886` à 0,97.
    #: Lectures exactes 8/40 → 17/40, plaques publiées justes 1/6 → 3/6, et
    #: l'échelle synthétique **latine** — le contrôle indépendant, sans idéogramme —
    #: passe de 40 à 43 sur 56.
    #:
    #: Vide désactive la famille. Le coût est de deux lignes de tenseur dans le lot
    #: déjà envoyé, soit ~38 ms par lecture là où le détecteur de plaques en coûte
    #: 700 : le rapport reste celui d'ADR 0015.
    plate_ocr_left_insets: tuple[float, ...] = (0.14, 0.22)
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

    # ── Ressemblance de véhicule (recherche par image) ───────────────────────
    #: Encodeur d'apparence de véhicule. Vide = <weights_dir>/vehicle-reid.onnx.
    #:
    #: **Optionnel, et son absence ne dégrade rien** : sans lui, la recherche par
    #: image est indisponible (`reidAvailable: false`) et pas un compteur ne change.
    #: Même doctrine que les deux étages de plaques.
    #:
    #: `.onnx` et non `.pt` : le modèle retenu (OSNet-AIN entraîné sur VeRi-776) n'a
    #: pas d'équivalent Ultralytics, et `onnxruntime` n'ayant pas de provider CUDA
    #: ici, il tourne sur CPU — 21,8 ms mesurés par vignette, acceptable parce qu'on
    #: encode **quelques fois dans la vie d'un véhicule** et non par image. C'est la
    #: marge `reid_appearance_improvement` qui le garantit ; la règle monotone seule
    #: ne le faisait pas. Voir ADR 0048, amendée par ADR 0050.
    reid_model_path: Path | None = None
    #: Similarité cosinus en dessous de laquelle un véhicule n'est pas publié.
    #:
    #: **Un plancher de déploiement, pas le seuil de l'utilisateur** : celui-ci vit
    #: côté client, sur le score brut, et peut donc bouger sans réanalyser (ADR 0048).
    #: Celui-ci ne sert qu'à ne pas transporter des scores dont on sait qu'ils ne
    #: veulent rien dire.
    reid_min_similarity: float = Field(0.0, ge=0.0, le=1.0)
    #: Largeur de véhicule, en pixels, sous laquelle on n'encode pas.
    #:
    #: **Mesuré, pas supposé** (`scripts/reid_bench.py --truth-ladder`) : l'entrée du
    #: réseau fait 208 px, et sous ce plancher un recadrage agrandi n'apporte aucune
    #: information — l'embedding ressemble surtout au flou. Même famille de réglage
    #: que `plate_ocr_min_width_px`, et même raison d'exister : ne pas payer une
    #: inférence pour un résultat qu'on sait sans valeur (ADR 0039).
    reid_min_vehicle_width_px: float = Field(96.0, ge=16.0, le=1024.0)
    #: Marge de largeur exigée pour **réencoder** une piste déjà encodée.
    #:
    #: La règle monotone d'ADR 0048 (« plus large que la meilleure vue ») ne bornait
    #: rien : sur un véhicule qui approche, la largeur croît de façon quasi monotone,
    #: donc elle est vraie à *presque chaque image analysée*. On payait jusqu'à un
    #: encodage par image — **21,8 ms de CPU mesurés par vignette** sur cette machine
    #: — pour un étage dont la docstring annonçait « une fois par véhicule ».
    #:
    #: `1.15` autorise au plus `log_1,15(400 / 96) ≈ 11` encodages sur la vie d'une
    #: piste, contre une centaine sans marge. Le bornage est **logarithmique**, d'où
    #: une valeur modeste : pousser à `1,5` ne diviserait le compte que par deux de
    #: plus tout en coûtant plus de séparation.
    #:
    #: Ce que ça coûte, chiffré : la séparation same/diff d'ADR 0048 décroît
    #: régulièrement (+0,462 à 208 px, +0,310 à 48 px, sans falaise), donc 15 % de
    #: largeur en moins valent ~0,015 de séparation — pour un seuil client à 0,55 et
    #: des moyennes mesurées à 0,816 et 0,249. Personne ne bascule.
    #:
    #: `1.0` désactive la marge et reproduit ADR 0048 au bit près.
    reid_appearance_improvement: float = Field(1.15, ge=1.0, le=4.0)
    #: Plafond d'encodages d'apparence **par image**. `0` = illimité.
    #:
    #: Le jumeau de `plate_detect_max_per_frame`, et il borne autre chose que la marge
    #: ci-dessus : celle-ci borne le total sur la vie d'une piste, celui-ci la
    #: **rafale sur une image**. Sans lui, une image chargée peut soumettre jusqu'à
    #: `MAX_BATCH` (16) vignettes à 21,8 ms pièce — ~350 ms de blocage CPU en un seul
    #: appel, pendant lequel le GPU dort et l'aperçu ne sort pas.
    #:
    #: Ce n'est **pas** un gain de moyenne : c'est un plafond de pire cas, et ce que
    #: l'utilisateur en voit est un aperçu qui cesse de hoqueter. Ce qui n'est pas
    #: servi n'est pas perdu — la piste repasse candidate à l'image suivante.
    reid_max_per_frame: int = Field(0, ge=0, le=32)
    #: Threads intra-op d'onnxruntime pour l'encodeur d'apparence. `0` = repli sur
    #: `inference_threads`. Voir `resolved_reid_intra_op_threads` pour la mesure.
    reid_intra_op_threads: int = Field(0, ge=0, le=32)
    #: Netteté minimale (variance du laplacien) d'un recadrage encodé.
    #:
    #: Un véhicule assez large mais flou de mouvement rend un embedding instable.
    #: Même métrique et même doctrine que `plate_ocr_min_sharpness`.
    reid_min_sharpness: float = Field(8.0, ge=0.0, le=1000.0)
    # Utilisés par scripts/fetch_reid_model.py uniquement, même règle que les autres
    # poids : le service ne télécharge jamais de lui-même.
    reid_model_url: str | None = None
    reid_model_sha256: str | None = None
    #: Taille maximale de l'image de requête, en kibioctets.
    #:
    #: Petite exprès : le client cadre avant d'envoyer, donc ce qui arrive est une
    #: vignette de véhicule. 2 Mio laissent passer un recadrage 4K non compressé et
    #: refusent une photo de téléphone entière — laquelle serait de toute façon
    #: étirée à 208 px par le réseau, donc n'apporterait rien.
    max_query_image_kb: int = Field(2048, ge=16, le=32768)

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
    #: Intervalle d'aperçu quand l'analyse est **bridée sur le temps de la scène**
    #: (`analysisSpeed` dans la requête), en millisecondes.
    #:
    #: Plus serré que le régime normal, parce que le bridage change ce qu'on attend
    #: de l'aperçu : à 1×, 200 ms d'intervalle ne montrent que cinq images de scène
    #: par seconde — la vitesse est juste, l'aperçu reste un diaporama. Brider *est*
    #: la décision de regarder l'analyse, donc celle d'accepter plus de trames sur
    #: le flux ; elles ne portent que des boîtes et des compteurs, jamais de pixels.
    #:
    #: **N'élargit jamais** `preview_interval_ms` : le minimum des deux est retenu.
    #: Un déploiement qui a délibérément desserré l'aperçu garde son arbitrage.
    preview_interval_paced_ms: int = Field(100, ge=0, le=5000)
    #: Intervalle de republication du **registre des véhicules** dans l'aperçu, en
    #: millisecondes. C'est lui qui permet au registre et à la statistique de se
    #: remplir *pendant* l'analyse au lieu d'attendre la fin.
    #:
    #: Une cadence à part, et dix fois plus lente que celle des boîtes, parce que
    #: les deux volumes ne se comparent pas : les pistes d'une image sont une
    #: poignée, le registre **grossit** avec l'analyse — 350 octets par véhicule
    #: mesurés sur les résultats archivés de ce dépôt. Le republier à la cadence des
    #: boîtes ferait donc croître le débit du flux avec l'avancement, pour un tableau
    #: que personne ne lit dix fois par seconde.
    #:
    #: `0` le retire de l'aperçu — le registre reste alors vide jusqu'à la fin —
    #: sans retirer l'aperçu, qui dépend de `preview_interval_ms` seul. L'aperçu
    #: **final** porte le registre quelle que soit cette valeur.
    preview_vehicles_interval_ms: int = Field(1000, ge=0, le=30000)
    job_ttl_minutes: int = Field(1440, ge=1)
    #: Durée de vie de la **vidéo déposée**, distincte de celle du job.
    #:
    #: Elle valait 60 minutes, au motif que « la vidéo n'est plus nécessaire une fois
    #: le résultat produit ». Ce motif a cessé d'être vrai le jour où l'historique a
    #: su rejouer une analyse : rouvrir un résultat redessine les boîtes sur l'image
    #: et déplace la lecture depuis la timeline, et les deux demandent la vidéo. Une
    #: purge à 60 minutes rendait donc la fonction inutilisable au bout d'une heure,
    #: sur des résultats gardés 24.
    #:
    #: **Reste un réglage à part, et c'est délibéré.** La vidéo est la donnée la plus
    #: lourde et la plus sensible du service — une scène de trafic contient des
    #: plaques réelles et des visages, là où un résultat ne porte que des boîtes et
    #: des compteurs. Un déploiement qui veut une rétention courte la baisse ici sans
    #: toucher à celle des résultats ; il perd le rejeu sur image, pas les chiffres.
    input_ttl_minutes: int = Field(1440, ge=1)

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

        **Le suffixe `.pt` fait partie du contrat, pas de la décoration.**
        Ultralytics choisit son backend d'après le suffixe du fichier
        (`ultralytics/nn/autobackend.py`, `_model_type()`), et rien ne vérifie
        que le contenu correspond. Un `.pt` déposé sous un nom en `.onnx` est
        donc lu par le backend onnxruntime, qui échoue — mais après que
        `plate_available` a déjà répondu « oui », puisque le fichier existe.
        Le résultat est un drapeau vert et zéro plaque à chaque image.
        Voir [ADR 0015](../../../docs/adr/0015-le-detecteur-de-plaques-en-pt.md).
        """
        return self.plate_model_path or self.weights_dir / "license-plate.pt"

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
    def resolved_reid_intra_op_threads(self) -> int:
        """Threads intra-op d'onnxruntime pour l'encodeur d'apparence.

        **Le même trou que l'OCR avait comblé, resté ouvert dans un second
        adaptateur.** `OnnxVehicleEmbedder` construisait ses `SessionOptions` sans
        budget, donc `TRAFFIC_INFERENCE_THREADS` atteignait torch et l'OCR mais pas
        lui — sur un étage qui coûte 21,8 ms de CPU par vignette pendant que le fil
        de décodage et le prétraitement torch veulent les mêmes cœurs.

        Mesuré ici : défaut (0) **17,0 ms**, 3 fils 17,5, 6 fils 18,5, **12 fils
        31,9 ms**. Borner à 3 coûte 3 % sur l'étage et rend trois cœurs au reste ;
        forcer 12 est **1,9× pire** — l'hyperthreading dessert ce graphe, et un
        opérateur qui poserait 12 « pour tout donner » ferait exactement cela.

        Même repli que l'OCR, et pour la même raison.
        """
        return self.reid_intra_op_threads or self.inference_threads

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

    @property
    def max_query_image_bytes(self) -> int:
        """La borne de l'image de requête en octets. Même patron que `max_upload_bytes`."""
        return self.max_query_image_kb * 1024

    @property
    def resolved_reid_model_path(self) -> Path:
        """Chemin effectif de l'encodeur de ressemblance. Même règle « vide ⇒ défaut ».

        Le suffixe `.onnx` fait partie du contrat : l'adaptateur charge par
        `onnxruntime`, qui ne lit que cela. Un `.pt` déposé sous ce nom rendrait
        `reidAvailable: true` puis échouerait à l'auto-test — d'où `probe()`.
        """
        return self.reid_model_path or self.weights_dir / "vehicle-reid.onnx"

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
        "reid_model_path",
        "reid_model_url",
        "reid_model_sha256",
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
        - `TRAFFIC_PLATE_MODEL_PATH=  # vide = <weights>/license-plate.pt` —
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

    @field_validator("inference_imgsz", "plate_net_size")
    @classmethod
    def _require_stride_multiple(cls, value: int, info: ValidationInfo) -> int:
        """Le côté doit être un multiple de 32, le pas du réseau.

        Refusé plutôt qu'arrondi. Ultralytics, lui, arrondit **en silence** vers le
        haut et poursuit : un opérateur qui pose 500 pour gagner du temps mesurerait
        en réalité 512, comparerait deux courses en croyant les avoir séparées, et
        le rapport du banc afficherait une valeur que l'inférence n'a pas utilisée.
        Une erreur au démarrage coûte dix secondes ; une mesure fausse peut coûter
        une décision.
        """
        if value % 32:
            name = f"TRAFFIC_{(info.field_name or '').upper()}"
            msg = (
                f"{name}={value} n'est pas un multiple de 32, le pas "
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
        paraissaient alors absents — `license-plate.pt` et les deux fichiers
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
