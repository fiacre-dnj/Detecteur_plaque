# ADR 0058 — « Survie d'une piste perdue » n'atteignait pas le tracker

- **Statut** : accepté
- **Date** : 2026-09-03
- **Même famille qu'**
  [ADR 0035](0035-le-seuil-de-confiance-n-atteignait-le-tracker-qu-une-fois.md) : un
  réglage écrit, persisté, affiché, et sans effet. Le troisième de ce module.

## Le symptôme

Aucun. C'est tout le problème : le curseur bougeait, le job repartait, les chiffres
restaient plausibles.

## Ce qui ne descendait pas

`maxLostMs` (200 à 15 000 ms, défaut 2 500) est publié par la requête, validé, persisté
dans `config_json`, affiché sous le libellé « Survie d'une piste perdue » avec l'aide
« Silence au-delà duquel une piste est abandonnée. Un véhicule masqué plus longtemps
repart comme un véhicule neuf ».

Son **unique** consommateur était `_release_lost`, dans le domaine. Côté moteur :

- `grep -rn track_buffer backend/src/` ne le trouvait **que dans des commentaires** ;
- `resolved_tracker_config` n'écrivait que `gmc_method`, `track_high_thresh`,
  `new_track_thresh`, `track_low_thresh` et `with_reid` — jamais le tampon ;
- **`EngineSpec` ne portait pas `max_lost_ms`** : la valeur ne *pouvait pas*
  physiquement atteindre l'adaptateur.

Le bug n'était donc pas dans un calcul. Il était dans l'absence de transport.

## Les deux horloges

Et même transportée, la valeur n'aurait pas suffi : les deux composants ne comptent pas
la même chose.

| | unité | abandon |
|---|---|---|
| domaine (`_release_lost`) | ms de **temps de scène** | `max_lost_ms` |
| tracker (`byte_tracker.py`) | **images analysées** | `track_buffer` |

Vérifié dans la roue installée : `self.max_frames_lost = args.track_buffer`, **sans
aucune mise à l'échelle par la cadence**. Le commentaire de `botsort_reid.yaml`
annonçait un « miroir exact » de `max_lost_ms = 2500` — vrai à 30 img/s et au pas 1,
faux partout ailleurs :

- **à pas 3** (30 img/s), le domaine oublie à 2,5 s pendant que le tracker tient 7,5 s.
  Le tracker rend alors un `track_id` que le domaine ne reconnaît plus,
  `_advance_tracks` crée une piste neuve et `_number_tracks` émet un `global_id` neuf :
  **un véhicule compté deux fois, en silence** ;
- **à 60 img/s** au pas 1, l'inverse : le tracker renonce à 1,25 s sous un curseur qui
  annonce 2,5.

## Et une troisième couche : la clé est gravée

Écrire `track_buffer` dans le fichier dérivé ne suffit pas non plus. Vérifié à
l'exécution sur la roue installée :

```python
t = BYTETracker(args(track_buffer=75))   # max_frames_lost = 75
t.args.track_buffer = 450 ; t.reset()    # max_frames_lost = 75  ← inchangé
```

`reset()` ne relit pas la clé, et `register_tracker` ne relit jamais le fichier une
fois les trackers en place (le mécanisme d'ADR 0035). Le réglage aurait donc été correct
à la **première** analyse d'un processus et inerte à toutes les suivantes.

Le module le savait déjà à moitié : `LIVE_TRACKER_KEYS` rangeait explicitement
`track_buffer` parmi les clés « consommées dans `__init__` et gravées dans l'objet ».
Personne n'avait relié ce constat au curseur de l'utilisateur, dont c'est pourtant le
seul objet.

## La décision

Trois pièces.

1. **`EngineSpec.max_lost_ms`** — le transport qui manquait. Comme `start_ms`, c'est un
   **indice** : un moteur qui l'ignore reste correct, parce que le domaine applique la
   règle de son côté quoi qu'il arrive. Le `FakeEngine` de la CI produit donc les mêmes
   chiffres, et la propriété qui rend ce projet testable est préservée.
2. **`track_buffer_frames(max_lost_ms, fps, stride)`** — la conversion, dans
   l'adaptateur parce que lui seul connaît la cadence et le pas, et **écrite une seule
   fois** : deux exemplaires divergeraient, et la panne serait un tampon deux fois trop
   court sans qu'aucun message ne le dise.
3. **`ENGRAVED_TRACKER_ATTRS`** — une catégorie **nouvelle** à côté de
   `_reapply_request_keys` : les clés gravées se reposent sur l'**instance**
   (`tracker.max_frames_lost`), pas sur `tracker.args`.

### Le défaut ne change rien, par construction

2 500 ms à 30 img/s au pas 1 valent exactement **75** — la valeur du fichier versionné.
`resolved_tracker_config` ne modifie donc rien, et une course entièrement au défaut rend
toujours le fichier de base lui-même. Deux tests le verrouillent.

### La garantie historique ne couvre plus tout

`REQUEST_TRACKER_KEYS ⊆ LIVE_TRACKER_KEYS` était **la** condition qui rendait
`reset_trackers` suffisante. Elle tient toujours pour les clés de requête, mais il
existe désormais **deux** façons de reposer un réglage. C'est écrit dans le module et
verrouillé par un test : la prochaine lecture doit voir la distinction, sinon une clé
gravée ajoutée un jour redeviendrait inerte en silence.

## Ce qui n'est pas traité

**Le direct n'impose aucun tampon.** Un flux caméra n'a pas de cadence déclarée, donc la
conversion ms → images est impossible : `track_buffer_frames` rend `0`, que
`resolved_tracker_config` lit comme « ne rien imposer », et le fichier de base garde sa
valeur. C'est le comportement d'avant cette ADR, conservé faute de pouvoir faire mieux.

## Conséquences

- **les comptages changent dès que la cadence n'est pas 30 ou que le pas n'est pas 1**,
  et c'est le but. Dans les deux sens selon la scène : moins de doublons à pas élevé,
  plus de continuité d'identité à 60 img/s ;
- **monter réellement le curseur coûte de l'association** : une piste perdue gardée 15 s
  reste dans `strack_pool` et concourt pour chaque détection proche de sa dernière
  position — l'échange d'identité classique de BoT-SORT, silencieux et plausible. Le
  curseur devient donc un vrai arbitrage, ce qu'il prétendait déjà être ;
- **ne pas « simplifier » en reconstruisant les trackers** : `track()` ré-enregistrerait
  ses rappels, `model.callbacks` empile, et `tracker.update()` tournerait deux fois par
  image.

## Comment le vérifier

La preuve la moins chère se faisait **avant** d'écrire une ligne, et elle reste le
contrôle de non-régression le plus parlant : deux analyses du même clip,
`frameStride = 3`, `maxLostMs` à 2 500 puis à 8 000, tout le reste identique.

Avant ce correctif, les deux courses rendaient des chiffres **strictement identiques** —
cette identité *était* le bug. Après, elles doivent diverger, et
`scripts/audit_lignes.py <job_id> --json` doit continuer à sortir en `0`.

```bash
cd backend && uv run pytest tests/unit/models_registry/test_track_buffer.py -q
```
