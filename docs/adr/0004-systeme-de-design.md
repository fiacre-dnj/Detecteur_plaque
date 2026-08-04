# ADR 0004 — Système de design : `DESIGN.md` est la source de vérité des jetons

- **Statut** : accepté
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
