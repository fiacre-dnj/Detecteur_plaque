# ADR 0044 — Les alertes deviennent un centre de notifications

- **Statut** : accepté
- **Date** : 2026-08-28
- **Amende** : [ADR 0043](0043-les-alertes-quittent-la-video-pour-une-colonne.md), dont
  elle garde le raisonnement et change la surface. Ne touche ni
  [ADR 0041](0041-les-alertes-se-calculent-cote-client.md) ni aucun calcul.

## Contexte

Les alertes ont eu trois surfaces en une journée, et chacune est morte de la même
cause : **la place qu'elle occupait n'était pas proportionnelle à ce qu'on venait y
chercher.**

- **la pile flottante posée sur la vidéo** — des cartes sur du bitume ne se lisent
  pas, et sur un carrefour chargé elles masquaient l'image qu'elles servaient à
  faire regarder ;
- **la section en bas de page** — sous la vidéo, sous la Statistique, sous le
  Registre : pendant l'analyse, personne n'y était ;
- **la colonne de 18 rem** d'ADR 0043 — elle réglait les deux premiers défauts, et
  en créait un troisième que son propre texte annonce sans le nommer : elle prend
  ses 18 rem à la scène **en permanence**, et 3 rem de plus aux résultats (23 →
  20 rem). La vidéo est ce qu'on regarde ; les alertes sont ce qu'on va chercher.

Il manquait par ailleurs quelque chose qu'aucune des trois n'a jamais eu : une
**synthèse**. Une liste dit ce qui s'est passé un par un, elle ne dit jamais ce
qu'il faut en penser. Sur cinquante infractions, la question posée est « lesquelles,
et faites par quels véhicules » — pas « quelle est la trente-septième ». La seule
facette offerte, « Tout / Infractions / Plaques », répondait à la question qu'on ne
se pose pas.

## Décision — une cloche dans la barre, et un tiroir

La colonne disparaît. La grille du studio redevient inconditionnelle
(`xl:grid-cols-[minmax(0,1fr)_23rem]`), ce qui supprime du même coup la classe
calculée et le point de rupture `2xl` qu'elle imposait.

Les alertes deviennent le **cinquième tiroir** de la barre du studio, comme
« Géométrie » est devenu le quatrième : `SettingsPanels` sait déjà dessiner une
pilule, tenir l'exclusivité d'un seul tiroir ouvert, fermer sur `Échap` ou sur un
clic extérieur, et flotter par-dessus la page sans la déplacer. Tout cela est
réutilisé tel quel ; `ExtraPanel` gagne seulement deux champs optionnels — `icon`
et `badge`.

Le coût replié est nul, et le coût déplié est celui d'un tiroir déjà accepté quatre
fois.

**La pilule ne porte aucun mot**, et c'est délibéré. L'icône bascule entre `Bell` et
`BellRing` — une cloche muette et une cloche qui sonne se distinguent d'un coup
d'œil là où « 0 » et « 3 » demandent de lire un chiffre — et la pastille porte le
compte **et** la gravité : rouge dès qu'une alerte `critical` existe, orange si
toutes sont `warning`. C'est la règle de tout ce module depuis ADR 0041 : la couleur
encode la gravité, jamais la famille.

**Ce n'est pas un retour à la pile flottante.** Rien n'est posé sur la scène, rien
n'est éphémère, et il n'y a toujours qu'une seule surface d'alerte — les trois
raisons pour lesquelles ADR 0043 l'avait supprimée tiennent toutes.

## Décision — le résumé passe devant la liste

Le tiroir a trois étages, et le premier n'est pas la liste :

1. **le résumé**, dérivé de `stats` : total d'infractions, puis une rangée par
   nature — contresens, ligne infranchissable, voie réservée ;
2. **les filtres**, sur trois axes qui se composent — nature, **type de véhicule**,
   ligne ;
3. **le flux**, du plus récent au plus ancien, borné à 200 entrées.

Le troisième axe est celui qui manquait : la classe **votée** du véhicule
(invariant 4), donc exactement la population que les cartes de Résultats comptent.
« Les camions qui remontent la voie de bus » se pose en deux clics.

## Décision — deux sources de chiffres, jamais mélangées

Le **résumé** vient de `violationCounts`, dérivé de `stats.byLine[*].byDirection[*]`
et **sans plafond**. Le **flux** vient du journal, borné à `ALERT_LIMIT` = 200, et
la borne est annoncée dès qu'elle est atteinte.

Afficher `alerts.length` comme un total ferait plafonner un compteur en silence sous
un tableau de bord qui continue de monter — c'est l'invariant 3, et c'est le défaut
que l'ancienne chronologie a déjà payé une fois.

`violationCounts` **déménage** de `features/results-dashboard/model/` vers
`shared/lib/violationTally.ts`, aux côtés de `lineRules.ts` et `lineViolations.ts` :
deux features en ont désormais besoin, et une feature n'importe jamais une autre.
C'est le même déménagement, pour la même raison, que celui des deux modules qu'il
rejoint. Il y gagne `byKind` et `byClass`, qui appliquent la **même** priorité que
`violationOf` — sens interdit avant voie réservée — ce qu'un test verrouille : sans
elle, le résumé compterait 6 là où le KPI juste à côté affiche 3.

`StudioPage` le calcule une fois et le passe en prop, plutôt que de laisser le
tiroir le recalculer : ce doivent être **exactement** les chiffres du KPI
« Franchissements interdits », lu à quelques secondes d'intervalle sur le même
écran.

## Ce qui ne change pas

- **Aucun calcul d'alerte.** `useAlertLog`, `alertsFromResult`, `plateWatch`,
  `lineViolations` et la priorité entre règles sont intacts. Une alerte reste
  cliquable et amène la tête de lecture à son instant, désactivée pendant une
  analyse et en direct.
- **Une seule région `aria-live`**, et elle ne porte qu'un nombre. Annoncer chaque
  carte ferait d'un lecteur d'écran un métronome sur un carrefour chargé — la raison
  même qui a tué la pile flottante.
- **Rien ne s'affiche sans règle ni plaque cherchée.** `alertsArmed` décide
  maintenant de la **pilule** en plus du panneau : un panneau qui rend `null`
  laisserait sinon un bouton qui n'ouvre rien.

## Conséquences

- **La scène récupère 18 rem et les résultats 3.** À 1856 px, la page passe de
  `912 | 320 | 288` à `1168 | 368`.
- **Un tiroir se ferme.** C'est le prix : lire une alerte pendant l'analyse demande
  un clic là où la colonne l'offrait sans geste. La pastille est ce qui rend ce prix
  acceptable — elle dit « il y a trois choses, dont une grave » sans rien ouvrir, ce
  qui est la question qu'on se pose en continu ; le détail, lui, ne se consulte que
  lorsqu'on décide de s'y arrêter.
- **La pilule d'alertes n'est jamais grisée pendant une analyse**, contrairement à
  ce que `disabled` fait aux réglages : lire ses alertes pendant que ça tourne est
  tout l'objet du changement. Elle suit `hasSource` comme les autres.
