# ADR 0004 — Système de design : `DESIGN.md` est la source de vérité des jetons

- **Statut** : accepté, **amendé le 2026-08-06** (thème clair — voir en fin)
- **Date** : 2026-08-05

## Contexte

Deux documents décrivent l'apparence de l'interface et ne disent pas exactement
la même chose :

- `DESIGN.md` définit un système sombre complet — surfaces `#121212`/`#181818`,
  un accent vert `#1ed760` « fonctionnel, jamais décoratif », une géométrie
  pilule/cercle, des ombres lourdes, une échelle typographique de 10 à 24 px ;
- `prompt/09` décrit les écrans et mentionne au passage
  `bg-slate-950 text-slate-200` pour la coquille, tout en exigeant par ailleurs
  (`prompt/08`) un `LINE_PALETTE`, un `ZONE_PALETTE` et un `CLASS_COLORS` pour le
  canvas — donc plusieurs couleurs, ce que `DESIGN.md` interdit.

## Décision

### 1. Les valeurs de `DESIGN.md` gagnent sur les classes Tailwind de `prompt/09`

`bg-slate-950 text-slate-200` était une indication de *thème* (« sombre »), pas
une palette arrêtée. La coquille utilise donc `#121212` et `#b3b3b3`. Les jetons
vivent dans `frontend/src/index.css` sous `@theme` (Tailwind v4, configuration
CSS-first, pas de `tailwind.config.js`), et **aucun composant n'écrit un
hexadécimal en dur**.

### 2. Chrome achromatique, canvas porteur de données

La contradiction sur les couleurs se résout en distinguant deux régions :

- le **chrome** (coquille, panneaux, tableaux, boutons) est achromatique — des
  gris — plus l'accent vert **fonctionnel uniquement** : action primaire,
  élément de navigation actif, `● Serveur prêt`, bouton de lecture ;
- le **canvas** de la scène porte de la couleur qui **encode une donnée** :
  une ligne de comptage, une zone, une classe de véhicule. C'est l'équivalent
  exact de la pochette d'album chez Spotify — le système est achromatique
  précisément pour que le contenu soit la seule source de couleur.

Corollaire non négociable : **le vert n'est jamais une couleur de classe de
véhicule**. Sinon « vert = compté » (le badge ✓) et « vert = camion » se
contrediraient sur la même image.

### 3. Manrope remplace SpotifyMixUI / CircularSp

Les polices de `DESIGN.md` sont propriétaires et ne peuvent pas être embarquées.
La CSP du service (`default-src 'self'`, voir `prompt/06`) interdit par ailleurs
Google Fonts et tout autre hôte externe. Manrope — variable, géométrique
semi-arrondie — est le substitut libre le plus proche de Circular ; elle est
auto-hébergée en `woff2` dans `frontend/public/fonts/` et déclarée en
`@font-face` local. L'échelle et les graisses de `DESIGN.md` §3 sont conservées
telles quelles.

`font-variant-numeric: tabular-nums` est appliqué à tous les chiffres de mesure
(cartes de synthèse, registre des véhicules, tableau de benchmark) : en chasse
proportionnelle, les colonnes se décalent à chaque rafraîchissement et un tableau
de mesures devient illisible.

## Conséquences

- L'accent vert étant réservé, les états positifs du canvas s'expriment par la
  **forme** (trait plein contre pointillés, badge ✓) et non par la couleur.
- Une revue de design consiste à vérifier qu'aucun composant n'introduit une
  couleur hors des jetons, et qu'aucun hexadécimal n'apparaît hors
  `index.css` et `shared/config/palettes.ts`.

## Amendement — 2026-08-06 : un thème clair, le sombre restant le défaut

L'interface propose une bascule sombre / clair dans l'entête. **Le sombre reste
le thème du projet** : c'est celui pour lequel `DESIGN.md` a été écrit, celui où
une scène vidéo occupe l'écran sans être cernée de blanc, et celui pour lequel
les couleurs de canvas ont été choisies. Le clair est une préférence explicite,
retenue une fois posée.

### Ce que le thème change, et ce qu'il ne change pas

Le thème redéfinit les **jetons** sous `:root[data-theme="light"]` — surfaces,
encres, bordures, ombres, accent, couleurs sémantiques. Aucun composant n'y
participe : les utilitaires compilent en `var(--color-…)`, donc changer la
variable suffit. Écrire une variante `dark:` par élément aurait été l'autre
voie ; c'est aussi celle où l'on en oublie une, et où l'oubli ne se voit que
dans le thème qu'on utilise le moins.

**Les couleurs du canvas ne changent pas** (`shared/config/palettes.ts`). Elles
sont posées sur des images de vidéo, pas sur le fond de la page : une boîte bleue
sur du bitume reste lisible quel que soit le thème autour. Le principe de la
décision 2 est intact — le chrome s'adapte, le contenu encode.

### Deux ajustements imposés par la mesure, pas par le goût

1. **L'accent et les couleurs sémantiques sont assombris en clair.** `#1ed760`
   sur blanc tombe sous 2:1. Le vert du thème clair est `#0e7a3c` (5,0:1 sur le
   fond, 5,4:1 pour l'encre blanche par-dessus). La règle « l'accent est
   strictement fonctionnel » ne bouge pas ; seule sa valeur change.
2. **`--color-ink-dim` est passé de `#667081` à `#5b6472`.** Mesuré à 4,19:1, il
   était sous le seuil AA — et c'est justement le jeton des aides et des libellés
   de 10 à 12 px. Toutes les paires jeton-sur-surface du thème clair sont
   au-dessus de 4,5:1, vérifiées dans le navigateur.

### La bascule coupe les transitions

Changer un jeton pendant qu'un élément porte `transition-colors` ne produit pas
l'animation attendue : l'élément **reste sur son ancienne couleur**, alors qu'un
élément monté après la bascule prend la bonne. Résultat observé : une entête à
moitié dans l'ancien thème. `switchTheme` pose donc `data-theme-switching` le
temps de deux frames, et le CSS y coupe toutes les transitions. C'est aussi le
comportement voulu : un thème change d'un coup, il ne se fond pas.

### Pourquoi pas `prefers-color-scheme`

Suivre le système ferait démarrer en clair la moitié des postes, sur une
interface pensée en sombre — et, sur les systèmes qui suivent l'heure, ferait
basculer l'écran au coucher du soleil au milieu d'une analyse. Le thème est donc
un choix de l'utilisateur, pas une déduction.

La préférence est appliquée à l'import de `main.tsx`, avant le premier rendu. Le
script en ligne dans `index.html` — la solution habituelle — est interdit par la
CSP (`default-src 'self'`), et l'assouplir pour une préférence de couleur serait
un mauvais échange.
