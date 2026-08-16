"""Le garde de format du script de récupération du modèle de plaques.

**Pourquoi ce garde mérite des tests alors que le script en entier n'en avait
aucun.** Ultralytics choisit son backend d'après le *suffixe* du fichier, jamais
d'après son contenu (`ultralytics/nn/autobackend.py`, `_model_type()`). Un `.pt`
téléchargé vers `license-plate.onnx` passe donc la vérification d'empreinte, existe
sur le disque, rend `plateAvailable: true` — et ne détecte jamais rien, avec pour
seule trace une ligne de journal par processus.

C'est le quatrième exemplaire du même mode de panne dans ce projet : le `.env`
commenté, le dictionnaire d'OCR décalé d'un cran, `weights_dir` ancré sur le CWD, et
maintenant celui-ci. Tous : un drapeau vert, aucune exception, des chiffres
plausibles. Voir ADR 0015.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

_SPEC = importlib.util.spec_from_file_location(
    "fetch_plate_model",
    Path(__file__).resolve().parents[2] / "scripts" / "fetch_plate_model.py",
)
assert _SPEC is not None
assert _SPEC.loader is not None
fetch_plate_model = importlib.util.module_from_spec(_SPEC)
sys.modules["fetch_plate_model"] = fetch_plate_model
_SPEC.loader.exec_module(fetch_plate_model)

suffix_mismatch = fetch_plate_model.suffix_mismatch


class TestFormatsAccordes:
    def test_un_pt_vers_un_pt_passe(self) -> None:
        assert suffix_mismatch("https://h.test/modele.pt", Path("/w/license-plate.pt")) is None

    def test_un_onnx_vers_un_onnx_passe(self) -> None:
        """L'ONNX reste accepté : il fonctionne, il est seulement cloué au CPU ici."""
        assert suffix_mismatch("https://h.test/m.onnx", Path("/w/license-plate.onnx")) is None

    def test_la_casse_de_l_url_est_ignoree(self) -> None:
        assert suffix_mismatch("https://h.test/M.PT", Path("/w/license-plate.pt")) is None

    def test_une_requete_apres_le_nom_ne_masque_pas_le_suffixe(self) -> None:
        """`?download=true` est la forme courante d'un lien de CDN.

        Un `Path(url).suffix` naïf lirait « .pt?download=true », ne reconnaîtrait
        aucun format connu, et laisserait donc passer **tous** les désaccords : le
        garde serait présent et inopérant, ce qui est pire qu'absent.
        """
        assert (
            suffix_mismatch("https://h.test/m.pt?download=true", Path("/w/license-plate.pt"))
            is None
        )


class TestFormatsEnDesaccord:
    def test_un_pt_vers_un_onnx_est_refuse(self) -> None:
        """**Le cas qui a motivé le garde.**"""
        reason = suffix_mismatch("https://h.test/modele.pt", Path("/w/license-plate.onnx"))

        assert reason is not None
        # Le message doit nommer les deux formats et le chemin à corriger : un refus
        # qui ne dit pas quoi changer se contourne en supprimant le garde.
        assert ".pt" in reason
        assert ".onnx" in reason
        assert "TRAFFIC_PLATE_MODEL_PATH" in reason

    def test_un_onnx_vers_un_pt_est_refuse_aussi(self) -> None:
        """Le garde est symétrique : les deux sens produisent un modèle muet."""
        assert suffix_mismatch("https://h.test/m.onnx", Path("/w/license-plate.pt")) is not None

    def test_le_desaccord_est_detecte_meme_avec_une_requete(self) -> None:
        reason = suffix_mismatch("https://h.test/m.pt?x=1", Path("/w/license-plate.onnx"))

        assert reason is not None


class TestUrlSansFormatAnnonce:
    """Une URL muette ne bloque pas : l'auto-test du démarrage reste le filet.

    Un lien signé, une redirection ou une route d'API n'annoncent aucun suffixe.
    Refuser dans ce cas empêcherait des installations légitimes de fonctionner, pour
    un doute que `probe()` lèvera de toute façon au démarrage suivant.
    """

    def test_une_url_sans_extension_passe(self) -> None:
        assert (
            suffix_mismatch("https://h.test/api/download/42", Path("/w/license-plate.pt")) is None
        )

    def test_une_extension_inconnue_passe(self) -> None:
        assert suffix_mismatch("https://h.test/m.bin", Path("/w/license-plate.pt")) is None
