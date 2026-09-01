# ADR 0043 — Les alertes quittent la vidéo pour une troisième colonne

- **Statut** : accepté, **amendé le 2026-08-28** par
  [ADR 0044](0044-les-alertes-deviennent-un-centre-de-notifications.md) : la colonne
  cède la place à une cloche et un tiroir dans la barre du studio. Le raisonnement
  qui a fait quitter la vidéo aux alertes est conservé — rien sur la scène, une
  seule surface, rien d'éphémère
- **Date** : 2026-08-27
- **Complète** : [ADR 0041](0041-les-alertes-se-calculent-cote-client.md), dont elle
  ne change ni le calcul, ni les compteurs, ni les règles.

## Contexte

ADR 0041 a donné deux surfaces aux alertes, et les deux sont mauvaises pour la même
raison — elles ne sont pas là où l'œil se trouve au moment où l'alerte arrive :

- **une pile flottante posée sur la scène**, en bas à droite de l'image. Elle
  répondait à un vrai besoin (« une alerte qu'il faut aller chercher n'alerte
  personne ») par un mauvais moyen : des cartes semi-opaques sur de la vidéo. Sur du
  bitume clair, un bandeau publicitaire ou une carrosserie blanche, le contraste
  n'est pas maîtrisable — le fond change à chaque image. Et sur un carrefour chargé,
  trois cartes plus le compteur « + N autres » couvrent la voie de droite, c'est-à-
  dire souvent **le véhicule même qu'elles signalent**. Une alerte qui masque sa
  propre preuve n'est pas une alerte, c'est un obstacle ;
- **une section en bas de page.** Sous la scène, sous la Statistique, sous les deux
  camemberts, sous le Registre. Pendant une analyse, personne n'y est.

Pendant ce temps, la page laissait de la place inoccupée exactement là où il en
fallait : `max-w-[1600px]` sur un écran de 1856 px, plus 24 px de gouttière de
chaque côté, soit ~290 px de marge vide à droite de la colonne de résultats.

## Décision — une colonne, prise sur la largeur des colonnes et de la scène

Les alertes vivent dans une **troisième colonne**, à droite des résultats, à hauteur
de la scène. La grille du studio passe donc de

```
[ scène | résultats 23rem ]   →   [ scène | résultats 20rem | alertes 18rem ]
```

**La page ne change pas de forme.** Le cadre reste à `max-w-[1600px]` et la gouttière
à 1,5 rem — les deux ont été réduits une fois (2100 px, puis 0,75 / 1 rem de
gouttière) et les deux ont été annulés le jour même sur retour de l'utilisateur : « la
page est devenue suffocante ». Le gain était d'une centaine de pixels de contenu, le
coût était les marges qui rendent la page lisible. **Une marge n'est pas de la place
perdue.**

La place vient donc de deux endroits, dans cet ordre :

1. **les colonnes se resserrent quand elles sont deux** — les résultats passent de 23
   à 20 rem, et les alertes prennent 18 ;
2. **la scène prend le reste sur elle.** C'est l'arbitrage central de cette ADR, et il
   tient à une asymétrie : une vidéo garde ses proportions à toute largeur, une carte
   de KPI non. Rétrécir la scène coûte de la définition à l'écran ; rétrécir une carte
   coupe des libellés.

**Mesuré à 1856 px de large** : 1552 px de contenu dans un cadre de 1600 centré
(128 px de marge de chaque côté, 24 px de gouttière), répartis en `912 | 320 | 288`
avec alertes, contre `1168 | 368` sans. La scène perd donc 256 px quand il y a quelque
chose à signaler, et **rien du tout** sinon.

## Décision — deux pistes de droite de même poids

20 et 18 rem, et non 23 / 19. À 23 / 19, la seconde colonne se lisait comme la
retombée de la première, une bande de reste ; deux colonnes de poids voisin annoncent
deux lectures de même rang, ce que « ce qui est compté » et « ce qui est signalé »
sont exactement.

Elles portent en conséquence **les mêmes classes de calage** — collées sous la barre,
`self-start`, et **chacune son propre défilement** borné à la hauteur de la fenêtre.
Ce dernier point n'est pas de la symétrie : sans lui, la plus longue des deux (dix
lignes tracées d'un côté, deux cents alertes de l'autre) impose sa hauteur à la rangée
de la grille, donc à la scène, et la vidéo se retrouve en haut d'un bloc de trois
écrans de vide.

Et **la même entête**, `shared/ui/PanelHeading` : aucune des deux features n'a le
droit d'importer l'autre, et deux titres côte à côte qui ne s'alignent pas se lisent
comme deux niveaux d'information.

## Décision — le chiffre de tête ne défile pas

Dans la colonne des résultats, l'entête **et** « Passages en entrée » sont collés en
haut du défilement ; tout le reste — KPI d'infraction, cartes par type, une carte par
ligne tracée — défile dessous.

La raison est fonctionnelle et non esthétique : ce chiffre est celui auquel **toutes**
les autres cartes se comparent. La somme des cartes par type lui est exactement égale,
la somme des entrées des cartes par ligne aussi (`entriesByClass` et `flowBalance`
partagent leur prédicat, verrouillé par un test). Sorti de l'écran, il obligeait à
remonter pour retrouver le total dont on venait de lire le détail — exactement le
défaut qui avait fait remonter la Répartition depuis le bas de page.

Deux détails qui la font tenir : un fond **opaque** (`bg-base/95` + `backdrop-blur`),
sans quoi des chiffres en mouvement défilent en transparence sous d'autres chiffres ;
et `-top-px` plutôt que `top-0`, parce qu'un arrondi de sous-pixel laisse sinon passer
une ligne de carte au-dessus de la tête pendant le défilement.

## Décision — le défilement des colonnes est dessiné, la barre système ne l'est pas

`.panel-scroll` (index.css) : curseur de 8 px au jeton `--color-line`, arrondi, piste
transparente, `scrollbar-gutter: stable`. Sur Windows, la barre par défaut fait 17 px
opaques — **5 % d'une colonne de 20 rem**, avec un fond gris qui n'appartient à aucune
surface du thème, et deux de ces rails côte à côte sur deux colonnes voisines.

`scrollbar-gutter: stable` est la partie qu'on ne devine pas : sans elle, l'apparition
de la barre au moment où une carte de trop arrive décale tout le contenu de la colonne
— les cartes sautent de 8 px pendant qu'on les lit. Les deux syntaxes sont
obligatoires et non redondantes (`scrollbar-width`/`-color` pour Firefox,
pseudo-éléments pour WebKit et Chromium) : aucun des deux moteurs ne comprend celle de
l'autre.

## Décision — une seule surface, donc un seul composant

`AlertToasts` et `AlertsSection` sont **supprimés** — pas masqués derrière un
drapeau comme `CrossingTimeline`, parce qu'ici il n'y a rien à conserver : les deux
rendaient la même liste, et c'était le double emploi lui-même qui posait problème.
Il reste `AlertsPanel`, qui reçoit `alerts` — journal vivant pendant l'analyse,
résultat relu après, l'appelant tranche — et ne connaît pas la différence.

Trois points qui ne se devinent pas :

- **la grille des cartes est en `auto-fill`, pas en points de rupture.** Le panneau
  vit dans une colonne de 18 rem au-delà de 1536 px, et **sous** les deux colonnes en
  dessous (`xl:col-span-2`), sur toute la largeur. `repeat(auto-fill, minmax(15rem,
  1fr))` rend une carte par rangée dans le premier cas et quatre dans le second sans
  qu'aucune classe `lg:` ait à deviner dans lequel il se trouve. Un composant qui
  déduit sa largeur d'un point de rupture se trompe le jour où on le déplace ;
- **`sticky` exige `self-start`.** Un enfant de grille s'étire par défaut sur toute la
  hauteur de sa rangée, et `position: sticky` n'a alors plus rien à faire. Sans lui,
  la colonne défilerait avec la page et disparaîtrait dès qu'on descend lire la
  Statistique ;
- **la colonne a son propre défilement**, borné à la hauteur de la fenêtre. Le journal
  plafonne à 200 alertes (ADR 0041) : une colonne qui grandit sans fin repousserait
  le bas de page à chaque événement, ce qui était précisément la raison de garder
  l'ancienne section **en dernier**. Son entête — titre, repère « en direct »,
  filtres — est collée en haut de ce défilement, comme le chiffre de tête l'est dans
  la colonne voisine.

## Décision — la troisième piste n'existe que si elle a du contenu

La classe de grille est **calculée** sur `alertsArmed`, jamais écrite en dur. Une
grille à trois pistes avec deux enfants laisse une piste vide : la scène perdrait 18
rem au profit de rien, sur tous les tracés qui ne déclarent ni sens interdit, ni voie
réservée, ni plaque recherchée — c'est-à-dire le cas normal. Le juge est le même
qu'ADR 0041 (`hasAnyRule || plateWatchlist.length > 0`), et pour la même raison : un
panneau « Alertes » vide se lirait « rien à signaler » alors que la vérité est « on
n'a rien demandé de signaler ».

## Ce qui ne change pas

- **aucun calcul, aucun compteur.** `useAlertLog`, `alertsFromResult`,
  `violationCounts`, les règles de `shared/lib/lineRules.ts` : rien n'est touché. Les
  KPI d'infraction viennent toujours de `stats`, le journal reste borné et sa borne
  reste annoncée (invariant 3) ;
- **les cartes par ligne des Résultats.** La colonne passe à 20 rem quand les alertes
  sont armées, et garde 23 rem sinon ; ses cartes sont en `col-span-2` avec un nom
  `truncate`, donc seuls les libellés qui débordaient déjà se coupent un cran plus tôt
  — aucun chiffre, aucune barre, aucune pastille ne change ;
- **le clic qui déplace la lecture**, et sa borne : inerte pendant une analyse et en
  direct, où la vidéo est pilotée par l'aperçu.

## Conséquence sur l'accessibilité, et elle n'est pas neutre

La pile flottante portait `aria-live="polite"` et annonçait donc chaque carte. La
colonne ne le fait pas : sur un carrefour chargé, cela ferait d'un lecteur d'écran un
métronome — le défaut que ce dépôt refuse déjà pour la rangée de chiffres techniques
et pour la chronologie.

Ce qui la remplace est **une seule région vivante ne portant qu'un nombre** (« 7
alertes »), et seulement pendant l'analyse. Une phrase courte par changement, au lieu
de quatre lignes de détail par alerte ; le détail reste lisible à la demande, dans la
liste juste dessous.

Le repère d'activité des deux entêtes, lui, **a perdu son texte** : le point pulsant
suffit à l'œil, et « en direct » écrit deux fois sur deux colonnes de 20 rem volait la
place du compteur. Le mot survit en `sr-only` et en `title`, parce qu'un point ne dit
rien à un lecteur d'écran.

## Alternatives écartées

- **garder la pile et l'opacifier.** Un fond opaque sur la vidéo ne règle que la
  lisibilité, pas l'occultation — et c'est l'occultation qui est le vrai défaut : la
  zone masquée est celle où le véhicule signalé se trouve ;
- **garder la pile ET la colonne.** Deux surfaces pour la même liste, donc deux jeux
  de règles d'affichage à garder d'accord, et une alerte affichée deux fois sur le
  même écran. C'est exactement le double emploi qui a fait retirer l'ancienne
  chronologie cliquable ;
- **faire de la colonne un tiroir de la barre.** Les quatre tiroirs portent des
  *réglages*, qu'on pose avant de lancer ; une alerte est un *fait*, qui arrive
  pendant. Les mettre au même endroit demanderait d'ouvrir un tiroir pour voir ce qui
  se passe — c'est-à-dire de recouvrir la vidéo, en revenant au défaut corrigé ici.
