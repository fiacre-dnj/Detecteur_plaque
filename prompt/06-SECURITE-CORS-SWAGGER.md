# 06 — CORS avancé, en-têtes de sécurité, limitation de débit, Swagger avancé

## 1. Ordre des middlewares — il compte

Starlette exécute les middlewares dans l'ordre **inverse** de leur ajout pour la
réponse. L'ordre d'ajout à respecter dans `create_app()` :

```python
app.add_middleware(RequestIdMiddleware)         # 1er ajouté = le plus externe
app.add_middleware(AccessLogMiddleware)
app.add_middleware(SecurityHeadersMiddleware)
app.add_middleware(BodySizeLimitMiddleware, max_bytes=settings.max_upload_mb * 1024 * 1024)
app.add_middleware(GZipMiddleware, minimum_size=1024)
app.add_middleware(CORSMiddleware, **cors_kwargs(settings))
if settings.env == "production":
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=settings.trusted_hosts)
    app.add_middleware(HTTPSRedirectMiddleware)   # si TLS terminé en amont : désactiver
```

Deux pièges à documenter en commentaire :
- **CORS doit voir la réponse d'erreur.** S'il est trop externe, une exception
  non gérée sort sans en-têtes CORS et le navigateur affiche « erreur CORS » à la
  place de la vraie erreur — heures perdues garanties.
- **GZip et SSE ne s'entendent pas** : l'en-tête `text/event-stream` doit
  échapper à la compression (GZipMiddleware de Starlette ne compresse pas les
  réponses en streaming, mais on vérifie explicitement par un test que le SSE
  arrive bien non tamponné).

## 2. CORS — configuration avancée

```python
def cors_kwargs(settings: Settings) -> dict[str, object]:
    return {
        "allow_origins": settings.cors_origins,            # liste EXPLICITE
        "allow_origin_regex": settings.cors_origin_regex or None,
        "allow_credentials": settings.cors_allow_credentials,
        "allow_methods": ["GET", "POST", "PUT", "DELETE", "OPTIONS"],
        "allow_headers": ["Authorization", "Content-Type", "X-Request-ID",
                          "If-None-Match", "Accept"],
        "expose_headers": ["X-Request-ID", "Content-Disposition",
                           "X-Total-Count", "Retry-After", "ETag"],
        "max_age": 600,                                     # cache du préflight
    }
```

Règles impératives :

1. **Jamais `allow_origins=["*"]`.** En production la liste vient de
   l'environnement ; en développement elle contient les deux formes
   (`localhost` **et** `127.0.0.1` : ce sont deux origines distinctes pour le
   navigateur, et c'est la cause classique du « ça marche sur l'un, pas sur
   l'autre »).
2. **`allow_credentials=True` est incompatible avec `*`** : le navigateur refuse
   la combinaison. Un validateur pydantic lève au démarrage si les deux sont
   demandés — échouer au boot vaut mieux qu'un bug en production.
3. `allow_origin_regex` pour les déploiements de prévisualisation
   (`^https://.*\.mon-domaine\.dev$`) : la regex doit être **ancrée** aux deux
   bouts, sinon `https://evil.com/#mon-domaine.dev` peut passer.
4. **`expose_headers` est obligatoire** pour que le client lise
   `Content-Disposition` (nom du CSV) et `X-Request-ID` (corrélation d'erreur).
   Sans cela le JS ne les voit pas, même s'ils sont envoyés.
5. `max_age: 600` évite un préflight par requête ; ne pas monter à 86 400 : un
   changement de politique resterait en cache une journée.
6. **En développement, la voie normale est le proxy Vite**, donc same-origin :
   CORS est le filet pour les appels directs et les outils. Ne pas relâcher la
   politique parce qu'un test manuel échoue en cross-origin — c'est l'occasion de
   vérifier que le proxy fonctionne.
7. **Le WebSocket n'est pas couvert par CORS** : la vérification d'`Origin` du
   handshake est faite à la main dans la route `realtime` (fermeture 1008 si
   l'origine n'est pas autorisée).

## 3. En-têtes de sécurité (`SecurityHeadersMiddleware`)

Posés sur **toutes** les réponses, avec `setdefault` (ne jamais écraser un
en-tête déjà positionné volontairement par une route) :

| En-tête | Valeur | Pourquoi |
|---|---|---|
| `Content-Security-Policy` | `default-src 'self'; img-src 'self' data: blob:; media-src 'self' blob:; script-src 'self'; style-src 'self' 'unsafe-inline'; connect-src 'self' ws: wss:; object-src 'none'; frame-ancestors 'none'; base-uri 'self'; form-action 'self'` | La SPA n'a besoin de rien d'externe. `blob:` est indispensable : la vidéo locale et les frames capturées sont des blobs. `frame-ancestors 'none'` remplace `X-Frame-Options` |
| `Strict-Transport-Security` | `max-age=31536000; includeSubDomains` (**production seulement**) | En dev sur HTTP, HSTS bloquerait le poste du développeur |
| `X-Content-Type-Options` | `nosniff` | Empêche l'interprétation d'un JSON en HTML |
| `Referrer-Policy` | `strict-origin-when-cross-origin` | Pas de fuite de chemin |
| `Permissions-Policy` | `camera=(self), microphone=(), geolocation=(), payment=()` | La webcam est nécessaire ; le reste non |
| `X-Frame-Options` | `DENY` | Compatibilité navigateurs anciens |
| `X-Permitted-Cross-Domain-Policies` | `none` | Legacy Flash/PDF |
| `Cross-Origin-Opener-Policy` | `same-origin` | Isole le contexte de navigation |
| `Cross-Origin-Resource-Policy` | `same-origin` | Empêche l'inclusion des réponses par un autre site |
| `Cache-Control` | `no-store` sur les réponses d'API dynamiques ; `private, immutable` sur un résultat de job | Un statut de job en cache est un statut faux |
| `Server` | **supprimé** | Ne pas annoncer uvicorn et sa version |

> **Différence importante avec l'ancienne version** : elle posait
> `Cross-Origin-Embedder-Policy: require-corp` parce qu'ONNX Runtime Web avait
> besoin de `SharedArrayBuffer`. **Ce besoin disparaît** avec l'analyse
> exclusivement backend. Ne pas remettre COEP : il casse le chargement de
> ressources tierces sans rien apporter ici. Documenter ce retrait dans une ADR.

Interdits : renvoyer un message d'exception interne dans un 500 ; journaliser un
corps de requête ; laisser `/docs` ouvert en production sans protection ; servir
un fichier dont le chemin vient d'une entrée utilisateur (toujours
`Path.resolve()` + vérification `is_relative_to(base_dir)`).

## 4. Limitation de débit et bornes

- **slowapi** (ou middleware maison) avec une limite globale par IP
  (`TRAFFIC_RATE_LIMIT`, défaut `60/minute`) et des limites spécifiques :
  `POST /jobs` → `10/minute`, `POST /benchmark` → `2/hour`,
  handshake WS → `10/minute`. Réponse **429** + `Retry-After`.
- **Limite de corps** (`BodySizeLimitMiddleware`) : refus **avant** lecture si
  `Content-Length` dépasse la limite, et arrêt en cours d'écriture si l'en-tête
  mentait (`Transfer-Encoding: chunked`).
- **Bornes de concurrence** : `max_concurrent_jobs`, `max_realtime_sessions`,
  benchmark unique. Ces bornes protègent le GPU autant que la mémoire.
- **Timeouts** : `uvicorn --timeout-keep-alive 15` ; le SSE est exclu par nature
  (streaming) ; aucun timeout sur un job (il peut durer des minutes) — c'est le
  TTL et l'annulation qui bornent.

## 5. Swagger / OpenAPI — configuration avancée

### 5.1 Métadonnées de l'application

```python
app = FastAPI(
    title="Traffic Analysis API",
    summary="Comptage de véhicules par vision : détection, suivi, ré-identification, ANPR.",
    description=DESCRIPTION_MARKDOWN,     # constante multi-lignes, en français
    version=__version__,                  # source unique : traffic_analysis.__version__
    openapi_tags=OPENAPI_TAGS,
    contact={"name": "Équipe Traffic Analysis", "email": "…"},
    license_info={"name": "AGPL-3.0", "url": "https://www.gnu.org/licenses/agpl-3.0.html"},
    servers=[{"url": "/", "description": "Origine courante"},
             {"url": "http://127.0.0.1:8000", "description": "Développement local"}],
    docs_url="/api/docs"   if settings.docs_enabled else None,
    redoc_url="/api/redoc" if settings.docs_enabled else None,
    openapi_url="/api/openapi.json" if settings.docs_enabled else None,
    swagger_ui_parameters={
        "docExpansion": "none",          # 40 routes dépliées = illisible
        "defaultModelsExpandDepth": 2,
        "displayRequestDuration": True,
        "filter": True,                  # champ de recherche
        "persistAuthorization": True,
        "tryItOutEnabled": True,
        "syntaxHighlight.theme": "obsidian",
    },
    lifespan=lifespan,
)
```

`DESCRIPTION_MARKDOWN` doit contenir, en français : ce que fait l'API, le
**modèle mental** (job différé vs temps réel), la convention de temps de scène,
la convention de sens `+1/−1`, un exemple `curl` de bout en bout, et un
avertissement sur la licence AGPL d'Ultralytics.

`AGPL-3.0` : Ultralytics est sous AGPL. La licence doit être déclarée dans
OpenAPI, dans le README et dans un fichier `LICENSE`. Ce n'est pas un détail
juridique optionnel pour un service exposé.

### 5.2 Tags documentés

```python
OPENAPI_TAGS = [
    {"name": "health",    "description": "Vivacité, préparation, diagnostic du service."},
    {"name": "models",    "description": "Catalogue des détecteurs, résidence mémoire, préchargement.",
     "externalDocs": {"description": "Choisir un modèle", "url": "…/docs/API.md#modeles"}},
    {"name": "jobs",      "description": "Analyse différée d'un fichier : dépôt, progression (SSE), résultat, export."},
    {"name": "realtime",  "description": "Comptage en direct sur un flux webcam (WebSocket)."},
    {"name": "benchmark", "description": "Mesure comparée des modèles sur cette machine."},
    {"name": "presets",   "description": "Géométries de comptage enregistrées."},
]
```

### 5.3 Chaque route est documentée pour de vrai

```python
@router.post(
    "/jobs",
    status_code=202,
    response_model=JobCreatedSchema,
    operation_id="createAnalysisJob",         # nom stable → client généré lisible
    summary="Dépose une vidéo et lance une analyse",
    description=(
        "Le corps est multipart : `file` porte la vidéo, `request` la configuration "
        "JSON (`AnalysisRequestSchema`). L'analyse est asynchrone : suivre la "
        "progression sur `/jobs/{id}/events` (SSE), puis récupérer `/jobs/{id}/result`."
    ),
    responses={
        202: {"description": "Job accepté", "content": {"application/json": {
              "example": {"jobId": "9f2c…", "status": "queued"}}}},
        413: {"model": ProblemDetails, "description": "Vidéo trop volumineuse"},
        415: {"model": ProblemDetails, "description": "Format de média non supporté"},
        422: {"model": ProblemDetails, "description": "Configuration invalide"},
        429: {"model": ProblemDetails, "description": "Trop de dépôts — réessayer plus tard"},
    },
)
```

Obligations :
- **`operation_id` explicite partout**, en camelCase verbe+objet. Sans lui,
  FastAPI génère `create_job_api_v1_jobs_post`, et tout client généré est
  illisible.
- **Un exemple par schéma** : `json_schema_extra={"examples": [...]}` sur les
  modèles, ou `Field(examples=[...])` sur les champs sensibles (`modelId`,
  `pixelsPerMeter`). Les exemples doivent être **réalistes** (un vrai id de
  modèle, une géométrie plausible), pas `"string"`.
- **`response_model_exclude_none=False`** : un `null` explicite (vitesse
  inconnue) est une information, ne pas l'effacer.
- Les réponses d'erreur référencent le **même** modèle `ProblemDetails` partout.
- Les routes SSE et WebSocket, que FastAPI documente mal, portent une
  `description` qui **décrit le protocole message par message** (les blocs de
  [`05`](05-API-ET-CONTRAT.md) sont recopiables tels quels).

### 5.4 Personnalisation du schéma (`core/openapi.py`)

Fonction `custom_openapi(app)` mise en cache qui :
1. appelle `get_openapi(...)` ;
2. injecte `components.securitySchemes` (`ApiKeyAuth` en `X-API-Key`,
   `BearerAuth` en JWT) **prêts à l'emploi** même si l'authentification n'est
   pas encore branchée — c'est le point d'extension documenté ;
3. injecte le schéma manuel du **résultat d'analyse** (servi en fichier, donc
   invisible pour FastAPI) ;
4. ajoute `x-logo` pour ReDoc et un `x-codeSamples` `curl` sur les trois routes
   principales ;
5. supprime les schémas orphelins générés par les alias camelCase.

### 5.5 Documentation en production

`TRAFFIC_DOCS_ENABLED=false` par défaut en production ⇒ `/api/docs`,
`/api/redoc` et `/api/openapi.json` renvoient 404. Si on veut les garder,
les protéger par une dépendance `Depends(verify_docs_access)` (Basic Auth ou
clé). **Un `openapi.json` public expose la surface d'attaque complète** : c'est un
choix, pas un défaut.

Un test vérifie que `GET /api/openapi.json` est un JSON valide, que chaque route
a un `operationId` unique, un `summary`, au moins une réponse d'erreur
documentée, et qu'aucun `operationId` généré automatiquement ne subsiste.

## 6. Sécurité applicative — la liste de contrôle

- [ ] Aucun `*` dans CORS, `allow_credentials` cohérent.
- [ ] Tous les en-têtes du tableau §3 présents (test automatisé sur une réponse).
- [ ] Limite d'upload appliquée **et** testée (fichier de 1 octet de trop ⇒ 413).
- [ ] Aucun chemin de fichier construit depuis une entrée utilisateur.
- [ ] Aucun message d'exception interne dans une réponse 5xx.
- [ ] Rate limiting actif sur les routes coûteuses.
- [ ] `Origin` vérifiée au handshake WebSocket.
- [ ] Docs désactivées ou protégées en production.
- [ ] Journaux sans données personnelles (pas de nom de fichier complet, pas
      d'image, pas d'IP en clair si le contexte l'exige).
- [ ] Les images uploadées sont supprimées à la purge TTL du job (et la purge est
      testée).
- [ ] `pip-audit` / `uv pip audit` et `bun audit` dans la CI, en avertissement.
