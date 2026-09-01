# ADR 0041 — Les alertes, et pourquoi elles se calculent côté client

- **Statut** : accepté
- **Date** : 2026-08-27
- **Complète** : [ADR 0040](0040-une-ligne-porte-un-type.md), qui donne à une ligne
  de quoi être enfreinte.
- **Amende** : [ADR 0004](0004-systeme-de-design.md) sur l'usage du rouge.

## Contexte

L'application compte et elle range. Elle ne dit jamais « regardez ça maintenant ».

Deux besoins l'exigent désormais : un véhicule qui remonte une ligne à sens unique
(ADR 0040), et une **plaque recherchée** — l'utilisateur saisit un numéro avant de
lancer, et veut être prévenu si elle passe. Les deux ont la même forme : un fait
rare, daté, attaché à un véhicule, qui mérite qu'on aille voir la vidéo.

## Décision — la règle vit côté client, le serveur accepte et rend

Ni les règles de ligne ni la liste de plaques ne sont lues par le domaine. Le
serveur les valide, les persiste dans `config_json` et les rend telles quelles.
`plate_watchlist` rejoint `AnalysisRequestSchema` pour cette seule raison : rouvrir
un résultat doit savoir ce qu'on cherchait.

Trois propriétés en découlent, et ce sont elles qui justifient le choix :

- **corriger ne demande jamais de réanalyser.** Déclarer un sens interdit ou ajouter
  une plaque après coup fait apparaître les alertes correspondantes sur un résultat
  déjà terminé — exactement comme basculer un sens entrée ↔ sortie depuis ADR 0016 ;
- **la règle n'existe qu'à un endroit**, donc elle ne peut pas diverger entre
  l'aperçu vivant, le direct et un résultat rouvert. Une plaque qui correspondrait
  pendant l'analyse et plus après serait le pire des deux résultats ;
- **rien n'est accumulé en parallèle** (invariant 3) : tout est dérivé de ce que le
  serveur publie déjà — `crossings`, `by_line`, le vote de plaque.

Le serveur **ne canonise pas** les plaques recherchées. La canonique du domaine
(`normalise_plate_text`) conserve le tiret ; celle de la comparaison client
(`normalisePlate`) ne le conserve pas. Canoniser côté serveur installerait une
seconde définition de « la même plaque ». Il ne fait que **borner** : dix entrées,
seize caractères, quatre caractères alphanumériques au minimum.

## Décision — les compteurs viennent de `stats`, la liste vient du journal

Deux sources, deux natures, et les mélanger est le piège :

- **les KPI d'infraction sont dérivés de `stats.byLine[*].byDirection[*]`**
  (`results-dashboard/model/violationCounts.ts`) — exacts, sans plafond. `total` pour
  un sens interdit, `byClass` pour une voie réservée ;
- **la liste détaillée vient du flux de franchissements**, et elle est **bornée** à
  200 entrées. La borne est **annoncée** dès qu'elle est atteinte, avec le rappel que
  les totaux affichés ailleurs portent, eux, sur toute l'analyse.

Afficher `alerts.length` comme un total le ferait plafonner en silence sous un
tableau de bord qui continue de monter. C'est précisément le défaut qu'avait
l'ancienne chronologie avant qu'on annonce sa borne.

**Les deux appliquent la même priorité**, et c'est ce qui les rend comparables : un
bus qui remonte une voie réservée à contresens enfreint deux règles et compte **une**
fois, du côté du sens interdit — il porte sur le trajet, la voie réservée sur le
véhicule. Un test verrouille l'égalité des deux règles.

## Décision — deux sources d'alertes, et la seconde remplace la première

- **pendant l'analyse**, `useAlertLog` accumule depuis l'aperçu vivant : les
  franchissements de la trame pour les infractions, `preview.tracks[].plateText` pour
  les plaques. L'aperçu **vivant** et non celui calé sur l'image affichée — une
  alerte est un *événement*, elle suit le serveur ; une boîte est un *état*, elle
  suit l'image. C'est la règle déjà écrite pour les compteurs et les flashs de ligne ;
- **après**, `alertsFromResult` relit le résultat complet à la tête de lecture. Elle
  **remplace** le journal vivant au lieu de s'y ajouter : le journal est borné, le
  résultat ne l'est pas, et les règles y sont relues sur le tracé courant.

Les franchissements sont filtrés **avant** d'être bornés, et c'est pourquoi
`crossingsBefore` existe au lieu de réutiliser `crossingsUpTo` : celle-ci borne à 200
*franchissements*, donc sur un carrefour chargé les infractions les plus anciennes
disparaîtraient avant même d'avoir été cherchées.

**Les pistes plutôt que le registre pour les plaques**, pendant l'analyse : le
registre de l'aperçu est restreint aux véhicules ayant franchi une ligne (ADR 0026),
alors qu'une plaque recherchée peut appartenir à un véhicule à l'arrêt. Le texte
comparé reste le **vote** sur la vie du véhicule dans les deux cas (invariant 4) —
jamais la lecture d'une image, qui donnerait deux plaques pour deux relectures du
même clip.

## Décision — l'horodatage d'une alerte de plaque n'a pas le même sens dans les deux modes

Un vote de plaque n'a pas d'instant : il porte sur toute la vie du véhicule. Il n'y a
donc pas de date « juste », seulement deux dates honnêtes :

- **pendant**, l'instant où la correspondance a été remarquée ;
- **après**, la première apparition du véhicule, que le registre connaît — c'est
  l'endroit où amener la vidéo pour le voir arriver.

Les deux mènent au même véhicule à l'écran, et c'est la seconde qui reste affichée
une fois l'analyse terminée. La clé de dédoublonnage (`globalId` + plaque
normalisée) garde la **première** date reçue : sans cela, une alerte republiée à
chaque image remonterait en tête de liste sans qu'il se soit rien passé.

## Décision — exacte, ou **probable**, jamais silencieuse

Une plaque correspond de deux façons :

- **exacte** — les deux formes normalisées sont identiques. Alerte rouge ;
- **probable** — l'une contient l'autre, à partir de quatre caractères
  significatifs. Alerte orange, libellée « correspondance probable ».

La partielle n'est pas du confort. [ADR 0029](0029-la-plaque-perdait-son-premier-caractere.md)
documente que l'OCR perd régulièrement le **premier caractère** d'une plaque
(`AR606L` lu `R606L`) : l'exact seul raterait le cas le plus fréquent, en silence,
sur précisément la fonctionnalité qu'on a demandée. Une correspondance exacte
l'emporte toujours sur une partielle, quel que soit l'ordre de la liste — afficher
« probable » alors qu'une entrée correspond exactement ferait douter d'une certitude.

Sous quatre caractères, rien ne correspond : deux plaques quelconques partagent trois
caractères par hasard, et une entrée plus courte serait un générateur de fausses
alertes plutôt qu'une recherche.

## Décision — la couleur encode la gravité, l'icône encode la nature

`--color-negative` pour une infraction et pour une plaque trouvée à coup sûr,
`--color-warning` pour une correspondance probable. Ce qui distingue les deux
familles est l'**icône** (`Ban`, `ShieldAlert`, `ScanSearch`, `TriangleAlert`) et le
titre, jamais la teinte : teinter par famille demanderait de retenir une convention
de plus, sur un écran qui en compte déjà deux — la couleur d'une ligne, la couleur
d'une classe.

C'est un **amendement assumé** à la règle telle que `StaleResultBanner` la formule :
« le rouge est réservé aux échecs ». Il y voulait dire « l'application a échoué », il
veut désormais **aussi** dire « la scène présente une infraction ». Le titre porte la
différence — « Sens interdit » ne se confond pas avec « Échec de l'analyse » — et la
règle de fond tient : le rouge n'est jamais décoratif.

## Décision — une alerte est cliquable, et c'est la seule chose qui l'est

Cliquer une alerte amène la tête de lecture à son instant.

L'ancienne chronologie cliquable avait été retirée pour double emploi avec la barre
de lecture : on y **parcourait** le temps. Ici on ne parcourt rien — on saute à un
fait précis, dont l'instant est justement ce qu'on vient de lire. Une alerte
invérifiable ne vaut rien.

Le geste est désactivé pendant une analyse et en direct : la vidéo y est pilotée par
l'aperçu, et le calage image par image reprendrait la main aussitôt — le clic
paraîtrait sans effet.

## Décision — la liste de plaques n'est pas persistée

Le seul réglage dans ce cas. Deux raisons :

- elle décrit une **recherche en cours** et non une préférence — comme l'intervalle
  d'analyse, qui vit pour cette raison dans `entities/analysis-range` ;
- écrire un numéro de plaque dans le `localStorage` du poste franchit le cran de
  confidentialité que ce projet impose déjà en laissant l'OCR décoché par défaut. Ce
  qu'on demande un consentement explicite pour **lire** ne se persiste pas par effet
  de bord.

`saveSettings` la retire avant d'écrire, `resetForNewSource` la vide.

## Conséquences

- La section « Alertes » remplace la chronologie des franchissements en bas de page.
  Cette dernière est **masquée, pas supprimée** : `SHOW_CROSSING_TIMELINE` dans
  `StudioPage`, un mot à changer pour la rendre, composant et tests intacts.
- **La pile flottante vit en bas à droite de la scène**, pas en haut : les deux coins
  hauts portent déjà le nom du fichier et les dimensions. Trois cartes au plus, un
  compteur pour le reste, aucune disparition automatique — une alerte qui s'efface
  toute seule oblige à surveiller l'écran en continu, ce qu'elle sert justement à
  éviter. `aria-live="polite"` et jamais `assertive` : sur un carrefour chargé,
  `assertive` ferait de la synthèse vocale un métronome.
- **Les infractions fonctionnent en direct**, les plaques non : le direct n'a pas
  d'ANPR (ADR 0007), donc ses pistes arrivent sans texte.
- Le registre gagne une colonne **« Infraction »**, calculée sur le registre entier et
  jamais sur les lignes rendues — une colonne qui apparaîtrait au défilement d'un
  tableau virtualisé décalerait toutes les autres sous le curseur.
- **Rien n'apparaît tant qu'aucune règle n'est posée ni aucune plaque cherchée.** Un
  « 0 infraction » sous une règle que personne n'a déclarée se lit « aucune
  infraction », l'inverse de la vérité — même honnêteté que le « — » de « Passages en
  entrée » et que le `null` de `LineFlow.entries`.
