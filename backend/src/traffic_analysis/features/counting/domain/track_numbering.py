"""Numérotation des véhicules et vote de leur type. **Aucune ré-identification.**

Ce module remplace la galerie d'apparence d'ADR 0009. Il ne compare rien, ne
mesure aucune ressemblance et ne recolle jamais deux pistes : **un objet suivi est
un véhicule**, et c'est le tracker qui décide ce qu'est un objet suivi
(ADR 0016).

Il reste deux responsabilités, et une seule ligne les sépare de « faire de la
ré-identification » :

1. **numéroter** — émettre un entier croissant par piste. Le numéro est local à la
   session, pas celui du tracker, et la raison est une panne silencieuse :
   `BaseTrack._count` d'Ultralytics est un attribut de *classe*, donc partagé par
   tout le processus. `JobManager` borne à un job simultané et `SessionService` à
   une session temps réel, mais ce sont **deux bornes indépendantes** — ouvrir la
   caméra pendant qu'un fichier s'analyse appelle `reset_trackers()`, remet le
   compteur global à zéro, et l'analyse en cours se remet à émettre des
   identifiants qu'elle a déjà utilisés. Deux véhicules distincts fusionneraient
   alors sous le même numéro, sans qu'aucune exception ne soit levée ;
2. **voter la classe** — la seule pièce de l'ancienne galerie qui survit, parce
   que c'est elle qui tient l'invariant 4 : un véhicule dont la lecture vacille
   entre `bus` et `truck` ne doit pas changer de compteur au gré des images. Le
   vote porte sur le numéro du véhicule, jamais sur la frame courante.

**Émettre et compter sont deux gestes distincts, et c'est délibéré.** Un numéro est
émis dès la première image d'une piste, pour que son agrégat existe tout de suite —
sans quoi la première lecture de plaque n'aurait nulle part où voter et
`first_seen_ms` daterait de la confirmation au lieu de la première apparition.
Mais seule une piste **confirmée** (`hits >= min_hits`) entre dans `size` : un
scintillement du détecteur sur une seule image n'est pas un véhicule.

La conséquence à connaître : la suite des numéros comptés **a des trous**. Un
scintillement consomme un numéro sans jamais être compté, donc `size` est inférieur
au dernier numéro émis. C'est le prix d'un numéro qui ne recule jamais, et il est
préférable à l'inverse : renuméroter à la confirmation ferait qu'un même véhicule
change de badge en cours de route.

Ce que ce module **ne fait pas**, délibérément : rattacher un véhicule revenu après
une occlusion longue. Au-delà de `track_buffer` (2,5 s), le tracker rend un nouvel
identifiant, ce module rend un nouveau numéro, et le véhicule compte une seconde
fois. C'est la conséquence assumée d'ADR 0016 — on compte des objets suivis, pas des
véhicules physiques.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(slots=True)
class _Vehicle:
    """Ce qu'on retient d'un véhicule numéroté : son type, et comment on l'a su.

    `votes` associe un libellé à `(class_id, nombre de voix)`. On garde
    l'identifiant de classe à côté du compte parce que le libellé seul ne suffit
    pas à reconstruire une observation : `class_id` est ce que le moteur a rendu,
    et c'est lui qu'on republie.

    `confirmed` est ce qui sépare « numéroté » de « compté ». Une fois vrai, il ne
    redevient jamais faux : un véhicule confirmé reste compté même après la mort de
    sa piste, sinon le total baisserait en cours d'analyse.
    """

    label: str
    class_id: int
    confirmed: bool = False
    votes: dict[str, tuple[int, int]] = field(default_factory=dict)


class TrackNumbering:
    """Attribue un numéro à chaque piste et vote son type.

    Trois états se succèdent pour un numéro, et les confondre est l'erreur à éviter :
    **émis** (`assign`), **compté** (`confirm`), et **libéré côté piste** (`forget`,
    qui ne décompte rien — seul l'identifiant de piste redevient disponible).
    """

    __slots__ = ("_by_class", "_confirmed", "_next_id", "_number_of_track", "_vehicles")

    def __init__(self) -> None:
        # Piste vivante → numéro. **Vidé par `forget`** quand la piste est
        # abandonnée : un identifiant de piste réémis par le tracker après cette
        # fenêtre désigne un autre véhicule, et lui rendre l'ancien numéro
        # fusionnerait les deux.
        self._number_of_track: dict[int, int] = {}
        # Numéro → véhicule. **Jamais purgé** : le registre, les agrégats de
        # plaques et la timeline y renvoient longtemps après que la piste a
        # disparu. Borné par le nombre de pistes du clip, pas par sa durée.
        self._vehicles: dict[int, _Vehicle] = {}
        # Répartition par type des véhicules **confirmés**. Somme toujours égale à
        # `size` — c'est `_retally` qui le garantit, en déplaçant une voix au lieu
        # d'en ajouter une.
        self._by_class: dict[str, int] = {}
        self._next_id = 0
        self._confirmed = 0

    @property
    def size(self) -> int:
        """**Le comptage global** : combien de véhicules confirmés ont été suivis.

        Pas le dernier numéro émis : une piste d'une seule image consomme un numéro
        sans jamais être comptée. Voir la note sur les trous, en tête de module.
        """
        return self._confirmed

    @property
    def issued(self) -> int:
        """Dernier numéro émis, confirmé ou non. Écart avec `size` = les scintillements."""
        return self._next_id

    def count_by_class(self) -> dict[str, int]:
        """Véhicules confirmés par type voté. Somme égale à `size`."""
        return dict(self._by_class)

    def number_of(self, track_id: int) -> int:
        """Numéro porté par cette piste, ou `0` si elle n'en a pas encore."""
        return self._number_of_track.get(track_id, 0)

    def label_of(self, vehicle_id: int) -> str:
        """Type **voté** de ce véhicule. `""` sur un numéro inconnu — `0` en est un."""
        vehicle = self._vehicles.get(vehicle_id)
        return "" if vehicle is None else vehicle.label

    def is_confirmed(self, vehicle_id: int) -> bool:
        """Ce véhicule est-il entré dans le comptage ?

        C'est le filtre du registre : `vehicles()` ne publie que des véhicules
        confirmés, ce qui rend `len(vehicles()) == size` vrai par construction.
        """
        vehicle = self._vehicles.get(vehicle_id)
        return vehicle is not None and vehicle.confirmed

    def assign(self, track_id: int, class_id: int, label: str) -> int:
        """Émet le numéro de cette piste, ou rend celui qu'elle porte déjà.

        Idempotente : la session l'appelle à chaque image sans avoir à retenir si
        elle l'a déjà fait. **N'incrémente aucun total** — voir `confirm`.
        """
        existing = self._number_of_track.get(track_id)
        if existing is not None:
            return existing

        self._next_id += 1
        vehicle_id = self._next_id
        self._number_of_track[track_id] = vehicle_id
        # Le type d'ouverture est celui de la première image. Il n'est pas
        # définitif : `vote` peut le déplacer, et `_retally` suit la répartition.
        self._vehicles[vehicle_id] = _Vehicle(label=label, class_id=class_id)
        return vehicle_id

    def confirm(self, vehicle_id: int) -> None:
        """Fait entrer ce véhicule dans le comptage. Idempotente, et sans retour.

        Le type retenu pour la répartition est celui **voté au moment de la
        confirmation**, pas celui de la première image : à `min_hits = 2` le vote a
        déjà deux voix, et une camionnette lue `car` sur sa première image n'a pas à
        rester classée voiture pour toute l'analyse.
        """
        vehicle = self._vehicles.get(vehicle_id)
        if vehicle is None or vehicle.confirmed:
            return
        vehicle.confirmed = True
        self._confirmed += 1
        self._by_class[vehicle.label] = self._by_class.get(vehicle.label, 0) + 1

    def forget(self, track_id: int) -> None:
        """Oublie la correspondance piste → numéro, pas le véhicule.

        Appelée quand la session abandonne une piste silencieuse depuis plus de
        `max_lost_ms`. Le véhicule garde son numéro, son type et sa place dans le
        comptage ; c'est seulement l'identifiant de piste qui redevient libre, pour
        que le tracker puisse le réémettre sans provoquer une fusion.
        """
        self._number_of_track.pop(track_id, None)

    def vote(self, vehicle_id: int, class_id: int, label: str) -> None:
        """Vote majoritaire cumulé pour le type d'un véhicule.

        **Une égalité laisse le tenant en place** : une lecture qui alterne
        bus/camion ne doit jamais faire osciller un véhicule entre deux compteurs.
        Repris tel quel de la galerie qu'ADR 0016 supprime — la règle était juste,
        c'est la ré-identification autour qui ne l'était pas.
        """
        vehicle = self._vehicles.get(vehicle_id)
        if vehicle is None:
            return

        current_class, current_count = vehicle.votes.get(label, (class_id, 0))
        vehicle.votes[label] = (current_class, current_count + 1)

        leader_label, (leader_class, leader_count) = max(
            vehicle.votes.items(), key=lambda item: item[1][1]
        )
        incumbent_count = vehicle.votes.get(vehicle.label, (vehicle.class_id, 0))[1]
        # `>` strict : à égalité, le tenant garde la place.
        if leader_label != vehicle.label and leader_count > incumbent_count:
            if vehicle.confirmed:
                self._retally(vehicle.label, leader_label)
            vehicle.label = leader_label
            vehicle.class_id = leader_class

    def _retally(self, previous_label: str, new_label: str) -> None:
        """Déplace la voix unique d'un véhicule d'un total de type à l'autre.

        Sans ce transfert, `count_by_class()` cesserait de sommer à `size` et la
        répartition par type afficherait plus de véhicules que le total — ce que
        l'utilisateur voit immédiatement.

        Appelée **seulement pour un véhicule confirmé** : un véhicule pas encore
        compté n'a aucune voix à déplacer, et lui en retirer une ferait descendre un
        total sous zéro.
        """
        if previous_label in self._by_class:
            self._by_class[previous_label] -= 1
            if self._by_class[previous_label] <= 0:
                del self._by_class[previous_label]
        self._by_class[new_label] = self._by_class.get(new_label, 0) + 1
