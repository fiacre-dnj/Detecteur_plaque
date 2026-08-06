# L'API

Ce document explique **ce que les routes veulent dire**. La forme exacte des
schémas — champs, bornes, exemples — est dans OpenAPI, qui est généré depuis le
code et ne peut donc pas mentir :

- `http://localhost:8000/api/docs` — Swagger UI
- `http://localhost:8000/api/redoc` — ReDoc
- `http://localhost:8000/api/openapi.json` — le schéma brut

Tout vit sous **`/api/v1`**. La documentation, elle, est sous `/api/docs` sans
version : ce n'est pas l'API, c'est sa notice.

## Ce qu'il faut savoir avant de lire la liste

**Le fil parle camelCase, Python parle snake_case.** `CamelModel` fait la
traduction dans les deux sens ; le miroir TypeScript de
`frontend/src/shared/api/contracts.ts` reprend les noms du fil, exactement.

**Les erreurs sont des Problem Details (RFC 9457)**, jamais un `{"error": "..."}`
maison. Trois champs comptent :

| Champ | Pour qui | Stabilité |
|---|---|---|
| `code` | la machine — le frontend branche dessus | stable |
| `detail` | l'humain, en français | peut changer sans préavis |
| `errors[]` | l'humain, **par champ** | présent sur les 422 |

Le détail par champ d'un 422 vit dans `errors[]` et **pas** dans `detail` : c'est
lui qui dit *lequel* des réglages est refusé, ce qu'un message global ne peut pas
faire.

**Les coordonnées sont en pixels de la vidéo source**, toujours. La seule
exception est le mode direct, où elles sont en pixels de l'image envoyée — et
c'est précisément pour cela que le serveur renvoie les dimensions qu'il a reçues
(voir plus bas).

**Le temps est du temps de scène** : `frame_index / fps × 1000`. Aucun horodatage
métier ne vient de l'horloge murale.

---

## Santé

| Méthode | Route | Ce qu'elle dit |
|---|---|---|
| GET | `/health/live` | le processus répond |
| GET | `/health/ready` | le service peut travailler — il **écrit réellement** dans `dataDir` |
| GET | `/health` | le diagnostic complet : device, version d'ultralytics, modèles résidents, disponibilité ANPR |

Les trois sont distinctes parce qu'elles répondent à trois questions
différentes. `live` est ce qu'un orchestrateur sonde toutes les trente secondes —
il ne doit rien coûter. `ready` vérifie l'inscriptibilité du disque, ce qui a un
coût, et n'a de sens qu'avant d'envoyer du travail. `health` est pour l'humain qui
cherche pourquoi une analyse s'est mal passée.

`plateAvailable: false` dans `/health` n'est pas une erreur : le modèle de plaques
est optionnel, et l'interface désactive l'option **en disant pourquoi** plutôt que
de produire une analyse sans plaques que rien n'expliquerait.

---

## Modèles

| Méthode | Route | |
|---|---|---|
| GET | `/models` | catalogue, état de résidence, palier, taille |
| POST | `/models/{modelId}/preload` | charge le modèle maintenant |
| DELETE | `/models/{modelId}/loaded` | libère l'instance |

Un modèle a trois états, et la distinction compte pour l'utilisateur : *au
catalogue* (connu, pas de fichier), *téléchargé* (fichier présent), *résident*
(chargé en mémoire). Le premier usage d'un modèle non téléchargé le récupère, ce
qui prend des dizaines de secondes — d'où le préchargement, qui rend ce délai
explicite au lieu de le faire subir au milieu d'une analyse.

**Le palier d'un modèle vient du catalogue, jamais de son nom de fichier.**
Renommer un fichier ne change pas ce qu'il est.

---

## Analyse différée

| Méthode | Route | |
|---|---|---|
| POST | `/jobs` | dépose une vidéo + une configuration → `202` |
| GET | `/jobs` | historique paginé, filtrable |
| GET | `/jobs/{jobId}` | l'état courant — **sans** la configuration |
| GET | `/jobs/{jobId}/config` | la configuration qui a produit ce job |
| GET | `/jobs/{jobId}/events` | progression en SSE |
| GET | `/jobs/{jobId}/result` | le résultat complet (`json.gz`) |
| GET | `/jobs/{jobId}/vehicles` | le registre, paginé |
| GET | `/jobs/{jobId}/crossings` | les franchissements, paginés |
| GET | `/jobs/{jobId}/export.csv` | le registre en CSV |
| DELETE | `/jobs/{jobId}` | annule si en cours, purge sinon |

### Le dépôt est en `multipart/form-data`

Deux parties : `file` (la vidéo) et `request` (la configuration, en JSON). La
seconde est une **chaîne**, pas un fichier — l'envoyer comme un `Blob` avec un
type `application/json` la fait traiter comme un second fichier, et le serveur
répond un 422 dont le message ne désigne pas la cause.

### Pourquoi `/config` est une route séparée

`GET /jobs/{jobId}` est interrogée toutes les trois secondes pendant toute
l'analyse, et c'est la même forme que chaque trame SSE. Y joindre la
configuration — géométrie comprise — la ferait voyager des centaines de fois pour
une valeur qui ne change jamais. Un test garantit cette séparation.

Sans `/config`, « ouvrir » et « relancer » une analyse de l'historique perdraient
silencieusement la géométrie de l'utilisateur, qui devrait retracer ses lignes de
mémoire.

### Le SSE

`/jobs/{jobId}/events` émet la même forme que `GET /jobs/{jobId}`. Le flux se
termine sur un statut terminal. Un client qui perd la connexion peut retomber sur
le sondage — c'est ce que fait l'interface, qui fusionne les deux sources en
gardant **la progression la plus avancée** : une trame en retard ne doit jamais
faire reculer la barre.

### La suppression fait deux choses

`DELETE /jobs/{jobId}` **annule** un job en cours et **purge** un job terminé.
Une seule route parce que c'est un seul geste du point de vue de l'utilisateur —
« je n'en veux plus » — et que l'obliger à savoir dans quel état est son job pour
choisir la bonne route serait lui faire porter un détail d'implémentation. Une
annulation produit le statut `cancelled`, **pas** `error` : l'utilisateur sait ce
qu'il a fait, lui dire que l'analyse a échoué serait faux.

---

## Comptage en direct — WebSocket

    ws://localhost:8000/api/v1/realtime      (wss:// depuis une page https:)

Le protocole est **strictement séquencé** :

```
client → init          {"type":"init","request":{…}}
serveur → ready        {"type":"ready","frameWidth":null,"frameHeight":null,"modelId":…,"device":…}
client → frame         {"type":"frame","timestampMs":123.4}
client → <JPEG binaire>                      ← immédiatement après, rien entre les deux
serveur → frameResult  {"type":"frameResult","frameWidth":960,"frameHeight":540,…}
```

`request` est **exactement** l'`AnalysisRequest` de `POST /jobs`. C'est ce qui
garantit qu'un même tracé donne les mêmes chiffres dans les deux modes ; deux
schémas parallèles finiraient par divulguer une différence de validation.

### `ready` renvoie les dimensions reçues — la règle la plus importante de l'API

Le client réduit ses images pour tenir le débit, et doit donc mettre sa géométrie
à la même échelle. **S'il oublie, rien ne se passe.** Le serveur applique
consciencieusement une ligne tracée pour du 1280 px à une image de 960 : elle est
comptée 25 % à côté, aucune erreur n'est levée, aucun journal n'est écrit, et les
chiffres restent plausibles. C'est le pire mode de défaillance qu'un logiciel de
mesure puisse avoir, parce qu'il est silencieux et crédible.

Le serveur ne peut pas le détecter seul : il ne connaît pas la résolution que le
client *croit* envoyer. Il dit donc ce qu'il a reçu, et c'est au client de
comparer et de refuser s'il y a un écart. `frameWidth`/`frameHeight` sont `null`
dans `ready` — aucune image n'a encore été décodée, et les inventer serait
exactement le mensonge que ce message existe pour empêcher. Ils sont réels dans
chaque `frameResult`, répétés à chaque image parce qu'une webcam peut renégocier
sa résolution en cours de session.

### Les codes de fermeture disent quoi faire

| Code | Sens | Réessayer ? |
|---|---|---|
| `1008` | origine refusée, ou `init` invalide | **non** — la requête est fautive |
| `1013` | une session est déjà active | oui |
| `1011` | erreur interne | oui, plus tard |
| `1006` | connexion perdue (fabriqué par le navigateur) | oui |

La distinction entre `1008` et `1013` n'est pas cosmétique : proposer
« Réessayer » après un `1008` enverrait l'utilisateur dans une boucle d'échecs
identiques.

La raison de fermeture est tronquée à **123 octets** — la RFC 6455 borne le corps
du message de fermeture, et une raison trop longue fait échouer la fermeture
elle-même, ce qui prive le client de son explication.

### L'`Origin` est vérifiée à la main

Un handshake WebSocket ne passe **jamais** par le middleware CORS. La vérification
est donc explicite, par comparaison exacte à `TRAFFIC_CORS_ORIGINS` — une
comparaison par préfixe laisserait passer `http://localhost:5173.evil.com`.

Une frame illisible produit un message `error` **sans fermer** : un JPEG tronqué
est un incident normal, et le client en enverra un autre dans quelques
millisecondes.

---

## Presets de géométrie

| Méthode | Route | |
|---|---|---|
| GET | `/presets` | la liste, pour choisir |
| POST | `/presets` | enregistre la géométrie courante → `201` |
| GET | `/presets/{id}?width=&height=` | **relit et met à l'échelle** |
| PUT | `/presets/{id}` | remplace |
| DELETE | `/presets/{id}` | supprime → `204` |

Un preset porte **la résolution pour laquelle il a été tracé**, et c'est ce qui le
rend réutilisable. Une ligne à `y = 400` traverse le milieu d'une image de 720 px
de haut et sort du cadre d'une image de 360 : sans cette information, recharger le
preset placerait les lignes ailleurs sans qu'aucune erreur ne le signale.

`GET /presets/{id}` avec `width` et `height` convertit la géométrie **et
l'annonce** par `scaled: true`. La conversion silencieuse serait pire que pas de
conversion : une géométrie qui bouge sans prévenir se lit comme un bug.
`originalWidth`/`originalHeight` restent toujours ceux de l'enregistrement, pour
que l'interface puisse dire d'où vient le preset.

Les deux axes sont mis à l'échelle **indépendamment**. Passer d'un 16/9 à un 4/3
déforme donc la géométrie — c'est correct, puisque l'image subit la même
déformation ; une homothétie uniforme laisserait une bande morte.

La liste, elle, rend les coordonnées d'origine : elle sert à parcourir des noms,
pas à charger, et ne connaît pas la résolution de la vidéo courante.

Un nom déjà pris est refusé en **409**, jamais écrasé — perdre une géométrie qu'on
croyait garder ne se découvre qu'en la rechargeant, bien trop tard.

---

## Benchmark

| Méthode | Route | |
|---|---|---|
| POST | `/benchmark` | mesure des modèles → `202` |
| GET | `/benchmark` | historique paginé |
| GET | `/benchmark/latest` | le dernier run |
| GET | `/benchmark/{runId}` | un run |
| GET | `/benchmark/{runId}/events` | progression en SSE |
| DELETE | `/benchmark/{runId}` | annule |

`/benchmark/latest` est déclarée **avant** `/benchmark/{runId}` : FastAPI résout
dans l'ordre, et l'inverse ferait interpréter « latest » comme un identifiant de
run.

Le protocole de mesure est ce qui donne un sens aux chiffres :

1. **une seule image de référence** pour tous les modèles — comparer sur des
   images différentes ne compare rien, et son `imageHash` est publié pour qu'on
   sache si deux runs sont comparables ;
2. **un run de chauffe est exécuté puis écarté** — la première inférence paie
   l'allocation des tampons et vaut plusieurs fois les suivantes ;
3. **médiane et p95**, jamais une moyenne : une pause du ramasse-miettes déplace
   une moyenne et laisse la médiane tranquille ;
4. les seuils sont ceux de **la requête**, pas ceux du catalogue ;
5. chaque modèle est **libéré après sa mesure** — vingt modèles résidents
   épuisent la mémoire — et la ligne le dit via `released` ;
6. un modèle en échec porte son `error` et **le run continue**.

`loadMs` vaut `0` si le modèle était déjà résident, et non `null` : la valeur est
connue, et elle est nulle.

Un seul benchmark à la fois. Deux runs simultanés se mesureraient l'un l'autre.

---

## Pagination

Toutes les routes qui listent rendent la même forme :

```json
{ "items": [], "total": 0, "limit": 50, "offset": 0 }
```

Limit/offset et non curseur : ces listes se parcourent par pages numérotées.
`limit` est borné à 200 — une page de dix mille lignes n'est utile à personne et
tient en mémoire des deux côtés.

## Limites et refus

| Situation | Statut | `code` |
|---|---|---|
| job, modèle ou preset inconnu | 404 | `*_not_found`, `unknown_model` |
| nom de preset déjà pris | 409 | `preset_name_taken` |
| configuration invalide | 422 | `validation_error` |
| fichier trop gros (`TRAFFIC_MAX_UPLOAD_MB`) | 413 | `payload_too_large` |
| format vidéo refusé | 415 | `unsupported_media_type` |
| trop de requêtes | 429 | `rate_limited` |
| persistance non configurée | 503 | `persistence_unavailable` |

Un `503` sur `/presets` ou `/benchmark` n'est pas une panne : ces deux
fonctionnalités exigent la base, et le dire vaut mieux que de rendre une liste
vide qui se lirait comme « vous n'avez rien enregistré ».

## Limitation de débit

Par adresse IP, en fenêtre glissante, en mémoire du processus. Un refus porte
`Retry-After` en secondes — et il est honnête : réessayer après ce délai réussit.

| Portée | Défaut | Pourquoi cette valeur |
|---|---|---|
| globale | 60/min | |
| `POST /jobs` | 10/min | chaque dépôt écrit des centaines de Mo sur le disque **avant** toute borne de concurrence |
| `POST /benchmark` | 2/h | jusqu'à vingt modèles mesurés et téléchargés |
| handshake `/realtime` | 10/min | le middleware CORS ne voit jamais passer un handshake |

Les limites de chemin ne portent que sur `POST` : sonder la progression toutes les
trois secondes est une lecture bon marché, et la brider casserait l'interface.
Chaque règle a sa propre file, donc épuiser le quota de dépôt ne bride pas les
lectures.

Chaque limite se règle par `TRAFFIC_RATE_LIMIT_*` ; `0` **désactive** la limite
correspondante — utile derrière une passerelle qui limite déjà.

Un handshake WebSocket refusé est fermé en **1013**, pas répondu en 429 : on ne
peut pas renvoyer de JSON sur un handshake.

## Durées de conservation

| Donnée | TTL par défaut | Réglage |
|---|---|---|
| **la vidéo déposée** | 60 min | `TRAFFIC_INPUT_TTL_MINUTES` |
| le job, son résultat et ses agrégats | 1440 min | `TRAFFIC_JOB_TTL_MINUTES` |

Deux échéances distinctes, et ce n'est pas une question de place disque : une
scène de trafic contient des plaques réelles et des visages, alors qu'un résultat
ne contient que des boîtes et des compteurs. La donnée sensible a la durée de vie
la plus courte que l'usage permet — et l'usage n'en a plus besoin dès que le
résultat existe. Un résultat reste donc consultable longtemps après que les images
ont disparu.
