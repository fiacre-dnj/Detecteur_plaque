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

        **Deux voies, dans cet ordre.** La chaîne entière d'abord : trois conditions
        cumulatives écartant chacune un mode d'erreur distinct — l'accord minimal
        écarte la lecture unique (invariant 4), la confiance cumulée écarte deux
        hésitations concordantes, la domination écarte le tirage au sort entre deux
        graphies proches.

        Le consensus par caractère ensuite, **et seulement si la première voie a
        refusé**. Le cas qu'il rattrape est exactement celui que la domination
        écarte : `AB123CD` et `AB123CO` à quasi-égalité. La domination a raison de
        refuser de choisir *entre les deux chaînes* — mais six des sept caractères
        sont unanimes, et jeter cette unanimité pour cause de désaccord sur le
        septième, c'est jeter la quasi-totalité de ce qu'on a mesuré. Le consensus
        tranche la case litigieuse avec la seule chose qui la départage : la
        confiance que le modèle a donnée à chacun.

        **Il ne peut rien inventer** : `_consensus` refuse toute chaîne que personne
        n'a lue. Sans cette garde, deux lectures franchement différentes de même
        longueur produiraient une chimère — un texte jamais vu, composé des
        caractères gagnants de chacune — et publier une plaque que personne n'a lue
        est précisément le pire résultat possible.
        """
        leader = self.leader
        if not leader:
            return None
        if self.reads.get(leader, 0) >= MIN_AGREEING_READS:
            accumulated = self.accumulated[leader]
            if (
                accumulated >= MIN_ACCUMULATED_SCORE
                and accumulated >= self._runner_up_score(leader) * DOMINANCE_RATIO
            ):
                return leader
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
        """
        published = self.text
        if published is not None and published != self.leader:
            consensus = self._consensus()
            if consensus is not None:
                return consensus[1]
        leader = self.leader
        reads = self.reads.get(leader, 0)
        if not leader or reads == 0:
            return 0.0
        return self.accumulated[leader] / reads

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
    def is_confident(self) -> bool:
        """Plus rien à apprendre : l'OCR peut cesser pour cette identité.

        Seuils plus stricts que ceux de `text` : publier est une décision sur ce
        qu'on affiche, s'arrêter est une décision sur ce qu'on dépense. On accepte
        d'afficher un texte qu'on continue de vérifier ; on ne cesse de vérifier que
        lorsque vérifier ne peut plus rien changer.
        """
        leader = self.leader
        if not leader or self.reads.get(leader, 0) < STOP_MIN_READS:
            return False
        if self.score < STOP_MIN_MEAN_SCORE:
            return False
        return self.accumulated[leader] >= self._runner_up_score(leader) * STOP_DOMINANCE

    def _runner_up_score(self, leader: str) -> float:
        """Confiance cumulée du meilleur **autre** candidat, `0` s'il n'y en a pas.

        `0` fait passer les deux tests de domination sans condition, ce qui est le
        comportement voulu : un candidat seul en lice ne dispute rien à personne.
        """
        others = [score for text, score in self.accumulated.items() if text != leader]
        return max(others, default=0.0)
