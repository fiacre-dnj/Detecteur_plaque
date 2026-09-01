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
et depuis le 2026-08-16 chacun est **obligatoirement** déclaré ([ADR
0021](docs/adr/0021-le-role-de-sens-devient-obligatoire.md)) — ce rôle donne le bilan
du carrefour et **est** le libellé affiché, il n'y a plus de nom libre à taper.

**Une ligne porte aussi un type depuis le 2026-08-27** ([ADR
0040](docs/adr/0040-une-ligne-porte-un-type.md)) : **quatre** types choisissables
depuis le 2026-08-28 — deux sens, **autorisé · interdit**, infranchissable, ou
comptage seul. Les deux « sens unique » ont fusionné : ils ne différaient que par le
rôle du côté autorisé pour une seule et même règle, et le chiffre de tête ne s'appuie
plus sur le bilan entrées / sorties (ADR 0045). Le côté autorisé reste `entry` — c'est
ce qui garde ces lignes dans les colonnes « Entrée par » du registre — et une paire
héritée `{exit, forbidden}` se relit sous le nouveau type plutôt que de tomber en
« à préciser ».

Le type est **dérivé** de la paire de rôles (`lineKind` / `rolesForKind` dans
`shared/lib/directions.ts`) et n'existe dans aucun champ du contrat — deux sources
pour la même vérité finiraient par se contredire. Les rôles sont donc cinq : `entry`,
`exit`, `forbidden` (« Interdit »), `transit` (« Passage », compté hors bilan) et
`neutral`, hérité et jamais produit par l'éditeur. **« Comptage seul » n'affiche
aucun sens, ni dans le panneau ni sur le trait** : les rangées diraient « Passage »
deux fois sous un bouton d'inversion déjà grisé, et le canevas peignait deux
étiquettes identiques plus une flèche au milieu du trait. Sur cette ligne les deux
côtés portent le même rôle, comptent pareil et s'affichent pareil — la flèche ne
répondait donc à aucune question qu'on puisse encore se poser, et elle en suggérait
une fausse : qu'un sens compterait et pas l'autre. Le **nom** de la ligne reste, il
n'indique pas un sens. `showsDirections` en est le seul juge, lu par le panneau **et**
par `draw.ts` — deux comparaisons `kind === "transit"` recopiées auraient fini par
diverger, et la panne aurait été un panneau muet au-dessus d'un trait bavard.

**Attention à ne pas confondre avec « Infranchissable »**, dont les deux rôles sont
identiques eux aussi : lui garde ses flèches et ses libellés, parce que savoir de quel
côté on n'aurait pas dû passer est toute l'information. `showsDirections` n'est donc
pas `lineHasRule` sous un autre nom, et un test verrouille l'écart.

Une ligne peut en plus être **réservée** à certaines classes (`allowedClassIds`),
indépendamment de son type — une voie de bus à sens unique porte les deux. Le panneau
**nomme les types barrés** (« Interdits : Camion, Bus — leur passage sera signalé »)
plutôt que de décrire la règle en général : c'était la seule façon de la vérifier sans
avoir lancé d'analyse. Piège à connaître : tant que `GET /models/classes` n'a pas
répondu, `lineRules` ne reconnaît aucun identifiant et **toutes** les voies réservées
disparaissent le temps d'une requête — c'est le repli délibéré « mieux vaut ne rien
signaler que tout signaler », pas une panne.

**Un franchissement interdit reste compté** : une infraction est un passage
*qualifié*, pas un passage retiré, et l'invariant 3 en dépend. C'est le client, et
lui seul, qui qualifie — voir « Ce que l'analyse signale » plus bas.

Deux modes partagent **le même** code de comptage — la même `AnalysisSession`, les
mêmes schémas de requête, les mêmes sérialiseurs — et c'est ce qui garantit qu'un
même tracé donne les mêmes chiffres dans les deux :

- **différé** : dépôt d'un fichier, analyse asynchrone suivie en SSE, résultat
  complet relu et rejoué sur la vidéo locale. Le flux SSE porte aussi un
  **aperçu** échantillonné (`event: preview`, ~5 Hz) : la vidéo locale se cale
  sur l'image analysée et le navigateur y dessine les boîtes, les compteurs et
  les franchissements du serveur **pendant** l'analyse
  ([ADR 0006](docs/adr/0006-apercu-live-des-analyses.md)).

  **Les boîtes suivent l'image, les compteurs suivent le serveur** (2026-08-25) —
  et c'est la règle à ne pas « harmoniser ». `useSyncedPreview` ne publie les boîtes
  de l'aperçu *N* qu'une fois l'image *N* **réellement présentée**
  (`requestVideoFrameCallback`, repli `seeked`). Avant, `GeometryCanvas` peignait au
  rendu React qui suit la trame SSE pendant que `currentTime = …` ne fait que
  *demander* une image : l'overlay courait devant la vidéo de tout le temps de
  décodage — « on dirait que le tracker est en avance ». Quatre points :
  - **`shouldSeek` compare désormais l'image AFFICHÉE**, pas la cible *demandée*.
    C'était le défaut de fond : le retard ne pouvait ni se voir ni se rattraper. La
    tolérance de 40 ms n'a pas changé, son opérande si ;
  - **une seule cible en attente, écrasée** — jamais une file, sinon un décodeur
    lent ferait rejouer le retard au lieu de le rattraper ;
  - **les compteurs, le journal et les flashs de ligne restent sur l'aperçu
    vivant.** Une boîte est un *état*, qu'on peut sauter sans rien perdre ; un
    franchissement est un *événement*, et l'aperçu qui le porte est le seul à le
    porter ;
  - **« Écart image »** (5ᵉ chiffre de `TechnicalMetrics`) mesure ce qui restait
    d'écart. Il doit osciller autour de zéro ; s'il **dérive** avec la position dans
    la vidéo, la cause est la cadence déclarée du conteneur (VFR, 29,97, rotation) et
    non le calage. Rien d'autre ne sépare ces deux cas.

  Le flux SSE porte aussi le
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

**Un véhicule reçoit une photo dès qu'il y a quelque chose à montrer de lui** ([ADR
0042](docs/adr/0042-une-capture-par-vehicule.md), élargie le 2026-08-31 par [ADR
0051](docs/adr/0051-une-photo-des-qu-il-y-a-quelque-chose-a-montrer.md)) : deux JPEG —
lui recadré, sa plaque — pris sur la même image, **une seule photo par véhicule**. Ils
vivent dans `data/jobs/<id>/snapshots/`, sont servis par
`GET /jobs/{id}/vehicles/{n}/{snapshot,plate}.jpg`, et **partent avec la vidéo** et
non avec le résultat — ce sont des plaques et des visages.

**Trois causes, une échelle de priorité**, publiées dans `snapshotKind` :
`plate_text` (une plaque a été **lue** sur cette image) > `plate_box` (une plaque y a
été **localisée** sans qu'aucun texte soit publié — trop petite, trop floue, lecture
refusée, OCR éteint) > `appearance` (l'apparence du véhicule vient d'être encodée pour
une recherche par image ; **aucune vignette de plaque** dans ce cas). Un tier plus haut
passe toujours, un tier plus bas jamais ; à tier égal, la règle monotone tranche.
Quatre points qui ne se devinent pas :

- **le rang n'est comparable qu'à l'intérieur de son tier** — une confiance pour
  `plate_text`, des pixels pour les deux autres. Les fondre en un nombre unique ferait
  perdre une plaque lue à 0,95 contre n'importe quelle boîte de 40 px, et le chiffre
  resterait plausible ;
- **les deux tiers en largeur portent une marge** (`TRAFFIC_SNAPSHOT_WIDTH_IMPROVEMENT`,
  1,15), et c'est ADR 0050 qui se rejouerait sans elle : une largeur croît à presque
  chaque image d'un véhicule qui approche, et l'étranglement du détecteur de plaques ne
  divise le problème que par trois. Pas de marge sur `plate_text`, dont le rang ne croît
  pas avec l'approche ;
- **on capture tout véhicule encodé, pas seulement les ressemblants** : le seuil
  exacte/probable vit côté client et se déplace sans réanalyser (ADR 0048/0041), donc une
  photo conditionnée à un seuil serveur manquerait au moment précis où l'on descend le
  curseur pour la regarder. Un véhicule dont `matchScore` est `null` a donc une photo ;
- **le plancher de recadrage de la vignette de plaque est à 8 px, pas 16**, et c'est une
  panne silencieuse déjà payée : `vehicle_crop.MIN_CROP_SIDE_PX` vaut 16 parce que c'est
  le plancher d'une **entrée de réseau**, alors qu'une plaque de vue de circulation fait
  27 à 88 px de large pour **9 à 28 px de haut**. `crop` rendait donc `None`, et le refus
  étant total, la photo du véhicule partait avec elle — mesuré sur une vraie course : 18
  encodages demandés, **zéro capture**, sans qu'une ligne de journal le dise. Aucune
  doublure ne pouvait le voir. `MIN_PLATE_CROP_SIDE_PX` vit dans
  `opencv_snapshot_encoder.py`, et un test l'y verrouille avec les dimensions mesurées ;
- **`snapshotScore` n'est plus le drapeau de présence** — c'est `snapshotMs`, doublé de
  `snapshotKind`. Deux causes sur trois n'ont rien lu ; dans l'autre sens la garantie
  tient par construction (`record_snapshot` *dérive* la confiance de la cause), donc
  non-nul implique `plate_text`. Un lecteur resté sur l'ancien drapeau **manque** les
  deux nouvelles populations, silencieusement. Le seul juge côté client est
  `shared/lib/snapshotKind.ts`, et `snapshotHasPlateFace(undefined)` vaut **`true`** :
  sur un résultat archivé, la lecture était la seule cause possible.

**Ils sont écrits pendant l'analyse depuis le 2026-08-28** ([ADR
0046](docs/adr/0046-les-captures-s-ecrivent-pendant-l-analyse.md)) : la colonne
« Capture » du registre se remplit au fil des lectures, et une alerte de plaque
arrive avec sa preuve. **Rien ne transite par le SSE** — l'objection d'ADR 0042 tient
toujours : seule l'écriture disque avance, par un rappel `on_snapshot` posé là où
l'encodeur vient de rendre les octets, dans le thread worker. L'écriture finale reste
comme filet, le refus `job_not_finished` de la route disparaît, et l'adresse porte
`?v=<snapshotMs>` — sans quoi `immutable` figerait pour un an la première capture d'un
véhicule dont la lecture s'améliore ensuite.

## `prompt/` est la spécification, pas de la documentation

Le dossier [`prompt/`](prompt/) (15 fichiers, à lire dans l'ordre depuis
[`prompt/README.md`](prompt/README.md)) **est** le cahier des charges. Quand il
écrit « obligatoire », « jamais » ou « exactement », c'est une contrainte qui a
coûté un bug dans une version antérieure.
[`prompt/13-PIEGES-CONNUS.md`](prompt/13-PIEGES-CONNUS.md) en tient la liste (68
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
uv run pytest                                                            # 1700 tests
uv run pytest tests/unit/counting/test_line_counter.py -k aller_retour   # un seul
uv run pytest --cov=src --cov-report=term-missing
uv run ruff check . && uv run ruff format --check . && uv run mypy src
uv run alembic upgrade head
uv run alembic revision --autogenerate -m "ajoute la table X"
uv run python scripts/fetch_weights.py --tiers nano,medium,large,xlarge
uv run python scripts/fetch_plate_model.py
uv run python scripts/fetch_plate_ocr_model.py       # modèle OCR + son dictionnaire
uv run python scripts/fetch_reid_model.py            # encodeur de ressemblance (optionnel)
uv run python scripts/audit_lignes.py                # « pourquoi cette ligne est à 0 ? »

# ── Frontend (cd frontend)
bun install
bun run dev                      # proxy /api → 127.0.0.1:8000, WebSocket compris
bun run lint && bun run typecheck && bun test && bun run build           # 882 tests
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
`zone_counter`, `track_numbering`, `tracking_session`, plus tout ce qui décide
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

`frontend/src/` : `app/` (câblage), `features/<capacité>/` (15), `entities/`,
`shared/`. Aucun dossier `components/`, `hooks/` ou `utils/` global.

La quatorzième est **`alerts`** (2026-08-27) : ce que l'analyse *signale*, par
opposition à ce qu'elle compte — infractions au tracé et plaques recherchées. Elle
n'importe aucune autre feature ; les **règles** qu'elle applique vivent dans
`shared/lib/lineRules.ts` et `shared/lib/lineViolations.ts`, et depuis le 2026-08-28
leurs **totaux** dans `shared/lib/violationTally.ts` — le centre de notifications et
le tableau de bord en ont tous deux besoin. Trois lecteurs, un seul juge — la même
raison qui a fait naître `shared/lib/directions.ts`
([ADR 0041](docs/adr/0041-les-alertes-se-calculent-cote-client.md),
[ADR 0044](docs/adr/0044-les-alertes-deviennent-un-centre-de-notifications.md)).

```
app → features → entities → shared
```

Une feature n'importe **jamais** une autre feature. Quand deux en ont besoin, le
câblage passe par `StudioPage` — c'est pourquoi `GeometryPanel` reçoit un
`onOpenPresets` plutôt que la modale elle-même, et pourquoi `SettingsPanels` reçoit
un emplacement `leading` où le studio pose le bouton d'import.

**Les trois pages ne se démontent plus en changeant d'onglet** (2026-08-19). Le
routeur n'a plus qu'une route (`path: "*"` → `AppShell`) et c'est
`app/layout/KeepAlivePages.tsx` qui monte les pages visitées et masque les autres
par l'attribut `hidden`. Un `<Outlet />` les démontait : aller voir l'historique
dix secondes coûtait la vidéo importée, le tracé, l'intervalle, la position de
lecture et le suivi SSE en cours — dont **rien** ne se reconstruit depuis l'URL,
la source étant un `File` local et la géométrie des pixels de cette vidéo-là.
Quatre conséquences à connaître avant d'y toucher :

- **l'appariement URL → page est à nous maintenant**, dans `layout/keepAlive.ts`,
  et il est testé : la comparaison est **exacte**, sinon `/` désignerait les trois
  onglets à la fois et deux pages s'afficheraient l'une sur l'autre ;
- **un garde « une seule fois » indexé sur le montage ne se réarme plus jamais.**
  Les deux effets de `StudioPage` qui lisent `location.state` — « Ouvrir » et
  « Relancer » depuis l'historique — retiennent donc **l'état de navigation
  appliqué** et non un booléen ; sans cela, le deuxième « Ouvrir » ne ferait rien ;
- **une page cachée n'est pas une page inerte** : SSE, session caméra et requêtes
  en vol continuent. C'est le but, mais cela veut dire qu'on ne peut plus compter
  sur le démontage pour arrêter quoi que ce soit ;
- **le défilement est mémorisé par page**, relevé en continu et rendu en
  `useLayoutEffect`. Masquer une page longue raccourcit le document, le navigateur
  recadre `scrollY`, et l'enregistrer au moment de la bascule sauvegarderait la
  valeur déjà tronquée.

#### La coquille : un rail, pas une entête (2026-08-31)

La navigation d'application vit dans un **rail vertical de 56 px, en icônes**
(`AppShell`), et le haut de page appartient à la seule barre du studio, collée à
`top: 0`. Elle a été une entête horizontale de ~76 px, empilée sur la barre de ~64 :
~140 px de chrome avant la première image, sous deux bordures et deux fonds
translucides presque identiques. La hauteur est la ressource rare de cet écran ; la
largeur ne l'est pas, le cadre étant borné à 1600 px
([ADR 0052](docs/adr/0052-la-navigation-passe-dans-un-rail-lateral.md)).

**L'invariant à ne pas franchir : le document défile sur `window`, et la coquille ne
porte AUCUN `overflow`.** Trois mécanismes en dépendent et **aucun ne casse
bruyamment** — `useScrollMemory` enregistrerait `0` pour les trois pages et ne
restituerait plus rien, la barre du studio se calerait sur le mauvais défileur, et le
`100dvh` de la colonne des résultats cesserait de décrire la zone utile. D'où
`sticky top-0 h-dvh` et non `fixed`.

Cinq points qui ne se devinent pas :

- **`--app-header-h` n'est plus mesurée**, elle est déclarée dans `index.css` : `0px`
  en rail, `3.5rem` sous 48rem où le rail se replie en barre horizontale. Les deux
  raisons du `ResizeObserver` sont mortes avec l'entête — plus rien ne s'enroule, et
  le badge serveur ne grandit plus. **Condition de retour** : si le rail replié porte
  un jour du texte de largeur variable, la constante ment et la barre du studio
  disparaît derrière lui, en fenêtre étroite seulement ;
- **`<header>` et non `<aside>`** : le repère `banner` est conservé. Un `<aside>`
  deviendrait `complementary`, et l'application n'en aurait plus du tout ;
- **56 / 40 / 44 px** : le rail est dimensionné par l'anneau de focus (2 px de contour
  à 2 px d'écart autour d'un bouton de 40). À 48 px, il toucherait les bords ;
- **`min-w-0` sur `<main>` est obligatoire**, sans quoi la largeur minimale du canvas
  et du registre pousse le rail hors de l'écran ;
- **le badge serveur perd son texte, pas son sens** : pastille plus `CUDA`/`CPU`
  empilés, et en erreur **le badge et « Réessayer » fusionnent en un seul bouton
  rond**. La phrase « Serveur injoignable » n'est plus lisible à l'œil, seule la teinte
  la porte — mais le studio grise déjà « Lancer l'analyse » et dit la cause là où le
  geste échoue.

#### La disposition du studio, depuis le 2026-08-12 (barre collante, géométrie en tiroir et actions dans le lecteur le 2026-08-19 ; cloche d'alertes le 2026-08-28 ; rail latéral le 2026-08-31)

```
rail  ━━ barre COLLANTE en haut de la fenêtre (sticky, top: --app-header-h = 0) ━━
56 px [⇧ Importer] [▶] ◕39% 330/817 │ [⊙][∑][◉] │ [⬡][🔍][🔔3]   suivis cadence latence écart flux
 ▣                     └─ tiroir flottant du panneau ouvert, 2 colonnes, PAR-DESSUS la page
 ⊡ Studio                     la cloche ouvre le MÊME genre de tiroir : résumé + filtres + flux
 🗂 Historique          TOUTES les pilules sont en ICÔNE SEULE ; le libellé se déplie au
 📊 Benchmark          survol et au focus, en poussant ses voisins (max-width, 150 ms)
 ●CUDA                 SAUF les commandes du job [▶][⏸][✕], qui ne se déplient JAMAIS
 ☀                     [▶] devient [⏸][✕] pendant l'analyse ; l'anneau les SUIT
                       groupes séparés par un filet : source+job │ réglages │ outils
                       sous 1280 px, les chiffres passent dans un 6ᵉ tiroir « État »
┌─────────────────────────────────────┬────────────────────┐
│ nom du fichier ⟨ ⟩ WxH              │ RÉSULTATS ⌾        │  23 rem
│ vidéo + canvas + HUD                │ KPI de tête        │
│ RIEN d'autre par-dessus             │  COLLÉ en haut     │
│ ┌ LECTURE ── mm:ss ────────────────┐│ + KPI interdits    │
│ │ rail de position                 ││ + 4 (5) cartes     │
│ │ INTERVALLE ── →──────────────────││   par type         │
│ │ rail d'intervalle                ││ + 1 carte PAR      │
│ │ ⏵ ⏮ ⏪ ±1i ⏩ ⏭ ↺ Vit.             ││   LIGNE tracée     │
│ │             [LANCER] [Fermer]    ││                    │
│                                      │ AVANT L'ANALYSE    │
│                                      │ le KPI à « — »     │
│                                      │ puis le récapi-    │
│                                      │ tulatif des        │
│                                      │ réglages           │
├─────────────────────────────────────┴────────────────────┤
│ STATISTIQUE — KPI de tête, une rangée par ligne (PAGINÉE   │  les trois sections
│   au-delà de 6), comparatifs groupés en une carte          │  vivent PENDANT
│ [camembert flux/ligne] [camembert véhicules/type]         │  l'analyse et après
│ REGISTRE — par véhicule, 2 filtres, export CSV            │  exports à la fin
│ (FRANCHISSEMENTS — chronologie, MASQUÉE 08-27)            │
└──────────────────────────────────────────────────────────┘

  tiroir de la CLOCHE (36 rem, flottant, ABSENT si aucune règle ni plaque) :
  ┌──────────────────────────────────────────────┐
  │ Alertes ⌾                        « 7 alertes »│
  │ RÉSUMÉ — total interdits (de `stats`, exact)  │
  │   + une rangée PAR NATURE, zéros non rendus   │
  │ FILTRER — Nature / Type de véhicule / Ligne   │
  │   trois axes qui SE COMPOSENT, comptes inclus │
  │ FLUX — vignette + quoi/qui/où/quand,          │
  │   clic = aller à l'instant, borné à 200       │
  └──────────────────────────────────────────────┘
```

**Ce qui a bougé le 2026-08-19, et pourquoi.** Cinq déplacements, tous motivés par
la même observation : le bas de page s'était allongé (trois sections plus la
chronologie), donc tout ce qui vivait « en haut à droite » finissait hors de
l'écran dès qu'on lisait un résultat.

- **la barre est collante** (`sticky`, décalée de `--app-header-h` ; `-mx-6 px-6`
  pour peindre son fond jusqu'aux gouttières). Sans le fond opaque, la vidéo défile
  visiblement sous les pilules. Cette hauteur a été **mesurée** par un
  `ResizeObserver` tant qu'une entête horizontale la portait — elle s'enroulait en
  fenêtre étroite, et le badge serveur grandissait d'un message d'erreur. Depuis le
  rail (2026-08-31) elle vaut **zéro** et n'est plus qu'une déclaration CSS : la barre
  est le premier élément de la page ;
- **« Géométrie » est le quatrième tiroir**, plus un panneau permanent de la
  colonne. `SettingsPanels` l'accepte par `panels` (`ExtraPanel[]`) — la feature
  des réglages ne connaît pas `geometry-editor`, c'est le studio qui câble, même
  règle que `leading`/`trailing`. `GeometryPanel` a **perdu sa carte et son
  titre** : le tiroir est déjà une région nommée « Géométrie » ;
- **les chiffres d'instant** — **objets suivis**, cadence serveur, latence, **écart
  image** et flux analysé — sont à l'extrémité de la barre (`TechnicalMetrics`,
  `trailing`). Depuis le 2026-09-01 ils sont **montés dès qu'une vidéo est chargée**, à
  « — » tant que rien n'a tourné, et en 12 px au lieu de 14 : la barre ne change plus de
  forme au moment où l'on lance, c'est-à-dire à l'endroit exact où l'on regarde. Ils
  sont en
  libellé plus chiffre sur deux lignes, sans carte. Ils tenaient quatre des six
  `MetricCard` de tête, à égalité visuelle avec le bilan du comptage. Ils étaient
  trois jusqu'au soir du 2026-08-19 : « Objets suivis » les a rejoints pour la même
  raison, c'est le nombre de pistes vivantes à *cette* image — un chiffre qui monte
  et redescend, jamais un résultat qui s'accumule. Contrepartie assumée : la
  `MetricCard` portait `aria-live="polite"` et cette rangée non, un compteur qui
  change à chaque image ferait d'un lecteur d'écran un métronome ;
- **le nom du fichier est sur la scène**, coin haut-gauche, dans **exactement**
  l'écrin du badge de dimensions d'en face (`SourceBadge`, `pointer-events-none`
  obligatoire — la scène est une surface de tracé) ;
- **« Fermer » est dans le lecteur** (`TransportBar.actions`, poussé par `ms-auto`),
  là où se réglait la vitesse — laquelle rejoint le groupe de boutons qui lit. Le
  rappel « Portion retenue » disparaît avec lui : l'intervalle est écrit deux rangées
  plus haut, dans l'entête du rail qui le dessine. **« Lancer l'analyse » y a vécu
  jusqu'au 2026-09-01** et est passé dans la barre, avec Suspendre, Reprendre et
  Annuler — voir « La barre pilote l'analyse » ci-dessous.

**Les deux rails du lecteur ont la même longueur, et c'est vérifiable** (mesuré :
`x = 79`, `w = 1128` pour les deux). Le temps courant était écrit *à côté* du
curseur de position, ce qui raccourcissait ce rail-là de la largeur de
« 03:26 / 03:26 » : une borne posée au milieu de l'intervalle ne tombait pas au
milieu de la vidéo. Les deux chiffres sont désormais en **entête de leur rail**,
d'où les deux libellés « LECTURE » et « INTERVALLE D'ANALYSE » qui se répondent.

**La Répartition n'a plus de section** : ses cartes sont dans les Résultats, en
`size="sm"` — elles découpent « Passages globaux » dont elles sont la somme
exacte, et un écran de défilement entre les deux obligeait à retenir un nombre
pour vérifier l'autre. `ClassEntriesGrid` est **supprimé**, son contenu replié
dans `ResultsDashboard`. Le titre « Répartition » ne disait rien de plus que
« Voiture », « Bus » juste dessous.

**La colonne de résultats n'a plus qu'une tête de lecture, et une carte par
ligne** (soir du 2026-08-19). Quatre changements liés, et aucun ne touche un
calcul :

- **le chiffre de tête s'appelle « Passages globaux »**, en `size="lg"` et sur toute
  la largeur de la colonne. Il a été « Entrées au carrefour » — un lieu que
  l'utilisateur n'a pas forcément — puis « Passages en entrée », la somme des sens
  marqués « entrée ».

  **Il compte désormais des véhicules distincts** ([ADR
  0045](docs/adr/0045-un-passage-global-est-un-vehicule.md)) :
  `crossingVehicles(vehicles).length`, c'est-à-dire **exactement le nombre de rangées
  du registre**. Un aller-retour y vaut 1, plus jamais 2. C'est une entorse assumée à
  l'invariant 3 — le mot « Passages » couvre ici un compte de véhicules — tenable
  parce que l'aide de la carte porte l'unité en toutes lettres, que rien ne divise ce
  chiffre par un autre, et que les passages bruts restent sur chaque carte de ligne.
  Le « — » ne dépend plus des rôles mais de `lines.length === 0` : une géométrie
  entièrement en « Comptage seul » rend donc un chiffre. `entriesByClass` est
  **supprimé** et remplacé par `crossedByClass`, pour que la somme des cartes par type
  reste exactement égale au chiffre de tête ;
- **une carte par ligne tracée**, pleine largeur elle aussi : pastille de couleur,
  **le nom saisi par l'utilisateur**, fréquentation, entrées, sorties, solde signé
  et la barre à deux segments. Le détail par ligne n'existait qu'en bas de page,
  sous la vidéo, alors que la question « combien sur *cette* ligne » se pose en même
  temps que le total. Tout est dérivé de `stats.byLine` et du tracé **courant** :
  renommer une ligne ou basculer un sens entrée ↔ sortie se voit sans réanalyser ;
- **`model/lineFlows.ts` est la seule définition du bilan d'une ligne.** Elle était
  écrite deux fois — en privé dans `highlights.ts`, en clair dans `LineFlowRow` — et
  trois écrans la lisent désormais. Deux copies d'une règle finissent par diverger,
  et ici ce serait un passage qui change de colonne selon l'écran qui le montre.
  `entries`/`exits` y valent `null` et **jamais `0`** quand aucun sens ne porte le
  rôle : « 0 sorties » se lit comme un comptage, pas comme un rôle non déclaré.
  `EntryExitBar` sort de `LineFlowDashboard` pour la même raison ;
- **les cartes par type suivent « Objets à compter »** (2026-08-21) : décocher
  « Moto » dans le tiroir Détection retire son KPI des Résultats et sa part du
  camembert, le recocher les rend. Un zéro sous une classe que l'analyse n'a
  jamais cherchée se lit comme « aucune moto n'est passée », alors que la vérité
  est « on n'en a pas cherché ». La règle vivait déjà pour « Personne » seule ;
  elle vaut maintenant pour toutes les classes, avec sa contrepartie inchangée :
  **une classe décochée qui porte des entrées garde sa carte**, sans quoi rouvrir
  un résultat archivé puis décocher une case effacerait une colonne de son propre
  contenu. `results-dashboard/model/visibleClasses.ts` en est le **seul** juge —
  les cartes et le camembert le lisent tous deux, deux listes divergeraient sur un
  décochage. `StudioPage` lui donne les **noms COCO** des classes cochées, traduits
  une fois contre le catalogue serveur (`cocoName` est la clé des `byClass` ;
  l'identifiant ne l'est nulle part), avec repli sur les quatre véhicules tant que
  le catalogue n'a pas répondu.

**La colonne n'est plus vide avant la première analyse** (soir du 2026-08-19). Entre
l'import d'une vidéo et le premier chiffre, elle était une bande de 24 rem inoccupée
sur toute la hauteur de la scène — et le squelette du chiffre de tête vivait,
lui, **tout en bas de la page**, sous la vidéo et la chronologie, là où personne ne
le voyait avant d'avoir défilé. Deux changements :

- **le squelette est monté dans la colonne**, à l'endroit exact qu'occupera le
  tableau réel : même libellé, même taille, même place. Un écran d'attente n'a de
  valeur que s'il annonce la forme de ce qui vient ;
- **« Configuration système » remplit le reste** (`ui/AnalysisSummary.tsx`, texte
  calculé par `model/analysisSummary.ts`, testé) : modèle, objets comptés, géométrie,
  portion analysée, plaques, cadence — les réglages qui partiront au serveur, relus
  d'un coup. Ils vivent dans **quatre tiroirs différents** de la barre, et les
  vérifier demandait d'ouvrir les quatre pendant que la place pour les lire ensemble
  restait inoccupée juste à côté. Trois points qui ne se devinent pas :
  - **les avertissements disent une conséquence, jamais un interdit** — « aucune
    ligne : les zones seules ne produisent pas de franchissement », et non « ligne
    manquante ». Lancer reste possible, `canAnalyse` en est le seul juge, et ce
    récapitulatif ne bloque rien ;
  - **il ne montre pas la durée de l'intervalle**, seulement ses bornes :
    `describeRange` demande la durée de la vidéo, qui n'est lisible que sur la
    balise `<video>` et ne vit dans aucun état réactif — le chiffre serait figé au
    premier rendu ;
  - **rien en caméra** : un flux n'a ni portion à choisir ni plaques, et
    `RealtimePanel` occupe déjà cette place avec ce qui le concerne.

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
dehors ou `Échap` le referme. Le rail de navigation (`AppShell`) est collé au bord
gauche sur toute la hauteur (`sticky top-0 h-dvh`, `z-40`) pour la même raison de
fond — rester atteignable pendant que la page défile à côté —, et **la barre du studio
l'est à son tour** depuis le 2026-08-19. Elle se cale sur `--app-header-h`, qui vaut
zéro depuis que le rail est vertical et redevient une hauteur sous 48rem.

#### La barre pilote l'analyse (2026-09-01)

Les commandes d'un job vivaient à **trois** endroits qu'on ne voit pas d'un même coup
d'œil — « Lancer » au bas du lecteur, « Suspendre » et « Annuler » sous la vidéo, les
réglages dans la barre. Elles sont désormais **toutes dans la barre**, juste après
l'import ([ADR 0053](docs/adr/0053-la-barre-du-studio-pilote-l-analyse.md)).

Six points qui ne se devinent pas :

- **toutes les pilules sont en icône seule**, et le libellé se déplie au survol **et au
  focus** en poussant ses voisins. `shared/ui/ToolbarButton` en est la seule
  implémentation — les tiroirs vivent dans `analysis-settings`, les commandes dans
  `analysis-job`, et une feature n'importe jamais une autre ;
- **les commandes du job ne se déplient pas** (`expandOnHover={false}`). Elles sont en
  tête de rangée, donc leur expansion pousserait tout ce qui suit — y compris l'anneau
  et les chiffres qu'on est justement en train de lire quand on hésite à suspendre —
  et elles changent de nature en cours de route, si bien qu'une pilule qui s'ouvre à
  l'instant où « Lancer » devient « Suspendre » se lit comme un déplacement ;
- **« Lancer » est bleu et non vert.** Le vert est celui du bouton d'import, à sa
  gauche immédiate : deux pastilles vertes voisines se lisaient comme un seul groupe.
  La **source est verte, le job est bleu**. `--color-info` ne servait nulle part
  ailleurs, et `text-accent-ink` lui va — ce jeton vaut noir en sombre et blanc en
  clair, exactement ce que demandent les deux bleus ;
- **l'anneau de progression suit ses commandes**, à gauche, et non les chiffres à
  droite : il répond au bouton qu'on vient de cliquer. Son détail ne porte que le
  compte d'images, le pourcentage centré dessus — la cadence y a figuré et en est
  partie, la rangée de chiffres l'affichant déjà sous « Cadence serveur » ;
- **c'est une `max-width` qu'on anime, et `grid-template-columns: 0fr → 1fr` a été
  essayé puis mesuré faux** : ce motif suppose un conteneur qui distribue de l'espace
  libre, alors que la pilule est un `inline-flex` dimensionné par son contenu. Mesuré,
  `1fr` forcé à la main : 48 px avant, 48 px après. La `max-width` donne 40 → 138 px ;
- **`analysisProgress` (pur, testé) est le seul juge de l'état du job.** La barre et le
  bloc sous la vidéo le lisent tous deux : deux calculs séparés afficheraient deux
  pourcentages du même job ;
- **un job en file d'attente n'affiche pas de compteur d'images.** `totalFrames` vaut
  zéro tant que le serveur n'a pas sondé la vidéo, et « 0 / 0 images · 0.0 img/s » se
  lit comme une analyse plantée. Vu à l'usage, derrière une analyse **suspendue** qui
  gardait sa place : le message dit désormais la cause de l'attente ;
- **le bloc sous la vidéo ne garde que ce que la barre ne peut pas porter** — l'envoi
  et ses octets, la préparation et le nom du modèle, l'échec, et la phrase qui explique
  ce qu'une pause coûte. Sa barre de progression n'apparaît que pendant l'envoi, la
  seule phase où l'anneau n'existe pas encore ;
- **entre 1280 et ~1500 px, pendant une analyse, le détail de l'anneau se tronque**
  plutôt que de faire passer la rangée sur deux lignes.

#### Ce que portent les quatre tiroirs, depuis le 2026-08-17 (le quatrième depuis le 2026-08-19)

Le contenu a été **réaligné sur le code réellement exécuté** : plusieurs textes
décrivaient un comportement d'avant ADR 0024 et ADR 0025, et deux chiffres du
diagnostic n'étaient renseignés par personne.

- **Détection** — modèle, confiance véhicules, classes à compter, ANPR, confiance
  plaques, OCR, **confiance lecture**, **les plaques recherchées** (2026-08-27),
  **et « Ignorer hors zone »**, qui vivait dans
  « Affichage » alors qu'il ne change pas ce qu'on voit mais ce que le détecteur
  reçoit, donc les chiffres. Deux textes étaient devenus faux : la confiance ne
  filtre plus le détecteur (elle décide ce qui *devient* une piste), et « Repérer les
  plaques » connaît désormais les **trois** états du serveur — absent, présent mais
  illisible (`plateAvailable && plateLoadable === false`), disponible. Le deuxième
  laissait cocher une option qui ralentissait l'analyse sans jamais rendre une plaque ;
  `model/plateCapability.ts` le tranche en un endroit, testé.

  **« Confiance lecture » (2026-08-24) n'est pas le doublon de « Confiance plaques »** :
  celle-ci porte sur la **localisation**, celle-là sur la **lecture**, et une plaque
  peut être parfaitement encadrée et illisible — c'est d'ailleurs pourquoi le registre
  affiche les deux confiances côte à côte. Elle n'apparaît qu'avec l'OCR (sans lecture,
  rien à filtrer), descend jusqu'à `0` (« aucune ») là où le seuil de localisation part
  de 0,05, et porte un bouton « Défaut » qui rend `null` — « suivre le plancher du
  serveur », qui n'est **pas** `0` (décision 27) ;
- **Comptage** — images avant comptage, survie d'une piste perdue, seuil IoU, un
  encart « décidé pour vous » qui énonce la bande morte (le comptage attend que le
  véhicule soit franchement d'un côté ; **la date, elle, est celle du passage sur le
  trait** depuis ADR 0038), le diagnostic, et les
  **quasi-franchissements**, redevenus visibles ;
- **Affichage** (« Affichage & analyse » jusqu'au 2026-08-31 : le libellé le plus
  long de la rangée coûtait ~130 px à la seule chose qui doit tenir sur une ligne, et
  le tiroir dit ce qu'il contient dès qu'il est ouvert ; depuis le 2026-09-01 aucun
  libellé n'est visible au repos de toute façon) — trajectoires (le seul
  réglage purement visuel), pas
  d'analyse et les deux cadences. L'**échelle globale** px/m y a vécu jusqu'au
  2026-08-21 : elle est supprimée avec toute la mesure de vitesse
  ([ADR 0034](docs/adr/0034-la-mesure-de-vitesse-est-retiree.md)) ;
- **Géométrie**, depuis le 2026-08-19 — lignes, zones, presets, **type de ligne** et
  voie réservée (2026-08-27, ADR 0040 ; le sélecteur de type remplace l'affichage nu
  des deux rôles, et le bouton d'inversion échange désormais la paire quel que soit
  le type).
  Fourni par le studio (`panels`) et non par cette feature, qui ne connaît pas
  `geometry-editor`. La longueur réelle par ligne en a disparu le 2026-08-21, pour
  la même raison.

**Double-cliquer une forme sur la vidéo déplie « Géométrie »** (2026-08-20,
**double-clic depuis le 2026-08-31**) : ouvrir le réglage d'un trait est un geste
distinct de sa manipulation, et l'utilisateur cherchait auparavant dans la barre où
le renommer ou lui donner ses rôles de sens. Le **simple clic sélectionne et rien de
plus** — c'est lui qui amorce le glisser, donc le geste le plus fréquent de cet
écran, et déplier un tiroir par-dessus la vidéo qu'on est en train de tracer était du
bruit à chaque déplacement de ligne. `GeometryCanvas` sépare les deux par
`onSelect` et `onActivate` ; le second refait un `hitTest` au lieu de lire la
sélection courante, qui serait périmée dans le cycle de rendu du double-clic (piège
42), et n'est jamais appelé en mode tracé de zone, où le double-clic **ferme** le
polygone. Trois points qui ne se devinent pas :

- **l'état du tiroir ouvert a quitté `SettingsPanels` pour `StudioPage`** : deux
  endroits l'ouvrent désormais, et un seul des deux est la barre. `openPanel` /
  `onOpenPanel` sont donc des props, et `GEOMETRY_PANEL_ID` est nommé une fois —
  deux littéraux `"geometrie"` divergeraient en silence, sur un clic qui n'ouvre
  plus rien ;
- **la surface de tracé est exemptée du clic « en dehors »**
  (`KEEP_PANELS_OPEN_ATTR`, posé sur une enveloppe `display: contents` autour du
  canvas). Sans elle, ouverture et fermeture tomberaient dans le **même**
  événement : le gestionnaire de `pointerdown` que `SettingsPanels` pose sur le
  document s'exécute *après* celui de React, donc la fermeture gagnerait. Effet de
  bord voulu : un clic sur la vidéo ne referme plus le tiroir qu'on est en train
  d'utiliser pour la tracer ;
- **deux bornes à l'ouverture** : rien pendant une analyse ou un direct (`busy`),
  où le panneau est grisé et où un formulaire intouchable par-dessus la vidéo
  serait du bruit ; rien sur un double-clic dans le vide, où le canvas n'appelle pas
  le rappel du tout — le clic qui le précède **désélectionne**, c'est la fin d'un
  réglage et pas son début. Fermer reste à `Échap`, au re-clic sur la pilule et au
  clic hors de la scène.

**Tracer la première zone coche « Ignorer hors zone »** (2026-08-24). Le geste dit
« ce qui m'intéresse est là-dedans », et il n'avait pourtant aucun effet sur les
chiffres tant qu'une case restée décochée dans un **autre** tiroir n'était pas
trouvée : l'utilisateur voyait son polygone dessiné, comptait toujours ce qui passait
dehors, et n'avait aucune raison d'aller chercher la cause dans « Détection ». Trois
bornes, et elles sont ce qui distingue un défaut d'une contrainte :

- **la première zone seulement** (`geometry.zones.length === 0` au moment du tracé).
  Décocher puis tracer une deuxième zone recocherait la case : ce serait combattre un
  choix explicite. Le passage de « aucune zone » à « une zone » est le seul moment où
  la question n'a jamais été posée ;
- **le tracé, pas le chargement.** Un preset porte son propre `maskOutsideZones` et
  l'impose. Un `useEffect` sur `zones.length` les ferait entrer en collision — le
  preset poserait `false`, l'effet verrait passer une zone et remettrait `true` ; c'est
  pourquoi la règle vit dans `handleCompleteZone`, sur l'événement, et non dans un
  effet ;
- **rien n'est verrouillé** : la case reste décochable, et `toRequest` retombe de
  toute façon à `false` s'il ne reste aucune zone.

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
  justifie reste vrai — leur somme égale le chiffre de tête, `crossedByClass`
  comptant depuis ADR 0045 la **même population** que `crossingVehicles`, verrouillé
  par un test. La matrice
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
  plus entrée sans être le plus fort afflux, cas verrouillé par un test.

  **La liste des lignes est paginée depuis le 2026-08-27**, six rangées par page
  (`LINES_PER_PAGE`, `model/paging.ts`, testé). La section est **sous** la vidéo :
  au-delà, la liste devenait le plus long bloc de la page pour sa partie la moins
  consultée, et repoussait la carte de comparatifs — qui répond déjà à « quelle
  ligne » — hors de l'écran. Quatre points qui ne se devinent pas :
  - **la page est bornée à la lecture, jamais corrigée par un effet.** Retirer trois
    lignes du tracé pendant qu'on lit la dernière page laisserait sinon, le temps
    d'un rendu, une liste vide sous une pagination qui annonce des rangées.
    `pageWindow` ramène la page demandée dans les bornes et c'est le cas que son
    test vise en premier ;
  - **l'ordre reste celui du tracé**, jamais un tri par fréquentation. La pastille
    de couleur relie la rangée à un trait sur la vidéo, et les chiffres changent à
    chaque image pendant l'analyse : trier ferait sauter les rangées sous le
    curseur. Le classement par valeur existe — il est dans les camemberts et les
    comparatifs, là où il ne coûte pas ce repère ;
  - **le rang de chaque ligne est écrit** : deux pages de rangées identiques en tout
    point sauf les chiffres ne disent pas laquelle on regarde ;
  - **les commandes n'existent que si elles servent** (`paginated`), et le décompte
    « Lignes 7–12 sur 14 » passe avant les deux chevrons : c'est lui qui dit qu'il y
    a une suite, et le seul élément utile quand les deux boutons sont grisés ;
- **les deux graphiques sont des camemberts côte à côte** (2026-08-17), sur une
  primitive partagée `ui/PieChart.tsx` — un SVG maison de `<path>`, légende et
  chiffres en HTML à côté (même règle que l'ancien histogramme : jamais de
  `<text>` SVG, que le `viewBox` mettrait à l'échelle). `LineFlowChart` ventile
  le total par ligne, `ClassEntriesChart` les entrées par type. Le premier
  répondait avant à « quand » (barres empilées par tranche de temps) et répond
  désormais à « quelle part » : **`flowBucketsByLine` et le clic-pour-se-déplacer
  sont supprimés**, pas masqués — un camembert n'a pas de position temporelle
  sur laquelle caler la lecture, et la barre de lecture standard reste le seul
  outil pour se déplacer dans le temps.

  **Les deux tiennent le grand nombre de parts depuis le 2026-08-27**, parce que rien
  ne borne le nombre de lignes tracées ni de types cochés : à douze lignes, le dessin
  devenait une roue de lamelles et sa légende, en colonne unique, montait à deux fois
  la hauteur du camembert — ce qui décrochait le graphique voisin de la rangée.
  Quatre règles, aucune ne touchant un chiffre (`model/pieSlices.ts`, testé) :
  - **au-delà de cinq parts, le reste devient UNE part** « N autres », au gris de
    `--color-line-muted` et jamais à une couleur de donnée — un agrégat coloré comme
    une ligne se lirait comme une ligne. Un bouton déplie le détail : rien ne
    disparaît, la lecture d'ensemble passe d'abord ;
  - **les parts sont classées par valeur décroissante, à tri stable.** Dans l'ordre du
    tracé, « quelle est la part dominante » se résolvait en comparant des angles à
    l'œil — ce qu'un camembert existe pour éviter. Le tri retombe sur l'index
    d'origine à égalité, sinon deux lignes à égalité permuteraient à chaque
    republication de l'aperçu et le dessin clignoterait pendant l'analyse ;
  - **les parts sans passage sont comptées, pas listées** (« 6 lignes sans passage »).
    Six rangées à « 0 — 0 % » prenaient plus de place que les parts qui portent le
    trafic ; le fait n'est pas perdu, il se lit dans la rangée de Statistique de la
    ligne et dans ses quasi-franchissements, qui disent en plus pourquoi. Et une part
    agrégée **nulle** n'est pas tracée du tout : un secteur d'angle nul est invisible
    sur le dessin et occuperait une rangée de légende ;
  - **la légende est en `auto-fill` et les deux cartes s'étirent**, donc le graphique
    ne sait pas — et n'a pas à savoir — s'il occupe une demi-rangée ou toute la page.
    Le passage côte à côte a reculé de `sm` à `lg` pour la même raison : à 640 px en
    deux colonnes, la légende tombait sous le dessin.

  **`unit` et `metric` sont des props, pas des devinettes** : un camembert de lignes
  compte des **passages**, un camembert de types compte des **entrées**. Les
  confondre dans une phrase de regroupement serait une erreur d'unité invisible, les
  deux chiffres étant plausibles (invariant 3) ;
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
  portent.

  **« Lignes franchies » n'existe plus** (soir du 2026-08-19) : elle est fondue
  dans ces deux colonnes, devenues **« Entrée par »** et **« Sortie par »**, qui
  portent maintenant la **ligne et l'heure** au lieu de l'heure seule. Elle
  listait les deux sens dans une même cellule pendant que ses voisines ne
  donnaient que l'instant : lire « ce véhicule est entré par la ligne 1 à 00:34 »
  demandait de recoller trois cellules, dont une par survol. Deux points qui ne se
  devinent pas :
  - **le contenu tient sur une rangée** — flèche à l'angle réel, nom de ligne
    tronqué, heure poussée à droite. Empiler la ligne et l'heure casserait
    `ROW_HEIGHT`, dont dépend la virtualisation au-delà de 200 lignes ;
  - **une troisième colonne « Hors rôle » apparaît, et seulement si une rangée en
    porte** : un franchissement dont le rôle n'est plus lisible — ligne retirée du
    tracé, ou sens resté `neutral` d'avant ADR 0021. Le ranger sous un rôle serait
    une invention, le taire ferait diverger le registre de « Passages », qui le
    compte. `crossingsWithoutRole` est le **complément exact** des deux rôles, et
    un test le verrouille. La colonne est décidée sur `vehicles` entier et non sur
    les lignes rendues : une colonne qui apparaîtrait au défilement d'un tableau
    virtualisé décalerait toutes les autres sous le curseur ;
- **les Franchissements sont MASQUÉS depuis le 2026-08-27**, et le bas de page n'a
  rien reçu à leur place : les **Alertes** y ont vécu quelques heures, puis dans une
  troisième colonne, et sont aujourd'hui derrière la cloche de la barre ([ADR
  0043](docs/adr/0043-les-alertes-quittent-la-video-pour-une-colonne.md), puis [ADR
  0044](docs/adr/0044-les-alertes-deviennent-un-centre-de-notifications.md)). Un seul mot à
  changer pour les rendre : `SHOW_CROSSING_TIMELINE` dans `StudioPage`, typé
  `boolean` exprès pour que TypeScript ne réduise pas la condition à `false` et que
  le lint ne la signale pas comme inutile. `CrossingTimeline.tsx`,
  `model/crossingTimeline.ts` et leurs tests sont **intacts** — ils compilent
  toujours, `ROLE_STYLE` et `crossingFacets` ayant reçu les deux nouveaux rôles.
  La raison du masquage : la chronologie posait un fait par rangée sans dire lequel
  méritait qu'on aille voir, ce à quoi une alerte répond directement. Ce qui suit
  décrit donc du code **conservé mais non monté** ;
- **la chronologie, telle qu'elle est écrite** (2026-08-17).
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
  gardée pour un futur besoin plutôt que supprimée pour un gain nul ;
- **le Registre montre la voiture** (2026-08-27) : une colonne « Capture » porte une
  vignette de 40 px du véhicule, et le clic l'ouvre en grand — le véhicule, sa plaque
  en dessous, **pourquoi** cette photo existe, l'instant et la confiance. La modale est
  `shared/ui/SnapshotDialog.tsx`, partagée avec les alertes, sur le patron `<dialog>`
  + `showModal()` de `PresetDialog`. Cinq points qui ne se devinent pas :
  - **la colonne apparaît dès la première capture** (`jobId !== null &&
    hasSnapshots(vehicles)`), pendant l'analyse comprise depuis ADR 0046. Elle se
    décide sur `vehicles` **entier** et jamais sur les rangées rendues : une colonne
    qui apparaîtrait au défilement décalerait toutes les autres sous le curseur.
    **Elle apparaît aussi sans ANPR depuis ADR 0051**, dès qu'une image de requête est
    fournie — la phrase « sans ANPR ni OCR, aucune colonne » qui vivait ici est
    abrogée, et le drapeau est `snapshotMs` et non plus `snapshotScore`.
    **Ce n'est pas la règle des trois boutons d'export**, qui restent liés à
    `result` : un CSV à mi-parcours ment sur son contenu, une vignette manquante ne
    ment sur rien ;
  - **la modale sait montrer une photo sans vignette de plaque, et dit pourquoi**
    (`snapshotHasPlateFace`) : une capture retenue pour la ressemblance du véhicule n'a
    pas de plaque, et la demander rendrait un 409 que la modale afficherait en
    « Capture purgée » — un repère d'échec sur un état parfaitement normal. Elle rend
    donc une phrase à la place, jamais l'icône barrée ;
  - **la rangée passe à 48 px, et seulement alors.** `visibleWindow` accepte déjà une
    hauteur en paramètre. **Le `height` d'une rangée n'est qu'un minimum en CSS** : la
    cellule de capture supprime son rembourrage vertical (`py-0`, son propre `<td>` et
    non le `Td` partagé), sinon la rangée rendue fait 57 px là où la virtualisation en
    calcule 48 — et les rangées dérivent au-delà de 200 lignes, jamais avant ;
  - **`loading="lazy"` est toute l'histoire de performance côté client** : seules les
    rangées visibles demandent leur image. Les routes sont exemptées de la limite de
    débit parce que ce sont des `GET /jobs/…` (ADR 0027), ce qui est indispensable
    ici ;
  - **une capture absente n'est pas une panne** : `onError` bascule sur un repère muet
    — pas encore écrite, jamais produite, ou purgée après le TTL de la vidéo. Pendant
    l'analyse **et seulement alors**, la vignette réessaie **une fois** (avec un
    paramètre `retry` qui casse le cache d'échec) : le fichier peut arriver quelques
    centaines de millisecondes après l'aperçu qui l'annonce. Après, réessayer
    doublerait des requêtes vouées à échouer sur chaque rangée visible. **La requête
    est composée dans `shared/api/jobUrls.ts` et nulle part ailleurs** : elle l'était
    chez les deux appelants, chacun devinant la ponctuation de l'autre — `&retry=` ici
    en supposant `?v=` présent, `?retry=` dans le tiroir d'alertes en supposant
    l'inverse. Aucun n'était faux, et les deux le devenaient au premier changement
    d'appelant ;
- **le Registre porte deux filtres qui se composent** (2026-08-27) : la recherche
  par plaque et un **filtre par ligne**, dont les options portent les noms saisis par
  l'utilisateur et se renomment sans réanalyser. `filterByLine` est le jumeau de
  `filterByPlate`, discipline référentielle comprise — rendre le tableau *par
  référence* quand aucune ligne n'est choisie, sinon la fenêtre virtualisée se
  recalcule à chaque frappe dans le champ voisin. Le `useEffect` qui remet
  `scrollTop` à zéro prend **les deux** en dépendance : un filtre qui réduit le jeu
  sans replier le défilement laisse une fenêtre au-delà de la fin, et le tableau
  *paraît* vide. Le message d'état vide **nomme le filtre en cause** — avec deux
  filtres, « aucune plaque ne contient X » enverrait corriger la recherche alors que
  c'est la ligne choisie qui ne porte rien. Les exports continuent d'ignorer les
  deux.

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

    **Il porte aussi les quatre champs de sens, et c'est une quatrième panne
    silencieuse de la même famille** (corrigée le 2026-08-26). `LineSchema` les
    acceptait — le client les envoyait donc — mais `_line_to_domain` les laissait
    tomber avant la persistance : `PresetLine` n'avait tout simplement pas ces
    champs. Un preset s'enregistrait sans erreur, se rechargeait sans erreur, et
    rendait des lignes dont tous les sens valaient `neutral`. Les **comptages
    restaient justes** ; c'est tout l'aval qui se taisait d'un coup — « Passages en
    entrée » à « — », cartes par ligne sans entrées ni sorties, comparatifs de
    Statistique tous à `null`, registre sans heure d'entrée ni de sortie **plus**
    une colonne « Hors rôle » apparue, chronologie retombée sur « sens ↑ ». Depuis
    ADR 0021 le rôle **est** le libellé affiché : le perdre éteint l'écran sans
    fausser un chiffre. Quatre points :
    - **aucune migration** : la géométrie vit dans une colonne JSON, précisément
      pour que sa forme évolue sans toucher au schéma. Un preset antérieur se relit
      et rend `neutral` ;
    - **`neutral` et jamais une devinette.** Deviner « entrée » fausserait un bilan
      que personne n'a demandé, alors que `neutral` déclenche le repère « à
      préciser » du panneau de géométrie, qui force un choix explicite ;
    - **la relecture valide le rôle contre les trois valeurs admises.** `PresetSchema`
      les type par un `Literal` : une valeur inattendue en base ferait échouer la
      validation de la *réponse*, donc un 500 sur `GET /presets` qui emporterait
      **toute** la liste pour une seule ligne fautive. Même doctrine que `_load` ;
    - **les champs de sens ne sont pas mis à l'échelle.** `scaled_to` ne touche
      qu'à des coordonnées : un rôle décrit le trait, pas sa position.

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
7. **Thème sombre par défaut, clair au choix** (bascule en bas du rail). Le clair
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

    **Ce levier a été construit et mesuré depuis, et il vaut 1,10×** : voir la
    décision 38 et
    [ADR 0054](docs/adr/0054-le-moteur-et-son-aval-se-recouvrent.md). Ne pas le
    relire comme une réserve encore disponible.

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
    - **le déplacement, lui, doit vivre dans l'adaptateur.** OpenCV décode après
      `CAP_PROP_POS_FRAMES`, puis rattrape par `grab()` et **vérifie où il est
      tombé** (le déplacement est approximatif sur plusieurs conteneurs, et
      l'accepter sans vérifier donnerait des horodatages faux sans lever).
      Ce déplacement a longtemps justifié un **second chemin** de lecture dans
      `iter_video`, et ce fichier a longtemps annoncé « trois `model.track()` dans ce
      module ». **Les deux sont périmés depuis ADR 0031** : le différé décode
      lui-même dans un fil séparé, donc le déplacement n'est plus un cas particulier
      — il vit dans `_iter_decoded` et gagne le lot d'images qu'il n'avait pas. Il y
      a **deux** `model.track()` dans ce module (différé et direct), et
      `test_engine_arguments.py` pose `EXPECTED_TRACK_CALLS = 2` ;
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
    - **`TRAFFIC_PLATE_DETECT_MAX_PER_FRAME` borne le coût, et ne l'améliore pas.**
      Le 1,27× qui lui était d'abord attribué venait surtout de ce qu'il évitait les
      appels à un seul recadrage, donc les pauses d'étalonnage cuDNN (décision 25). Une
      fois cette cause corrigée : `0` → 11,0 img/s et **180 plaques localisées**,
      `2` → 9,0 et 137, `1` → 13,8 et 76. Il **coûte des plaques**, à peu près
      proportionnellement aux recadrages écartés.

    **Et surtout** : sur une vue de circulation 1080p, les plaques font moins de 48 px
    et le plancher de lecture est à 64 (invariant 12) — **aucune plaque ne peut être
    publiée**, donc l'ANPR y dépense 73 % du budget pour rien. Le service le dit déjà
    (`plate_unread_reason = too_small`, décision 14). Les deux gestes qui règlent cela
    sont de resserrer le plan ou de filmer plus défini, pas de régler quoi que ce soit.
    [ADR 0032](docs/adr/0032-l-ocr-n-etait-pas-le-goulot-le-detecteur-de-plaques-l-est.md).
25. **L'autotune cuDNN se réétalonnait à chaque plaque, et coûtait jusqu'à 2× la
    cadence.** `TRAFFIC_INFERENCE_CUDNN_AUTOTUNE` est **à `false` par défaut** depuis
    [ADR 0033](docs/adr/0033-l-autotune-cudnn-se-reetalonnait-a-chaque-plaque.md), qui
    abroge le défaut d'ADR 0013. Quatre points, et le premier est le plus utile pour
    déboguer n'importe quoi d'autre ici :
    - **ce n'était pas un coût, c'était une pause.** L'étage de plaques annonçait 99 ms
      par image ; sa **médiane valait 27 ms** et six appels sur 90 dépassaient la
      seconde, pesant 73 % du poste. Une moyenne ne distingue pas les deux, et les deux
      appellent des gestes opposés — d'où les `p50 / p90 / max` **par appel** que le banc
      rend désormais, avec un `⚠` dès qu'un maximum dépasse le double de la médiane ;
    - **la cause est la forme d'entrée.** Ultralytics impose `rect=True` en prédiction,
      donc un recadrage soumis **seul** produit une forme qui dépend de son rapport
      d'aspect ; cuDNN réétalonne à chaque forme neuve, une seconde à chaque fois. Deux
      recadrages de tailles différentes forcent au contraire une entrée **carrée
      constante** — c'est pourquoi les images chargées n'en souffraient pas ;
    - **couper l'autotune ne touche aucun pixel** : mêmes détections, même plaque
      publiée, mêmes comptages, sur les deux scènes et les quatre courses. Gain mesuré
      en courses alternées : **1,7× à 2,1×** sur une scène clairsemée, **1,3× à 1,5×**
      sur une scène dense. Et ce qu'il rendait au chemin dont la forme *est* fixe :
      7,92 ms contre 8,00, soit rien ;
    - **ne pas « corriger » en forçant `rect=False` sur les plaques.** Même gain, et une
      plaque publiée en moins : le remplissage change la boîte d'un sous-pixel, donc la
      vignette d'OCR, donc le vote.
26. **« Confiance véhicules » n'atteignait le tracker qu'à la première analyse d'un
    processus.** Même sortie anticipée d'Ultralytics que celle qui avait motivé
    `reset_trackers` : `on_predict_start` **sort immédiatement** quand
    `predictor.trackers` existe et que `persist` est vrai, donc le fichier de suivi
    n'est **jamais relu** — et c'est lui qui porte le seuil de l'utilisateur depuis
    ADR 0024. Le curseur bougeait, le fichier dérivé était écrit, son chemin
    journalisé, et aucun chiffre ne changeait. Mesuré, trois analyses de suite dans un
    même processus sur la même fenêtre : `0,20 → 0,80 → 0,20` rendait **3, 3, 3**
    véhicules ; il rend désormais **3, 1, 3**. Trois points :
    - **la panne est invisible en développement**, parce que la première analyse après
      un démarrage est la seule qui obéit — et c'est celle qu'on regarde ;
    - **`reset_trackers(model, tracker_config)` repose les clés de requête** sur les
      trackers vivants. C'est suffisant parce que `REQUEST_TRACKER_KEYS ⊆
      LIVE_TRACKER_KEYS` : ces clés-là sont relues à chaque image sur `self.args`, pas
      gravées à la construction. Un test verrouille l'inclusion, un autre le fait que
      le fichier dérivé ne change rien d'autre ;
    - **ne pas « simplifier » en supprimant `predictor.trackers`.** Ultralytics
      ré-enregistrerait ses rappels, `model.callbacks` **empile**, et un
      `on_predict_postprocess_end` en double appelle `tracker.update()` deux fois par
      image — des chiffres plausibles et complètement faux. Les rappels par défaut de
      la bibliothèque portent les mêmes noms que ceux du tracker, donc les
      désinscrire à la main n'est pas fiable.

    [ADR 0035](docs/adr/0035-le-seuil-de-confiance-n-atteignait-le-tracker-qu-une-fois.md).
27. **La confiance de **lecture** est un réglage de l'utilisateur, pas du déploiement.**
    `plate_ocr_min_text_score` (0,50) refusait déjà toute lecture moins sûre, mais depuis
    un fichier de configuration. « Des plaques fausses, ou pas de plaques » est pourtant
    une question de scène, pas de machine — la seule des seuils d'OCR qui le soit.
    `plateTextConfidence` voyage donc par requête, comme `plate_confidence`, et descend
    jusqu'à l'adaptateur en argument de `PlateReader.read`. Trois points :
    - **`null` n'est pas `0`** : le premier garde le plancher du déploiement, le second
      accepte **toutes** les lectures. Les confondre publierait des plaques que le
      serveur refusait jusque-là ;
    - **le filtre vit dans l'adaptateur et nulle part ailleurs** : une lecture sous le
      plancher ne devient pas un `PlateText`, donc ne traverse pas le port, donc ne
      vote pas. Filtrer des deux côtés laisserait deux endroits décider de ce qui vote ;
    - **il n'économise aucune inférence** — la lecture a lieu puis est refusée. L'aide
      à l'écran le dit, parce que monter ce curseur pour accélérer une analyse est le
      contresens naturel. Un véhicule dont toutes les lectures sont refusées tombe sur
      `no_consensus`, ce qui est exact : la tentative a bien eu lieu.

    Mesuré sur le vrai lecteur : `null` et `0` publient `A8254S`, `0,99` refuse les
    trois lectures et ne publie rien.
    [ADR 0036](docs/adr/0036-la-confiance-de-lecture-devient-un-reglage-de-l-utilisateur.md).
28. **Le plancher du détecteur suit le curseur quand celui-ci descend.** `detector_floor`
    lisait `track_low_thresh` du fichier de base et le rendait tel quel, ce qui défaisait
    ADR 0024 à l'autre bout de sa plage : **sous 0,10 le curseur était mort** — le
    détecteur ne rendait jamais une boîte à 0,07 — et pire, le fichier dérivé obtenait
    `track_high_thresh < track_low_thresh`, donc **une bande basse vide** et la seconde
    association BYTE de nouveau morte. Il rend désormais
    `min(base_low, confiance × base_low / base_high)`, le rapport venant du **fichier
    versionné lui-même** (0,10 / 0,25). Trois points :
    - **rien ne change au défaut** : au-dessus de `track_high_thresh` du fichier (0,25), le
      `min` rend exactement l'ancienne valeur. Seul le bas de la plage descend, là où le
      curseur ne servait à rien ;
    - `track_low_thresh` rejoint `REQUEST_TRACKER_KEYS` — il dépend de la requête, donc il
      doit être reposé par `reset_trackers` (ADR 0035). La condition
      `REQUEST_TRACKER_KEYS ⊆ LIVE_TRACKER_KEYS` tient **sans rien faire** : la clé y était
      déjà ;
    - **ce n'est pas toute la cause du problème de motos.** `nms.py` fait `cls.max(1)`
      **puis** filtre par classe : l'évidence `motorcycle 0,48` d'une ancre dont le top-1
      est `person 0,55` est jetée sans recours. `multi_label=True` serait le remède mais la
      clé n'existe pas dans `cfg/default.yaml` — à mesurer, jamais à adopter en défaut.

    [ADR 0037](docs/adr/0037-le-plancher-du-detecteur-suit-le-curseur-quand-il-descend.md).
29. **Un franchissement porte la date de son intersection, pas de sa preuve.**
    Voir « Ce véhicule est compté deux fois » plus bas pour le mécanisme complet.
    [ADR 0038](docs/adr/0038-un-franchissement-est-date-de-son-intersection.md).
30. **On ne paie plus d'inférence pour une plaque prouvée illisible.** Sur une vue de
    circulation réelle, la détection de plaques pesait **73 % du budget pour zéro plaque
    publiable** — elles font moins de 48 px pour un plancher de lecture à 64. Dès qu'une
    piste a reçu **une seule** détection réelle, on connaît son rapport
    plaque/véhicule et donc la largeur de véhicule qu'il faudrait ; on se tait tant qu'elle
    n'est pas atteinte. Quatre points :
    - **elle suspend, elle n'abandonne pas** : `largeur × rapport ≥ plancher` redevient
      vrai **tout seul** quand le véhicule s'approche. C'est une mesure, pas un délai, et
      c'est ce qui répond à « on perdrait la plaque publiée trois secondes plus tard » ;
    - **aucun texte ne peut être perdu, par construction** : le nombre comparé est le
      **même** que celui dont `PlateOcrPolicy.should_read` se sert pour refuser de lire.
      Ce qui est payé est le **rectangle**, d'où `TRAFFIC_PLATE_DETECT_READABLE_GATE` ;
    - **sans OCR la porte ne s'arme jamais** : le service ne pose le plancher que si un
      lecteur tourne réellement ;
    - **la garde est en position 1 bis, avant celle de l'ancre**, et c'est le seul détail
      qui peut faire échouer tout le mécanisme en silence : une piste suspendue perd son
      ancre, et « pas d'ancre → toujours détecter » la relancerait à chaque image.

    [ADR 0039](docs/adr/0039-ne-pas-payer-pour-une-plaque-prouvee-illisible.md).
31. **Une ligne porte un type, et le type est dérivé de ses deux rôles.** Cinq rôles
    (`entry`, `exit`, `forbidden`, `transit`, `neutral`), **quatre** types
    choisissables depuis le 2026-08-28 — les deux « sens unique » ont fusionné en
    « Autorisé · interdit », de paire `{entry, forbidden}` —, aucun champ `lineKind`
    dans le contrat. Une ligne peut en plus être **réservée** à
    certaines classes, indépendamment de son type. Trois points à ne pas rediscuter :
    - **le serveur ne lit rien de tout cela**, exactement comme les rôles depuis
      ADR 0016. `test_regles_de_ligne.py` verrouille la propriété : quatre
      descriptions de la même ligne rendent les mêmes totaux, les mêmes ventilations
      par classe **et** les mêmes horodatages ;
    - **un franchissement interdit reste compté.** L'invariant 3 en dépend, et c'est
      ce qui rend l'infraction dérivable côté client ;
    - **`null` et jamais `[]` pour `allowedClassIds`.** Une liste vide dirait « aucune
      classe ne passe », donc **tout** franchissement en infraction — se tromper de
      repli fabrique un écran d'alertes entièrement faux. Le repli est écrit trois
      fois (reducer, schéma de requête, relecture de preset) et testé aux trois.

    [ADR 0040](docs/adr/0040-une-ligne-porte-un-type.md), amendée le 2026-08-28 :
    types fusionnés, `{exit, forbidden}` hérité relu sous le nouveau type, et
    « Comptage seul » n'affiche plus ses deux sens.
32. **Les alertes se calculent côté client, et leurs compteurs viennent de `stats`.**
    Infractions au tracé et plaques recherchées partagent une seule feature,
    `features/alerts`. Quatre points :
    - **`plateWatchlist` voyage dans la requête sans être comparé à quoi que ce
      soit** : le serveur borne (dix entrées, seize caractères, quatre alphanumériques
      minimum) et **ne canonise pas** — la canonique du domaine conserve le tiret,
      celle de la comparaison client non, et deux définitions de « la même plaque »
      finiraient par diverger ;
    - **le journal d'alertes est borné (200) et sa borne est annoncée ; les KPI, eux,
      sortent de `stats.byLine[*].byDirection[*]`** et ne plafonnent pas. Afficher
      `alerts.length` comme un total est le défaut que l'ancienne chronologie a déjà
      payé (invariant 3) ;
    - **une seule infraction par franchissement**, sens interdit prioritaire sur voie
      réservée. `violationOf` et `violationCounts` appliquent la **même** priorité —
      y compris dans les ventilations `byKind` / `byClass` du résumé — et un test le
      verrouille : sans elle, la liste et le KPI diraient deux chiffres différents sur
      le même écran ;
    - **la liste de plaques n'est pas persistée** — elle décrit une recherche en
      cours, et écrire un numéro de plaque dans le `localStorage` du poste franchirait
      le cran de confidentialité que le projet impose déjà en laissant l'OCR décoché.

    [ADR 0041](docs/adr/0041-les-alertes-se-calculent-cote-client.md), que
    [ADR 0043](docs/adr/0043-les-alertes-quittent-la-video-pour-une-colonne.md) puis
    [ADR 0044](docs/adr/0044-les-alertes-deviennent-un-centre-de-notifications.md)
    déplacent — pile flottante, puis section du bas de page, puis colonne de 18 rem,
    et aujourd'hui **une cloche et un tiroir** dans la barre du studio. Aucune de ces
    trois ADR ne change un calcul ; `violationCounts` a seulement déménagé dans
    `shared/lib/violationTally.ts` et gagné ses ventilations.
33. **Un véhicule reçoit une photo, et une seule, dès qu'il y a quelque chose à
    montrer.** Deux JPEG — le véhicule recadré, sa plaque — pris sur la **même** image.
    **Trois causes depuis le 2026-08-31** (ADR 0051), en échelle de priorité :
    `plate_text` (plaque lue) > `plate_box` (plaque localisée, aucun texte publié) >
    `appearance` (apparence encodée pour une recherche par image, **sans vignette de
    plaque**). Publiées dans `snapshotKind` ; le rang ne se compare qu'à l'intérieur
    d'un tier — une confiance d'un côté, des pixels de l'autre — et les deux tiers en
    largeur portent la marge d'ADR 0050 (`TRAFFIC_SNAPSHOT_WIDTH_IMPROVEMENT`), sans
    quoi on encoderait un JPEG par image et par véhicule. `snapshotScore` n'est plus le
    drapeau de présence : c'est `snapshotMs`, et non-nul **implique** `plate_text`.
    Les cinq points d'origine restent vrais :
    - **le score est celui de l'image, jamais celui du vote.** `PlateTextVote.score`
      est une moyenne sur la vie du véhicule : il bouge quand une *autre* image est
      lue, donc classer les images dessus ferait recapturer sans rapport avec la
      qualité de l'image courante. Mesuré : capture 0,982 pour un vote à 0,852 ;
    - **aucun nouveau seuil.** Une plaque n'existe qu'au-dessus de « Confiance
      plaques » et un texte qu'au-dessus de « Confiance lecture » (ADR 0036) : la
      capture hérite des deux gratuitement ;
    - **jamais depuis une boîte reprojetée** (ADR 0010) : le point d'accroche est la
      branche *mesure fraîche* de `_detect_plates`, la seule où les deux boîtes, le
      texte et les pixels coexistent ;
    - **encodage à l'amélioration.** Mesuré sur 1 800 images, **du temps où la lecture
      était la seule cause** : 41 encodages, 98 ms, 0,056 % du temps d'analyse. Le
      chiffre qui compte est 41 — c'est la règle monotone qui protège le chemin
      critique, pas la vitesse de l'encodeur, et un test **compte les appels** pour
      cette raison. **Ces trois chiffres ne valent plus depuis ADR 0051** : la
      population photographiée est d'un autre ordre de grandeur, et les recopier
      serait malhonnête ;
    - **écriture au fil de l'eau depuis le 2026-08-28**, et non plus à la fin : un
      rappel `on_snapshot`, appelé depuis le thread worker exactement là où les octets
      viennent d'être produits, et **après** `record_snapshot` — le fichier existe donc
      quand l'aperçu suivant l'annonce. L'écriture finale reste comme filet, et le
      rappel suit la règle monotone : une écriture par amélioration retenue, jamais par
      lecture ;
    - **les captures sont purgées avec la vidéo**, pas avec le résultat : ce sont des
      plaques et des visages, la donnée même que le TTL court efface.

    [ADR 0042](docs/adr/0042-une-capture-par-vehicule.md), amendée par
    [ADR 0046](docs/adr/0046-les-captures-s-ecrivent-pendant-l-analyse.md) puis par
    [ADR 0051](docs/adr/0051-une-photo-des-qu-il-y-a-quelque-chose-a-montrer.md).
34. **La ReID d'apparence du tracker n'est gratuite que sur une tête avec NMS.**
    `botsort_reid.yaml` porte `with_reid: true` et `model: auto` depuis le début, et
    ADR 0013 l'a gardée sur une mesure — 0,3 à 3,5 ms par image — restée vraie pour v8,
    11 et 12 et **fausse d'un facteur 19** pour la famille 26, arrivée après elle. Sur
    une tête `end2end`, `trackers/track.py` ne pose pas son crochet et remplace `auto`
    par un `yolo26n-cls.pt` **téléchargé au runtime**, exécuté par recadrage et par
    image. Mesuré sur 1080p : `yolo26n` 61,81 → **15,09 img/s**, poste `tracker` 1,33 →
    **45,19 ms**, **franchissements identiques**. Quatre points :
    - **la question est posée au graphe, jamais au nom du fichier** (invariant 10, et
      ici il n'est pas décoratif) : `end2end` est une clé du *yaml de modèle*, donc un
      poids réexporté peut la porter sans s'appeler « yolo26 », et l'inverse.
      `head_is_end2end` lit `model.model.model[-1].end2end` ;
    - **le repli est conservateur** : sans réponse, l'apparence reste active, c'est-à-dire
      le comportement d'avant. Se tromper dans ce sens coûte de la cadence sur un modèle
      exotique ; dans l'autre, cela changerait des comptages sur v8/11/12 ;
    - **le fichier de base reste à `with_reid: true`** et seule la famille `end2end` est
      dérivée — d'où un `appearance_reid=True` par défaut sur `resolved_tracker_config`,
      qui laisse tous les appelants antérieurs inchangés. Seul `with_reid` est posé, pas
      `model` : `build_encoder` sort sur son premier argument, donc changer `model`
      serait un réglage sans effet (ADR 0016) ;
    - **le fichier de suivi ne peut plus être résolu avant le bail**, puisque la réponse
      dépend du modèle chargé : `_tracker_for` prend le modèle, `iter_video` résout dans
      son `with`, et `UltralyticsStream` reçoit le *résolveur* au lieu du chemin. Le nom
      du dérivé porte l'apparence, sinon deux jobs du même processus qui ne diffèrent que
      par elle écriraient dans le même fichier.

    Vérifié contre le vrai moteur : `yolo26n` 15,09 → **60,16 img/s** (3,99×),
    `yolov8n` **« comptage identique »**.
    [ADR 0047](docs/adr/0047-la-reid-d-apparence-n-est-gratuite-que-sur-une-tete-avec-nms.md).
35. **On peut rechercher un véhicule par image, et cela ne change aucun comptage.**
    Importer une photo, la cadrer, lancer : les véhicules ressemblants portent un
    `matchScore`. Ce n'est **pas** une réintroduction d'ADR 0016, qui a fermé la porte à
    *l'apparence branchée sur le compteur* — une recherche est un index de consultation,
    et `TestAucuneRegression` compare comptages, ventilations **et horodatages** avec et
    sans encodeur. Sept points :
    - **le tracker ne peut pas servir à cela**, et c'est mesurable :
      `emb_dists[dists_mask] = 1.0` annule la distance d'apparence dès que l'IoU tombe
      sous 0,5, et le descripteur d'`auto` fait ~64 dimensions de caractéristiques de
      *détection*. Un encodeur dédié est nécessaire ;
    - **le modèle est `vehicle-reid-0001`** (OSNet-AIN, 8,8 Mo, 512-d, MIT, rank-1
      96,31 % / mAP 85,15 % sur VeRi-776), récupéré par `scripts/fetch_reid_model.py`
      avec SHA-256 obligatoire. ONNX donc **CPU** — 21,8 ms mesurés par vignette — ce
      qui n'est tenable que parce qu'on encode **quelques fois dans la vie d'un
      véhicule**. Ce fichier a longtemps écrit « une fois par véhicule », et c'était
      faux : la règle monotone seule (« plus large que la meilleure vue ») est vraie à
      presque chaque image d'un véhicule qui approche, donc on encodait par image. Ce
      que la mesure comptait — « 8 suivis, 2 encodés » — était un nombre de
      *véhicules*, pas d'*encodages*. Il faut la **marge de largeur**
      (`TRAFFIC_REID_APPEARANCE_IMPROVEMENT`, 1,15) pour borner le total, et le
      **plafond par image** (`TRAFFIC_REID_MAX_PER_FRAME`) pour borner la rafale —
      [ADR 0050](docs/adr/0050-la-regle-monotone-de-la-reid-ne-bornait-rien.md) ;
    - **le prétraitement n'a aucun effet, sauf l'ordre des canaux.** Mesuré :
      `cos(x/255, (x/255−mean)/std) = 1,0` et même `cos(x/255, x) = 1,0` — le « AIN »
      est de l'*instance normalization*, donc le réseau est invariant aux
      transformations affines par canal. Mais `cos(rgb, bgr)` descend à **0,508** : le
      graphe veut du RGB, et nos images sont en BGR. Aucune normalisation d'intensité
      n'est appliquée — une arithmétique prouvée sans effet est du code mort ;
    - **les distributions se recouvrent, donc on classe et on ne tranche pas.**
      `sameMin` 0,387 < `diffMax` 0,891 : aucun seuil global n'est à la fois sûr et
      utile. L'écran promet des candidats à vérifier, jamais un verdict ;
    - **la clé monotone est la largeur de boîte**, pas « largeur × netteté ». La netteté
      demande un recadrage, donc des pixels que le domaine n'a pas — et la première
      version, qui interrogeait le pré-filtre avec `0.0`, excluait définitivement tout
      véhicule déjà encodé : une meilleure vue ne pouvait jamais remplacer la première.
      La netteté reste un **plancher** dans l'adaptateur ;
    - **le score au serveur, le seuil au client** — dérogation bornée à ADR 0041. Ce que
      cette ADR protégeait (corriger sans réanalyser) est préservé : `matchScore` est
      publié brut et le curseur vit dans `shared/lib/vehicleMatch.ts`, seul juge lu par
      trois features. Transporter les 512 flottants aurait multiplié par six le poids du
      registre dans l'aperçu ;
    - **l'image de requête ne touche jamais le disque** : troisième partie multipart, lue
      en mémoire, bornée à 2 Mio, absente de `config_json` — donc ni persistée ni relue.
      Le **cadrage est côté client**, ce qui borne ce qui part et fait converger les deux
      côtés de la comparaison sur `vehicle_crop`.

    `reid_min_vehicle_width_px = 96` est un garde de **coût** et non une falaise : la
    séparation décroît régulièrement (+0,462 à 208 px → +0,310 à 48 px) sans effondrement,
    contrairement au plancher d'OCR. Mesuré en pipeline : 8 véhicules suivis, **2 encodés**.
    [ADR 0048](docs/adr/0048-rechercher-un-vehicule-par-image.md).
36. **Le plafond absolu de cadence ne contredit plus la lecture à vitesse normale.**
    `ScenePacer` retient la période la **plus longue** des deux bridages. Sur une source
    60 fps, `analysisSpeed: 1` demande 16,7 ms et `maxAnalysisFps: 30` en impose 33,3 :
    le plafond gagnait, et l'aperçu défilait à **0,5×** — l'inverse exact de ce
    qu'ADR 0019 garantit. Mesuré, carte chaude, comptage seul : la machine tient
    **58,8 img/s** pour une cible de 60, et le défaut la coupait à 30. Trois points :
    - **le défaut de `maxAnalysisFps` repasse à `null`**, `analysisSpeed` reste à `1` :
      le partage de la machine n'est pas relâché, c'est la cadence de scène — le
      bridage qui décrit ce que l'utilisateur veut voir — qui redevient seul juge ;
    - **une migration de schéma ciblée** (`SETTINGS_SCHEMA_VERSION` 1 → 2) était
      nécessaire, sans quoi le correctif n'atteignait personne : `mergeSettings` ne
      réécrit jamais un choix persisté et `isSupportedFpsCap(30)` est vrai. `migrateV1`
      **retire** le champ, et seulement s'il vaut exactement `30` — un `60` ou un `null`
      est un choix explicite, et le défaire serait pire que le bug ;
    - **le profil ANPR n'y gagne rien** : à 17 à 21 img/s il est très loin sous les 30,
      qui ne mordaient jamais. Ce qui rend la vitesse normale atteignable avec l'ANPR
      est **le pas d'analyse** — à pas 3 sur du 60 fps, 20 img/s analysées font avancer
      la scène à vitesse normale.

    [ADR 0049](docs/adr/0049-le-plafond-absolu-contredisait-la-lecture-a-vitesse-normale.md).
37. **La règle monotone de la ReID ne bornait rien, et le GPU n'est pas le goulot.**
    Deux résultats d'un même lot d'optimisation, et le second contredit l'intuition qui
    l'a motivé :
    - **`should_embed` était vraie à presque chaque image.** « Plus large que la
      meilleure vue » l'est sur tout véhicule qui approche : on payait jusqu'à un
      encodage ONNX/CPU par image, **21,8 ms mesurés par vignette**, pour un étage que
      trois docstrings annonçaient comme « une fois par véhicule ». Corrigé par une
      **marge** (`TRAFFIC_REID_APPEARANCE_IMPROVEMENT`, 1,15) qui borne le *total* sur
      la vie d'une piste — 11 encodages au lieu d'une centaine — et un **plafond par
      image** (`TRAFFIC_REID_MAX_PER_FRAME`) qui borne la *rafale*. Le mode de panne
      d'ADR 0029 ne s'y rejoue pas : le consommateur de l'OCR est un **vote** qu'on
      affamait, celui de la ReID un **remplacement** ([ADR 0050](docs/adr/0050-la-regle-monotone-de-la-reid-ne-bornait-rien.md)).
      **La leçon vaut pour toute nouvelle clé de rang en largeur**, et elle s'est
      appliquée une seconde fois le 2026-08-31 à la largeur de boîte de plaque
      (ADR 0051) : l'étranglement du détecteur, une image sur trois, ne divise le
      problème que par trois ;
    - **la carte n'est pas saturée, et c'est mesuré.** `pipeline_bench --gpu-probe`
      relève une utilisation **p50 50 % / max 71 %** sur 1080p ANPR+OCR, pour une crête
      VRAM de 332 Mio sur 4096. Le nouveau poste `plateInference` montre que **16,74 des
      22,20 ms** de l'étage de plaques sont du calcul CUDA : le levier y est « moins de
      recadrages », pas « moins de Python ». Les deux instruments concordent —
      `inference + plateInference` = 52 % du budget, NVML en relève 50.

    **Deux pièges de mesure sur cette machine**, tous deux payés ici : l'horloge du GPU
    monte de **885 à 1518 MHz** au fil des premières courses, soit 1,72× — une
    comparaison de lots lue sur des courses successives conclut exactement l'inverse de
    la vérité, et il faut des **courses alternées sur carte chaude**. Et le bruit entre
    deux courses identiques est de **11 %** : tout gain inférieur n'existe pas. C'est
    pourquoi le budget de threads OpenCV (`TRAFFIC_OPENCV_THREADS`) reste à `0` — mesuré
    sans effet en pipeline réel, contrairement à ce qu'un micro-banc laissait espérer.
38. **Le moteur et son aval se recouvrent, et c'est tout ce qu'il restait à
    recouvrir.** `iter_video` est un générateur : le `track()` du modèle pour l'image
    suivante n'était appelé qu'une fois `AnalysisService` sorti de la précédente —
    plaques, OCR, captures, apparence. Un fil et un lot d'avance (`prefetch`, jumeau
    exact de `decode_ahead` un étage plus bas) les font avancer ensemble.
    `TRAFFIC_INFERENCE_PREFETCH_BATCHES`, **`1` par défaut**, `0` rend le chemin
    séquentiel à l'identique. Quatre points, et le troisième est le plus utile :
    - **aucun chiffre ne change** — ni l'ordre des appels au modèle, ni leurs
      arguments, ni l'état du tracker, ni l'ordre des images rendues. Cinq paires de
      courses alternées rendent les mêmes véhicules, franchissements et plaques ;
    - **le `join` n'est PAS borné**, contrairement à celui de `decode_ahead`, et
      `yield from` remplace la boucle `for`. Le fil tient le *modèle*, sous le bail
      d'`iter_video` : une expiration ou une fermeture laissée au ramasse-miettes
      relâcherait le bail sous une inférence en vol — invariant 9 ;
    - **le gain est de 1,10× au mieux, et l'hypothèse de départ était fausse.** Elle
      annonçait « moteur GPU contre aval CPU, donc `max` au lieu de la somme ».
      L'aval est **lui aussi** du GPU aux deux tiers : détection de plaques 22,0 ms
      par image dont 17,9 de passe avant. Deux flux CUDA sur une carte se
      sérialisent ; seules les moitiés CPU se recouvrent. Le gain suit donc
      exactement la quantité d'OCR de la scène — **1,10× quand elle publie, 1,05×
      quand elle localise sans lire, 1,00× quand elle ne se déclenche jamais** —, et
      c'est le *signe* (cinq paires alternées gagnées sur cinq) et non le rapport qui
      le rend crédible, 11 % étant le bruit de cette machine ;
    - **le rapport du banc ne s'additionne plus.** Les postes sont désormais
      concurrents : leur somme dépasse le temps par image, et `decodeAndOther`,
      calculé par différence, tombe à zéro. Ce n'est pas une panne de mesure.

    [ADR 0054](docs/adr/0054-le-moteur-et-son-aval-se-recouvrent.md).
39. **Un véhicule déjà vu est signalé, jamais fusionné.** Une **galerie interne au
    clip** (`counting/domain/appearance_gallery.py`) : chaque franchisseur y dépose
    l'apparence de sa meilleure vue et y est comparé aux précédents. Née d'un cas
    d'usage précis — la même vidéo doublée sur une timeline, dont la seconde moitié
    doit se reconnaître.

    **Ceci n'abroge pas ADR 0016**, et c'est la seule question qui compte. La galerie
    supprimée alimentait le **compteur** : elle ré-attachait une identité, donc `#1`
    réapparaissait au milieu d'une vidéo et le total n'avançait pas. Celle-ci ne
    touche aucun compteur — les deux numéros existent, les deux véhicules sont
    comptés, les deux franchissements aussi. Ce n'est pas une nuance de vocabulaire :
    `TestAucuneRegression` compare `crossings`, `tracked_vehicles`, `by_class`, la
    ventilation `by_line` **entière** et les **horodatages**, avec et sans galerie.
    Son échec devrait faire retirer la fonctionnalité, pas la corriger.

    Cinq points qui ne se devinent pas :
    - **interroger avant de déposer.** `lookup` exclut bien son propre numéro, mais
      déposer d'abord ferait remonter, au franchissement **suivant du même
      véhicule**, sa propre vue précédente à un score proche de 1 — un aller-retour
      se signalerait lui-même ;
    - **la garde temporelle** : un déposant n'est éligible que s'il avait **disparu**
      avant que le candidat n'apparaisse. Deux véhicules simultanément visibles ne
      peuvent pas être le même objet physique, et c'est le faux positif le plus
      visible en trafic dense. La galerie tient donc sa **propre** fenêtre de
      présence (`observe` sur toute piste visible) plutôt que de l'interroger sur la
      session — ce qui lierait un index de consultation au cœur du comptage ;
    - **le franchissement contourne la marge de largeur et le plafond par image, pas
      les planchers de l'adaptateur.** La question se pose au moment du passage, et
      un franchissement n'a pas de seconde chance — c'est un instant, pas un état.
      Mais un embedding sur 40 px ressemble surtout au flou (ADR 0048) : un score
      calculé dessus serait plausible et faux. Le coût est donc borné par le nombre
      de **franchissements**, pas d'images, ce qui évite d'avoir à inventer la marge
      d'ADR 0050 ;
    - **deux seuils et pas un** — `reid_rematch_min_similarity` côté serveur,
      `DEFAULT_REMATCH_THRESHOLD` (0,75) côté client, tous deux distincts de leurs
      jumeaux d'ADR 0048. Ici personne n'a demandé ce véhicule, donc un faux positif
      coûte plus cher ; et surtout on compare à **tous** les précédents, donc le
      meilleur score d'un lot de cent est mécaniquement plus haut que celui d'un lot
      de deux — un seuil partagé dériverait avec la durée de la vidéo ;
    - **la colonne « Déjà vu » du registre est cliquable et ouvre les deux véhicules
      côte à côte.** Sans elle, l'écran affirmait une ressemblance sans donner le
      moyen de la vérifier : comparer deux captures demandait d'ouvrir la première,
      la fermer, retrouver la seconde rangée, l'ouvrir — donc de comparer **de
      mémoire**. `model/rematchPair.ts` en est le seul juge et cherche l'antécédent
      dans **tous** les véhicules, jamais dans le jeu filtré ; l'ordre est
      chronologique, jamais « celui qu'on a cliqué » ;
    - **`isViolation` ne se décide plus sur `alert.line !== null`.** Ce raccourci
      était exact tant que seules les infractions nommaient une ligne, et il est
      devenu faux à l'instant où une re-détection en a porté une : elle aurait été
      teintée, comptée et filtrée comme une infraction, sans que rien ne lève. Une
      propriété vraie par coïncidence qui cesse de l'être en silence — la famille de
      panne que ce fichier documente le plus.

    **Le seuil n'est pas mesuré**, et l'ADR le dit : la vidéo doublée est le cas
    idéal (métrage identique au pixel près) et valide le câblage, pas le chiffre.
    `scripts/reid_bench.py` est l'outil pour trancher sur du métrage réel.
    [ADR 0055](docs/adr/0055-signaler-un-vehicule-deja-vu.md).

## Ce que l'analyse signale — les alertes

Depuis le 2026-08-27, l'écran ne fait plus que compter et ranger : il **signale**.
Trois familles, une seule feature (`features/alerts`), un seul type d'alerte —
elles partagent tout ce qui compte à l'écran : un véhicule, un instant, une
gravité, un motif.

- **les infractions** — sens interdit, ligne infranchissable, voie réservée. Le
  prédicat vit dans `shared/lib/lineViolations.ts`, les règles résolues dans
  `shared/lib/lineRules.ts` : les alertes signalent, le tableau de bord compte, le
  registre affiche, et un seul juge les départage ;
- **les plaques recherchées** — saisies dans le tiroir Détection, comparées au
  **vote** de plaque (invariant 4). Correspondance *exacte* en rouge, *probable* —
  l'une contient l'autre — en orange, parce qu'ADR 0029 documente que l'OCR perd
  régulièrement le premier caractère d'une plaque. Différé seulement : le direct n'a
  pas d'ANPR ;
- **les véhicules déjà vus** (2026-09-01, [ADR
  0055](docs/adr/0055-signaler-un-vehicule-deja-vu.md)) — chaque véhicule qui
  franchit une ligne, **quel qu'en soit le type**, est comparé aux franchisseurs
  antérieurs de la même analyse. Case à cocher dans le tiroir Détection, **éteinte
  par défaut**. À ne pas confondre avec la recherche par image (ADR 0048), qui
  compare à une photo fournie : ici la vidéo est comparée à elle-même, et les deux
  peuvent porter un score sur le même véhicule sans dire la même chose.

Cinq points qui ne se devinent pas :

- **deux sources, et la seconde remplace la première.** `useAlertLog` accumule
  pendant l'analyse depuis l'aperçu **vivant** — une alerte est un *événement*, elle
  suit le serveur, là où une boîte suit l'image. Une fois terminé, `alertsFromResult`
  relit le résultat complet à la tête de lecture, sur le tracé **courant** : déclarer
  un sens interdit après coup fait apparaître ses alertes sans réanalyser ;
- **on filtre avant de borner, jamais l'inverse.** `crossingsBefore` existe pour cela
  au lieu de réutiliser `crossingsUpTo`, qui borne à 200 *franchissements* : sur un
  carrefour chargé, les infractions les plus anciennes disparaîtraient avant d'avoir
  été cherchées ;
- **les pistes plutôt que le registre pour les plaques, pendant l'analyse.** Le
  registre de l'aperçu est restreint aux franchisseurs (ADR 0026) ; une plaque
  recherchée peut appartenir à un véhicule à l'arrêt ;
- **la couleur encode la gravité, l'icône encode la nature.** Rouge pour une
  infraction et pour une plaque trouvée à coup sûr, orange pour une correspondance
  probable. C'est un amendement assumé à « le rouge est réservé aux échecs » de
  `StaleResultBanner` : il veut désormais aussi dire « la scène présente une
  infraction », et le titre porte la différence ;
- **une hypothèse porte son pourcentage** (2026-08-31). Une plaque recherchée affiche
  sa **confiance de lecture**, un véhicule ressemblant sa **ressemblance** — le titre
  dit « exacte » ou « probable », le chiffre dit à quel point. Sans lui, les deux
  seuls faux positifs que cet écran puisse produire — l'OCR qui perd un caractère
  (ADR 0029), des distributions de similarité qui se recouvrent (ADR 0048) — se
  présentent comme des certitudes. Quatre points qui ne se devinent pas :
  - **une infraction n'en porte pas**, et c'est délibéré : un franchissement est un
    fait observé, pas une hypothèse. La plaque qu'il porte n'est qu'un renseignement
    de contexte, souvent absente — le franchissement est émis avant la passe OCR de
    la même image ;
  - **le score vient d'une carte `globalId → scores` passée en prop, jamais de
    l'`Alert`** — même piège que `capturedMs` : `mergeAlerts` garde la **première**
    occurrence d'une clé, donc un score porté par l'alerte serait gelé à sa première
    publication alors que les deux montent en cours d'analyse (ADR 0050, invariant 4).
    Une carte figée à « 57 % » sous un registre qui affiche « 84 % » pour le même
    véhicule se lit comme un désaccord entre deux écrans ;
  - **le repli sur le score gelé de l'alerte reste nécessaire pour les plaques** : le
    registre de l'aperçu est restreint aux franchisseurs (ADR 0026), et une plaque
    recherchée peut appartenir à un véhicule à l'arrêt, absent de la carte ;
  - **`alertScore` nomme l'unité en même temps que le nombre** (`read` / `match`).
    Lecture et ressemblance ne mesurent pas la même chose, et les afficher sous le
    même mot serait une erreur d'unité invisible, les deux chiffres étant plausibles.

  Les deux se lisent aussi **sous la photo en grand** : `shared/lib/snapshotCaption.ts`
  est le juge unique de cette légende — elle vivait dans le registre seul, et la copie
  du studio avait déjà perdu la confiance de lecture en route. `formatScore` a suivi le
  même chemin vers `shared/lib/score.ts`, trois features l'affichant ;
- **rien ne s'affiche tant qu'aucune règle n'est posée ni aucune plaque cherchée.**
  Un « 0 infraction » sous une règle que personne n'a déclarée se lit « aucune
  infraction », l'inverse de la vérité — même honnêteté que le « — » de « Passages en
  entrée ».

**Elles vivent derrière une cloche, jamais sur la vidéo ni dans une colonne**
(2026-08-28, [ADR
0044](docs/adr/0044-les-alertes-deviennent-un-centre-de-notifications.md), qui amende
[ADR 0043](docs/adr/0043-les-alertes-quittent-la-video-pour-une-colonne.md)). Trois
surfaces sont mortes de la **même** cause — la place qu'elles occupaient n'était pas
proportionnelle à ce qu'on venait y chercher : la pile flottante posée sur la scène,
la section du bas de page, puis la colonne de 18 rem qui les remplaçait toutes deux.
Cette dernière réglait ce qu'on lui demandait et prenait ses 18 rem à la vidéo **en
permanence**, plus 3 rem aux résultats (23 → 20), pour une liste qu'on consulte par
à-coups. La grille du studio redevient donc inconditionnelle
(`xl:grid-cols-[minmax(0,1fr)_23rem]`), sans classe calculée ni point de rupture
`2xl`.

`AlertsPanel` est aujourd'hui le **cinquième tiroir** de la barre, fourni par le
studio comme « Géométrie » (`panels`). Neuf points :

- **la pilule ne porte aucun mot** : l'icône bascule entre `Bell` et `BellRing` — une
  cloche muette et une cloche qui sonne se distinguent d'un coup d'œil là où « 0 » et
  « 3 » demandent de lire un chiffre — et la pastille porte le **compte** et la
  **gravité**, rouge dès qu'une alerte `critical` existe, orange sinon. `ExtraPanel`
  gagne pour cela deux champs optionnels, `icon` et `badge` ; le libellé passe en
  `aria-label` et en infobulle, jamais nulle part ;
- **`alertsArmed` décide de la pilule autant que du panneau.** Un `AlertsPanel` qui
  rend `null` laisserait un bouton qui n'ouvre rien : le tiroir n'est donc pas monté
  du tout sans règle posée ni plaque recherchée ;
- **la pilule n'est jamais grisée pendant une analyse**, contrairement à ce que
  `disabled` fait aux quatre tiroirs de réglages : lire ses alertes pendant que ça
  tourne est tout l'objet du changement. Elle suit `hasSource`, comme les autres ;
- **le résumé passe devant la liste.** C'est le changement de fond : une liste dit ce
  qui s'est passé un par un, elle ne dit jamais ce qu'il faut en penser. Sur cinquante
  infractions, la question est « lesquelles, et faites par quels véhicules », pas
  « quelle est la trente-septième » ;
- **trois axes de filtre qui se composent** — nature, **type de véhicule** (la classe
  votée, invariant 4), ligne — chacun avec son compte, et les comptes portent sur le
  journal **entier** et non sur la liste déjà filtrée : des comptes qui rétrécissent à
  mesure qu'on filtre empêchent de savoir ce qu'on trouverait en changeant d'axe.
  `alertFilters.ts` en est le seul juge, et `filterAlerts` rend la liste **par
  référence** quand rien n'est filtré — le panneau se rerend à chaque aperçu SSE ;
- **deux sources de chiffres, jamais mélangées.** Le résumé vient de
  `violationCounts` (dérivé de `stats`, sans plafond), le flux du journal (borné à
  200, borne **annoncée**). Afficher `alerts.length` comme un total ferait plafonner
  un compteur en silence — invariant 3, le défaut que l'ancienne chronologie a déjà
  payé ;
- **`violationCounts` a déménagé dans `shared/lib/violationTally.ts`**, aux côtés de
  `lineRules.ts` et `lineViolations.ts` : deux features en ont besoin, et une feature
  n'importe jamais une autre. Il y gagne `byKind` et `byClass`, qui appliquent la
  **même** priorité que `violationOf` — sens interdit avant voie réservée — ce qu'un
  test verrouille : sans elle le résumé compterait 6 là où le KPI affiche 3.
  `StudioPage` le calcule une fois et le passe en prop, pour que les deux surfaces
  affichent le **même** nombre ;
- **une seule région vivante, et elle ne porte qu'un nombre.** La pile flottante
  annonçait chaque carte en `aria-live` ; sur un carrefour chargé cela faisait d'un
  lecteur d'écran un métronome. Le compteur (« 7 alertes »), en `polite` pendant
  l'analyse seulement, dit qu'il se passe quelque chose en une phrase courte ;
- **la carte porte un filet de gravité à gauche** (`SEVERITY_RAIL`, opaque) en plus de
  son écrin teinté à 10 % : c'est lui qui rend une pile parcourable sans lecture, l'œil
  suivant une colonne de traits. La teinte reste celle de la **gravité**, jamais celle
  de la ligne — qui encode déjà une identité sur le canvas.

Dans les Résultats, **le chiffre de tête ne défile pas** : l'entête et « Passages
globaux » sont collés en haut du défilement, le reste passe dessous. C'est le total
auquel toutes les autres cartes se comparent — les cartes par type en sont la somme
exacte — et sorti de l'écran il obligeait à remonter pour retrouver le total dont on
venait de lire le détail. Fond opaque obligatoire, et `-top-px` plutôt que `top-0` :
un arrondi de sous-pixel laisse sinon passer une ligne de carte au-dessus de la tête.
Son défilement est dessiné (`.panel-scroll`, index.css) avec `scrollbar-gutter:
stable` — sans elle, l'apparition de la barre système au moment où une carte de trop
arrive décale tout le contenu de la colonne, et cette barre fait 17 px opaques sur
Windows. La page, elle, ne change pas de forme : le cadre reste à `max-w-[1600px]` et
la gouttière à 1,5 rem (`--app-gutter`), tous deux réduits une fois puis rétablis le
jour même — **une marge n'est pas de la place perdue**.

Une alerte est **cliquable** et amène la tête de lecture à son instant — la seule
chose de cet écran qui le soit. L'ancienne chronologie cliquable avait été retirée
parce qu'on y *parcourait* le temps, ce que la barre de lecture fait déjà ; ici on
saute à un fait précis, et une alerte invérifiable ne vaut rien. Le geste est
désactivé pendant une analyse et en direct, où la vidéo est pilotée par l'aperçu.

## Il n'y a plus de mesure de vitesse

Supprimée le 2026-08-21 ([ADR
0034](docs/adr/0034-la-mesure-de-vitesse-est-retiree.md), qui abroge [ADR
0025](docs/adr/0025-la-calibration-se-fait-par-ligne.md)) : ni `domain/speed.py`,
ni `domain/scale_field.py`, ni échelle globale px/m, ni longueur réelle par ligne,
ni colonne « Vitesse » au registre ou aux CSV. Les champs `pixelsPerMeter`,
`lengthMeters`, `speedPxS`, `avgSpeedPxS` et `avgSpeedKmh` ont quitté le contrat
des deux côtés, et la migration `7c1f4b2ae903` retire les deux colonnes de
`job_vehicles`.

Conséquence à connaître : **une ligne n'a plus aucun champ que le serveur
interprète.** Nom et rôles de sens ne font que traverser, donc corriger un tracé
après coup ne demande plus jamais de réanalyser — ce qui n'était pas vrai de la
longueur.

Un résultat archivé garde les anciennes clés dans son `result.json.gz` ; elles sont
ignorées à la relecture, aucun compteur n'en dépendant.

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
# « Le GPU est-il saturé ? » — utilisation NVML à 5 Hz et crête VRAM torch.
uv run python scripts/pipeline_bench.py --videos data/jobs/<id> --anpr --ocr \
    --frames 600 --warmup 40 --start 11 --gpu-probe --json out/gpu.json
# « Le recouvrement moteur/aval sert-il sur MA scène ? » — 0 rend le chemin
# séquentiel d'avant ADR 0054, dans le même processus, comme témoin.
uv run python scripts/pipeline_bench.py --videos data/jobs/<id> --anpr --ocr \n    --frames 250 --warmup 30 --start 20 --prefetch 0 --json out/sequentiel.json
```

**Deux pièges de mesure propres à cette machine, et ils dominent tout le reste.**
L'horloge du GPU monte de **885 à 1518 MHz** au fil des premières courses d'une
session, soit **1,72×** : quatre courses successives font croire à un gain de 1,8×
qui n'est que la montée en régime, et une comparaison de lots lue ainsi conclut
l'inverse de la vérité. Les mesures se font donc en **courses alternées, carte déjà
chaude**, et `--warmup` chauffe le *modèle*, pas la *carte*. Second piège : le bruit
entre deux courses strictement identiques est de **11 %** — tout gain inférieur
n'existe pas, et le prétendre serait malhonnête.

Six choses à savoir avant de lire un rapport :

- **`--gpu-probe` répond directement à « la carte est-elle saturée »**, ce qu'aucun
  poste ne disait : `inference` est un *plancher* de temps GPU et `plateDetect`
  mélange GPU et CPU, donc la fourchette allait de 16 à 95 %. Le poste
  `plateInference` tranche l'étage dominant — mesuré, 16,74 des 22,20 ms sont du
  calcul CUDA — et les deux instruments doivent concorder : `inference +
  plateInference` valait 52 % du budget quand NVML en relevait 50 ;
- **`plateInference` et `gmc` sont CONTENUS** dans `plateDetect` et `tracker`, et le
  rapport le dit désormais (« inclus dans … ») : les additionner donnerait 82 % pour
  un seul étage ;

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

**L'horodatage d'un passage était celui de la sortie de bande** — jusqu'à **2,2 s**
de retard pour un gros véhicule abordant une ligne presque parallèlement, le
comptage juste et sa date tardive. Corrigé le 2026-08-25 ([ADR
0038](docs/adr/0038-un-franchissement-est-date-de-son-intersection.md), qui
**complète** ADR 0018 sans rien lui retirer) : le compteur retient à chaque image
l'**écart signé** au trait, et quand le signe bascule il retient l'instant
**interpolé** de l'intersection. Le côté tranché décide *s'il faut compter*, l'écart
brut dit *quand c'est arrivé*. **Aucun comptage ne change** — c'est la propriété qui
rend le changement livrable, et tous les tests de `TestBandeMorte` sont intacts.

Trois conséquences qui ne se devinent pas :

- **l'ordre d'émission n'est plus l'ordre des dates.** La bande est proportionnelle
  à la boîte, donc un poids lourd peut être daté *avant* une moto pourtant comptée
  plus tôt. C'était l'unique objection d'ADR 0018, et elle se règle en trois
  endroits : `result.crossings` trié après la boucle, `pending_crossings` trié par
  trame SSE, et `appendCrossings` qui **insère** au lieu d'empiler. Sans le
  troisième, `previous.deltaMs` — le temps de traversée du carrefour — deviendrait
  négatif. La base de données, elle, triait déjà ;
- **`DirectionTally.record` prend `min` / `max`** au lieu de « première » et
  « dernière écriture », des deux côtés (`models.py` et `replay.ts`). Sinon un sens
  rendrait `first_ms > last_ms` ;
- **un résultat archivé garde ses anciennes dates.** Il n'est pas réanalysé, aucune
  clé ne change, il ne cesse pas de se relire — il est simplement daté à l'ancienne.
  Deux analyses du même clip, avant et après, montrent **les mêmes totaux à des
  secondes différentes**.

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

- `uv` vit dans **`C:\Users\User\.local\bin\uv.exe`** (et plus dans
  `%LOCALAPPDATA%\Microsoft\WinGet\Packages\astral-sh.uv_*\`, que les versions
  antérieures de ce fichier indiquaient : ne pas l'y chercher). Ce dossier **est** sur
  le `PATH` de PowerShell ; il ne l'est pas toujours pour un shell lancé autrement, et
  les hooks pre-commit qui appellent `uv run` échouent alors avec « Executable `uv` not
  found ». L'ajouter au `PATH` avant de committer.
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
| Nombre | 1700 (1 skip) | 882 |
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
