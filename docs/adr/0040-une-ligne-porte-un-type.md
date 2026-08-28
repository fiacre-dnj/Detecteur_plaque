# ADR 0040 — Une ligne porte un type, et un sens peut être interdit

- **Statut** : accepté, **amendé le 2026-08-28**
- **Date** : 2026-08-27
- **Amende** : [ADR 0021](0021-le-role-de-sens-devient-obligatoire.md) et
  [ADR 0016](0016-compter-les-objets-suivis.md) — sans toucher au comptage,
  seulement au vocabulaire des sens et à l'édition d'une ligne.

## Amendement du 2026-08-28 — quatre types choisissables, pas cinq

« Sens unique · entrée » et « Sens unique · sortie » **fusionnent** en un seul type,
**« Autorisé · interdit »**, de paire `{entry, forbidden}`.

Ils ne différaient que par le rôle du côté autorisé, pour une seule et même règle :
un sens passe, l'autre est signalé. Deux pilules obligeaient donc à choisir un bilan
de carrefour au moment où l'on décrivait une interdiction — et depuis
[ADR 0045](0045-un-passage-global-est-un-vehicule.md) le chiffre de tête ne s'appuie
plus sur ce bilan.

Trois points :

- **le côté autorisé reste `entry`**, et non `transit`. C'est ce qui garde ces
  lignes dans les colonnes « Entrée par » du registre et dans les comparatifs de
  Statistique ; un rôle neutre les en aurait sorties sans que rien ne le dise ;
- **une paire héritée `{exit, forbidden}` se relit sous le nouveau type.**
  `lineKind` la range en `oneway` plutôt qu'en `undeclared` : retirer un type du
  vocabulaire ne doit pas transformer une ligne réglée en ligne à régler.
  `rolesForKind` la normalise au premier re-choix, et jamais avant — relire un
  preset ne réécrit rien ;
- **aucun champ du contrat ne bouge.** Le type reste dérivé, les rôles restent
  `entry` / `forbidden` des deux côtés du réseau, et aucune migration n'est due.

**Et « Comptage seul » n'affiche plus ses deux sens.** Les deux rangées y disaient
« Passage » deux fois sous un bouton d'inversion déjà grisé : trois éléments
d'interface pour zéro information. Une phrase les remplace. Le canevas, lui, garde
ses deux flèches — elles disent de quel côté est chaque sens, ce qui reste vrai et
sert à relier une rangée à un trait.

## Contexte

Depuis ADR 0021, chaque sens d'une ligne est **obligatoirement** entrée ou sortie,
et le rôle **est** le libellé affiché. Deux sens, deux rôles, un bouton qui les
inverse : c'est tout ce qu'une ligne pouvait dire d'elle-même.

Or une ligne de comptage décrit une voie, et une voie porte des règles que ce
vocabulaire ne sait pas exprimer :

- une rue à **sens unique** — un sens autorisé, l'autre interdit ;
- une **ligne continue** ou un accès fermé — les deux sens interdits ;
- une **voie réservée** — bus, cycles — que d'autres classes n'ont pas le droit
  d'emprunter ;
- une simple **route de transit**, qui n'est pas un carrefour : « Passages en
  entrée » y affiche « — » et se lit comme une panne, alors que le comptage est
  juste.

Les trois premières ont un point commun que l'application ne savait pas voir : un
franchissement peut être une **infraction**, et personne n'était prévenu.

## Décision — cinq rôles, parce qu'il y a cinq significations

```
DirectionRole = 'entry' | 'exit' | 'forbidden' | 'transit' | 'neutral'
```

- `entry` / `exit` — le bilan du carrefour, inchangés ;
- `forbidden` — « Interdit ». Le franchissement est **compté quand même**, et
  signalé ;
- `transit` — « Passage ». Compté, délibérément hors bilan ;
- `neutral` — **hérité uniquement** : « personne ne l'a dit ». L'éditeur ne le
  produit pas, mais un preset ou un `configJson` d'avant ADR 0021 peut le porter.

`transit` et `neutral` ne pouvaient pas être le même rôle. `flowBalance.declared`
distingue « aucun rôle déclaré » — d'où le « — » de « Passages en entrée » — d'un
choix explicite ; les confondre ferait lire un comptage de transit comme un oubli,
et inversement.

## Décision — une infraction est un passage **qualifié**, jamais retiré

Un franchissement interdit reste dans `crossings` et dans `by_line`. L'invariant 3
(`crossings == Σ by_line[*].total`) en dépend, et c'est aussi ce qui rend
l'infraction **dérivable** côté client : l'interface ne compte rien elle-même, elle
relit ce que le serveur publie.

Conséquence directe : le serveur n'a **rien** à faire de ces règles.
`backend/tests/unit/counting/test_regles_de_ligne.py` verrouille la propriété — les
quatre descriptions d'une même ligne rendent exactement les mêmes totaux, les mêmes
ventilations par classe et les mêmes horodatages. Un mot ne change pas un chiffre.

## Décision — le type est **dérivé** de la paire de rôles, jamais stocké

`shared/lib/directions.ts` porte `lineKind(line)` et son inverse
`rolesForKind(kind)`, et un test vérifie l'aller-retour sur les cinq types
choisissables.

Aucun champ `lineKind` dans le contrat, et c'est la décision principale de cette
ADR : un type stocké *à côté* des rôles serait une seconde source pour la même
vérité. Changer un rôle sans toucher au type — ou l'inverse — donnerait une ligne
qui s'affiche « sens unique » tout en comptant deux sens, sans que rien ne plante.
C'est la famille de bug que ce dépôt documente le plus.

Le panneau de géométrie lit `lineKind` et écrit `rolesForKind` : le type est donc un
choix de **paire**, posé en un geste (`setLineKind`). Poser les rôles un par un
laisserait exister, entre deux gestes, une paire que `lineKind` ne sait pas nommer.

Le bouton d'inversion d'ADR 0021 devient `swapLineDirections`, qui **échange** les
deux rôles sans en juger : sur une ligne ordinaire il inverse entrée et sortie, sur
une ligne à sens unique il fait passer le côté interdit d'un bord du trait à l'autre.
C'est la même opération, et un seul geste. Il est désactivé quand les deux rôles sont
identiques — il n'y aurait rien à échanger, et un bouton sans effet se lit comme un
bouton cassé.

## Décision — la voie réservée est **orthogonale** au type

`CountingLine.allowedClassIds: number[] | null` — `null` = aucune restriction.

Une voie de bus peut être à sens unique **et** réservée : les fondre dans un même
sélecteur rendrait ce cas inexprimable, alors qu'il est le plus courant des deux. Le
panneau porte donc un sélecteur de type **et**, en dessous, un interrupteur « Voie
réservée » avec ses classes.

Trois points qui ne se devinent pas :

- **des identifiants COCO, pas des noms.** C'est la monnaie du catalogue et
  d'`AnalysisRequest.classIds`. La traduction vers les noms — les clés de `byClass` —
  se fait **une seule fois**, dans `shared/lib/lineRules.ts`, contre le catalogue du
  serveur. Comparer un identifiant à un nom ne lèverait rien : aucune correspondance
  ne serait jamais trouvée, donc **tout** franchissement passerait pour une
  infraction ;
- **`null` et jamais `[]`.** Une liste vide dirait « aucune classe n'a le droit de
  passer », ce que le type « Infranchissable » exprime déjà, en le disant. Le repli
  est écrit trois fois — reducer, schéma de requête, relecture de preset — et testé
  aux trois endroits ;
- **une classe que le catalogue ne connaît plus est ignorée, jamais devinée.** Si
  *aucune* n'est reconnue, la restriction disparaît au lieu de devenir un ensemble
  vide : mieux vaut ne rien signaler que tout signaler.

## Décision — le rouge sur le canvas, borné au mot « Interdit »

`CANVAS.forbidden` rejoint `shared/config/palettes.ts`. C'est la seule couleur du
canvas qui encode une **valeur** plutôt qu'une identité, et l'exception est étroite
exprès : le trait garde `line.color`, qui dit *quelle* ligne c'est, et la boîte du
véhicule garde sa couleur de classe. Seul le libellé du sens interdit vire au rouge.

Sans elle, « Interdit » s'écrivait dans la teinte de sa ligne, à côté d'« Entrée »
écrit dans la même teinte : la seule différence était le mot, à lire, sur une vidéo
qui défile.

La flèche d'un sens interdit est **conservée** : un sens interdit est un sens, et
savoir de quel côté il l'est est toute l'information. Seul `neutral` n'en affiche
pas — il n'y a rien à orienter.

## Ce qui ne change pas

- **Aucune migration.** La géométrie vit dans des colonnes JSON — `config_json` pour
  un job, `lines_json` pour un preset — précisément pour que sa forme évolue sans
  toucher au schéma. Un preset antérieur se relit et rend `neutral` / `null`.
- **La relecture valide contre les valeurs admises.** `PresetSchema` type ces
  champs ; une valeur inattendue en base ferait échouer la validation de la
  *réponse*, donc un 500 sur `GET /presets` qui emporterait **toute** la liste pour
  une seule ligne fautive. `_role` et `_class_ids` dégradent la ligne et laissent le
  reste lisible.
- **`isEntryRow` est inchangé.** Il reste le seul juge de ce qu'est une entrée, et
  `flowBalance.declared` garde sa définition exacte — au moins un sens `entry` ou
  `exit`. Une géométrie entièrement en « comptage seul » affiche donc toujours « — »
  pour le bilan du carrefour, ce qui est la vérité.

## Conséquences

- Une ligne dit enfin ce qu'elle est, et l'écran peut signaler ce qui l'enfreint
  (voir [ADR 0041](0041-les-alertes-se-calculent-cote-client.md)).
- **`crossingsWithoutRole` a dû devenir un complément exact.** Elle comparait à
  `=== "neutral"`, écrit quand `neutral` était le seul rôle sans colonne : l'arrivée
  d'« Interdit » et de « Passage » aurait fait disparaître ces franchissements des
  deux côtés du registre — ni rangés sous un rôle, ni comptés hors rôle. Un passage
  perdu, sans que rien ne plante. La colonne « Hors rôle » devient **« Autres
  passages »** dans le même mouvement : `transit` *a* un rôle, délibérément choisi,
  et le dire « hors rôle » se lirait comme un oubli de l'utilisateur.
- Corriger un type de ligne ou une voie réservée après coup est **instantané** et ne
  demande jamais de réanalyser — la même propriété que les rôles depuis ADR 0016.
- Le panneau de géométrie reçoit le catalogue de classes du serveur en prop, fourni
  par le studio : la feature `geometry-editor` ne connaît ni `analysis-settings` ni
  la route qui le publie, même câblage que `onOpenPresets`.
