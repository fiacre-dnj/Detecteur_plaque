"""La piste naissante et le mur d'association — le mécanisme, pas un correctif.

**Rien n'est changé ici.** Ce module verrouille un comportement du tracker qui n'est
documenté nulle part et qui explique une partie du « on a du mal à détecter les motos ».
Le jour où l'on touchera à `fuse_score` ou à `proximity_thresh`, ces tests diront
exactement ce qu'on gagne et ce qu'on perd — aujourd'hui la mesure manque pour trancher,
faute de métrage contenant des deux-roues.

**Le mécanisme.** Une piste née après la première image analysée n'est pas rendue tout
de suite : `byte_tracker.py` ne pose `is_activated` immédiatement qu'à `frame_id == 1`,
et `_format_output` ne rend que les pistes activées. Elle doit donc, dès l'image
suivante, se réapparier à une détection de la bande haute pour un coût ≤ 0,7, sinon elle
est `mark_removed()` — **détruite**, pas perdue, sans passer par `track_buffer`.

Deux garde-fous censés se relayer se ferment au même endroit, IoU ≈ 0,5 :

- `fuse_score: true` multiplie le score dans le coût (`matching.py`,
  `fuse_sim = iou_sim * det_scores`), donc le seuil n'est franchi que si
  `IoU × score ≥ 0,3` ;
- `proximity_thresh: 0.5` coupe le secours de l'apparence en dessous d'IoU 0,5
  (`bot_sort.py`, `emb_dists[dists_mask] = 1.0`).

Conséquence : un objet qui se déplace de plus d'environ **un quart de sa propre largeur
de boîte** par image analysée renaît sous un `track_id` neuf à chaque image, chacun vu
une seule fois, donc `hits` n'atteint jamais `min_hits`. Il est peint dans l'aperçu et
compté nulle part.

**La tolérance est une fraction de la largeur de l'objet** : une boîte étroite — une
moto, un piéton — est donc punie là où une voiture à la même vitesse ne l'est pas. C'est
une cause de suivi, distincte du NMS d'ADR 0057 et de la containment d'ADR 0056, et
cumulative avec elles.

Les valeurs de `config/botsort_reid.yaml` sont dites « laissées aux valeurs éprouvées
d'Ultralytics ». Elles sont éprouvées sur MOT17 — des piétons plein cadre — pas sur des
deux-roues de 60 px en vue de circulation.
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest
import yaml

from traffic_analysis.features.models_registry.infrastructure.ultralytics_engine import (
    TRACKER_CONFIG,
)

np = pytest.importorskip("numpy")
bot_sort = pytest.importorskip("ultralytics.trackers.bot_sort")

BASE = yaml.safe_load(TRACKER_CONFIG.read_text(encoding="utf-8"))

#: Boîte carrée de 60 px — l'ordre de grandeur d'une moto sur une vue de circulation.
BOX_SIDE = 60.0

#: Images alimentées après l'amorçage.
FRAMES = 14


class _Detections:
    """Le minimum de ce que `BOTSORT.update` lit d'un `Results.boxes`."""

    def __init__(self, xywh: Any, conf: Any, cls: Any) -> None:  # noqa: ANN401
        self.xywh = np.asarray(xywh, dtype=np.float32).reshape(-1, 4)
        self.conf = np.asarray(conf, dtype=np.float32)
        self.cls = np.asarray(cls, dtype=np.float32)

    def __len__(self) -> int:
        return len(self.conf)

    def __getitem__(self, mask: Any) -> _Detections:  # noqa: ANN401
        return _Detections(self.xywh[mask], self.conf[mask], self.cls[mask])

    @property
    def xyxy(self) -> Any:  # noqa: ANN401
        x, y, w, h = self.xywh.T
        return np.stack([x - w / 2, y - h / 2, x + w / 2, y + h / 2], axis=1)


EMPTY = _Detections(np.empty((0, 4)), np.empty(0), np.empty(0))

#: Une apparence CONSTANTE, alimentee comme `on_predict_postprocess_end` le fait
#: (`trackers/track.py`, `kwargs = {"feats": getattr(result, "feats", None)}`).
#:
#: Constante a dessein : on mesure le mur GEOMETRIQUE, pas la qualite du descripteur.
#: Une apparence identique a chaque image est le cas le plus favorable — ce qui rend
#: le mur d'autant plus parlant quand il se ferme quand meme.
FEATS = np.ones((1, 64), dtype=np.float32) / 8.0


def tracker_args(**overrides: Any) -> SimpleNamespace:  # noqa: ANN401
    """Les arguments **du fichier versionné**, surchargeables un par un.

    Lus du fichier plutôt que recopiés : un test qui figerait ses propres valeurs
    cesserait de décrire ce qui tourne réellement à la première modification du
    déploiement, et passerait quand même.
    """
    args = {
        "tracker_type": BASE["tracker_type"],
        "track_high_thresh": 0.35,
        "track_low_thresh": BASE["track_low_thresh"],
        "new_track_thresh": 0.35,
        "match_thresh": BASE["match_thresh"],
        "fuse_score": BASE["fuse_score"],
        "track_buffer": BASE["track_buffer"],
        "gmc_method": BASE["gmc_method"],
        "proximity_thresh": BASE["proximity_thresh"],
        "appearance_thresh": BASE["appearance_thresh"],
        "with_reid": BASE["with_reid"],
        "model": BASE["model"],
        "device": "cpu",
    }
    args.update(overrides)
    return SimpleNamespace(**args)


def run(score: float, dx: float, **overrides: Any) -> tuple[int, int]:  # noqa: ANN401
    """Un objet qui entre après le début et se déplace de `dx` par image.

    Rend `(hits du meilleur identifiant, nombre d'identifiants créés)`. Le premier dit
    si la piste a tenu, le second si elle a renaît à chaque image.

    Deux images vides d'abord : c'est ce qui rend la piste **naissante**. Née à
    `frame_id == 1`, elle serait activée d'office et le mur ne se poserait pas — la
    différence entre un objet déjà là au début du clip et un objet qui entre dans le
    champ, c'est-à-dire le cas courant.
    """
    tracker = bot_sort.BOTSORT(tracker_args(**overrides))
    for _ in range(2):
        tracker.update(EMPTY, None, feats=None)

    seen: dict[int, int] = {}
    for index in range(FRAMES):
        detections = _Detections([[100.0 + index * dx, 300.0, BOX_SIDE, BOX_SIDE]], [score], [3.0])
        for row in tracker.update(detections, None, feats=FEATS):
            track_id = int(row[4])
            seen[track_id] = seen.get(track_id, 0) + 1
    return (max(seen.values()) if seen else 0), len(seen)


class TestLaPremisse:
    def test_le_fichier_versionne_porte_bien_ces_valeurs(self) -> None:
        """Si l'une d'elles changeait, tout ce module décrirait autre chose."""
        assert BASE["fuse_score"] is True
        assert BASE["proximity_thresh"] == 0.5
        assert BASE["match_thresh"] == 0.8


class TestLObjetLentTientSaPiste:
    @pytest.mark.parametrize("dx", [0.0, 6.0, 12.0])
    def test_un_deplacement_sous_le_quart_de_la_boite_est_suivi(self, dx: float) -> None:
        """Une seule identité, vue à chaque image : le cas nominal."""
        assert run(0.40, dx) == (FRAMES - 1, 1)


class TestLeMurSeFermeEtSaPositionDependDuScore:
    """**Le mur, mesuré.** Une boîte de 60 px, apparence constante :

    | score | 12 px | 18 px | 24 px | 30 px |
    |---|---|---|---|---|
    | 0,85 | suivi | suivi | suivi | rien |
    | 0,60 | suivi | suivi | rien | rien |
    | 0,40 | suivi | **7 identités** | rien | rien |

    Deux façons de perdre l'objet, et la première est la plus trompeuse.
    """

    def test_a_la_frontiere_l_objet_renait_a_chaque_image(self) -> None:
        """**Sept identités, chacune vue une fois.**

        `hits` ne peut donc jamais atteindre `min_hits = 2` : l'objet est peint dans
        l'aperçu et compté nulle part. C'est le pire des deux modes de perte — il
        *paraît* suivi.
        """
        assert run(0.40, 18.0) == (1, 7)

    def test_au_dela_rien_n_est_rendu_du_tout(self) -> None:
        """Passé la frontière, la piste naissante n'est jamais activée : zéro sortie."""
        assert run(0.40, 24.0) == (0, 0)

    def test_un_score_eleve_repousse_le_mur(self) -> None:
        """`fuse_score` multiplie le score dans le coût : mieux scoré, plus tolérant.

        C'est ce qui rend le défaut si trompeur — le **même** déplacement passe ou casse
        selon la confiance, donc le symptôme paraît intermittent. Et une moto score
        structurellement plus bas qu'une voiture (ADR 0037 : 0,20 à 0,35 couramment).
        """
        assert run(0.85, 24.0) == (FRAMES - 1, 1)
        assert run(0.60, 24.0) == (0, 0)


class TestLesLeviersMesures:
    """Deux leviers, mesurés et **délibérément pas adoptés**.

    Les adopter changerait des comptages pour toutes les classes, et la mesure qui le
    trancherait demande du métrage contenant des deux-roues, qu'aucun clip de ce dépôt
    ne fournit. Ces tests existent pour que l'arbitrage soit chiffré le jour venu.
    """

    def test_couper_fuse_score_fait_tenir_la_piste(self) -> None:
        """Le levier qui marche : `fuse_score: false` retire le score du coût.

        Le même objet tient sa piste bien au-delà du mur. La clé est déjà dans
        `LIVE_TRACKER_KEYS`, donc rien de `reset_trackers` n'aurait à bouger.

        Pourquoi ne pas l'adopter : il retire le score pour **toutes** les classes et
        fabrique des échanges d'identité en trafic dense — silencieux et plausibles,
        deux identités valant deux véhicules et deux passages (invariant 6).
        """
        assert run(0.40, 24.0, fuse_score=False) == (FRAMES - 1, 1)

    def test_proximity_thresh_agit_dans_le_sens_INVERSE_de_son_nom(self) -> None:
        """**Le piège de nommage, et il a failli coûter un mauvais réglage.**

        « Seuil de proximité » se lit « il faut être au moins aussi proche », donc
        *monter* devrait resserrer... mais la ligne est
        `dists_mask = dists > (1 - self.proximity_thresh)` : c'est une **distance** qui
        est comparée. Monter à 0,8 n'autorise l'apparence qu'à partir d'IoU 0,8, donc
        **resserre** ; baisser à 0,2 l'autorise dès IoU 0,2, donc élargit.

        Mesuré, et c'est l'inverse de ce que l'analyse initiale annonçait : à 0,8 la
        piste meurt même à 12 px, un déplacement que le **défaut** suit sans peine.
        """
        assert run(0.40, 24.0, proximity_thresh=0.2) == (FRAMES - 1, 1)
        assert run(0.40, 12.0, proximity_thresh=0.8) == (0, 0)
        assert run(0.40, 12.0) == (FRAMES - 1, 1)
