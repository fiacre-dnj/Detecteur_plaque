"""Le consensus du texte de plaque d'une identité, sur toute sa vie.

**C'est l'invariant 4 appliqué au texte.** On publie la plaque du *véhicule*, jamais
celle de la frame courante : sinon le registre afficherait la dernière lecture — la
plus tardive, souvent la plus oblique — et deux relectures du même clip donneraient
deux plaques.

Confiance **cumulée** et non nombre de voix, contrairement à `IdentityGallery.vote`
qui compte des voix : trois lectures floues à 0,4 ne doivent pas battre deux lectures
nettes à 0,95. Le poids d'une voix, ici, est sa confiance.

Pur : aucun numpy, aucun cv2. La totalité du fichier est testable seule.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Sequence

#: Nombre minimal de lectures **concordantes** avant de publier un texte. Deux et
#: non une : une lecture unique **est** la lecture de la frame courante, exactement
#: ce que l'invariant 4 interdit de publier.
MIN_AGREEING_READS = 2

#: Confiance cumulée minimale. Deux lectures à 0,60 passent ; deux lectures à 0,45
#: non — deux hésitations qui se ressemblent ne font pas une certitude.
MIN_ACCUMULATED_SCORE = 1.2

#: Le gagnant doit dominer son suivant. `AB123CD` et `AB123CO` lus une fois chacun
#: sont un tirage au sort, et publier un tirage au sort est le pire des résultats
#: possibles. 1,5 et non 2,0 : trop sévère, une plaque dont le dernier caractère
#: vacille ne serait jamais publiée du tout.
DOMINANCE_RATIO = 1.5

#: Seuils d'**arrêt** de l'OCR, plus stricts que ceux de publication : on cesse de
#: dépenser des inférences quand plus rien ne peut être appris. C'est la plus grosse
#: économie de tout le dispositif — un véhicule dont la plaque est établie en trois
#: frames ne coûte plus rien pendant les quarante suivantes.
STOP_MIN_READS = 3
STOP_MIN_MEAN_SCORE = 0.88
STOP_DOMINANCE = 3.0


@dataclass(slots=True)
class _PositionalEvidence:
    """Ce que les lectures d'une **même longueur** disent, position par position.

    Groupé par longueur parce que comparer la position 4 de `AB123CD` avec la
    position 4 de `AB1234CD` ne veut rien dire : deux textes de longueurs
    différentes ne décrivent pas les mêmes cases.
    """

    reads: int = 0
    #: Confiance cumulée des **lectures** de cette longueur, tous textes confondus.
    #: Une lecture pèse sa confiance, exactement comme dans `accumulated` — et
    #: surtout pas la somme de ses caractères, qui vaudrait sept fois plus et
    #: rendrait `MIN_ACCUMULATED_SCORE` sans effet sur cette voie.
    weight: float = 0.0
    #: Une case par position : caractère → confiance cumulée.
    positions: list[dict[str, float]] = field(default_factory=list)

    def observe(self, text: str, score: float, char_scores: Sequence[float]) -> None:
        if not self.positions:
            self.positions = [{} for _ in text]
        self.reads += 1
        self.weight += score
        for index, character in enumerate(text):
            # Sans confiance par caractère — une doublure de test, un lecteur d'une
            # autre implémentation — chaque caractère pèse la confiance de la
            # lecture entière. Le vote reste correct, il est seulement moins fin.
            weight = float(char_scores[index]) if len(char_scores) == len(text) else score
            slot = self.positions[index]
            slot[character] = slot.get(character, 0.0) + weight

    def consensus(self) -> tuple[str, float]:
        """Le texte position par position, et sa confiance moyenne par caractère.

        Le gagnant d'une position est le caractère de plus forte confiance cumulée
        — l'estimateur exact de « qu'a vu le modèle, tout compte fait ». Diviser
        par le nombre de lectures du groupe, et non par le total de la position,
        fait qu'une lecture divergente **abaisse** la confiance au lieu de
        disparaître : c'est ce qu'on veut publier au bout du fil.
        """
        if not self.positions or self.reads == 0:
            return "", 0.0
        characters: list[str] = []
        total = 0.0
        for slot in self.positions:
            if not slot:
                return "", 0.0
            winner = max(slot, key=lambda character: slot[character])
            characters.append(winner)
            total += slot[winner] / self.reads
        return "".join(characters), total / len(self.positions)


@dataclass(slots=True)
class PlateTextVote:
    """Ce que la session retient des lectures de plaque d'une identité.

    Vivant (`slots=True` seul, pas `frozen`) : il est mis à jour frame après frame,
    comme `SessionTrack`. Il vit sur l'agrégat d'identité et non sur la piste — la
    piste est détruite à chaque occlusion longue, l'identité non, et c'est la même
    raison qui fait porter la déduplication sur l'identité (invariant 6).
    """

    #: Candidat → somme des confiances de ses lectures.
    accumulated: dict[str, float] = field(default_factory=dict)
    #: Candidat → nombre de ses lectures. Distinct de la somme : l'accord minimal se
    #: compte en lectures, la domination se pèse en confiance.
    reads: dict[str, int] = field(default_factory=dict)
    #: Candidat en tête. Mémorisé plutôt que recalculé, pour que l'égalité puisse
    #: laisser le tenant en place — même règle que `IdentityGallery.vote`.
    leader: str = ""
    #: Longueur → preuve position par position. Voir `_PositionalEvidence`.
    by_length: dict[int, _PositionalEvidence] = field(default_factory=dict)

    def observe(self, text: str, score: float, char_scores: Sequence[float] = ()) -> None:
        """Enregistre une lecture. Une chaîne vide ne vote pas.

        Une chaîne vide est le refus de `normalise_plate_text` : la compter
        reviendrait à faire voter « rien », et « rien » finirait par gagner sur les
        clips où la plupart des recadrages sont illisibles.

        La lecture est enregistrée **deux fois** : comme chaîne entière, et position
        par position. Les deux répondent à des questions différentes — « quel texte
        a été lu le plus sûrement » et « quel caractère occupe la case 4 » — et la
        seconde n'a de sens qu'à côté de la première, qui seule garantit qu'on ne
        publie que du déjà-lu.
        """
        if not text:
            return

        self.accumulated[text] = self.accumulated.get(text, 0.0) + score
        self.reads[text] = self.reads.get(text, 0) + 1

        # `>` strict : à égalité, le tenant garde la place. Une lecture qui alterne
        # entre deux graphies proches ne doit pas faire osciller la plaque affichée.
        incumbent = self.accumulated.get(self.leader, 0.0)
        if self.accumulated[text] > incumbent:
            self.leader = text

        self.by_length.setdefault(len(text), _PositionalEvidence()).observe(
            text, score, char_scores
        )

    @property
    def text(self) -> str | None:
        """Texte publiable, ou `None` tant qu'aucun candidat ne convainc.

        **Deux voies, dans cet ordre.** La chaîne entière d'abord, par
        `_consolidated` : les trois conditions cumulatives de toujours — l'accord
        minimal écarte la lecture unique (invariant 4), la confiance cumulée écarte
        deux hésitations concordantes, la domination écarte le tirage au sort entre
        deux graphies proches — appliquées à un décompte qui ne fait plus concourir
        une lecture partielle contre la lecture complète dont elle est un morceau.

        Le consensus par caractère ensuite, **et seulement si la première voie a
        refusé**. Le cas qu'il rattrape est exactement celui que la domination
        écarte : `AB123CD` et `AB123CO` à quasi-égalité. La domination a raison de
        refuser de choisir *entre les deux chaînes* — mais six des sept caractères
        sont unanimes, et jeter cette unanimité pour cause de désaccord sur le
        septième, c'est jeter la quasi-totalité de ce qu'on a mesuré. Le consensus
        tranche la case litigieuse avec la seule chose qui la départage : la
        confiance que le modèle a donnée à chacun.

        **Aucune des deux voies ne peut rien inventer** : toutes deux refusent une
        chaîne que personne n'a lue. Sans cette garde, deux lectures franchement
        différentes de même longueur produiraient une chimère — un texte jamais vu,
        composé des caractères gagnants de chacune — et publier une plaque que
        personne n'a lue est précisément le pire résultat possible.
        """
        consolidated = self._consolidated()
        if consolidated is not None:
            return consolidated[0]
        consensus = self._consensus()
        return consensus[0] if consensus is not None else None

    @property
    def score(self) -> float:
        """Confiance **moyenne** du gagnant — jamais la somme.

        Une somme dépasserait 1,0 dès la deuxième lecture, et un score de confiance
        supérieur à 1 sur le fil est un bug visible par tout le monde.

        Le score suit la voie qui a publié : quand c'est le consensus qui tranche,
        rendre la moyenne de la chaîne gagnante mentirait — elle ignorerait les
        lectures divergentes, alors que c'est justement leur existence qui rend ce
        texte moins sûr que l'autre voie ne l'aurait dit.

        **Le score de la voie consolidée est celui des lectures directes du gagnant**,
        jamais de son soutien consolidé. Le soutien sert à *choisir* quel texte
        publier ; il ne dit rien de la confiance avec laquelle ce texte-là a été lu, et
        y mêler la confiance d'un morceau plus court gonflerait un chiffre affiché à
        l'écran.
        """
        consolidated = self._consolidated()
        if consolidated is not None:
            return consolidated[1]
        consensus = self._consensus()
        if consensus is not None:
            return consensus[1]
        leader = self.leader
        reads = self.reads.get(leader, 0)
        if not leader or reads == 0:
            return 0.0
        return self.accumulated[leader] / reads

    def _consolidated(self) -> tuple[str, float] | None:
        """Le gagnant une fois les lectures **partielles** reversées à la complète.

        **C'est le correctif du « on n'a récupéré que la moitié du texte ».** `R606L`
        n'est pas une plaque rivale de `AR606L` : c'est la même plaque, lue à un
        caractère près. Le décompte d'origine les opposait, et la partielle gagnait —
        parce qu'elle est lue **plus souvent** : elle sort de tous les prétraitements,
        là où la complète ne sort que des meilleurs. Mesuré de bout en bout sur une
        vidéo réelle, le serveur publiait `R606` pour une plaque `苏A·R606L` dont il
        avait par ailleurs la lecture complète en magasin.

        Un candidat reçoit donc la confiance cumulée de tous les candidats dont il est
        un **sur-texte contigu**, puis les trois conditions de publication de toujours
        s'appliquent à ce total.

        **Deux gardes, et la seconde est celle qui empêche l'inverse du bug.** Un
        caractère parasite de tête — l'idéogramme de province lu comme un `T`, donnant
        `TA96886` là où `A96886` est juste — fabrique lui aussi un sur-texte, qui
        aspirerait les voix du bon :

        - **un sur-texte ne reçoit rien tant qu'il n'a pas ses propres
          `MIN_AGREEING_READS`.** C'est la règle que tout ce fichier applique déjà —
          une lecture unique est la lecture de la frame courante (invariant 4) — et
          elle suffit ici : un caractère parasite ne survient que sur la variante qui
          l'a fabriqué, donc une fois, alors qu'un vrai caractère de plus est relu à
          chaque image où la plaque est lisible ;
        - **la domination ne se joue que contre de vrais rivaux**, c'est-à-dire les
          candidats qui ne sont ni un morceau ni une extension du gagnant. Compter un
          morceau de soi-même comme rival rendrait la garde ininterprétable : plus la
          plaque est lue, moins elle pourrait être publiée.

        **Sans relation de sous-texte, cette méthode est exactement l'ancien code** —
        `support` vaut `accumulated`, `reads_eff` vaut `reads`, et le gagnant est
        `leader`. C'est ce qui rend le changement additif, et c'est verrouillé par un
        test.
        """
        if not self.accumulated:
            return None

        support: dict[str, float] = {}
        reads_eff: dict[str, int] = {}
        for candidate in self.accumulated:
            donors = self._donors(candidate) if self.reads[candidate] >= MIN_AGREEING_READS else ()
            support[candidate] = self.accumulated[candidate] + sum(
                self.accumulated[donor] for donor in donors
            )
            reads_eff[candidate] = self.reads[candidate] + sum(self.reads[d] for d in donors)

        # À soutien égal, le plus long gagne : il porte strictement plus
        # d'information, et le départage doit être déterministe pour qu'une
        # relecture du même clip publie la même plaque (invariant 4).
        winner = max(support, key=lambda text: (support[text], len(text)))
        if reads_eff[winner] < MIN_AGREEING_READS or support[winner] < MIN_ACCUMULATED_SCORE:
            return None
        rival = max(
            (
                score
                for other, score in support.items()
                if other != winner and other not in winner and winner not in other
            ),
            default=0.0,
        )
        if support[winner] < rival * DOMINANCE_RATIO:
            return None
        return winner, self.accumulated[winner] / self.reads[winner]

    def _donors(self, candidate: str) -> tuple[str, ...]:
        """Les candidats dont `candidate` est un sur-texte contigu.

        Contigu — `in` et non une sous-séquence — délibérément : `A6L` est une
        sous-séquence de `AR606L` sans en être une lecture partielle plausible, alors
        qu'un caractère manqué **au bord** est précisément le mode de panne mesuré.
        Accepter les sous-séquences ferait donner ses voix à n'importe quoi.
        """
        return tuple(
            other for other in self.accumulated if other != candidate and other in candidate
        )

    def _consensus(self) -> tuple[str, float] | None:
        """Le texte reconstruit position par position, ou `None` s'il ne convainc pas.

        Le groupe de longueur retenu est celui de plus forte confiance cumulée, et il
        doit dominer les autres : mélanger les positions de `AB123CD` et de
        `AB1234CD` produirait un décalage, pas un consensus.
        """
        if not self.by_length:
            return None
        length = max(self.by_length, key=lambda size: self.by_length[size].weight)
        evidence = self.by_length[length]
        if evidence.reads < MIN_AGREEING_READS or evidence.weight < MIN_ACCUMULATED_SCORE:
            return None

        rival = max(
            (other.weight for size, other in self.by_length.items() if size != length),
            default=0.0,
        )
        if evidence.weight < rival * DOMINANCE_RATIO:
            return None

        text, score = evidence.consensus()
        # La garde décisive : on ne publie que du déjà-lu.
        if not text or text not in self.accumulated:
            return None
        return text, score

    @property
    def best_guess(self) -> tuple[str, float] | None:
        """Le meilleur candidat même **sans** consensus, ou `None` si rien n'a été lu.

        Ne remplace jamais `text` : c'est un indice à afficher *en plus*, marqué
        comme incertain, jamais à la place — republier la lecture de la frame la
        plus favorable serait exactement ce que l'invariant 4 interdit. La
        différence est que `text` engage le serveur (« ceci est la plaque ») alors
        que `best_guess` ne fait que rapporter ce qu'il a vu sans y souscrire.

        Même candidat que celui qui alimenterait `text` s'il passait les trois
        seuils de publication — `leader`, sans leur filtre.
        """
        leader = self.leader
        if not leader:
            return None
        reads = self.reads.get(leader, 0)
        if reads == 0:
            return None
        return leader, self.accumulated[leader] / reads

    @property
    def is_confident(self) -> bool:
        """Plus rien à apprendre : l'OCR peut cesser pour cette identité.

        Seuils plus stricts que ceux de `text` : publier est une décision sur ce
        qu'on affiche, s'arrêter est une décision sur ce qu'on dépense. On accepte
        d'afficher un texte qu'on continue de vérifier ; on ne cesse de vérifier que
        lorsque vérifier ne peut plus rien changer.

        **Le sujet de la question est le texte publié, pas le meneur direct.** Depuis
        que `_consolidated` peut publier autre chose que `leader`, mélanger les deux
        rendrait ce prédicat incohérent avec `score` — et les trois seuils ne
        parleraient plus du même candidat. Les lectures et la domination sont donc
        celles du texte qu'on s'apprête à afficher, et le soutien consolidé n'entre
        pas dans le calcul : arrêter de lire est une décision qui doit se prendre sur
        ce qu'on a réellement lu de **ce** texte.
        """
        published = self.text
        if published is None or self.reads.get(published, 0) < STOP_MIN_READS:
            return False
        if self.score < STOP_MIN_MEAN_SCORE:
            return False
        return self.accumulated[published] >= self._runner_up_score(published) * STOP_DOMINANCE

    def _runner_up_score(self, leader: str) -> float:
        """Confiance cumulée du meilleur **autre** candidat, `0` s'il n'y en a pas.

        `0` fait passer les deux tests de domination sans condition, ce qui est le
        comportement voulu : un candidat seul en lice ne dispute rien à personne.
        """
        others = [score for text, score in self.accumulated.items() if text != leader]
        return max(others, default=0.0)
