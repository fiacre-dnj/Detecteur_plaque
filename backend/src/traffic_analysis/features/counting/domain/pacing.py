"""Cadencer l'analyse sur le temps de la scène.

**Pourquoi brider une analyse rapide.** L'aperçu live n'est pas une vidéo : le
client *cale* sa balise `<video>` sur le temps de scène de chaque échantillon, il
ne la lit pas (`useFollowAnalysis`). Or les échantillons sont espacés en **temps
mural** — au plus un toutes les 200 ms. Le curseur avance donc, par seconde
réelle, de `fps_analyse / fps_vidéo` seconde de scène : à 55 images par seconde
sur une source à 25 fps, l'aperçu défile **2,2× trop vite**. Ce n'est pas un
défaut de l'aperçu, c'est la conséquence arithmétique d'un GPU plus rapide que la
scène.

Le remède est ici : attendre entre deux images pour que le temps de scène analysé
n'aille jamais plus vite que le temps réel — ou qu'un multiple choisi de celui-ci.

**Le compromis est explicite et il coûte cher** : une analyse bridée à 1× dure
exactement la durée de la vidéo. C'est pourquoi le défaut reste *illimité* — qui
ne demande rien garde son débit — et pourquoi la cadence voyage par requête
plutôt que par déploiement : seul l'utilisateur devant sa vidéo sait s'il veut la
regarder ou obtenir ses chiffres.

**L'horloge murale est légitime ici**, comme pour la mesure de cadence, et pour la
même raison : ce module ne produit aucun horodatage métier. Il ne fait que décider
d'une attente. Tous les temps de scène restent `frame_index / fps × 1000`
(invariant 1).
"""

from __future__ import annotations

from dataclasses import dataclass, field

#: Cadence en deçà de laquelle on refuse de brider, en multiples du temps réel.
#:
#: Une valeur très basse ferait d'une analyse de trente secondes une analyse de
#: plusieurs minutes passées à dormir, et allongerait d'autant le délai de prise en
#: compte d'une annulation — qui n'est observée qu'entre deux images.
MIN_SPEED = 0.25

#: Cadence au-delà de laquelle brider n'a plus de sens : aucune machine n'atteint
#: huit fois le temps réel sur une source réaliste, donc l'attente serait toujours
#: nulle et le bridage un mensonge à l'écran.
MAX_SPEED = 8.0

#: Retard, en périodes, au-delà duquel on renonce à rattraper.
#:
#: **Trois, et c'est une valeur mesurée.** Le coût d'une image varie beaucoup —
#: mesuré sur un clip de 240 images à 1× : 14,8 ms en moyenne, mais 60 images
#: dépassent leur période de 33,3 ms. Sans rattrapage du tout, chacune de ces
#: pointes repoussait définitivement l'échéance : 1,58 s perdues, soit un bridage à
#: « 1× » qui rendait **0,82×**. En autorisant trois périodes de retard à être
#: rattrapées, ces pointes sont absorbées.
#:
#: La borne est ce qui rend le rattrapage invisible : au pire, trois images partent
#: à pleine vitesse — une centaine de millisecondes de scène. Sans borne, un vrai
#: décrochage (chargement de poids, passe ANPR chère) serait suivi d'une rafale
#: d'images sans attente, donc d'une accélération visible de l'aperçu : exactement
#: le symptôme que le bridage existe pour corriger.
MAX_LATENESS_PERIODS = 3.0


@dataclass(slots=True)
class ScenePacer:
    """Combien attendre avant d'analyser l'image suivante.

    **Le rattrapage est autorisé, borné à `MAX_LATENESS_PERIODS`.** Les deux bornes
    sont mesurées, pas choisies par prudence — voir la constante : sans rattrapage,
    un bridage à 1× rendait 0,82× ; sans borne, un décrochage serait suivi d'une
    rafale visible.

    Au-delà de la borne, l'échéance repart du temps réellement écoulé. En deçà, elle
    reste sur sa grille absolue, et l'image suivante dort d'autant moins.
    """

    #: Temps de scène couvert par une image analysée, divisé par la cadence voulue.
    period_s: float
    #: Échéance de la prochaine image, en temps de travail écoulé.
    #:
    #: Amorcée à une période, et non à zéro : `wait_s` est appelée **après** avoir
    #: analysé une image, donc la première échéance à honorer est celle de la
    #: seconde image. À zéro, les deux premières images partiraient à la suite sans
    #: attendre.
    _due_s: float = field(init=False, default=0.0)

    def __post_init__(self) -> None:
        self._due_s = self.period_s

    @staticmethod
    def for_video(fps: float, frame_stride: int, speed: float | None) -> ScenePacer | None:
        """Le cadenceur d'une vidéo, ou `None` s'il n'y a rien à brider.

        Trois refus, tous rendus par `None` plutôt que par une exception : aucun
        n'est une erreur de l'utilisateur, et aucun ne justifie de renoncer à
        compter.

        - `speed is None` — le défaut : personne n'a demandé de bridage ;
        - `fps <= 0` — un conteneur mal formé ne dit pas sa cadence, donc on ne
          sait pas ce que « temps réel » voudrait dire pour lui. Défensif : le
          `probe()` de l'adaptateur réel retombe sur sa cadence de repli avant
          d'en arriver là, mais `VideoInfo` autorise la valeur et `duration_ms`
          s'en protège de la même façon ;
        - une cadence hors bornes, ramenée dans l'intervalle par le schéma
          d'entrée bien avant d'arriver ici.

        `frame_stride` entre dans le calcul : avec un pas de 3, chaque image
        analysée fait avancer la scène de trois images. Cadencer sur le nombre
        d'images analysées et non sur le temps de scène qu'elles couvrent
        brimerait l'analyse au tiers de la vitesse demandée.
        """
        if speed is None or speed <= 0.0:
            return None
        if fps <= 0.0:
            return None
        return ScenePacer(period_s=frame_stride / (fps * speed))

    def wait_s(self, elapsed_s: float) -> float:
        """Temps à attendre avant l'image suivante, en secondes.

        Appelée une fois par image analysée, **après** l'avoir analysée.

        @param elapsed_s Temps de **travail** écoulé depuis le début de l'analyse,
            pauses déduites. Une analyse suspendue vingt minutes ne doit pas
            reprendre en rafale pour rattraper son échéance : elle n'a pas
            ralenti, elle a attendu.
        """
        wait = self._due_s - elapsed_s
        if wait <= -MAX_LATENESS_PERIODS * self.period_s:
            # Décrochage franc : l'échéance repart d'ici, sinon les images suivantes
            # partiraient en rafale pour rattraper tout le retard accumulé.
            self._due_s = elapsed_s + self.period_s
            return 0.0
        # Sur la grille absolue, en avance comme en retard rattrapable. C'est ce qui
        # absorbe les pointes de coût : les images suivantes dorment d'autant moins.
        self._due_s += self.period_s
        return wait if wait > 0.0 else 0.0
