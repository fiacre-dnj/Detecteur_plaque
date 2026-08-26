# ADR 0035 — Le seuil de confiance n'atteignait le tracker qu'une seule fois par processus

- **Statut** : accepté
- **Date** : 2026-08-24
- **Corrige** [ADR 0024](0024-le-detecteur-descend-sous-le-seuil-de-l-utilisateur.md), dont
  le mécanisme était juste et le câblage à moitié mort.

## Le symptôme

« Dans la configuration DÉTECTION, la configuration *Confiance véhicules* ne fonctionne
pas. »

Le curseur bouge, la requête part avec la bonne valeur, le fichier de suivi dérivé est
écrit avec la bonne valeur, son chemin est journalisé — et les chiffres ne changent pas
d'un véhicule. Rien ne lève, rien n'est signalé.

## La cause

ADR 0024 fait voyager le seuil de l'utilisateur jusqu'au tracker par un **fichier**, seule
forme qu'Ultralytics accepte : `resolved_tracker_config` écrit un YAML dérivé portant
`track_high_thresh` et `new_track_thresh`, et son chemin part en `tracker=…` à chaque
appel de suivi.

Or Ultralytics ne lit ce fichier qu'**une fois** (`trackers/track.py`) :

```python
def on_predict_start(predictor, persist=False):
    ...
    if hasattr(predictor, "trackers") and persist:
        return                      # ← le fichier n'est jamais relu
    tracker = check_yaml(predictor.args.tracker)
```

C'est la **même** sortie anticipée que celle qui avait motivé `reset_trackers` (état
hérité d'une analyse à l'autre : 19, puis 26, puis 33 véhicules uniques sur un fichier
identique). Elle a une seconde conséquence, restée invisible : le registre garde
l'instance de modèle d'un job à l'autre (invariant 9), donc `predictor.trackers` existe
dès la deuxième analyse, donc **toutes les analyses d'un processus tournent au seuil de la
première**.

`reset_trackers` remettait bien l'état à zéro — mais `reset()` ne touche pas `args`, où
vivent les seuils. Le seuil de la première analyse survivait à tout.

**C'est pourquoi la panne ne se voit jamais en développement** : la première analyse après
un démarrage est celle qu'on regarde, et c'est la seule qui obéit.

## Ce qui est mesuré

Même vidéo (1920×1080, fenêtre de 8 s), `yolov8n`, trois analyses **dans le même
processus** :

| Seuil demandé | Avant | Après |
|---|---|---|
| 0,20 | 3 véhicules | 3 véhicules |
| 0,80 | **3 véhicules** | **1 véhicule** |
| 0,20 | 3 véhicules | 3 véhicules |

La colonne « avant » est le symptôme exact : trois lignes identiques pour trois réglages
différents. La troisième ligne compte autant que la deuxième — elle prouve que le report
n'est pas un aller simple.

## La décision

`reset_trackers(model, tracker_config)` **repose les clés de requête** du fichier sur les
trackers déjà construits, en plus de nettoyer leur état.

Deux ensembles sont nommés dans le module, et leur relation est ce qui rend le correctif
valable :

- `REQUEST_TRACKER_KEYS` = `{track_high_thresh, new_track_thresh}` — ce que la requête
  change. `resolved_tracker_config` les écrit dans le fichier, `reset_trackers` les repose
  sur les trackers vivants : **une seule liste**, sinon un réglage ajouté d'un côté
  n'arriverait au tracker qu'à la première analyse du processus, c'est-à-dire la panne
  ci-dessus revenue par l'autre porte ;
- `LIVE_TRACKER_KEYS` — ce que le tracker relit à **chaque image** sur `self.args`
  (vérifié dans la roue installée : `byte_tracker.py` lit `track_high_thresh` dans
  `update()` et `new_track_thresh` dans `init_track()`). Tout le reste — `track_buffer`,
  `gmc_method`, `with_reid`, `proximity_thresh` — est consommé dans `__init__` et gravé
  dans l'objet.

`REQUEST_TRACKER_KEYS ⊆ LIVE_TRACKER_KEYS` est **la** condition de validité, et un test la
verrouille.

## L'alternative rejetée, et pourquoi

Faire **oublier** les trackers (`del predictor.trackers`) est plus général : Ultralytics
relirait alors le fichier entier, y compris les clés de construction. C'est ce qu'on
aurait écrit d'instinct.

Elle est refusée parce qu'elle échange une panne silencieuse contre une pire. L'appel de
suivi suivant vérifie `if not hasattr(self.predictor, "trackers")` et **ré-enregistre les
rappels** ; or `model.callbacks` est le même objet que `predictor.callbacks`, et
`add_callback` **empile**. Un `on_predict_postprocess_end` en double appelle
`tracker.update()` deux fois par image : deux fois le filtre de Kalman, deux fois
l'association, des identifiants qui sautent — des chiffres plausibles et complètement
faux, sans la moindre erreur.

Il faudrait donc désinscrire les rappels d'Ultralytics à la main, en les reconnaissant
parmi les autres — et les rappels par défaut de la bibliothèque **portent exactement les
mêmes noms** (`utils/callbacks/base.py`). Une reconnaissance approximative se traduirait
par le doublon ci-dessus. Reposer trois flottants sur un objet vivant est moins ambitieux
et sans zone d'ombre.

## Conséquences

- **une analyse relancée avec un autre seuil rend d'autres chiffres**, ce que tout le monde
  croyait déjà vrai. Les mesures antérieures comparant deux seuils dans un même processus —
  s'il en existe — comparaient deux fois le même ;
- **le direct est concerné aussi**, et c'était le cas le plus sournois : il partage
  l'instance résidente avec le différé, donc une session caméra ouverte après une analyse
  héritait du seuil de l'analyse. `UltralyticsStream` repose le sien à l'ouverture ;
- **`gmc_method` n'est pas reposé**, et n'a pas à l'être : il vient du déploiement
  (`TRAFFIC_TRACKER_GMC`), il est fixé à la construction du moteur, et il ne varie donc
  jamais dans un processus. S'il devenait un réglage de requête, `REQUEST_TRACKER_KEYS`
  cesserait d'être incluse dans `LIVE_TRACKER_KEYS` et le test le dirait.
