# 08 — Architecture frontend : React par feature, lazy par défaut

## 1. Principe

**Feature-Sliced Design** : le code est rangé par *ce qu'il fait pour
l'utilisateur*, pas par *ce qu'il est techniquement*. Un dossier `features/`
par capacité, un `shared/` pour le socle réutilisable, un `app/` pour le
câblage. Aucun dossier `components/`, `hooks/`, `utils/` global : ce sont des
sacs qui grossissent sans jamais se vider.

Règle de dépendance : `app → features → entities → shared`. Une feature
**n'importe jamais** une autre feature ; si deux features ont besoin de la même
chose, elle descend dans `entities/` ou `shared/`.

## 2. Arborescence

```
frontend/src/
├── main.tsx                       # createRoot + providers
├── index.css                      # Tailwind v4 : @import "tailwindcss" + @theme
├── app/
│   ├── App.tsx                    # <Providers><RouterProvider/></Providers>
│   ├── router.tsx                 # createBrowserRouter, routes PARESSEUSES
│   ├── providers/
│   │   ├── QueryProvider.tsx      # QueryClient + defaults
│   │   ├── ThemeProvider.tsx      # thème sombre par défaut
│   │   └── index.tsx              # composition
│   └── layout/
│       ├── AppShell.tsx           # entête + <Outlet/> + <Suspense/>
│       └── BackendStatusBadge.tsx
│
├── shared/
│   ├── api/
│   │   ├── contracts.ts           # miroir EXACT des schémas backend
│   │   ├── httpClient.ts          # fetch typé : erreurs, timeouts, garde content-type
│   │   ├── problemDetails.ts      # parse RFC 9457 → message FR
│   │   ├── sse.ts                 # abonnement EventSource typé
│   │   ├── websocket.ts           # RealtimeSocket (une frame en vol)
│   │   └── queryKeys.ts           # fabrique de clés React Query
│   ├── ui/                        # primitives SANS logique métier
│   │   ├── Button.tsx  Slider.tsx  Toggle.tsx  Section.tsx
│   │   ├── MetricCard.tsx  Skeleton.tsx  EmptyState.tsx
│   │   ├── ErrorBoundary.tsx  Table.tsx  Badge.tsx  Tooltip.tsx
│   ├── lib/
│   │   ├── geometry.ts            # sideOfLine, pointInPolygon, distanceToSegment (miroir du backend)
│   │   ├── format.ts              # formatTime, formatNumber (locale fr-FR)
│   │   ├── csv.ts                 # export client si besoin
│   │   ├── canvas.ts              # dpr, scaling, drawLabel
│   │   └── invariant.ts
│   └── config/
│       ├── vehicleLabels.ts       # libellés FR des classes
│       └── palettes.ts            # LINE_PALETTE, ZONE_PALETTE, CLASS_COLORS
│
├── entities/                      # objets métier partagés entre features
│   ├── geometry/                  # types CountingLine / CountingZone + reducer d'édition
│   ├── track/                     # type TrackedVehicle + adaptateur depuis l'API
│   ├── model/                     # type VehicleModel + regroupement par palier
│   └── stats/                     # type CountingStats + EMPTY_STATS + dérivations
│
└── features/
    ├── counting-studio/           # l'écran principal
    │   ├── ui/                    # StudioPage, StudioSidebar, StudioToolbar…
    │   ├── model/                 # état du studio (reducer), sélecteurs
    │   ├── api/                   # hooks React Query propres à la feature
    │   └── index.ts               # export public de la feature (une seule porte)
    ├── media-source/              # dépôt de fichier, démo, webcam
    ├── geometry-editor/           # canvas d'édition lignes/zones
    ├── video-transport/           # lecteur maison (vitesse, pas-à-pas)
    ├── analysis-job/              # dépôt, SSE, résultat, annulation
    ├── timeline-replay/           # relecture d'un résultat sur la vidéo locale
    ├── realtime-counting/         # webcam + WebSocket
    ├── results-dashboard/         # cartes, détail par ligne/zone, histogramme
    ├── vehicle-registry/          # tableau des identités (virtualisé)
    ├── model-picker/              # sélecteur groupé par palier
    ├── benchmark/                 # page de benchmark
    ├── geometry-presets/          # enregistrer/charger une géométrie
    └── job-history/               # historique persisté
```

Chaque feature expose **un seul `index.ts`**. Importer
`features/benchmark/ui/BenchmarkTable` depuis une autre feature est interdit
(règle oxlint `no-restricted-imports` sur `features/*/!(index)`).

## 3. Patterns imposés

| Pattern | Où | Ce qu'il achète |
|---|---|---|
| **Container / Presentational** | `features/*/ui` | Un composant qui dessine ne connaît ni React Query ni `fetch`. Testable avec des props |
| **Hook-façade** | `features/*/api/use*.ts` | Un composant consomme `useAnalysisJob()`, pas trois hooks React Query et un `useState` |
| **Adaptateur** | `entities/track/adapt.ts`, `features/timeline-replay/lib` | La vue rend un résultat serveur **sans modification** : l'adaptateur absorbe la différence de vocabulaire |
| **Reducer pour l'état complexe** | `entities/geometry/reducer.ts` | Lignes + zones + sélection + brouillon de tracé = une machine. Cinq `useState` qui doivent rester cohérents sont un bug qui attend |
| **Fonctions pures en dehors de React** | `shared/lib/*`, `features/*/lib/*` | Tout ce qui est calculable sans DOM est testé par `bun test`, sans navigateur ni GPU |
| **Provider composé** | `app/providers` | Un seul point de câblage ; `main.tsx` reste lisible |
| **Frontière d'erreur + frontière de suspense par route** | `app/layout` | Un panneau qui casse ne blanchit pas l'application |
| **Clés de requête centralisées** | `shared/api/queryKeys.ts` | Une invalidation ne rate jamais sa cible |

Anti-patterns explicitement interdits :
- **`useMemo` / `useCallback` / `React.memo` pour la performance.** Le React
  Compiler est activé : il mémoïse. `useCallback` n'est autorisé **que** quand
  une identité stable est une exigence de *correction* (dépendance d'effet,
  nettoyage d'effet) — et le commentaire doit le dire.
- `useEffect` pour dériver un état d'un autre (calculer au rendu) ou pour
  synchroniser deux `useState` (fusionner en un).
- Prop drilling au-delà de deux niveaux (descendre dans `entities` ou un
  contexte de feature).
- `any`, `as unknown as`, `!` non justifié, `// @ts-ignore`.
- Un `.tsx` qui exporte à la fois un composant et des données non constantes
  (oxlint `react/only-export-components`) : les données partagées vont dans un
  `.ts` voisin.

## 4. État : trois catégories, trois mécanismes

| Catégorie | Exemple | Mécanisme |
|---|---|---|
| **État serveur** | catalogue de modèles, santé, historique, résultat de job, benchmark | **React Query** (cache, revalidation, `staleTime` explicite) |
| **État d'interface durable** | modèle sélectionné, seuils, réglages de comptage, préférences d'affichage | `useReducer` dans un contexte de feature + **persistance `localStorage`** (schéma versionné, migration silencieuse, valeurs hors bornes ignorées) |
| **État éphémère local** | ouverture d'un panneau, survol, brouillon de tracé | `useState` dans le composant |

Réglages React Query par défaut :
`retry: 1`, `refetchOnWindowFocus: false` (une analyse ne doit pas repartir
parce qu'on a changé d'onglet), `staleTime: 30_000` pour le catalogue,
`staleTime: 0` pour un statut de job, `gcTime: 5 min`.

**Le suivi de progression n'est pas du polling React Query** : c'est un SSE, avec
un sondage de secours de 3 s (le SSE peut tomber : proxy, mise en veille de
l'onglet). Ce hook est le seul endroit où les deux coexistent, et il est commenté
comme tel.

## 5. Client HTTP

Un seul module, `shared/api/httpClient.ts` :

```ts
export class ApiError extends Error {
  readonly status: number;
  readonly code: string;
  readonly requestId: string | null;
}

async function request<T>(path: string, init?: RequestInit & { timeoutMs?: number }): Promise<T>
```

Obligations :
1. **URL toujours relative** (`/api/v1/...`) : même origine en dev (proxy Vite) et
   en production (backend qui sert le build).
2. **Garde `content-type`** : si la réponse est `text/html`, lever
   « API introuvable — le backend est-il démarré ? ». Le repli SPA de Vite répond
   `index.html` en **HTTP 200** pour une route inconnue, donc un mauvais chemin ne
   produit jamais de 404 : sans cette garde, on débogue un JSON cassé pendant une
   heure.
3. **Timeout** via `AbortSignal.timeout()` ; 2,5 s pour le *health check*
   (au-delà, le backend est considéré absent), 30 s pour le reste, **aucun** pour
   un upload.
4. Traduction des erreurs : `problemDetails.ts` transforme un
   `application/problem+json` en message français utilisable ; un corps
   non-JSON tombe sur « Le serveur a répondu {status} ».
5. `fetchHealth()` rend `null` au lieu de lever : l'appelant affiche « backend
   injoignable » et désactive l'analyse, il n'affiche pas une erreur rouge.
6. Progression d'upload : `XMLHttpRequest` (le `fetch` n'expose pas la
   progression d'envoi) **isolé dans une seule fonction commentée** — c'est le
   seul endroit du code où l'on n'utilise pas `fetch`.

## 6. Lazy loading — exigence explicite du projet

### 6.1 Routes paresseuses
```tsx
const StudioPage    = lazy(() => import("@/features/counting-studio").then(m => ({ default: m.StudioPage })));
const BenchmarkPage = lazy(() => import("@/features/benchmark"));
const HistoryPage   = lazy(() => import("@/features/job-history"));
```
`createBrowserRouter` avec `lazy:` par route, `<Suspense fallback={<PageSkeleton/>}>`
dans `AppShell`, et une `errorElement` par route.

### 6.2 Composants lourds, chargés à l'usage
- **Registre des véhicules** : importé paresseusement, il n'apparaît qu'avec un
  résultat.
- **Histogramme de flux** : idem.
- **Panneau de benchmark**, **modale de presets**, **export CSV** : `import()` au
  clic.
- **Feature webcam** : `import()` seulement quand l'utilisateur choisit la
  caméra (elle embarque la capture JPEG et le client WebSocket).

### 6.3 Préchargement à l'intention
Sur `onMouseEnter` / `onFocus` d'un lien ou d'un bouton qui mènera à un chunk :
déclencher l'`import()` sans attendre le clic (`void import(...)`). Le gain
perçu est supérieur à celui de n'importe quelle micro-optimisation de rendu.

### 6.4 Données paresseuses
- **La timeline n'est pas chargée avant d'être nécessaire** : le hook de
  relecture ne demande `/result` qu'à l'affichage du studio avec un job terminé.
- L'historique et le registre sont **paginés** côté API (`limit`/`offset`), pas
  filtrés côté client sur 10 000 lignes.
- Le tableau du registre est **virtualisé maison** (fenêtre + `IntersectionObserver`,
  ~60 lignes de code) : au-delà de 200 lignes, le DOM devient le goulot. Un
  bouton « afficher les N restants » couvre le cas simple ; la virtualisation
  s'active au-delà d'un seuil.
- `<video preload="metadata">` : on n'a besoin que des dimensions avant que
  l'utilisateur lance la lecture.

### 6.5 Budget
`bun run build` doit produire un chunk d'entrée **< 200 ko gzip**. Un dépassement
est un sujet de revue, pas un avertissement à museler. Documenter les tailles
dans `docs/ARCHITECTURE.md` après chaque lot.

## 7. Conventions TypeScript / React senior

- Composants **fonctionnels**, `export function Xxx()` nommé (pas de `default`
  sauf pour les modules chargés par `lazy`).
- Props typées par une `interface XxxProps` déclarée juste au-dessus.
  Pas de `React.FC` (il gêne les génériques et impose `children`).
- **Unions discriminées** plutôt que booléens multiples :
  `type SourceState = { kind: "none" } | { kind: "file"; file: File; media: LoadedMedia } | { kind: "demo"; media: LoadedMedia } | { kind: "webcam"; stream: MediaStream }`.
  Cela supprime les états impossibles (« webcam + fichier »), qui étaient une
  source réelle de bugs.
- Nommage : composants `PascalCase`, hooks `useXxx`, fonctions pures
  `verbeObjet`, types `PascalCase`, constantes `UPPER_SNAKE`.
  **Anglais pour le code, français pour l'UI.**
- Un fichier = un rôle ; au-delà de ~250 lignes, découper. Un composant qui
  dépasse 150 lignes de JSX cache probablement deux composants.
- Accessibilité **non négociable** : `aria-label` sur les contrôles sans texte,
  `aria-pressed` sur les bascules, `role="group"` sur les groupes de vitesse,
  navigation clavier complète du sélecteur de modèle (flèches + `Home`/`End` +
  `Échap`), focus visible, contrastes AA, `aria-live="polite"` sur les compteurs
  qui changent, `aria-hidden` sur les icônes décoratives.
- Les icônes viennent **uniquement** de `lucide-react`, taille via
  `className="size-4"`, jamais de `width`/`height` en dur.
- Tailwind v4 : configuration **CSS-first** dans `index.css` (`@theme` pour les
  couleurs et rayons de la marque). Pas de `tailwind.config.js`. Classes triées
  logiquement (layout → espacement → typographie → couleur → état). Pas de
  `@apply` sauf pour un motif répété trois fois et documenté.

## 8. Journalisation et diagnostic côté client

- Aucun `console.log` en production (règle oxlint). `console.error` autorisé
  dans une frontière d'erreur.
- Une **frontière d'erreur** par zone : coquille d'application, scène vidéo,
  panneau de résultats. Le message est en français, propose « recharger », et
  affiche le `requestId` s'il vient d'une `ApiError` — c'est ce qui rend un
  rapport d'incident exploitable.
- Un badge d'état du backend permanent : joignable / injoignable, device,
  version Ultralytics, modèles résidents (au survol).

## 9. Ce que le frontend ne fait plus (et ne doit pas refaire)

L'ancienne version portait un pipeline d'inférence complet dans le navigateur.
**Tout cela disparaît** : décodage de sortie YOLO (dense/end2end), NMS,
letterbox, tracker à centroïdes, galerie de ré-identification, métriques
d'inférence, gestion de session ONNX, cascade WebGPU→WASM, en-têtes COOP/COEP,
benchmark client.

Il **reste** au frontend, et c'est volontaire, une copie **minimale** de la
géométrie (`sideOfLine`, `pointInPolygon`, `distanceToSegment`) : elle sert
uniquement au **test de sélection à la souris** dans l'éditeur (cliquer *dans*
une zone) et au dessin. Elle ne compte rien. Un commentaire doit l'affirmer, et
un test doit vérifier que `sideOfLine` du frontend donne le **même signe** que la
convention documentée du backend — sinon les flèches de sens affichées
mentiraient.
