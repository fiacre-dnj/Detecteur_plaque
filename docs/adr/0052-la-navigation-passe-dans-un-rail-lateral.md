# ADR 0052 — La navigation passe dans un rail latéral

- **Statut** : accepté
- **Date** : 2026-08-31
- **Amende** : [ADR 0004](0004-systeme-de-design.md), sur rien d'essentiel — les
  jetons, la pilule obligatoire et l'accent strictement fonctionnel sont conservés ;
  et [ADR 0044](0044-les-alertes-deviennent-un-centre-de-notifications.md), sur sa
  seule décision « la pilule ne porte aucun mot », qui est **renversée** parce que sa
  prémisse a disparu.
- **Ne touche aucun calcul.** Aucun compteur, aucun sérialiseur, aucun contrat. Les
  1700 tests backend et les 895 tests frontend sont inchangés, et c'est ce qui rend
  ce lot livrable d'un bloc.

## Contexte

L'écran du studio est une vidéo, un lecteur et une colonne de résultats : **la hauteur
est sa ressource rare.** Elle était pourtant coiffée de deux bandes horizontales
empilées — l'entête d'application (~76 px) puis la barre de réglages (~64 px) — soit
**~140 px de chrome** avant la première image, sous deux `border-b border-line/40` et
deux `bg-base/95 backdrop-blur` presque identiques dont rien ne disait lequel était le
principal.

La largeur, elle, n'est pas rare : le cadre est borné à `max-w-[1600px]` et tout écran
plus large affiche déjà du vide sur les côtés.

Trois défauts s'ajoutaient à l'empilement, tous vérifiés dans le code :

- **les chiffres techniques décrochaient.** La rangée est un `flex flex-wrap` avec
  `ms-auto` sur le `trailing` : dès que les pilules remplissaient la largeur, les cinq
  chiffres passaient à la ligne et se collaient à droite, en rangée orpheline sous les
  boutons ;
- **sept pilules de poids visuel identique** (`bg-surface`, `label-caps`,
  `ChevronDown`), sans rien qui sépare ce qui règle le calcul de ce qui agit sur la
  scène ;
- **le sous-titre était faux.** « Détection, suivi, ré-identification et franchissement
  de lignes » annonçait une ré-identification retirée par
  [ADR 0016](0016-compter-les-objets-suivis.md). La recherche par image d'ADR 0048 n'en
  est pas : elle ne touche aucun compteur.

## Décision

**La navigation d'application quitte le haut pour un rail vertical de 56 px, en
icônes.** Le haut de page revient à la seule barre contextuelle du studio, collée à
`top: 0`. Sous 48rem le rail se replie en barre horizontale de 3,5 rem.

Avec, cinq changements de la barre du studio : icône **avant** le libellé (jamais à sa
place), trois familles séparées par un filet (source · réglages · outils de scène),
suppression du `ChevronDown`, « Affichage & analyse » raccourci en « Affichage », et
repli des chiffres techniques dans un sixième tiroir sous 1560 px.

## Ce que la mesure a tranché contre l'intuition

**Le budget de la rangée ne dépend pas de la fenêtre.** Il plafonne à **1552 px**,
parce que la rangée vit dans le cadre `max-w-[1600px]` : au-delà de ~1704 px de
fenêtre, agrandir n'ajoute plus rien. Relevé sur la barre réelle, en pixels : import
219, trois réglages 461, trois outils libellés 484, chiffres techniques **507**.

Les chiffres techniques avaient d'abord été estimés à ~360 px, et le plan prévoyait de
rendre leur libellé aux outils de scène au-dessus de `2xl` (1536). La mesure a montré
deux choses :

- à 1600 px, la rangée **débordait sur deux lignes** — exactement le défaut qu'elle
  devait corriger ;
- avec les alertes armées, il faut 1695 px pour 1552 disponibles : **il n'existe aucune
  largeur d'écran** où les libellés d'outils tiennent. Un point de rupture en aurait
  promis une.

D'où : **les outils de scène gardent l'icône seule, à toute largeur.** Le total tombe à
1376 px, soit 176 px de marge. Et le repli des chiffres est calé à **1560 px** — 1480
suffisent, les 80 de plus absorbent un libellé qui s'allonge.

Ne pas « corriger » en élargissant le cadre : il a valu 2100 px le temps d'un essai,
annulé le jour même — une marge n'est pas de la place perdue.

## La mesure de hauteur est supprimée

`--app-header-h` était publiée par un `ResizeObserver` dans `AppShell`
(`useHeaderHeight`). Sa docstring nommait ses deux raisons d'exister, et **les deux
disparaissent avec l'entête** : « elle s'enroule sur deux lignes en fenêtre étroite »
(un rail vertical n'a pas de largeur à saturer, et replié c'est **une** rangée de
boutons `shrink-0` sans `flex-wrap`) et « le badge serveur grandit quand il porte une
erreur » (il devient un bouton rond de 40 px comme les autres).

Le rail a une hauteur **de construction**. Le jeton passe donc en CSS pur — `0px`, et
`3.5rem` sous 48rem — et ses trois lecteurs, qui portent tous le repli `,0px`, ne sont
pas touchés.

**La condition de retour, à réarmer si elle est franchie** : le jour où le rail replié
porte du texte de largeur variable ou s'enroule, la constante ment et la barre du
studio disparaît derrière lui — en fenêtre étroite seulement, c'est-à-dire jamais
pendant le développement.

## Conséquences

- **L'invariant du montage** : le document défile sur `window`, et la coquille ne porte
  **aucun `overflow`**. Trois mécanismes en dépendent et aucun ne casse bruyamment —
  `useScrollMemory` enregistrerait 0 pour les trois pages, la barre collante se calerait
  sur le mauvais défileur, et `100dvh` de la colonne des résultats cesserait de décrire
  la zone utile. D'où `sticky top-0 h-dvh` et non `fixed`, le même arbitrage que
  l'ancienne entête faisait déjà ;
- **`<header>` et non `<aside>`** : le point de repère `banner` est conservé. Un
  `<aside>` deviendrait `complementary` et l'application n'aurait plus de bannière —
  invisible en développement, réel au lecteur d'écran ;
- **56 / 40 / 44 px** : le rail est dimensionné par l'anneau de focus, `:focus-visible`
  dessinant 2 px de contour à 2 px d'écart. À 48 px de rail, il toucherait les bords ;
- **le badge serveur perd son texte, pas son sens.** Pastille plus `CUDA`/`CPU` empilés,
  et en erreur **le badge et « Réessayer » fusionnent en un seul bouton** : la surface
  qui dit le problème est celle qui le corrige. Perte assumée — la phrase « Serveur
  injoignable » n'est plus lisible à l'œil, seule la teinte `warning` la signale. Ce
  n'est pas le seul canal : le studio grise déjà « Lancer l'analyse » et affiche la
  cause là où le geste échoue ;
- **`ExtraPanel.icon` change de contrat** et ADR 0044 est amendée. L'icône seule se
  justifiait quand la cloche était la seule pilule non textuelle ; depuis que toutes
  portent une icône, c'est un glyphe muet au milieu de mots qui fait exception. Le
  libellé est **toujours** posé en `aria-label` et en `title`, donc le nom accessible ne
  dépend ni d'une largeur ni d'un affichage ;
- **le tiroir cesse de dépendre de littéraux** : `start-6` et `calc(100%-3rem)`
  devaient valoir `--app-gutter` par convention et par rien d'autre. Ils le lisent
  désormais ;
- **la table de navigation est dérivée et testée.** `NAV_ITEMS` se construit sur
  `PAGE_PATHS`, et `navigation.test.ts` verrouille l'aller-retour
  `activePageId(item.to) === item.id` : un chemin changé d'un seul côté donnait un lien
  qui compile, s'affiche et mène à la page d'erreur, sans que rien ne le dise.

## Vérifié contre le vrai serveur

Navigateur piloté contre le backend et le frontend réels — le projet a déjà payé deux
fois le « vert en CI, faux en production ».

| Largeur | Attendu | Relevé |
|---|---|---|
| 1900 | une ligne, chiffres dans la barre | 1 ligne, 1307/1552 |
| 1600 | une ligne, chiffres dans la barre | 1 ligne, 1284/1481 |
| 1400 | chiffres en tiroir « État » | pilule présente, 848/1281 |
| 700 | rail horizontal, barre dessous | rail 700×56, barre à `top: 56px` |

Plus : `--app-header-h` à `0px` en rail et `3.5rem` replié ; rail 56×900 `sticky` ;
`aria-current="page"` posé par `NavLink` seul ; aucun débordement horizontal du
document (`scrollWidth === clientWidth`) ; les deux thèmes, le rail passant de
`#181818` à `#ffffff` sans qu'aucun composant n'écrive un hexadécimal.

**Non vérifiable par ce protocole** : la restauration du défilement entre pages. Le
navigateur piloté n'émet **ni `resize` ni `change` de `MediaQueryList`** sous
l'émulation de viewport, et un `window.scrollTo` programmatique suivi de clics
synthétiques ne la reproduit pas — **le même essai sur `HEAD`, avant ce lot, donne le
même résultat.** Ce n'est donc pas une régression ; c'est un angle mort de l'outil, à
lever à la main.
