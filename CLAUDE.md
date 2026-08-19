# CLAUDE.md

Guide pour Claude Code (claude.ai/code) dans ce dépôt.

> Ce fichier décrit **ce qui existe**. Les 14 lots sont écrits ; l'application
> compte des véhicules de bout en bout, en différé comme en direct.
> [`prompt/`](prompt/) reste la spécification normative — quand les deux
> divergent, ce fichier a raison sur l'état du code et `prompt/` sur ce qui était
> demandé.

## Ce que fait l'application

Détection, suivi et comptage de véhicules sur une vidéo ou un flux caméra. Toute
l'inférence est côté serveur ; le navigateur pilote, dessine la géométrie de comptage et
rejoue le résultat.

**Il n'y a plus de ré-identification** depuis le 2026-08-13 : un objet suivi est un
véhicule, et c'est le tracker qui décide ce qu'est un objet suivi
([ADR 0016](docs/adr/0016-compter-les-objets-suivis.md)). Deux comptages coexistent et ne
se divisent jamais l'un par l'autre — les **véhicules** (`trackedVehicles`, tracé ou pas)
et les **passages** (`crossings`, par ligne et par sens). Chaque ligne porte deux sens,
et depuis le 2026-08-16 chacun est **obligatoirement** entrée ou sortie ([ADR
0021](docs/adr/0021-le-role-de-sens-devient-obligatoire.md)) — ce rôle donne le bilan
du carrefour et **est** le libellé affiché, il n'y a plus de nom libre à taper.

Deux modes partagent **le même** code de comptage — la même `AnalysisSession`, les
mêmes schémas de requête, les mêmes sérialiseurs — et c'est ce qui garantit qu'un
même tracé donne les mêmes chiffres dans les deux :

- **différé** : dépôt d'un fichier, analyse asynchrone suivie en SSE, résultat
  complet relu et rejoué sur la vidéo locale. Le flux SSE porte aussi un
  **aperçu** échantillonné (`event: preview`, ~5 Hz) : la vidéo locale se cale
  sur l'image analysée et le navigateur y dessine les boîtes, les compteurs et
  les franchissements du serveur **pendant** l'analyse
  ([ADR 0006](docs/adr/0006-apercu-live-des-analyses.md)). Il porte aussi le
  **registre** des véhicules, à une cadence propre et plus lente (1 s), ce qui
  fait vivre les quatre sections du bas de page pendant l'analyse
  ([ADR 0026](docs/adr/0026-le-registre-se-remplit-pendant-l-analyse.md)) ;
- **direct** : frames JPEG sur WebSocket, une image en vol à la fois.

En différé **seulement**, une passe ANPR optionnelle localise les plaques puis en
**lit le texte** (OCR) ; le texte publié est un vote sur la vie du véhicule, pas la
lecture de la frame courante ([ADR 0007](docs/adr/0007-lecture-du-texte-de-plaque.md)),
et ce vote tranche caractère par caractère quand deux graphies proches s'égalisent
([ADR 0008](docs/adr/0008-precision-de-l-anpr.md)). Le détecteur est **étranglé** —
une image sur trois par piste — et les images sautées portent la dernière plaque
mesurée, reprojetée sur la boîte du véhicule
([ADR 0010](docs/adr/0010-etranglement-du-detecteur-de-plaques.md)). Le direct n'a
pas d'ANPR du tout.

## `prompt/` est la spécification, pas de la documentation

Le dossier [`prompt/`](prompt/) (15 fichiers, à lire dans l'ordre depuis
[`prompt/README.md`](prompt/README.md)) **est** le cahier des charges. Quand il
écrit « obligatoire », « jamais » ou « exactement », c'est une contrainte qui a
coûté un bug dans une version antérieure.
[`prompt/13-PIEGES-CONNUS.md`](prompt/13-PIEGES-CONNUS.md) en tient la liste (66
entrées) — **le relire avant de déboguer quoi que ce soit**.

Si une contrainte semble fausse : le dire avec la preuve, proposer l'alternative,
écrire une ADR. Ne jamais la contourner en silence.

## Commandes

`uv` provisionne Python 3.12 lui-même : ne jamais invoquer un `python` du `PATH`
pour du code de ce projet.

```bash
# ── Tout servir (backend + interface, un seul origin)
docker compose up                # http://localhost:8000

# ── Backend (cd backend)
uv sync
uv run uvicorn traffic_analysis.main:app --reload --port 8000
uv run pytest                                                            # 1526 tests
uv run pytest tests/unit/counting/test_line_counter.py -k aller_retour   # un seul
uv run pytest --cov=src --cov-report=term-missing
uv run ruff check . && uv run ruff format --check . && uv run mypy src
uv run alembic upgrade head
uv run alembic revision --autogenerate -m "ajoute la table X"
uv run python scripts/fetch_weights.py --tiers nano,medium,large,xlarge
uv run python scripts/fetch_plate_model.py
uv run python scripts/fetch_plate_ocr_model.py       # modèle OCR + son dictionnaire
uv run python scripts/audit_lignes.py                # « pourquoi cette ligne est à 0 ? »

# ── Frontend (cd frontend)
bun install
bun run dev                      # proxy /api → 127.0.0.1:8000, WebSocket compris
bun run lint && bun run typecheck && bun test && bun run build           # 628 tests
bun test src/features/realtime-counting/model/scale.test.ts              # un seul

# ── Dépôt
uvx pre-commit run --all-files
```

**Il n'y a pas d'extra `gpu`.** `pyproject.toml` déclare
`[tool.uv] torch-backend = "auto"` **et** une source explicite : sur Windows,
`torch` et `torchvision` viennent de l'index **cu126**. `auto` seul ne suffisait
pas — il joue à la résolution, et le lockfile committé fige son verdict, donc une
machine NVIDIA recevait la roue CPU en silence
([ADR 0012](docs/adr/0012-torch-cuda-sur-windows.md)). Pour forcer une variante —
poste Windows sans GPU, build reproductible : `UV_TORCH_BACKEND=cpu uv sync`.

## Architecture

### Backend — vertical par feature, hexagonal à l'intérieur

`backend/src/traffic_analysis/` : `core/` (socle transverse, aucune feature),
`features/<nom>/` et `api/router.py`. Sept features : `counting`, `jobs`,
`models_registry`, `realtime`, `benchmark`, `presets`, `health`. Chacune porte son
`domain/` (pur), `application/` (ports + services), `infrastructure/`
(adaptateurs) et `api/` (routes).

Règle de dépendance, **outillée** par `backend/tests/test_architecture.py` — il a
rejeté du code trois fois pendant l'écriture des lots 7 et 8, et il avait raison à
chaque fois :

```
api → application → domain
infrastructure → application (ports) → domain
core ← tout le monde ;  core → rien des features
feature A → feature B  UNIQUEMENT par son `application`
```

`features/*/domain/**` n'importe jamais `fastapi`, `sqlalchemy`, `ultralytics`,
`cv2` ni `pydantic`. `numpy` reste autorisé — il servait aux descripteurs de
ré-identification, supprimés par ADR 0016, et le domaine ne l'importe plus nulle part ;
la règle reste ouverte parce qu'un calcul vectoriel y est légitime. C'est ce qui permet à
la CI de tourner **sans GPU, sans poids et sans ultralytics**, en injectant un
`FakeEngine`.

Cette architecture a un prix, payé deux fois : un bug de chemin de configuration
du tracker et une erreur d'encodage multipart ont traversé 500 tests verts, parce
que le moteur factice ne les atteint jamais. **Vérifier contre le vrai serveur
avant de déclarer une fonctionnalité terminée.**

`features/counting/domain/` est le cœur : `geometry`, `models`, `line_counter`,
`zone_counter`, `track_numbering`, `speed`, `tracking_session`, plus tout ce qui décide
de
l'ANPR sans toucher un pixel — `plate_geometry` (le filtre de plausibilité et les
raisons de non-lecture), `plate_policy` (les deux étranglements), `plate_anchor`,
`plate_text`, `plate_vote`. Sa spécification est
[`prompt/03-DOMAINE-COMPTAGE.md`](prompt/03-DOMAINE-COMPTAGE.md).

Le filtre géométrique vit dans le domaine **et pas dans l'adaptateur**, et ce
déplacement est ce qui rend les 426 gardées / 112 jetées d'ADR 0008 vérifiables :
derrière `ultralytics`, la CI ne les traversait jamais.

`features/models_registry/infrastructure/` est le **seul** endroit qui importe
`ultralytics`.

`counting/application/dto.py` et `request_schema.py` sont le contrat publié de la
feature `counting` : `jobs`, `realtime` et `benchmark` importent de là, jamais du
domaine.

### Frontend — Feature-Sliced Design

`frontend/src/` : `app/` (câblage), `features/<capacité>/` (13), `entities/`,
`shared/`. Aucun dossier `components/`, `hooks/` ou `utils/` global.

```
app → features → entities → shared
```

Une feature n'importe **jamais** une autre feature. Quand deux en ont besoin, le
câblage passe par `StudioPage` — c'est pourquoi `GeometryPanel` reçoit un
`onOpenPresets` plutôt que la modale elle-même, et pourquoi `SettingsPanels` reçoit
un emplacement `leading` où le studio pose le bouton d'import.

#### La disposition du studio, depuis le 2026-08-12 (barre collante, géométrie en tiroir et actions dans le lecteur le 2026-08-19)

```
━━ barre COLLANTE sous l'entête (sticky, top: --app-header-h, z-30) ━━━━━━━━━━
[⇧ Importer] [Détection ▾] [Comptage ▾] [Affichage ▾] [Géométrie ▾]  cadence · latence · flux →
             └─ tiroir flottant du panneau ouvert, 2 colonnes, PAR-DESSUS la page
┌──────────────────────────────┬──────────────────┐
│ nom du fichier ⟨   ⟩ WxH · fps│ RÉSULTATS         │  aside 24 rem
│ vidéo + canvas + HUD          │ 2 KPI de tête     │
│ ┌ LECTURE ───── mm:ss/mm:ss ┐ │ + 4 (5) cartes    │
│ │ rail de position          │ │   par type,       │
│ │ INTERVALLE ─── mm:ss→mm:ss│ │   MÊME longueur   │
│ │ rail d'intervalle         │ │   de rail que la  │
│ │ ⏵ ⏮ ⏪ ±1i ⏩ ⏭ ↺  Vitesse  │ │   position        │
│ │              [LANCER] [Fermer]                  │
├──────────────────────────────┴──────────────────┤
│ STATISTIQUE — KPI de tête, une rangée par ligne,  │  les trois sections
│   comparatifs groupés en une carte                │  vivent PENDANT
│ [camembert flux/ligne] [camembert entrées/type]   │  l'analyse et après
│ REGISTRE — tableau par véhicule, export CSV/JSON  │  exports à la fin
│ FRANCHISSEMENTS — chronologie, PENDANT ET APRÈS   │  jamais en direct
└──────────────────────────────────────────────────┘
```

**Ce qui a bougé le 2026-08-19, et pourquoi.** Cinq déplacements, tous motivés par
la même observation : le bas de page s'était allongé (trois sections plus la
chronologie), donc tout ce qui vivait « en haut à droite » finissait hors de
l'écran dès qu'on lisait un résultat.

- **la barre est collante** (`sticky`, décalée de `--app-header-h` que `AppShell`
  mesure et publie ; `-mx-6 px-6` pour peindre son fond jusqu'aux gouttières).
  Sans le fond opaque, la vidéo défile visiblement sous les pilules. La hauteur
  d'entête est **mesurée** et non écrite en dur : elle s'enroule en fenêtre
  étroite, et le badge serveur grandit quand il porte une erreur ;
- **« Géométrie » est le quatrième tiroir**, plus un panneau permanent de la
  colonne. `SettingsPanels` l'accepte par `panels` (`ExtraPanel[]`) — la feature
  des réglages ne connaît pas `geometry-editor`, c'est le studio qui câble, même
  règle que `leading`/`trailing`. `GeometryPanel` a **perdu sa carte et son
  titre** : le tiroir est déjà une région nommée « Géométrie » ;
- **les trois chiffres de machine** — cadence serveur, latence, flux analysé —
  sont à l'extrémité de la barre (`TechnicalMetrics`, `trailing`), en libellé plus
  chiffre sur deux lignes, sans carte. Ils tenaient trois des cinq `MetricCard` de
  tête, à égalité visuelle avec le bilan du carrefour ;
- **le nom du fichier est sur la scène**, coin haut-gauche, dans **exactement**
  l'écrin du badge de dimensions d'en face (`SourceBadge`, `pointer-events-none`
  obligatoire — la scène est une surface de tracé) ;
- **« Lancer l'analyse » et « Fermer » sont dans le lecteur** (`TransportBar.actions`,
  poussés par `ms-auto`), là où se réglait la vitesse — laquelle rejoint le groupe
  de boutons qui lit. Le rappel « Portion retenue » disparaît avec eux : l'intervalle
  est écrit deux rangées plus haut, dans l'entête du rail qui le dessine.

**Les deux rails du lecteur ont la même longueur, et c'est vérifiable** (mesuré :
`x = 79`, `w = 1128` pour les deux). Le temps courant était écrit *à côté* du
curseur de position, ce qui raccourcissait ce rail-là de la largeur de
« 03:26 / 03:26 » : une borne posée au milieu de l'intervalle ne tombait pas au
milieu de la vidéo. Les deux chiffres sont désormais en **entête de leur rail**,
d'où les deux libellés « LECTURE » et « INTERVALLE D'ANALYSE » qui se répondent.

**La Répartition n'a plus de section** : ses cartes sont dans les Résultats, en
`size="sm"` — elles découpent « Entrées au carrefour » dont elles sont la somme
exacte, et un écran de défilement entre les deux obligeait à retenir un nombre
pour vérifier l'autre. `ClassEntriesGrid` est **supprimé**, son contenu replié
dans `ResultsDashboard`. Le titre « Répartition » ne disait rien de plus que
« Voiture », « Bus » juste dessous.

**La chronologie des franchissements survit à la fin de l'analyse** — c'était sa
condition d'affichage (`session.result === null`) qui la démontait à la seconde où
l'on commence à vérifier un comptage. Après coup elle lit le résultat complet à la
tête de lecture (`crossingsUpTo`, la fonction qui existait pour cela et avait perdu
son consommateur), donc elle ne montre jamais un passage que la vidéo n'a pas
atteint. `timelineEvents` dans `StudioPage` choisit la source ; `!live.active`
reste, le direct n'ayant pas de journal.

**Les sections du bas se mettent à jour en direct depuis le 2026-08-17** ([ADR
0026](docs/adr/0026-le-registre-se-remplit-pendant-l-analyse.md)) : l'aperçu SSE
transporte désormais le registre (`JobPreview.vehicles`), les mêmes
`VehicleRecord` que le résultat final par le même sérialiseur. Un seul jeu de
composants, deux sources de même forme — `dashboardStats` dans `StudioPage`
choisit l'aperçu pendant, la tête de lecture après. Trois points qui ne se
devinent pas :

- **le registre est republié dix fois moins souvent que les boîtes** (1 s contre
  100 ms) : il **grossit** avec l'analyse, à ~350 octets par véhicule, là où les
  pistes d'une image restent une poignée. Les aperçus intermédiaires portent
  `vehicles: null`, qui veut dire **« inchangé »** et jamais « aucun véhicule »
  — `carryVehicles` reporte la dernière liste, une fois, pour qu'aucun
  consommateur n'ait à connaître la convention ;
- **les trois boutons d'export restent masqués tant que l'analyse tourne**
  (`result` est `null`) : un CSV à mi-parcours serait amputé sans dire de
  combien. Même règle que les exports qui ignorent la recherche par plaque ;
- **le direct (caméra) ne gagne rien**, faute d'aperçu SSE donc de registre.
  Seule la Répartition, qui ne lit que `by_class`, reste servie dans les trois
  modes — elle est depuis le 2026-08-19 dans les cartes de Résultats, ce qui ne
  change rien à cette règle : elle suit `resultStats` et non `dashboardStats`.

Le tiroir ouvrait initialement **en flux normal**, pleine largeur — il grandissait
la page et poussait la vidéo et les résultats de plusieurs centaines de pixels vers
le bas à chaque ouverture. Depuis le 2026-08-16 il **flotte** (`position: absolute`,
ancré sous la barre, `z-30`) : la page ne bouge plus quand on l'ouvre. Un clic en
dehors ou `Échap` le referme. L'entête de l'application (`AppShell`) est fixée en
haut de l'écran (`sticky top-0 z-40`) pour la même raison de fond — rester
atteignable pendant que la page défile en dessous, et **la barre du studio l'est à
son tour** depuis le 2026-08-19, calée sur la hauteur mesurée de cette entête.

#### Ce que portent les quatre tiroirs, depuis le 2026-08-17 (le quatrième depuis le 2026-08-19)

Le contenu a été **réaligné sur le code réellement exécuté** : plusieurs textes
décrivaient un comportement d'avant ADR 0024 et ADR 0025, et deux chiffres du
diagnostic n'étaient renseignés par personne.

- **Détection** — modèle, confiance véhicules, classes à compter, ANPR, confiance
  plaques, OCR, **et « Ignorer hors zone »**, qui vivait dans « Affichage » alors
  qu'il ne change pas ce qu'on voit mais ce que le détecteur reçoit, donc les
  chiffres. Deux textes étaient devenus faux : la confiance ne filtre plus le
  détecteur (elle décide ce qui *devient* une piste), et « Repérer les plaques »
  connaît désormais les **trois** états du serveur — absent, présent mais illisible
  (`plateAvailable && plateLoadable === false`), disponible. Le deuxième laissait
  cocher une option qui ralentissait l'analyse sans jamais rendre une plaque ;
  `model/plateCapability.ts` le tranche en un endroit, testé ;
- **Comptage** — images avant comptage, survie d'une piste perdue, seuil IoU, un
  encart « décidé pour vous » qui énonce la bande morte et son coût (l'horodatage
  est celui de la *sortie* de bande), le diagnostic, et les
  **quasi-franchissements**, redevenus visibles ;
- **Affichage & analyse** — trajectoires (le seul réglage purement visuel), pas
  d'analyse, les deux cadences, et l'**échelle globale** px/m, désormais présentée
  pour ce qu'elle est depuis ADR 0025 : un repli, que la longueur d'une ligne
  l'emporte localement dès qu'elle est saisie ;
- **Géométrie**, depuis le 2026-08-19 — lignes, zones, presets, rôles de sens et
  longueur réelle par ligne. Fourni par le studio (`panels`) et non par cette
  feature, qui ne connaît pas `geometry-editor`.

Les boutons du tiroir sont **grisés tant qu'aucune vidéo n'est chargée** : régler
la détection, le comptage, l'affichage ou la géométrie n'a rien à quoi s'appliquer
sans source. La scène vide n'affiche plus une phrase inerte mais une invite
cliquable (icône, « Importer une vidéo », glisser-déposer) — le bouton de la barre
et cette invite déclenchent le même import, `handleFile`. Le nom du fichier
importé, qui a occupé l'extrémité de la barre, est depuis le 2026-08-19 **posé sur
la vidéo** ; cette extrémité porte les compteurs techniques.

Elle est l'inverse de la précédente, où les réglages tenaient la colonne de droite
et les résultats vivaient sous la grille. Conséquences à connaître :

- **le direct n'a plus de porte d'entrée.** Les cartes « démonstration » et
  « caméra » sont retirées de l'écran — elles étaient désactivées depuis longtemps.
  `realtime-counting`, `RealtimePanel`, `media.selectCamera` et `isCamera` sont
  **intacts** : rouvrir la porte est un `useCallback` et un bouton dans la barre ;
- **la chronologie cliquable a été retirée le 2026-08-17, sans remplacement.**
  Elle avait quatre étages depuis le 2026-08-13 — rail de densité, bandeau de
  synthèse, filtres ligne/sens/type, liste groupée — mais faisait double emploi
  avec la barre de lecture standard pour se déplacer dans le temps, et n'ajoutait
  que du détail brut. `timeline-replay/ui/CrossingTimeline.tsx` et
  `model/timeline.ts`/`timelineFilters.ts` sont supprimés, pas seulement masqués ;
- **le bas de page n'a plus d'onglets.** L'ancien `Tabs` à cinq entrées
  (Répartition, Par ligne & sens, Mouvements, Flux, Registre) est remplacé par
  des sections toujours empilées, jamais en accordéon — **Statistique**
  (`LineFlowDashboard`) et **Registre** (`VehicleRegistry`). La Répartition y a
  vécu jusqu'au 2026-08-19 sous la forme d'un `ClassEntriesGrid` **aujourd'hui
  supprimé** : ses cartes sont dans `ResultsDashboard`, où l'invariant qui les
  justifie reste vrai — valeur = entrées seulement, cohérente par construction
  avec le KPI « Entrées au carrefour », `entriesByClass` partageant son prédicat
  `role === "entry"` avec `flowBalance`, verrouillé par un test. La matrice
  origine-destination
  (« Mouvements ») et l'occupation de zone disparaissent **sans
  reconstruction**, décision assumée : ce tableau de bord ne parle que de
  lignes ;
- **la Statistique est dense, pas aérée** (2026-08-17). Chaque ligne tient sur
  **une rangée** — nom, entrées, sorties, solde signé, part du trafic, puis une
  seule barre à deux segments — et non plus sur une carte à deux barres
  empilées, qui laissait la moitié de la section en vide. La phrase-bilan
  (`crossroadFlowSentence`) survit en `aria-label` de la rangée et **elle seule
  porte la précision qui compte** : *« entrer » veut dire entrer **dans le
  carrefour**, pas dans la rue*. Les comparatifs tiennent dans **une** carte en
  grille, plus une `MetricCard` chacun. Deux nouveaux s'ajoutent aux trois
  existants, et **ils ne disent pas la même chose** : `mostEnteredLine` /
  `mostExitedLine` donnent le compte **brut** (« quelle ligne sert le plus à
  entrer »), là où `strongestInflowLine` / `strongestOutflowLine` donnent le
  **solde net** — une ligne qui reçoit 10 entrées et laisse ressortir 9 est la
  plus entrée sans être le plus fort afflux, cas verrouillé par un test ;
- **les deux graphiques sont des camemberts côte à côte** (2026-08-17), sur une
  primitive partagée `ui/PieChart.tsx` — un SVG maison de `<path>`, légende et
  chiffres en HTML à côté (même règle que l'ancien histogramme : jamais de
  `<text>` SVG, que le `viewBox` mettrait à l'échelle). `LineFlowChart` ventile
  le total par ligne, `ClassEntriesChart` les entrées par type. Le premier
  répondait avant à « quand » (barres empilées par tranche de temps) et répond
  désormais à « quelle part » : **`flowBucketsByLine` et le clic-pour-se-déplacer
  sont supprimés**, pas masqués — un camembert n'a pas de position temporelle
  sur laquelle caler la lecture, et la barre de lecture standard reste le seul
  outil pour se déplacer dans le temps ;
- **le Registre n'est plus « inchangé »** (2026-08-17). Le titre `<h2>Registre</h2>`
  que `StudioPage` empilait au-dessus est retiré — `VehicleRegistry` porte déjà
  le sien, « Registre des véhicules », et les deux se lisaient comme deux
  sections. Le tableau gagne **Durée**, **Zones** et **Conf. détection**
  (`bestPlateScore`, distincte de la confiance de *lecture* déjà présente : une
  plaque peut être bien localisée et illisible, ou l'inverse), traduit le type
  en français par `classLabel`, et colle ses en-têtes (`sticky top-0`).
  **Il dit désormais *quand*, et pas seulement *par où*** : deux colonnes
  **Entrée** et **Sortie** portent l'instant du franchissement, au **dixième de
  seconde** (`formatSceneTimePrecise`) — deux passages du même véhicule sur deux
  lignes voisines tombent régulièrement dans la même seconde, et `formatSceneTime`
  les affichait à la même heure. Le rôle est lu sur le **tracé courant** par
  `vehicle-registry/model/roleCrossings.ts`, donc basculer un sens
  entrée ↔ sortie déplace l'heure de colonne sans réanalyser ; une ligne retirée
  du tracé n'est **pas** rangée par défaut dans « entrée » et la cellule se tait.
  Un rôle qui porte plusieurs franchissements — aller-retour, deux lignes en
  travers de la même voie, piste coupée par une occlusion (invariant 6) — affiche
  le premier instant et annonce les autres par « +N », jamais fusionnés. Les deux
  en-têtes de gauche sont renommés dans le même mouvement : **« Présent de / à »**
  et **« Durée à l'écran »** (`firstSeenMs → lastSeenMs`, un temps de **présence
  dans le champ**), parce que « Vu de / à » et « Durée » se lisaient comme l'heure
  et le temps du franchissement — exactement ce que les deux nouvelles colonnes
  portent ;
- **les Franchissements sont une chronologie, plus un tableau** (2026-08-17).
  `CrossingLog` est **supprimé**, remplacé par
  `analysis-job/ui/CrossingTimeline.tsx` et son modèle
  `model/crossingTimeline.ts`. Le tableau posait un fait par rangée sans rien dire
  de ce qui se lit *entre* deux faits ; les relations sont maintenant calculées en
  un parcours et rendues sur une colonne vertébrale, groupée par tranches de temps.
  Six points qui ne se devinent pas :
  - **`gapMs`** donne le rythme — quatre passages en 1,5 s et quatre passages en
    deux minutes s'affichaient identiquement. `null` sur le plus ancien du journal,
    où ce qui précède a pu être oublié : un « +0,0 s » s'y lirait comme une
    simultanéité ;
  - **`previous` relie une sortie à l'entrée du même véhicule**, ce qui donne le
    **temps de traversée du carrefour** — la seule mesure de ce genre que
    l'interface produise. Elle serait plausible et fausse si elle liait deux
    véhicules, d'où un test dédié ;
  - **`passageIndex`** dit « 2ᵉ passage » là où un aller-retour se lisait comme un
    doublon d'affichage (invariant 6) ;
  - **les compteurs de la section sont ceux du journal, pas de l'analyse**, et la
    borne est **annoncée** dès qu'elle est atteinte. L'ancienne version affichait
    `events.length` comme un total : il plafonnait donc à `LOG_LIMIT` (200) en
    silence sous un tableau de bord qui continuait de monter (invariant 3) ;
  - **les tranches de temps sont adaptatives** (`chooseBucketMs`, échelle 5 s →
    10 min, cible ~4 passages par tranche) et **alignées sur des bornes rondes** :
    à 10 s fixes, un journal étalé sur trente minutes produirait jusqu'à 180
    en-têtes pour 200 événements, et « 00:17 → 00:31 » ne se relie à rien sur la
    barre de lecture. Les tranches vides ne sont pas rendues ;
  - **le rôle du sens est l'information de tête**, lu sur le tracé courant comme au
    registre — « sens + » était le contrat machine. Entrée et sortie se distinguent
    par le **poids et l'angle de la flèche**, jamais par une teinte : la couleur
    encode déjà la ligne au nœud et la classe au véhicule ;
  - **la flèche est pivotée à l'angle réel du tracé**, pas un pictogramme d'entrée ou
    de sortie — voir « Une flèche, trois écrans » ci-dessous ;

  Trois précisions sur le périmètre : les filtres rôle/ligne sont un outil de
  **lecture** et non de navigation — aucun clic ne déplace la tête de lecture, ce
  qui était le double emploi ayant fait retirer l'ancienne chronologie cliquable ;
  la section est masquée **en direct** (`!live.active`), parce que
  `session.events` vient du suivi SSE d'un *job* et qu'en caméra elle affichait son
  vide pour toute la session, sous des compteurs qui montaient ; et **aucune région
  `aria-live`**, qui ferait d'un lecteur d'écran un métronome sur un carrefour
  chargé ;
- **`classLabel` et `VEHICLE_CLASSES` ont déménagé dans `shared/lib/classes.ts`**,
  pour la même raison que `shared/lib/directions.ts` : quatre features nomment une
  classe, et une feature n'importe jamais une autre feature. Tant qu'ils vivaient
  dans `results-dashboard/model/labels.ts`, la chronologie écrivait `car #12` là où
  le registre écrivait `Voiture` pour le même véhicule — invariant 12 ;
- **`shared/ui/Tabs.tsx` reste**, sans consommateur pour l'instant — une
  primitive ARIA générique et accessible (flèches, Home/Fin, roving `tabIndex`),
  gardée pour un futur besoin plutôt que supprimée pour un gain nul.

#### Une flèche, trois écrans — `directionHeadingDeg`

Trois endroits affichent le sens d'un franchissement, et ils montrent tous la
**même flèche au même angle** : le panneau de géométrie (`DirectionRoleRow`), la
chronologie des franchissements (`RolePill`) et les puces « Lignes franchies » du
registre (`CrossingArrow`). L'angle est celui du **tracé réel** — la
perpendiculaire au trait, orientée du côté d'arrivée — et non un pictogramme
conventionnel : c'est ce qui permet de relier une rangée de tableau au trait qu'on
voit sur la vidéo, ce qu'aucune icône « entrée » ou « sortie » ne permet.

`shared/lib/directions.ts` en est le **seul** juge, `directionHeadingDeg(line,
sign)` — plus `crossingHeadingDeg(lines, lineId, direction)`, même forme et même
repli que `crossingDirectionName`. Quatre points qui ne se devinent pas :

- **la négation du sens négatif vit là et nulle part ailleurs.** Elle était écrite
  en clair dans `GeometryPanel`, et c'est exactement le signe qu'on inverse sans le
  remarquer : `shared/lib/geometry.ts` documente le mode de panne — des flèches à
  l'envers sous des rôles et des totaux par ailleurs justes, sans rien qui plante.
  Un test reconstruit le vecteur depuis l'angle rendu et demande à `sideOfLine` —
  la formule du backend — de quel côté on tombe ;
- **`ArrowUp` + rotation CSS, jamais un glyphe unicode.** `↑ ↗ →` ne pivotent qu'à
  45° près : sur une ligne oblique, « presque perpendiculaire » est précisément ce
  qui fait douter du sens affiché ;
- **sans angle calculable, pas d'angle inventé.** `null` sur un segment dégénéré
  (une ligne qu'on vient de commencer à tracer) ou une ligne retirée du tracé
  depuis l'analyse. Les deux consommateurs traitent ce cas différemment, et c'est
  le texte voisin qui tranche : la chronologie n'affiche **aucune** flèche parce
  que son libellé de repli est déjà « sens ↑ », le registre retombe sur le
  **glyphe** parce que le sien est l'identifiant de la ligne, où retirer la flèche
  ferait disparaître le sens ;
- **`-180°` et `180°` sont la même rotation**, et c'est le zéro négatif du normal
  d'une ligne horizontale qui décide laquelle sort d'`atan2`. Les tests normalisent
  ; la fonction, non — normaliser ferait diverger son chiffre de celui
  d'`arrowRotationDeg` pour une flèche identique à l'écran.

### Le contrat, pas un build

Pas de monorepo tool. `frontend/src/shared/api/contracts.ts` est le miroir
**exact** des schémas pydantic ; une fixture JSON committée est parsée dans un
test typé, donc un renommage côté backend casse un test côté frontend.

### Livraison

Une seule image (`backend/Dockerfile`, trois étapes) sert le backend **et** le
build du frontend, sur un seul origin. Cela supprime le CORS à ouvrir, le
tamponnage SSE du proxy et le relais WebSocket — les trois pannes de déploiement
habituelles. Un **seul worker** uvicorn : l'état en mémoire (`ProgressHub`, baux
de modèles, compteur de sessions) n'est pas partagé entre processus.

## Invariants à ne jamais violer

Chacun est un bug déjà payé.

1. **Le temps est du temps de scène.** Tout horodatage métier est
   `frame_index / fps × 1000`, jamais `time.time()`. Le seul usage légitime de
   l'horloge murale est la mesure de performance. En direct, le client compte
   depuis le début de session — un flux caméra n'a pas d'index de frame.
2. **Les coordonnées sont en pixels de la vidéo source.** Jamais en pixels
   modèle, jamais en pixels CSS. Les conversions se font aux frontières.
3. **Un compteur affiché est dérivé, jamais accumulé en double.**
   `crossings == Σ by_line[*].total` et `total == positive + negative`.
   **Et surtout : ne jamais diviser un compteur de passages par un compteur de
   véhicules.** Les deux unités ont divergé au 2026-08-12 (ADR 0014) et le « taux de
   franchissement » l'a payé — il affichait 200 % dès le premier aller-retour, en le
   documentant comme voulu. Le numérateur est `crossed_unique`, le nombre de
   véhicules **distincts** ayant franchi, dérivé de
   `LineCounter.counted_identities()` — la même source que le badge ✓, pour que les
   deux ne puissent pas se contredire.
4. **On compte sous `identity_label`** (vote majoritaire sur la vie du véhicule),
   jamais sous la lecture de la frame courante. Le vote est le seul morceau de
   l'ancienne galerie d'apparence qui survit à ADR 0016, et c'est lui qui rend le type
   cohérent entre véhicules de types différents. **Le texte de plaque suit la même règle** :
   ce qui est publié est le vote de `PlateTextVote` sur toute la vie du véhicule,
   jamais la lecture de la frame — sinon deux relectures du même clip donnent deux
   plaques.
5. **Le badge ✓ dérive du tally**, jamais de la comptabilité interne d'une piste.
6. **Deux comptages, deux unités, et on ne les divise jamais l'un par l'autre.**
   - **véhicules** — `tracked_vehicles` : *un objet suivi = un véhicule*, qu'il ait
     franchi une ligne ou non. Seules comptent les pistes **confirmées**
     (`hits >= min_hits`) ;
   - **passages** — `crossings` et tous les `by_line` : chaque franchissement observé
     compte. Un aller-retour compte **2**, deux lignes en travers de la même voie
     comptent **2**, une occlusion qui coupe une piste compte **2**.

   **Ce que l'écran met en avant a changé le 2026-08-17** ([ADR
   0023](docs/adr/0023-un-vehicule-compte-est-un-vehicule-qui-franchit.md)) : le
   serveur publie toujours tout objet suivi confirmé, mais le **registre** et le KPI
   « Véhicules ayant traversé le carrefour » ne montrent que les véhicules ayant
   **franchi**. Le KPI compte les véhicules distincts **entrés** (sens `entry`), le
   registre ceux ayant franchi une ligne dans **n'importe quel** sens. Les deux
   prédicats vivent dans `results-dashboard/model/crossedVehicles.ts` et sont
   **calculés côté client** : c'est ce qui rend le basculement d'un sens
   entrée ↔ sortie instantané. `len(vehicles()) == tracked_vehicles` reste vrai
   côté serveur et ne l'est plus à l'écran.

   Le garde d'ADR 0009 est **supprimé**, plus débranché : `dedupe_by_identity`,
   `reid_count` et `reid_hits` n'existent plus. `domain/reid.py` non plus — il est
   remplacé par `domain/track_numbering.py`, qui numérote et vote la classe, sans
   jamais comparer deux apparences.
   **Un résultat archivé avant le 2026-08-13 ne se recharge plus dans le studio** :
   son `result.json.gz` porte les anciennes clés, et ses chiffres ne sont de toute
   façon pas comparables.
   [ADR 0016](docs/adr/0016-compter-les-objets-suivis.md), qui abroge
   [ADR 0009](docs/adr/0009-un-comptage-par-vehicule.md) et amende
   [ADR 0014](docs/adr/0014-compter-des-passages.md).
7. **`_release_lost` avant `_number_tracks`.** L'ordre reste, la raison a changé :
   il ne s'agit plus de relâcher une identité avant qu'une autre piste la réclame
   (plus rien n'est admis), mais de **libérer l'identifiant de piste** avant de
   numéroter. Un `track_id` réémis par le tracker au-delà de `max_lost_ms` doit
   recevoir un numéro neuf, sinon deux véhicules fusionnent — et
   `BaseTrack._count` d'Ultralytics étant un attribut de *classe*, une session temps
   réel qui démarre pendant une analyse suffit à provoquer ce cas.
8. **La timeline stocke des `snapshot()`**, pris **après** la passe ANPR **et**
   après la passe OCR. Un snapshot pris entre les deux porterait des boîtes muettes
   que l'analyse, elle, avait su lire.
9. **Un bail (`lease`) par usage de modèle.** Deux `track()` simultanés sur la
   même instance mélangent deux vidéos — des chiffres plausibles et faux.
10. **Ne jamais déduire une caractéristique d'un modèle de son nom de fichier.**
11. **Tout ce qui touche OpenCV, PyTorch ou le disque en volume part dans un
    thread worker** (`anyio.to_thread.run_sync`).
12. **Le code parle français à l'utilisateur, anglais au compilateur.**
    Identifiants et types en anglais ; docstrings, commentaires et copie
    d'interface en français.

### Les deux pannes silencieuses

Elles méritent leur propre section parce qu'elles ne lèvent **rien** : pas
d'exception, pas de journal, et des chiffres qui restent plausibles.

13. **La géométrie du direct est mise à l'échelle d'envoi.** Le client réduit ses
    frames à 960 px ; une ligne tracée sur du 1280 px appliquée à une image de 960
    est comptée **25 % à côté**. Le serveur ne peut pas le détecter — il ne connaît
    pas la résolution que le client croit envoyer — donc il renvoie les dimensions
    reçues, et le client compare et **refuse de compter** en cas d'écart.
    `pixelsPerMeter` est mis à l'échelle lui aussi : c'est un rapport pixels/mètre.
    Voir `frontend/src/features/realtime-counting/model/scale.ts`.
14. **L'aperçu d'un job porte les dimensions décodées par le serveur.** Le client
    les compare à celles de sa balise `<video>` et **suspend le dessin** en cas de
    désaccord — SAR non carré, rotation portée par les métadonnées. Le serveur ne
    peut pas détecter cet écart : il ne sait pas ce que le navigateur affiche. Des
    boîtes décalées se lisent comme un défaut de détection, jamais comme un défaut
    de repère.
15. **Un preset porte la résolution pour laquelle il a été tracé.** Le serveur le
    convertit à la lecture et **l'annonce** par `scaled`. Une conversion
    silencieuse serait pire que pas de conversion : une géométrie qui bouge sans
    prévenir se lit comme un bug.

## Décisions déjà prises — ne pas les rediscuter

1. **Analyse 100 % backend.** Aucune inférence navigateur.
   [ADR 0003](docs/adr/0003-analyse-100-pourcent-backend.md).
2. **Python 3.12 épinglé**, borne haute `<3.13`.
   [ADR 0001](docs/adr/0001-python-312.md).
3. **Aucun poids dans git.** [ADR 0002](docs/adr/0002-pas-de-poids-dans-git.md).
   Le dossier `yolo/` que les versions antérieures de ce fichier décrivaient
   **n'existe plus** : ne pas le chercher. Tous les poids vivent dans
   `backend/.weights/`, tous en `.pt`, tous récupérés par script.
4. **`torch` en variante automatique** selon le matériel, pas d'extra.
   [ADR 0005](docs/adr/0005-torch-cpu-par-defaut.md).
5. **Persistance SQLite + SQLAlchemy async + Alembic.** Sept tables. La timeline
   complète, elle, part dans un `json.gz` sur disque : plusieurs centaines de Mo
   n'ont rien à faire dans une base mono-écrivain que personne ne requête.
6. **`DESIGN.md` est la source de vérité des jetons visuels**, avec deux
   arbitrages dans [ADR 0004](docs/adr/0004-systeme-de-design.md) : les valeurs de
   `DESIGN.md` remplacent le `bg-slate-950` de `prompt/09`, et l'accent vert est
   **strictement fonctionnel** — la couleur du canvas encode une donnée, donc le
   vert n'est jamais une couleur de classe.
7. **Thème sombre par défaut, clair au choix** (bascule dans l'entête). Le clair
   ne fait que redéfinir les jetons sous `:root[data-theme="light"]` : aucune
   variante `dark:` dans les composants, et **les couleurs du canvas ne changent
   pas** — elles sont posées sur de la vidéo, pas sur le fond de page. Amendement
   d'[ADR 0004](docs/adr/0004-systeme-de-design.md).
8. **OCR de plaque : onnxruntime + PP-OCRv3 rec, en différé seulement, texte voté
   sur la vie du véhicule.** Aucune dépendance nouvelle — `onnxruntime` et `onnx`
   étaient déjà des dépendances dures. Ni PaddleOCR (600 Mo de `paddlepaddle` et un
   téléchargement de poids au runtime) ni EasyOCR.
   [ADR 0007](docs/adr/0007-lecture-du-texte-de-plaque.md).
9. **La précision de l'ANPR se joue au filtre géométrique, pas au modèle.** Sur 538
   détections réelles, 112 étaient la boîte du véhicule entier — dont certaines à
   0,87 de confiance, donc inatteignables par un seuil. La mosaïque d'inférence
   existe mais reste **désactivée par défaut** : elle échange du rappel contre de la
   vitesse (côté 2 : 3,4× pour −16 % de rappel ; côté 3 : 6,6× pour −44 %), et ce
   n'est pas un arbitrage à faire en silence.
   [ADR 0008](docs/adr/0008-precision-de-l-anpr.md).
10. **On compte des passages, les personnes à part, et l'utilisateur choisit les
    classes.** Chaque franchissement observé compte : la déduplication par identité
    d'ADR 0009 est **supprimée** depuis ADR 0016 (le drapeau ne reste pas non plus).
    Les franchissements sont ventilés
    en `vehicle` / `person` par une propriété **dérivée** de `by_class` — jamais un
    second compteur. Les classes cochables sont servies par
    `GET /api/v1/models/classes`, pas recopiées dans l'interface, et le défaut reste
    les quatre véhicules.
    **Aucun modèle du catalogue ne sait détecter une charrette** : COCO n'a pas
    cette classe, et l'ajouter au catalogue donnerait une case qui ne détecte jamais
    rien. Les deux vraies voies — vocabulaire ouvert (YOLO-World/YOLOE) ou
    entraînement dédié — sont décrites dans l'ADR.
    [ADR 0014](docs/adr/0014-compter-des-passages.md), qui abroge
    [ADR 0009](docs/adr/0009-un-comptage-par-vehicule.md).
11. **Le détecteur de plaques est étranglé, et une ancre rend l'étranglement
    invisible.** Il tournait une inférence 640×640 par piste et par image :
    **823 ms/image mesurées**, soit près de dix minutes pour 30 s de vidéo. Les
    images sautées reçoivent la dernière plaque *mesurée*, reprojetée en
    coordonnées relatives à la boîte du véhicule — les rectangles ne clignotent
    donc pas, ce qui était l'objection d'ADR 0007. Mesuré : **180 → 62 recadrages**
    (2,9×). Deux règles absolues : **l'OCR ne lit jamais une boîte reprojetée**, et
    une reprojection ne nourrit aucun agrégat.
    [ADR 0010](docs/adr/0010-etranglement-du-detecteur-de-plaques.md).
12. **Le plancher de lecture est mesuré, pas supposé — et il y en a _deux_.** Ne
    pas les confondre, c'est ce qui faisait dire à ce fichier « ~64 px » ici et
    « ~150 px » plus bas, les deux étant vrais :
    - **64 px, le seuil de tentative** (`min_width_px`) — en dessous, l'OCR
      n'essaie même pas. Ni 32 (cinq fois trop permissif) ni 150 (qui
      supprimerait toute lecture) ;
    - **~150 px, le seuil de fiabilité** — en dessous, elle essaie et se trompe
      souvent.

    L'échelle de vérité terrain : 8/8 lectures justes à 320 px, **7/8 à 64 px**
    depuis ADR 0029 (4/8 avant), **0/8 à 48 px** — rejouable par
    `scripts/anpr_bench.py --truth-ladder`. Entre 64 et 150 px, l'OCR travaille
    mais son vote est incertain, et c'est précisément là que `PlateTextVote`
    gagne sa place.

    **L'échelle synthétique n'est pas un juge suffisant, et ADR 0029 l'a payé.**
    Elle rend des plaques françaises trop propres : couper CLAHE y gagne quatre
    lectures et en perd sur de vraies vignettes, parce qu'il n'y a là que du bruit
    à amplifier alors qu'il rattrape le contraste d'une vraie prise de vue. Tout
    réglage de contraste ou de prétraitement se tranche sur des vignettes réelles,
    l'échelle ne servant qu'à vérifier qu'on n'a rien cassé au cas latin.

    L'OCR relit une identité seulement si la nouvelle vignette bat la meilleure
    déjà lue en **qualité = largeur × netteté**.
13. **Un échec porte son message et son code.** Une `AppError` fait traverser
    `detail` et `code` jusqu'à l'écran ; tout le reste garde la phrase générique,
    parce qu'un `RuntimeError` porte des chemins serveur. Le modèle est **chargé
    avant** le passage en « en cours », donc un modèle absent échoue sans jamais
    prétendre travailler. `weights_dir` relatif est ancré sur le paquet et non sur
    le CWD. [ADR 0011](docs/adr/0011-un-job-en-echec-dit-ce-qu-il-est.md).
14. **Un véhicule sans plaque publiée dit pourquoi**, parmi cinq raisons qui
    appellent cinq gestes différents, avec la largeur de la meilleure plaque vue.
    Ce n'est pas un confort : l'étranglement et le plancher de lecture rendent le
    silence plus fréquent, et un silence non expliqué se lit comme une panne.
15. **Le détecteur de plaques est un `.pt` sur GPU ; l'OCR reste un `.onnx` sur
    CPU.** Ce n'est pas une incohérence, c'est une mesure : `onnxruntime` n'a pas de
    provider CUDA ici, donc tout ONNX est cloué au CPU — mais PP-OCRv3 rec est un
    modèle CTC qu'Ultralytics ne sait pas charger, et son seul équivalent `.pt`
    imposerait PaddlePaddle (600 Mo, refusé en ADR 0007). Les poids véhicules, eux,
    étaient déjà des `.pt` par nécessité (`track()` a besoin de BoT-SORT + ReID + GMC).

    **Le rapport de coût entre les deux s'est inversé, et la phrase qui vivait ici
    est maintenant fausse.** Elle disait « l'OCR coûte 66 ms par vignette contre 702
    pour l'ancien détecteur, rapport 10,7 à 1 — optimiser l'OCR ne rend rien de
    perceptible ». Deux changements l'ont retournée : ADR 0015 a divisé le détecteur
    par ~15 en le passant sur GPU, et ADR 0029 a porté le lot d'OCR de 3 à 5
    variantes. Mesuré après ADR 0030, par image analysée : **OCR 262 ms (60 %)**,
    suivi des véhicules 90 ms (21 %), détection de plaques 81 ms (19 %). **C'est
    l'OCR qu'il faut optimiser maintenant**, et le seul levier structurel restant est
    de la recouvrir avec le travail GPU — elle est aujourd'hui sérialisée avec lui.

    **Cette conclusion a été vérifiée, et elle ne vaut que pour ce profil-là.** Les
    262 ms viennent d'une mesure où les trois étages sont forcés sur chaque image. Sur
    une vraie vue de circulation, l'OCR pèse **0,3 %** et la détection de plaques
    **73 %** : voir la décision 24 et
    [ADR 0032](docs/adr/0032-l-ocr-n-etait-pas-le-goulot-le-detecteur-de-plaques-l-est.md).
    [ADR 0015](docs/adr/0015-le-detecteur-de-plaques-en-pt.md),
    [ADR 0030](docs/adr/0030-le-detecteur-de-plaques-payait-une-inference-par-vehicule.md).
16. **Un objet suivi est un véhicule, et les sens de ligne portent un nom.** La galerie
    de ré-identification est supprimée : elle relâchait une identité puis la
    ré-attachait, donc le même `#1` réapparaissait au milieu d'une vidéo et faussait le
    comptage. Trois points qui ne se devinent pas :
    - **le numéro publié (`globalId`) n'est pas le `track_id` du tracker.** Il est local
      à la session, parce que `BaseTrack._count` d'Ultralytics est un attribut de
      *classe* : ouvrir la caméra pendant qu'un fichier s'analyse le remet à zéro, et
      l'analyse en cours réémettrait des identifiants déjà utilisés. La panne est
      silencieuse et **fusionne deux véhicules** ;
    - **la suite des numéros a des trous.** Un numéro est émis dès la première image
      d'une piste — sinon la première lecture de plaque n'a pas d'agrégat où voter et
      `first_seen_ms` date de la confirmation — mais seule une piste confirmée entre
      dans `tracked_vehicles` ;
    - **une occlusion plus longue que `track_buffer` (2,5 s) donne un véhicule de
      plus.** C'est la contrepartie assumée d'un numéro qui ne revient jamais en
      arrière, verrouillée par
      `test_un_vehicule_occulte_trop_longtemps_compte_deux_fois`.

    Les noms et rôles de sens (`entry` / `exit`, plus `neutral` pour une ligne tracée
    avant qu'il devienne obligatoire) traversent le domaine **sans qu'aucun compteur
    les lise** : ils sont persistés dans `config_json` et agrégés côté client
    seulement.
    [ADR 0016](docs/adr/0016-compter-les-objets-suivis.md).
17. **L'analyse peut être bridée sur le temps de la scène, et le rattrapage est
    borné.** L'aperçu live *cale* la vidéo du client sur l'image analysée, il ne la
    lit pas : le curseur avance donc de `fps_analyse / fps_vidéo` seconde de scène
    par seconde réelle, soit **1,70× mesuré** sur cette machine. `analysisSpeed`
    borne la cadence — **`1` (temps réel) par défaut depuis ADR 0019**, pour que la
    lecture locale reste à vitesse normale sans réglage à toucher ; `null`
    (« Illimitée ») reste un choix explicite pour qui veut ses chiffres au plus vite.
    `1` rend 0,99× et fait durer l'analyse la durée de la vidéo. C'est une cadence
    **maximale** : `2` rend 1,82× parce que le travail par image approche la période.
    Le piège est dans le cadenceur, pas dans le réglage : **interdire tout
    rattrapage servait 0,82× en annonçant 1×**. Le coût d'une image est irrégulier —
    60 images sur 240 dépassent leur période — et chaque dépassement était perdu
    définitivement. Trois périodes de retard sont donc rattrapables, au-delà on
    renonce (sinon un décrochage produirait la rafale que le bridage corrige). Ni la
    gigue de `sleep` (0,4 ms) ni le coût de l'aperçu resserré n'y étaient pour quoi
    que ce soit — les deux ont été mesurés et écartés.
    **`processing_fps` d'un run bridé mesure le bridage, pas la machine** : l'attente
    n'est pas retranchée, contrairement au temps de pause.
    `maxAnalysisFps` (ADR 0020) est un **second** bridage, indépendant : un plafond
    **absolu** en images par seconde réelle (illimité, 30 ou 60), qui ignore la
    cadence de la source et `frame_stride`. Les deux se composent — c'est la
    période la plus longue des deux qui gagne — et chacun agit même quand
    l'autre vaut `null`. **`30` par défaut depuis ADR 0022** : la cadence vidéo
    la plus courante, qui ne borne rien en pratique sur une source à cette
    cadence ou en dessous.
    [ADR 0017](docs/adr/0017-brider-l-analyse-sur-le-temps-de-la-scene.md), dont
    [ADR 0019](docs/adr/0019-la-lecture-locale-reste-a-vitesse-normale.md) change le
    défaut sans toucher au mécanisme, et qu'
    [ADR 0020](docs/adr/0020-un-plafond-absolu-de-cadence.md) complète d'un second
    axe de bridage, dont
    [ADR 0022](docs/adr/0022-le-plafond-absolu-vaut-30-img-s-par-defaut.md) change
    à son tour le défaut.
18. **L'aperçu porte le registre, à une cadence à part.** Les quatre sections du
    bas de page — Répartition, Statistique, camemberts, Registre — se remplissent
    **pendant** l'analyse et non plus à la fin. Ce n'était pas un choix
    d'ergonomie : `JobPreview` ne portait pas de `vehicles`, et l'écran montrait
    donc des compteurs qui montaient au-dessus d'une page vide. Rien n'est
    reconstruit côté navigateur — ce serait un agrégat parallèle, donc condamné à
    diverger (invariant 3), et ni le vote de classe ni celui de plaque ne se
    refont depuis des images échantillonnées (invariant 4). Trois réserves
    portent le compromis : le registre est republié **dix fois moins souvent** que
    les boîtes parce qu'il grossit avec l'analyse (~350 o/véhicule mesurés) et
    `null` veut dire **« inchangé »**, jamais « aucun véhicule » ; il est
    restreint aux véhicules **ayant franchi**, la population qu'ADR 0023 affiche
    déjà ; et l'aperçu **final** le porte toujours, même réglage coupé, sinon la
    dernière liste serait celle d'un échantillon quelconque. Les exports restent
    masqués jusqu'à la fin.
    [ADR 0026](docs/adr/0026-le-registre-se-remplit-pendant-l-analyse.md).
19. **La limite de débit globale n'inclut plus la lecture d'un job.** « Ouvrir »
    depuis l'historique reconstruit tout le studio — vidéo, géométrie, les quatre
    sections de résultat — et c'était déjà vrai côté code. Testé en conditions
    réelles (navigateur piloté contre le vrai serveur), ce parcours échouait par
    intermittence, **en silence** : une seule réouverture déclenche une vingtaine
    de requêtes en quelques secondes — quinze rien que pour la vidéo, chargée
    **par plages** par le navigateur — et la limite globale (60/minute par
    défaut) les comptait toutes sans exception. Une fois le quota épuisé,
    `EventSource` retente sans jamais alerter (délibéré, voir `useJobProgress`)
    et peut ne plus jamais reprendre le dessus : le studio reste bloqué sur son
    écran d'avant-analyse, sans le moindre message. La limite exempte désormais
    les **lectures** (`GET`) de `/jobs/{id}/…` — configuration, statut,
    résultat, vidéo, flux d'événements — jamais les écritures : déposer,
    annuler, suspendre ou reprendre un job restent comptés, et `POST /jobs`
    garde en plus sa propre règle à 10/minute, la protection que `prompt/06`
    §4 visait réellement (l'écriture sur disque, pas la lecture d'un résultat
    déjà là).
    [ADR 0027](docs/adr/0027-la-limite-de-debit-globale-exempte-la-lecture-d-un-job.md).
20. **Une analyse peut ne porter que sur une fenêtre de la vidéo.** « Lancer
    l'analyse serveur » ouvre désormais une modale — toute la vidéo, à partir de la
    position de lecture, entre deux moments précis, ou annuler — et deux poignées
    glissables dessinent l'intervalle **sur la barre de lecture**. `startMs` /
    `endMs` (ms de temps de scène, `0` / `null` par défaut, fin **exclue**)
    voyagent dans `AnalysisRequest`. Cinq points qui ne se devinent pas :
    - **les horodatages restent absolus** : une analyse lancée à 00:34 date son
      premier franchissement à 00:34. Les décaler à zéro ferait sauter la vidéo
      locale au mauvais endroit pendant toute l'analyse — elle se cale sur le temps
      de scène de l'aperçu — et rendrait deux fenêtres du même clip incomparables ;
    - **la fenêtre est tranchée par `AnalysisService`, pas par l'adaptateur.**
      `EngineSpec.start_ms` n'est qu'un **indice de performance** : le `FakeEngine`
      l'ignore et produit les mêmes chiffres. C'est ce qui évite un troisième
      exemplaire du bug « vert en CI, faux en production » ;
    - **le déplacement, lui, doit vivre dans l'adaptateur.** `LoadImagesAndVideos`
      d'Ultralytics ne sait pas se déplacer, donc `iter_video` a un **second
      chemin** — OpenCV décode après `CAP_PROP_POS_FRAMES`, puis rattrape par
      `grab()` et **vérifie où il est tombé** (le déplacement est approximatif sur
      plusieurs conteneurs, et l'accepter sans vérifier donnerait des horodatages
      faux sans lever). Il y a donc **trois** `model.track()` dans ce module, ce que
      `test_engine_arguments.py` compte exprès ;
    - **une fenêtre vide est refusée, pas rendue en compteurs à zéro** : le schéma
      refuse une fin qui ne suit pas le début, et `run_video` refuse — après avoir
      sondé la vidéo — une fenêtre hors du fichier (`empty_analysis_range`) ;
    - **l'intervalle n'est pas persisté** et vit dans `entities/analysis-range` : il
      décrit *cette* vidéo, donc `resetForNewSource` le remet à neuf comme la
      géométrie. Le direct n'en a rien (un flux n'a ni début ni fin), et
      `launchSignature` ne le compare pas — un résultat reste juste pour sa fenêtre,
      qui est **rappelée sous le bouton de lancement**.

    [ADR 0028](docs/adr/0028-analyser-une-fenetre-de-la-video.md).
21. **La plaque perdait son premier caractère, pour trois raisons distinctes.** Le
    registre affichait `606L` pour une plaque `苏A·R606L`, **à 81 % de confiance** —
    un texte tronqué présenté comme lu, ce qui est pire qu'un refus. Les trois
    causes, et l'ordre d'importance n'est pas celui qu'on devine :
    - **le vote était affamé.** `plate_ocr_quality_improvement` valait `1.25`, donc
      une plaque n'était relue que si la vignette battait la meilleure de 25 % en
      largeur × netteté : deux ou trois lectures sur la vie d'un véhicule, réparties
      sur quatre graphies voisines, donc aucune ne pouvait dominer. **C'est le seul
      changement nécessaire et suffisant** sur le cas mesuré : à `1.0`, le serveur
      publie `AR606L`. Son raisonnement d'origine était déjà couvert par
      `plate_ocr_skip_iou`, et il ne coûte rien — un vote qui converge déclenche
      `stop_when_confident`, qui arrête le *détecteur*, le vrai goulot ;
    - **un caractère hors alphabet mange son voisin.** `en_PP-OCRv3_rec` ne connaît
      que l'ASCII imprimable ; l'idéogramme de province d'une plaque chinoise n'a
      aucune classe où aller, et le CTC doit bien émettre quelque chose pour ces pas
      de temps. `LEFT_INSET_FRACTIONS = (0.14, 0.22)` ajoute deux variantes rognées
      à gauche, dans le **même** lot. Vignettes justes 8 → 17 sur 40, et l'échelle
      latine — le contrôle indépendant, sans idéogramme — 39 → 43 sur 56, dont
      **4/8 → 7/8 au palier 64 px**. L'ajout est strictement additif : sur une plaque
      latine la variante coupe un vrai caractère, rend une chaîne plus courte, et la
      confiance cumulée la fait perdre ;
    - **une lecture partielle concurrençait la complète, et gagnait.** `R606L` n'est
      pas une rivale d'`AR606L`, c'en est un morceau — mais elle est lue **plus
      souvent**, parce qu'elle sort de tous les prétraitements. `_consolidated`
      reverse la confiance d'un sous-texte contigu à son sur-texte. Deux gardes, et
      la seconde est celle qui empêche l'inverse du bug : un sur-texte ne reçoit rien
      tant qu'il n'a pas ses propres `MIN_AGREEING_READS` (sinon `TA96886`, où le `T`
      est l'idéogramme mal lu, aspirerait les voix d'`A96886`), et la domination ne se
      joue que contre de **vrais** rivaux. Sans relation de sous-texte, c'est
      exactement l'ancien code, ce qui est verrouillé par un test.

    **Quatre pistes plausibles ont été mesurées et rejetées** — élargir le recadrage
    (la hauteur d'entrée étant fixe à 48 px, élargir *rétrécit* les glyphes : 8 → 0
    sur 40), un consensus spatial des caractères, trois réglages « gratuits », et un
    filtre d'attachement contre les fausses détections sur l'habillage vidéo. Ne pas
    les re-proposer sans lire l'ADR : chacune a sa mesure.
    [ADR 0029](docs/adr/0029-la-plaque-perdait-son-premier-caractere.md).
22. **Le détecteur de plaques paie une inférence par image, plus une par véhicule.**
    `detect_many` découpait le travail en paquets de `side²` recadrages — le côté de
    la mosaïque d'ADR 0008 — et le défaut `side = 1` faisait donc *un paquet par
    véhicule*, c'est-à-dire un `predict` par piste. La docstring du module annonçait
    pourtant le bon comportement depuis ADR 0015. Rien ne levait, aucun chiffre publié
    ne changeait : seule la cadence était deux fois trop basse. Mesuré à 3,7 véhicules
    par image : **217 → 107 ms par image sur l'étage**, et **5,84 → 10,63 img/s de
    bout en bout** avec ANPR et OCR actives, à comptages et plaques identiques.
    Quatre points qui ne se devinent pas :
    - **le lot est une dimension de tenseur, pas de pixels.** Chaque recadrage garde
      son letterbox 640×640, donc rien n'est troqué contre du rappel — contrairement
      à la mosaïque, qui rétrécit les plaques dans l'entrée du réseau (côté 2 : 3,4×
      pour −16 %). La mosaïque reste intacte pour les machines sans GPU ;
    - **les boîtes ne sont pas identiques au bit près** : sur 240 véhicules, aucune
      plaque gagnée ni perdue, mais une IoU de 0,943 au minimum. L'ancien chemin
      passait par un redimensionnement de mosaïque *avant* le letterbox ; le lot n'a
      plus que le letterbox, donc un rééchantillonnage de moins. Une comparaison au
      pixel près entre deux versions échouera, et c'est attendu ;
    - **grouper l'OCR de la même façon est 1,6× plus LENT** (380 contre 232 ms) :
      `batch_width` aligne tout le lot sur la vignette la plus large. Un appel par
      piste est la bonne forme, il ne faut pas la « corriger » ;
    - **un test compte les appels à `predict`**, parce qu'une régression rendrait
      exactement les mêmes boîtes deux fois plus lentement.

    [ADR 0030](docs/adr/0030-le-detecteur-de-plaques-payait-une-inference-par-vehicule.md).
23. **La résolution ne coûtait qu'une chose : le décodage, et il attendait le GPU.**
    Mesuré sur une même scène réencodée à quatre paliers, `yolov8n`, sans ANPR :
    l'inférence vaut **8,00 ms à toutes les résolutions** — l'entrée du réseau vaut
    640 quoi qu'il arrive — le prétraitement 2,3 à 3,0 ms, et tout le reste est du
    décodage : 3,2 ms en 720p, 21,7 en 4K, soit 58 % du budget. Le décodage étant du
    travail CPU pendant que la carte attend, il vit désormais dans un **fil séparé**
    qui rend des lots d'images consécutives : **1080p 47 → 58 img/s, 1440p 35 → 59,
    2160p 27 → 40**, à comptage identique, et la cadence est devenue *plate* de 720p
    à 1440p. Quatre points qui ne se devinent pas :
    - **il n'y a plus qu'un chemin de lecture.** Le chemin « avec borne de début »
      existait parce que le chargeur d'Ultralytics ne sait pas se déplacer ; depuis
      que le différé décode lui-même, le déplacement n'est plus un cas particulier —
      et il gagne le lot d'images qu'il n'avait pas ;
    - **le fil doit mourir avec le générateur**, et le producteur ne doit jamais
      bloquer indéfiniment sur une file pleine : une fenêtre d'analyse qui atteint sa
      borne ou une annulation laisserait sinon un fil vivant sur un décodeur ouvert.
      Mesuré : une annulation rend la main en **0,30 s** ;
    - **l'accélération matérielle d'OpenCV est acceptée et 2,3× plus lente** (13,70
      contre 5,87 ms sur du H.264 1080p réel) : la surface décodée doit revenir de la
      mémoire graphique. Ne pas la « réactiver » ;
    - **la résolution n'achète rien au détecteur de véhicules et tout aux plaques.**
      Sur la scène mesurée, l'OCR ne se déclenche **jamais** en 720p (plaques sous le
      plancher de 64 px) et publie une plaque en 4K — où l'étage de plaques coûte
      même *moins* cher, un vote acquis arrêtant le détecteur.

    [ADR 0031](docs/adr/0031-le-decodage-payait-la-resolution-sur-le-chemin-critique.md).
24. **L'OCR n'est pas le goulot ; le détecteur de plaques l'est.** ADR 0030 annonçait
    l'inverse — OCR 262 ms, 60 % du budget — sur un profil où les trois étages sont
    forcés sur chaque image. Mesuré sur une **vue de circulation réelle** (1080p, 6 à
    14 véhicules par image, ANPR et OCR actives) : détection de plaques **76 ms, 73 %**,
    OCR **0,4 ms, 0,3 %**. Trois choses en découlent, et aucune ne se devine :
    - **le coût est linéaire en recadrages** — 21,5 ms pour un, 139,7 pour huit :
      chaque véhicule paie une inférence entière, l'équivalent d'une image complète.
      Le lot d'ADR 0030 amortit le coût d'appel, jamais le calcul ;
    - **descendre le côté d'entrée du détecteur ne marche pas.** `TRAFFIC_PLATE_NET_SIZE`
      existe et **reste à 640** : sur 60 images, 640 → 448 → 320 donne 94 → 22 → **0**
      plaques localisées pour 96 → 56 → 34 ms. Le rappel s'effondre bien plus vite que
      le coût ne baisse ;
    - **`TRAFFIC_PLATE_DETECT_MAX_PER_FRAME` borne le coût, et n'est pas monotone** :
      `2` rend 1,27× à 1,51× à comptage identique, `1` ne rend rien. Le coût par appel
      dans le pipeline (~99 ms pour un recadrage) vaut cinq fois celui mesuré hors
      pipeline (21,5 ms) : quelque chose domine que le nombre de recadrages n'explique
      pas, et c'est le prochain sujet de mesure.

    **Et surtout** : sur une vue de circulation 1080p, les plaques font moins de 48 px
    et le plancher de lecture est à 64 (invariant 12) — **aucune plaque ne peut être
    publiée**, donc l'ANPR y dépense 73 % du budget pour rien. Le service le dit déjà
    (`plate_unread_reason = too_small`, décision 14). Les deux gestes qui règlent cela
    sont de resserrer le plan ou de filmer plus défini, pas de régler quoi que ce soit.
    [ADR 0032](docs/adr/0032-l-ocr-n-etait-pas-le-goulot-le-detecteur-de-plaques-l-est.md).

## Les vitesses en km/h : la calibration est **par ligne**

`to_kmh` n'invente jamais une distance : sans échelle, le registre reste en px/s.
Mais une échelle **unique pour toute l'image ne peut pas être juste** — une caméra
de trafic regarde en biais, donc un mètre vaut quelques pixels au fond et quelques
dizaines devant. Mesuré sur une vidéo du dépôt, à largeur supposée égale sur les
quatre lignes : **37 à 143 px/m, un facteur 3,9**.

Chaque ligne porte donc `lengthMeters` (`length_m` au domaine), sa longueur réelle
— une largeur de chaussée, un passage piéton. `domain/scale_field.py` en tire
l'échelle **locale** et retient la **ligne calibrée la plus proche** (distance au
*segment*, pas à sa droite). Pas d'interpolation entre deux lignes : elle
inventerait une échelle que personne n'a mesurée.

La conversion se fait **déplacement par déplacement**, à l'échelle du milieu de
chaque segment ; les mètres sont cumulés à part des pixels. Convertir le total à
la fin annulerait la calibration locale pour un véhicule qui change de profondeur.

Trois points à ne pas confondre :

- **c'est purement additif** — sans ligne calibrée, `ScaleField` retombe sur le
  curseur global et l'estimateur se comporte exactement comme avant ;
- **la mesure locale l'emporte sur le curseur global**, jamais l'inverse ;
- **`lengthMeters` est le seul champ de ligne que le serveur interprète.** Un rôle
  ou un nom se corrige sans réanalyser ; **une longueur, non.**

[ADR 0025](docs/adr/0025-la-calibration-se-fait-par-ligne.md).

## Mesurer avant d'optimiser l'ANPR

`backend/scripts/anpr_bench.py` est le banc. Il existe parce qu'aucun chiffre des
ADR 0007 et 0008 n'était rejouable — tous produits hors dépôt, à la main — et
qu'ADR 0008 a déjà démontré une fois que l'intuition se trompe ici.

```bash
cd backend
# Rejouable sans aucune vidéo, donc en CI. Valide le banc lui-même.
uv run python scripts/anpr_bench.py --synthetic --truth-ladder --json out/ladder.json
# Sur de vraies vidéos, avant / après.
uv run python scripts/anpr_bench.py --videos D:/TesteIA/Video --frames 40 \
    --ocr --json out/apres.json --compare out/avant.json
```

Le couple `textsDecoded` / `textsPublished` est le chiffre qui explique tout : un
`118 / 0` dit que la chaîne lit du bruit et le **refuse**. Ce n'est pas une panne.

## Mesurer avant d'optimiser la cadence

`backend/scripts/pipeline_bench.py` est l'autre banc : il chiffre ce qui tourne à
**chaque** image — décodage, prétraitement, inférence, NMS, suivi, détection de
plaques, OCR, domaine, sérialisation — là où `anpr_bench.py` mesure la *justesse*
de la lecture.

```bash
cd backend
# Ce que la résolution coûte, à contenu identique : la même scène réencodée aux
# quatre paliers, comptages comparables d'un palier à l'autre.
uv run python scripts/pipeline_bench.py --videos data/jobs/<id> \
    --ladder 720,1080,1440,2160 --frames 200 --json out/echelle.json
# Avec l'ANPR et l'OCR, c'est-à-dire les deux tiers du budget réel.
uv run python scripts/pipeline_bench.py --videos data/jobs/<id> --anpr --ocr \
    --frames 400 --warmup 20 --start 12 --json out/anpr.json --compare out/avant.json
```

Quatre choses à savoir avant de lire un rapport :

- **`--anpr` fait tourner la vraie `AnalysisService`**, assemblée par le même
  `build_counting_stack` que le service. Sans le drapeau, le banc ne mesure que le
  comptage — et l'ANPR pèse 60 à 80 % du budget quand elle est active ;
- **le bloc `work` explique tout écart de coût** : il compte les recadrages soumis
  au détecteur de plaques et les vignettes soumises à l'OCR **par image**. Trois
  fois plus cher en 4K peut venir de l'étage ou du nombre de vignettes, et les deux
  appellent le contraire l'un de l'autre ;
- **une course sans véhicule ne mesure ni l'ANPR ni l'OCR** : les premières
  secondes d'un clip sont souvent vides, d'où `--start` ;
- **le cache de l'échelle est indexé par nom, hauteur et instant de départ, pas par
  nombre d'images** : augmenter `--frames` sur une échelle déjà générée mesure
  l'ancien palier, plus court. Le codec rendu vaut alors `cache` — le rapport
  n'affirme jamais un réencodage qui n'a pas eu lieu.

`backend/scripts/build_fixtures.py` régénère les fixtures du contrat. **Toujours
les régénérer, jamais les corriger à la main** : une fixture éditée pour faire
passer `tsc` affirme ce que le frontend espère au lieu de ce que le backend
produit, ce qui retire la seule propriété qu'on lui demandait.

## « Cette voiture est passée et elle n'est pas comptée »

C'est la réclamation la plus fréquente et la plus difficile à trancher : elle est
irréfutable et invérifiable à la fois. Elle se règle en deux gestes, jamais en
modifiant le compteur.

**1. `scripts/audit_lignes.py`.** Il rejoue la géométrie *seule* sur la timeline
persistée d'un job — sans le compteur, dont il réimplémente exprès les primitives —
puis confronte les deux. Un franchissement présent dans la trajectoire et absent des
totaux est un bug du compteur, et le script le nomme ; le code de sortie vaut alors
`1`.

```bash
uv run python scripts/audit_lignes.py                    # le dernier job terminé
uv run python scripts/audit_lignes.py <job_id> --json out/audit.json
```

**2. Les quasi-franchissements**, `diagnostics.nearMisses`, par ligne, publiés dans
les stats et affichés **dans le tiroir « Comptage »**, sous le diagnostic. Ils ont
passé quelques jours invisibles : ils vivaient sur les cartes de ligne du tableau de
bord, que la refonte du bas de page a remplacées par des rangées compactes, et rien
ne les avait repris. Une piste qui s'éteint à
moins d'une **demi-boîte** d'un trait sans jamais le franchir. Le seuil est relatif à
la boîte du véhicule et non en pixels, pour qu'il veuille dire la même chose en 720p
et en 4K, et les pistes **encore vivantes** en sont exclues — approcher n'est pas
manquer, et un chiffre qui clignote pendant l'aperçu ne se lit pas.

Ce que ce diagnostic sépare, et que rien ne séparait avant : une ligne à `0` parce
que personne ne passe, et une ligne à `0` parce qu'elle est posée là où le suivi
s'arrête. Les deux affichaient le même chiffre et appellent des gestes opposés.

Mesuré sur `video_7.mp4`, quatre lignes, `yolov8n` : **10 franchissements comptés,
10 franchissements géométriques, zéro refus** — et **7 quasi-franchissements**, dont
trois sur une ligne tracée à 60 px du bord droit d'une image de 1280, où les pistes
mouraient à ~33 px du trait. Le comptage était juste ; le tracé ne l'était pas.

**Un quasi-franchissement ne s'ajoute à aucun total** et n'affirme pas qu'un
véhicule est passé : le véhicule a pu faire demi-tour ou stationner. Il dit que le
tracé et le suivi se sont manqués de peu.

**3. Les deux compteurs de score, vivants depuis le 2026-08-17.**
`highDetections` et `rescuedByLowScore` valaient `0` sur **toutes** les analyses
jamais produites : le domaine annonçait en commentaire que l'adaptateur les
renseignerait « s'il peut les observer », et l'adaptateur ne l'a jamais fait. Le
panneau affichait donc deux zéros immuables — et surtout son alerte « aucune
détection, à aucun seuil », qui se déclenchait à chaque analyse et envoyait chercher
le défaut dans la vidéo alors que le comptage marchait.

Ils sont comptés dans `AnalysisSession._count_scores`, en **observations suivies** et
non en images, de part et d'autre de `confidence_threshold` — que `SessionConfig`
transporte désormais *pour le diagnostic seul*, le comptage ne le lisant jamais
(le tracker l'a déjà appliqué, ADR 0024). `rescuedByLowScore` mesure donc la bande
basse de BoT-SORT en train de travailler : mesuré sur `video_7.mp4`, **11 263
observations au-dessus du seuil pour 3 972 en dessous**, soit un quart des
observations qui prolongent une piste sans jamais en ouvrir une.

`lowDetections` est **supprimé** du domaine et du contrat, pas laissé à zéro : après
le suivi, une détection non associée n'existe plus — Ultralytics ne rend que les
boîtes porteuses d'un identifiant — donc ce chiffre prétendait mesurer
l'inobservable. Un compteur affiché qui ne peut pas bouger se lit comme « aucune
détection faible », l'inverse de la vérité.

## « Ce véhicule est compté deux fois »

L'autre moitié de la réclamation, et elle a une cause **distincte** : le côté d'une
piste était tranché par le seul signe d'un produit vectoriel, donc un centroïde à un
dixième de pixel du trait avait un côté parfaitement défini. Un véhicule arrêté sur
une ligne produisait **trois** passages en 0,14 s, aux distances +0,1 / −0,1 /
+0,2 px ; un véhicule dont la boîte s'effondre puis se rétablit en produisait trois
autres.

Depuis le 2026-08-14, une **bande morte** d'un quart de demi-boîte entoure chaque
trait : le côté n'y est pas tranché, exactement comme pour un centroïde tombant pile
sur la ligne. Trois points qui ne se devinent pas :

- **ce n'est pas un garde d'identité.** La bande ne regarde ni le numéro du
  véhicule, ni les autres lignes, ni ce qui a déjà été compté. ADR 0016 reste
  entier : un aller-retour franc compte 2, deux lignes franchies comptent 2 ;
- **le segment testé enjambe la bande** (`settled_centroid`). Une bande morte naïve
  *perd* les franchissements lents — à la sortie de bande, l'image précédente est du
  même côté que la piste, donc le segment ne coupe rien. Ce mode de panne est pire
  que les doublons qu'on corrige, et il est verrouillé par
  `test_un_vehicule_qui_traverse_la_bande_compte_une_fois` ;
- **`0.25` a été fixé par les deux bornes**, pas choisi : le bruit mesuré plafonne à
  0,10 demi-boîte, et à `0.5` un poids lourd de 400 px obtenait une bande de 100 px
  qui avalait le trajet du test de non-régression cabine/remorque.

Le contrôle qui vaut la mesure : `yolo11s` et `yolo11m`, deux détecteurs différents,
publient désormais **les mêmes 14 passages** sur `video_7.mp4`, aux mêmes secondes.
Avant la bande, ils différaient de quatre.
[ADR 0018](docs/adr/0018-une-bande-morte-autour-du-trait.md).

**L'horodatage d'un passage est celui de la sortie de bande**, pas du contact avec le
trait : mesuré jusqu'à **2,2 s** de retard pour un gros véhicule abordant une ligne
presque parallèlement. Le comptage est juste, sa date est tardive.

**La bande avait un angle mort, corrigé le 2026-08-17** ([ADR
0023](docs/adr/0023-un-vehicule-compte-est-un-vehicule-qui-franchit.md)) : une piste
qui **naît dans la bande** n'a pas de côté tranché, et son premier côté tranché
servait d'*amorçage* — le franchissement était perdu, en silence. Le compteur retient
désormais la dernière position d'avant-amorçage et son côté **brut** ; si la piste se
range du côté opposé, le franchissement est compté, sous les deux mêmes conditions
géométriques qu'un franchissement ordinaire. Cela concerne tout véhicule entrant dans
le champ près du trait, et toute piste recréée après une occlusion à cet endroit —
donc **le cas dominant en trafic dense**.

**Le mécanisme BYTE du tracker était débranché**, et c'est la troisième cause de
franchissement perdu ([ADR
0024](docs/adr/0024-le-detecteur-descend-sous-le-seuil-de-l-utilisateur.md)).
BoT-SORT range les détections en deux bandes : la **haute** associe et crée des
pistes, la **basse** (`track_low_thresh` → `track_high_thresh`) sert *uniquement*
à prolonger une piste dont la confiance plonge. Or Ultralytics filtre **avant** le
tracker, et le projet lui passait `conf = confidence_threshold` (0,35) : rien ne
tombait jamais dans la bande 0,10–0,25, et la seconde association était du code
mort. Une confiance qui plonge une image coupait la piste → identifiant neuf →
ré-amorçage du compteur → franchissement perdu, **et** véhicule compté deux fois.

Désormais le détecteur reçoit `track_low_thresh`, et le seuil de l'utilisateur
part dans le fichier de suivi dérivé sur `track_high_thresh` **et**
`new_track_thresh`. Cette seconde clé est ce qui rend le changement **strictement
additif** : une détection faible prolonge une piste, elle n'en ouvre jamais.
Mesuré sur vidéo réelle : **+21 % d'observations suivies, pistes distinctes
inchangées, franchissements 61 → 61, objets suivis 92 → 83** (−9 pistes
fragmentées). `confidence_threshold` ne filtre donc plus le détecteur : il décide
ce qui *devient* une piste.

Conséquence sur le diagnostic de comptage (panneau « Détection ») : `low_detections`
prétendait mesurer des détections jetées *avant* le suivi — une quantité qu'aucun
adaptateur n'a jamais su observer, si bien que ce champ valait `0` sur **toutes**
les analyses jamais produites et déclenchait l'alerte « aucune détection, à aucun
seuil » à chaque fois. Il est supprimé, remplacé par `rescued_by_low_score` compté
sur les **observations suivies** (`Diagnostics`, `AnalysisSession._count_scores`) :
un chiffre élevé n'y signale plus une perte, c'est le mécanisme ci-dessus qui
travaille.

**Et un identifiant de piste recyclé fabriquait des fantômes.** `_LineState` est clé
par `(track_id, global_id, ligne)` et **pas** par `(track_id, ligne)` : Ultralytics
recycle ses identifiants, et l'ancienne clé rendait au nouveau véhicule le côté et la
dernière position de son prédécesseur — le segment testé reliait le dernier point de A
au premier point de B, traversait le trait, et comptait un passage que personne
n'avait fait. Une réactivation courte garde le même `global_id`, donc la même mémoire :
le piège 11 de `prompt/13` reste couvert.

## Pièges d'environnement de cette machine

- `uv` a été installé par winget et vit dans
  `%LOCALAPPDATA%\Microsoft\WinGet\Packages\astral-sh.uv_*\`. **Il n'est pas sur le
  `PATH` du shell Bash ni de PowerShell** : les hooks pre-commit qui appellent
  `uv run` échouent alors avec « Executable `uv` not found ». Ajouter ce dossier au
  `PATH` avant de committer.
- Le Python du système est un **3.14** : il ne peut pas faire tourner ce backend.
  Toujours passer par `uv run`.
- **Jamais de commentaire en fin de ligne après une valeur vide dans un `.env`.**
  `TRAFFIC_PLATE_MODEL_PATH=  # vide = …` donne au réglage la valeur
  `« # vide = … »` : le service cherche alors son modèle de plaques à ce chemin,
  ne le trouve pas, et l'ANPR reste indisponible **sans qu'aucun message ne
  mentionne la cause**. Ce piège a tenu l'ANPR hors service pendant tout le
  projet, avec le bon fichier au bon endroit. Le commentaire va au-dessus de la
  clé ; `Settings._blank_means_unset` neutralise en plus les `.env` déjà écrits.
- Le modèle de plaques vit dans **`backend/.weights/license-plate.pt`**, récupéré
  par `scripts/fetch_plate_model.py` depuis l'URL documentée dans `.env.example`.
  Un `.pt` et non un `.onnx` : `onnxruntime` n'a **pas de provider CUDA** ici
  (vérifié : `['AzureExecutionProvider', 'CPUExecutionProvider']`), donc un ONNX
  reste sur le CPU quel que soit le GPU. Mesuré, même modèle, même image : 45,2 ms
  sur GPU contre 183,9 ms sur CPU
  ([ADR 0015](docs/adr/0015-le-detecteur-de-plaques-en-pt.md)).
- **Le suffixe du fichier de plaques fait partie du contrat.** Ultralytics choisit
  son backend d'après le *nom*, jamais d'après le contenu. Un `.pt` déposé sous un
  nom en `.onnx` rend `plateAvailable: true` puis ne détecte **jamais rien** —
  quatrième exemplaire de la panne silencieuse de cette section. Le script de
  récupération refuse désormais ce désaccord avant d'écrire.
- **`plateAvailable` ne dit que « le fichier est là ».** `plateLoadable` dit « il se
  charge » : un auto-test au démarrage (une inférence à vide, accroché au `warmup`,
  donc désactivé par `TRAFFIC_WARMUP=false`). `plateAvailable: true` +
  `plateLoadable: false` est **l'état à surveiller** — poids présents, ANPR muette,
  tout vert par ailleurs. `null` = pas encore testé, ce n'est pas un échec.
- **`weights_dir` relatif est ancré sur `backend/`, plus sur le répertoire de
  lancement.** Avant ce correctif, lancer `uvicorn` depuis la racine du dépôt
  faisait paraître *tous* les poids absents et rendait l'ANPR indisponible sans
  qu'aucun message ne le dise — même famille que le piège du `.env` ci-dessus. Le
  chemin résolu est journalisé au démarrage et exposé dans `/health`
  (`weightsDir`) : en cas de doute, le regarder avant de chercher ailleurs. Un
  chemin **enraciné** (`/opt/poids`, `C:\poids`) traverse inchangé.
- **La contrainte `1×3×640×640` n'existe plus** — elle était celle de l'ancien
  export ONNX, dont la grille d'ancres était gravée dans le graphe (vérifié par
  chirurgie de graphe : toute autre forme faisait échouer le `Reshape` du DFL).
  C'était la raison d'être de la mosaïque comme seul levier de débit d'ADR 0008. En
  `.pt`, lot et résolution sont libres. `NET_SIZE` reste néanmoins à **640**, qui est
  la résolution d'entraînement du modèle, et la mosaïque reste **désactivée par
  défaut** : son arbitrage rappel/vitesse garde sa valeur sans GPU, et ne se change
  pas en silence.
- **L'OCR a un plancher de fiabilité, mesuré : ~150 px de large.** En dessous elle
  décroche (80 px → 3/8, 48 px → 0/8) ; en dessous de 64 px elle n'essaie même pas
  (invariant 12). Sur des plaques de 27 à 88 px, elle ne lira quasiment rien, quel
  que soit le prétraitement. Elle se tait au lieu d'inventer, ce qui est voulu — mais
  ne pas conclure à une panne. **ADR 0015 accélère la détection, pas la lecture** :
  ne pas lire ce gain de vitesse comme un gain de justesse.
- L'OCR demande **deux** fichiers dans `backend/.weights/` :
  `license-plate-ocr.onnx` (`en_PP-OCRv3_rec`, 97 classes) et
  `license-plate-ocr.charset.txt` (`en_dict.txt`, 95 lignes), récupérés ensemble par
  `scripts/fetch_plate_ocr_model.py`. `plateOcrAvailable` est faux si l'un des deux
  manque, et c'est délibéré : le dictionnaire **fait partie du contrat du modèle** —
  l'indice 37 signifie ce que le dictionnaire d'entraînement disait. Un dictionnaire
  d'une autre taille ne lève rien, il rend des plaques fausses et plausibles ;
  l'adaptateur refuse donc de charger si les tailles ne correspondent pas.
- **`en_dict.txt` contient une ligne dont le seul contenu est un espace.** C'est un
  caractère de l'alphabet, pas un blanc de mise en forme : un `line.strip()` qui
  l'écarte décale tout ce qui suit de deux crans. Ce bug a traversé 1 030 tests verts
  et n'a été trouvé qu'en installant les vrais poids — troisième cas où une doublure
  ne pouvait pas voir. 95 lignes + espace de `use_space_char` + blanc CTC = 97.
  Voir [ADR 0007](docs/adr/0007-lecture-du-texte-de-plaque.md), « Effet de bord ».
- **Un GPU depuis le 2026-08-12 : Quadro P1000 (Pascal, `sm_61`, 4 Go).** Trois
  conséquences qui ne se devinent pas :
  - **la roue torch doit être cu126**, épinglée par marqueur `win32` dans
    `pyproject.toml`. C'est la dernière ligne qui embarque `sm_61` : CUDA 13 a
    supprimé Pascal, et le pilote annonce pourtant CUDA 13.0, donc une détection
    automatique choisit une roue qui s'installe, répond `is_available() == True`,
    puis échoue à la première inférence ;
  - **`half` reste faux sur cette carte**, et le code le décide seul depuis
    ADR 0012 (capability < 7.0). Avant Volta le fp16 est *plus lent* que le fp32 :
    38,9 ms → 48,9 ms mesurées. Ne pas « réactiver » `TRAFFIC_HALF` en croyant
    optimiser ;
  - **les mesures de benchmark antérieures au 2026-08-12 sont des mesures CPU**,
    et les chiffres des ADR 0007, 0008 et 0010 n'ont pas été rejoués sur GPU.
    Les comparer à une mesure GPU sans le dire serait trompeur — c'est pourquoi un
    run persisté porte son `device`.

  Repère : `yolov8n` sur une image 1280×720 coûte 147,8 ms sur CPU et 38,9 ms sur
  ce GPU. Le conteneur, lui, n'a toujours pas de GPU.
  [ADR 0012](docs/adr/0012-torch-cuda-sur-windows.md).
- Le frontend est passé de pnpm à **bun** ; `bun.lock` est le lockfile committé.
  La version est épinglée en **trois** endroits qui doivent rester d'accord :
  `frontend/package.json` (`packageManager`), l'image `oven/bun` des deux
  Dockerfiles, et `bun-version` dans la CI.
- L'alias `@/*` est déclaré dans **trois** fichiers : `frontend/tsconfig.json` (le
  seul que `bun test` lit), `tsconfig.app.json` (pour `tsc -b`) et
  `vite.config.ts`.
- La roue `ultralytics` embarque son propre paquet `tests` : les helpers vivent
  dans `backend/tests/support/`, importés en `from tests.support.engine import …`,
  et `conftest.py` ne contient que des fixtures.
- Le hook `mixed-line-ending` **corrige** les fins de ligne au premier passage et
  fait donc échouer le premier `git commit` : ré-ajouter et recommitter.
- Le disque `C:` de cette machine est régulièrement **plein**, ce qui fait échouer
  les builds Docker avec une erreur d'entrée/sortie de BuildKit qui ne mentionne
  jamais l'espace disque. Vérifier `df -h` avant de conclure à un défaut du
  `Dockerfile`.

## Tests

| | Backend | Frontend |
|---|---|---|
| Nombre | 1526 (1 skip) | 628 |
| Lanceur | pytest, `asyncio_mode = "auto"` | `bun test` (**pas** vitest) |
| Isolation | base SQLite sous `tmp_path`, moteur factice | — |

`filterwarnings = ["error", …]` : un avertissement fait échouer la suite.

**Ne jamais borner l'attente d'un test par un nombre d'itérations.** Des tests de
benchmark passaient nus et échouaient sous `--cov` pour cette raison : un test dont
le verdict dépend de la vitesse de la machine ne prouve rien. Attendre la tâche
réelle (`await service.wait_for_idle()`), ou une échéance en temps.

## Git

Jamais de travail sur `main`. Une branche par lot, Conventional Commits avec
portée obligatoire, un commit qui compile et passe les tests même en
intermédiaire. Détails dans [CONTRIBUTING.md](CONTRIBUTING.md) et
[`prompt/11`](prompt/11-GIT-ET-CONVENTIONS.md).
