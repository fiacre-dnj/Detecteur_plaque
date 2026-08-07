# ADR 0011 — Un job en échec dit ce qu'il est

- **Statut** : accepté
- **Date** : 2026-08-07

Séparée d'[ADR 0010](0010-etranglement-du-detecteur-de-plaques.md) délibérément :
une ADR qui traite deux décisions indépendantes devient impossible à citer.

## Contexte

« L'analyse ne fonctionne pas » n'était pas un défaut de calcul. C'était un défaut
d'**information**, et quatre causes se cumulaient pour qu'un échec n'affiche
strictement rien.

1. **Le message était jeté côté serveur.** `JobManager._run` remplaçait *toute*
   exception par « L'analyse a échoué. Consultez les journaux du serveur. » Or le
   registre levait déjà une `UnavailableError("Le modèle « X » n'a pas pu être
   chargé…", code="model_unavailable")`, et `core/errors.py` porte depuis toujours
   `.detail` (français, humain) et `.code` (machine, stable). Ce message, rédigé
   pour être lu, n'atteignait personne — et « consultez les journaux » ne dit rien
   à qui n'a pas accès aux journaux.
2. **Le client ignorait les statuts non-`done`.** `handleDone` sortait sur
   `finished.status !== "done"`, donc un échec serveur n'alimentait aucun des deux
   canaux d'affichage du Studio.
3. **Le seul endroit qui rendait `job.error` était démonté au mauvais moment.**
   La barre de progression était montée sur `busy`, qui exclut les statuts
   terminaux : à la seconde où le job passait en `error`, le message disparaissait
   avec elle.
4. **Le téléchargement d'un modèle avait lieu après `running`.** Le catalogue
   annonce vingt modèles, `backend/.weights/` en portait trois : dix-sept choix sur
   vingt déclenchaient un téléchargement au clic, mais seulement à la première
   itération d'`iter_video`. L'écran affichait donc « en cours, 0 % » pendant une à
   deux minutes, et un échec réseau s'y lisait comme un service planté.

Une cinquième cause, du même genre, n'était visible nulle part : `weights_dir`
valait `Path("./.weights")`, résolu depuis le **répertoire d'exécution**.

## Décision

### 1. Une `AppError` traverse, tout le reste non

`except Exception` se scinde en deux branches. Une `AppError` a été levée
**délibérément**, avec un message écrit pour un humain : son `detail` et son `code`
vont jusqu'à l'écran. Tout le reste — `RuntimeError`, `OSError`, une erreur d'une
bibliothèque tierce — porte un message écrit pour un développeur (chemins du
serveur, noms de classes) et garde la phrase générique.

C'est **la** propriété à préserver, et deux tests la tracent côte à côte : un
`RuntimeError("chemin /srv/prive/poids.pt")` ne doit rien laisser fuir ; une
`UnavailableError` doit tout faire traverser.

`error_code` suit la chaîne complète — `JobRecord`, le port `set_status`, les deux
adaptateurs, une migration Alembic, `JobSchema`, `contracts.ts`. Deux champs et non
un, pour la raison qui vaut déjà dans `AppError` : le message d'interface se
réécrit sans casser de client, le code non. C'est lui qui permet à l'interface de
brancher une action — « précharger « X » puis relancer » — sans faire de
correspondance sur du texte français.

### 2. Le modèle est chargé avant `running`

Un port étroit `ModelPreparer` (une seule méthode, `prepare`) est appelé **avant**
la transition vers « en cours ». Un modèle impréparable fait donc échouer le job
**sans qu'il ait jamais prétendu travailler**, avec le message du registre — que la
décision 1 rend maintenant visible.

`preparing` est publié sur l'unique trame qui précède la transition, et **jamais
persisté**. Ce n'est délibérément pas un `JobStatus` : en faire un toucherait la
machine à états, `is_terminal`, les libellés et tous leurs tests, pour un état qui
ne dure que le temps d'un chargement.

*Effet de bord documenté* : `prepare` prend un bail sur le modèle. Si une session
temps réel occupe la même instance, la préparation attend — correct (invariant 9),
mais cela signifie qu'une préparation peut durer sans qu'un octet soit téléchargé.
D'où le libellé « Préparation » plutôt que « Téléchargement ».

*Câblage* : le préparateur n'est branché qu'avec le **moteur réel**. Avec une
doublure, il déclencherait un vrai téléchargement Ultralytics pour un modèle que
rien n'appellera — ce que l'architecture existe précisément pour éviter. La suite
d'intégration l'a prouvé en échouant.

### 3. `weights_dir` est ancré sur le paquet, pas sur le CWD

Un validateur ancre les chemins **relatifs** de `weights_dir` et `data_dir` sur la
racine du paquet. Lancer `uvicorn` depuis la racine du dépôt plutôt que depuis
`backend/` faisait autrement paraître *tous* les poids absents —
`license-plate.onnx` et les deux fichiers d'OCR compris — et l'ANPR devenait
indisponible sans qu'aucun message ne mentionne le répertoire de lancement. Le
service démarre, le catalogue répond, rien n'a l'air cassé : même famille de panne
que le commentaire en fin de ligne du `.env`.

Le critère est « porte une racine », et **non** `is_absolute()`. La nuance est
propre à Windows et elle compte : là-bas, `Path("/opt/poids").is_absolute()` est
**faux**. S'y fier ferait réécrire un chemin de production en
`<backend>/opt/poids` sur une machine de développement — c'est-à-dire déplacer
silencieusement un chemin écrit explicitement, exactement le mode de panne que ce
validateur supprime.

Le chemin **résolu** part dans le journal de démarrage et dans `/health`
(`weightsDir`) : un opérateur doit pouvoir voir *où* le service regarde, même
discipline que `plateAvailable`.

`_tidy_downloaded_weights` garde son `Path.cwd()` : Ultralytics dépose réellement
dans le répertoire courant, ce n'est ni le même chemin ni le même besoin.

### 4. Dire l'attente **avant** le clic

La modification la moins risquée du lot, et celle qui supprime à elle seule la
lecture « ça ne marche pas quand je change de modèle » : le catalogue expose déjà
`downloaded`, il suffisait de s'en servir. Au-dessus du bouton :

> Premier usage de « X » : environ N Mo seront téléchargés au lancement. Comptez
> une à deux minutes avant que la progression démarre.

Et le sélecteur précharge à la sélection — sur `onSelect` et **jamais** sur la
navigation au clavier : les confondre lancerait vingt téléchargements pour un
parcours de la liste, ce que la docstring du composant avait anticipé.

## Alternatives écartées

| Alternative | Pourquoi non |
|---|---|
| Faire traverser **toutes** les exceptions | Fait fuir des chemins serveur et des noms de classes. Le test qui l'interdit préexistait à ce lot. |
| Un `JobStatus` « preparing » | Touche la machine à états, `isTerminal`, `statusLabel` et tous leurs tests, pour un état transitoire. |
| Précharger côté client seulement | Ne couvre ni le client API, ni la relance depuis l'historique, ni le benchmark. Le serveur est le seul endroit qui puisse refuser proprement. |
| Précharger côté serveur seulement | Laisse l'attente au moment du clic. Les deux ensemble déplacent l'attente au moment du choix. |

## Conséquences

Tout échec d'analyse porte désormais un message actionnable qui ne disparaît pas,
et `model_unavailable` porte le bouton qui répare. Choisir un modèle absent ne
produit plus un 0 % muet.

**Coût** : une migration de plus (`error_code`), et un champ de plus dans un
contrat déjà large. Les deux sont le prix d'un échec lisible.
