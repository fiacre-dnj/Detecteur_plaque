# Journal des modifications

Le format suit [Keep a Changelog](https://keepachangelog.com/fr/1.1.0/) et le
versionnage suit [SemVer](https://semver.org/lang/fr/).

Ce journal dit ce qui change **pour l'utilisateur**. Il n'est pas un `git log` :
« déplace `geometry.py` » n'y a pas sa place, « les allers-retours ne comptent
plus deux fois dans le même sens » si.

## [Non publié]

### Ajouté

- **L'analyse dit quand un véhicule est déjà passé.** Une case « Signaler les
  véhicules déjà vus » dans le tiroir Détection : chaque véhicule qui franchit une
  ligne — de n'importe quel type — est comparé à ceux qui ont franchi avant lui, et
  une ressemblance forte déclenche une alerte, avec son pourcentage, la ligne
  franchie et la photo des deux véhicules à comparer. Le registre gagne une colonne
  « Déjà vu » qui nomme le véhicule d'origine, et l'export CSV deux colonnes.
  **Un clic sur cette colonne ouvre les deux véhicules côte à côte**, avec leur
  plaque quand elle a été lue : c'est là que vous tranchez. Sans cet écran, comparer
  deux photos demandait d'ouvrir la première, la fermer, retrouver la seconde rangée
  et l'ouvrir — donc de les comparer de mémoire.
  **Aucun chiffre ne change** : un véhicule reconnu reste un véhicule de plus et son
  passage reste compté. L'écran signale, il ne fusionne pas — deux passages du même
  véhicule sont deux passages, et c'est à vous de dire si c'est bien la même
  voiture, sur les captures.
  Éteinte par défaut, et gratuite tant qu'elle l'est. Deux choses à savoir avant de
  s'y fier : deux véhicules visibles en même temps ne sont jamais rapprochés, si
  ressemblants soient-ils ; et un véhicule trop petit ou trop flou à l'écran reste
  sans réponse plutôt que d'en recevoir une inventée.

- **Les alertes disent à quel point elles sont sûres.** Une plaque recherchée affiche
  sa **confiance de lecture**, un véhicule trouvé par recherche par image sa
  **ressemblance**, en pourcentage sur la carte — jusqu'ici seul le mot « probable »
  distinguait une hypothèse d'une certitude. Le chiffre suit l'analyse : il monte
  quand une meilleure vue du véhicule est encodée ou qu'une nouvelle lecture gagne le
  vote, et il ne peut plus rester en désaccord avec le registre. Une infraction, elle,
  n'en porte pas : c'est un fait observé, pas une hypothèse.
  La photo en grand porte les deux pourcentages elle aussi, y compris quand on
  l'ouvre depuis une alerte — où la confiance de lecture manquait.

- **Une photo dès qu'il y a quelque chose à montrer.** La capture ne demande plus
  qu'une plaque ait été *lue* : un véhicule dont la plaque est seulement **repérée**
  — trop petite, trop floue, illisible — reçoit désormais sa photo, et c'est là
  qu'elle sert le plus, puisqu'elle permet de lire ce que le serveur a refusé
  d'affirmer. Un véhicule trouvé par **recherche par image** en reçoit une aussi, sans
  qu'aucune option de plaque ne soit cochée : l'alerte disait « à vérifier sur la
  capture » et il n'y en avait pas.
  Toujours **une seule photo par véhicule** : une plaque lue passe devant une plaque
  repérée, qui passe devant une ressemblance. La modale et l'infobulle du registre
  disent maintenant *pourquoi* cette image a été gardée, et une photo retenue pour la
  ressemblance l'annonce au lieu d'afficher une vignette de plaque cassée. Les
  candidats d'une recherche par image ont leur photo **même sous le curseur de
  ressemblance**, de sorte que le baisser après coup montre bien les nouveaux
  candidats.
- **Une photo par véhicule dont la plaque est lue.** Le registre gagne une colonne
  « Capture » : la voiture recadrée, et sa plaque en dessous. Un clic ouvre l'image en
  grand, avec l'instant de la prise de vue et la confiance de lecture ; les flèches du
  clavier passent d'un véhicule à l'autre sans refermer.
  **C'est la meilleure lecture qui décide de l'image gardée** — à 80 % de confiance on
  capture, à 90 % on remplace, et une lecture moins sûre ensuite ne change plus rien.
  Une seule photo par véhicule, donc, et c'est la plus lisible.
  Le cas le plus utile est celui qu'on n'attendait pas : quand l'OCR **refuse** de
  publier une plaque faute de consensus, la photo permet de la lire soi-même.
  La capture se déclenche avec les réglages déjà en place — il n'y a aucun nouveau
  seuil à régler — et elle ne coûte rien : **98 ms sur 176 s d'analyse, soit
  0,056 %**, mesurés sur une vraie course.
- **La capture apparaît aussi sur les alertes de plaque recherchée**, à côté de
  l'alerte. La grande image y montre le texte **lu** face au texte **cherché** : c'est
  là qu'on tranche, en regardant la plaque — l'OCR perd régulièrement un caractère, et
  une correspondance annoncée « probable » ne se valide pas autrement.
- **Une ligne de comptage a maintenant un type, et un sens peut être interdit.**
  Cinq choix dans le tiroir Géométrie : deux sens (le cas ordinaire), sens unique en
  entrée, sens unique en sortie, infranchissable, ou comptage seul. Sur une ligne à
  sens unique, les deux sens s'appellent « Entrée » et « Interdit », et le mot
  interdit s'écrit en rouge sur la vidéo, du bon côté du trait. Le comptage ne change
  pas d'un chiffre : un véhicule qui passe là où c'est interdit est compté comme les
  autres — il est en plus **signalé**. Changer le type d'une ligne après coup ne
  demande pas de relancer l'analyse.
- **Une ligne peut être réservée à certains types de véhicules** — une voie de bus,
  une piste cyclable. Tout autre type qui la franchit est signalé. Le réglage est
  indépendant du type de ligne : une voie de bus à sens unique se décrit avec les
  deux.
- **Des alertes, pendant l'analyse et après.** Sur la vidéo, une pile de cartes
  annonce ce qui vient de se passer — le numéro du véhicule, son type, sa plaque, la
  ligne franchie, la flèche à l'angle réel du tracé et l'instant au dixième de
  seconde. En bas de page, une section « Alertes » les reprend toutes, filtrables par
  nature, et **cliquer une alerte amène la vidéo au moment du fait**. Les alertes
  n'apparaissent que si une règle a été posée ou une plaque recherchée : un « 0 » sous
  une règle que personne n'a déclarée se lirait comme « aucune infraction ».
- **On peut rechercher une plaque pendant l'analyse.** Jusqu'à dix numéros se
  saisissent dans le tiroir Détection ; dès qu'une plaque lue correspond, une alerte
  le dit. La casse et les séparateurs sont ignorés, et une lecture à un caractère près
  déclenche une alerte « probable » plutôt que rien — la lecture perd régulièrement le
  premier caractère d'une plaque. La liste n'est pas conservée après fermeture, et un
  avertissement prévient si elle est remplie alors que la lecture des plaques est
  désactivée.
- **De nouveaux chiffres pour les infractions.** Un compteur « Franchissements
  interdits » en tête de la colonne de résultats, le détail sur chaque carte de ligne,
  la ligne la plus empruntée à contresens parmi les comparatifs de Statistique, et une
  colonne « Infraction » au registre — qui n'apparaît que si le tracé en déclare une.
- **Un filtre par ligne au registre des véhicules**, à côté de la recherche de plaque,
  avec les noms que vous avez donnés aux lignes. Les deux filtres se composent, et le
  message affiché quand rien ne correspond dit lequel des deux est en cause.
- **Un curseur « Confiance lecture », dans le tiroir Détection.** Il décide de la
  sûreté minimale d'une lecture de plaque : sous ce seuil, le texte n'est pas retenu et
  le véhicule reste sans plaque plutôt qu'avec une plaque douteuse. Le serveur
  appliquait déjà cette règle, mais à une valeur fixée dans sa configuration, hors de
  portée. À ne pas confondre avec « Confiance plaques », qui porte sur le **repérage**
  du rectangle : une plaque peut être parfaitement encadrée et illisible. Le bouton
  « Défaut » revient au réglage du serveur, et le curseur descend jusqu'à « aucune »
  pour qui préfère tout voir. Il ne change pas la durée d'une analyse : la lecture a
  lieu de toute façon, elle est seulement retenue ou non.
- **Tracer la première zone coche « Ignorer hors zone ».** Le geste dit « ce qui
  m'intéresse est là-dedans » ; jusqu'ici il fallait encore aller cocher une case dans
  un autre tiroir pour que ce soit vrai, sans quoi tout ce qui passait à l'extérieur
  était compté quand même. La case reste décochable, et une deuxième zone ne la recoche
  pas — une géométrie chargée depuis un preset garde, elle, le réglage enregistré avec
  elle.
- Socle du dépôt : licence AGPL-3.0, hooks de pré-commit, journal, guide de
  contribution, et les cinq premières décisions d'architecture documentées.
- Le service répond : `GET /api/v1/health/live` (vivacité),
  `/health/ready` (le répertoire de données est-il inscriptible ?) et
  `/health` (version et environnement).
- La documentation interactive de l'API est sur `/api/docs`.
- Toute erreur est une réponse *Problem Details* en français, avec un code
  machine stable et un identifiant de requête à citer en cas d'incident. Une
  erreur interne ne divulgue jamais de détail technique.
- Les journaux portent l'identifiant de la requête qui les a produits : signaler
  un problème en citant cet identifiant suffit à retrouver toute la chaîne.
- **Le comptage existe** : franchissements de lignes par sens, entrées et
  occupation de zones, ré-identification des véhicules qui disparaissent puis
  reviennent, vote de classe majoritaire et estimation de vitesse.
- Un aller-retour compte une fois dans chaque sens ; une boîte qui tremble sur
  une ligne ne compte qu'une fois ; un véhicule occulté puis revenu reste le même
  véhicule.
- Sans échelle px/m fournie, les vitesses restent en px/s plutôt que d'être
  converties à tort en km/h.
- En dessous de trois secondes de flux analysé, le débit estimé est annoncé
  comme indisponible au lieu d'afficher un chiffre qui oscille.
- **On peut déposer une vidéo et suivre son analyse** : `POST /api/v1/jobs`,
  progression en direct par flux SSE, résultat complet téléchargeable, et
  historique paginé des analyses.
- Une analyse s'annule en cours de route, proprement : le traitement s'arrête
  entre deux images plutôt que d'être interrompu de force.
- Une seconde analyse déposée pendant qu'une autre tourne est **acceptée** et
  attend son tour, au lieu d'être refusée.
- Les vidéos et résultats des analyses terminées sont purgés automatiquement
  après leur durée de rétention.
- **Les analyses survivent au redémarrage du service** : jobs, statistiques,
  registre des véhicules et franchissements sont conservés en base.
- Le registre et les franchissements se consultent page par page, avec des
  filtres — par type de véhicule, par ligne, par sens, par fenêtre de temps —
  sans avoir à télécharger le résultat complet.
- **Export CSV** du registre et des franchissements, directement ouvrable dans
  un Excel français : accents corrects, colonnes séparées, nombres reconnus
  comme des nombres. Une vitesse inconnue reste une case vide, jamais un zéro.
- **Vingt détecteurs au catalogue** : quatre familles (YOLOv8, YOLO11, YOLO12,
  YOLO26) dans les cinq paliers, du nano à l'extra large. Chaque modèle indique
  s'il est déjà téléchargé et s'il est chargé en mémoire, pour qu'une première
  analyse n'attende jamais sans explication.
- Un modèle peut être préchargé à l'avance, ou déchargé pour libérer la mémoire.
  Le service n'en garde que deux en mémoire par défaut et évince le plus ancien.
- `/api/v1/health` annonce le device utilisé, la version d'Ultralytics, les
  modèles résidents et la disponibilité de la lecture de plaques.
- Un modèle inconnu est refusé au dépôt, avec la liste des identifiants valides,
  au lieu de faire échouer l'analyse une minute plus tard.
- Deux scripts : `fetch_weights.py` pour pré-télécharger les poids choisis, et
  `fetch_plate_model.py` qui vérifie l'empreinte SHA-256 du modèle de plaques
  avant de l'installer.
- Le service pose une politique de sécurité complète sur toutes ses réponses et
  n'annonce plus quel serveur il utilise.
- Un envoi trop volumineux est refusé dès son annonce, sans être lu.
- La documentation d'API peut être fermée en production (`TRAFFIC_DOCS_ENABLED`),
  et chaque route y porte un résumé, un identifiant lisible et un exemple.
- En production, le service peut servir lui-même l'interface
  (`TRAFFIC_STATIC_DIR`) : une seule adresse, aucun réglage de CORS.
- **L'interface existe.** On choisit une source — fichier, clip de démonstration
  ou caméra —, on trace ses lignes et ses zones directement sur l'image, on lance
  l'analyse et on suit sa progression.
- Les lignes et les zones se dessinent, se déplacent, se renomment et se
  suppriment sur l'image. Une ligne peut être restreinte à une zone.
- Après une analyse, la vidéo se rejoue **avec** ses boîtes, ses trajectoires et
  ses compteurs. Reculer dans la vidéo fait **baisser** les compteurs : ce qui est
  affiché correspond toujours à ce qui a été vu jusqu'à l'instant montré.
- Le registre des véhicules se consulte, se trie et s'exporte en CSV — un CSV qui
  s'ouvre correctement dans Excel en français, accents compris.
- Déplacer une ligne après une analyse affiche un bandeau « résultat obsolète »
  plutôt que de laisser croire que les chiffres décrivent le nouveau tracé.
- **Comptage en direct sur la caméra**, avec les mêmes règles que l'analyse d'un
  fichier. La latence et le nombre d'images abandonnées sont affichés : un
  abandon élevé est normal et signifie que le serveur est le facteur limitant.
- Si le serveur ne reçoit pas des images de la taille que l'interface croit
  envoyer, le direct **s'arrête et le dit**. Compter dans ces conditions
  produirait des chiffres faux mais plausibles.
- L'historique des analyses : rouvrir un résultat **avec sa géométrie**, relancer
  la même configuration — ce qui crée une nouvelle analyse sans toucher à
  l'ancienne — ou supprimer.
- **Presets de géométrie** : enregistrer un tracé sous un nom et le recharger sur
  une autre vidéo. Un preset enregistré pour une autre résolution est adapté
  automatiquement, et l'interface **le dit avant** de le charger, avec les deux
  résolutions.
- Le sélecteur de modèles se parcourt au clavier et annonce, pour chaque modèle,
  sa taille et s'il faudra le télécharger.
- Le tableau de benchmark se trie par colonne et recharge le dernier résultat à
  l'ouverture.
- **`docker compose up` sert l'application complète** sur une seule adresse. Les
  analyses, la base et les poids téléchargés survivent à un redémarrage.
- **La lecture locale d'une analyse en cours reste à vitesse normale par
  défaut.** Sans plus toucher à rien, la vidéo ne défile plus tantôt accélérée,
  tantôt ralentie selon la charge du serveur. Un plafond **absolu**, en 30
  (le défaut) ou 60 images par seconde, reste disponible en plus pour brider
  le débit du serveur lui-même, indépendamment de la cadence de la vidéo.
- **Chaque sens de ligne est désormais obligatoirement « Entrée » ou
  « Sortie ».** Le panneau de géométrie n'offre plus de nom libre à taper, ni
  de menu déroulant par sens : les deux sens s'affichent en lecture seule
  (flèche, libellé) et un seul bouton les **inverse** — inutile de choisir
  deux fois pour une paire qui n'a jamais que deux états possibles. Une ligne
  fraîchement tracée contribue donc tout de suite au bilan entrées/sorties du
  carrefour, sans geste supplémentaire. Les flèches de sens (canvas et
  panneau) pointent désormais **exactement** perpendiculairement à la ligne,
  à n'importe quel angle, au lieu d'un glyphe figé ou arrondi au 45° le plus
  proche.
- **Le nom de la ligne et les libellés de sens s'estompent pendant qu'une
  analyse tourne**, différée ou en direct, pour laisser la place aux boîtes et
  aux compteurs — sauf le sens qui vient tout juste de compter, qui reste net.
- La vidéo locale se cale **toujours** sur l'image que le serveur analyse
  pendant qu'une analyse tourne : la case à décocher pour reprendre la main a
  disparu, le gel est désormais inconditionnel et expliqué à l'écran.
- Le tableau de résultats perd la carte « Véhicules détectés » ; les repères
  « Image … » et « Véhicules : … » affichés en surimpression de la vidéo
  disparaissent aussi — la résolution et la cadence de lecture suffisent. La
  durée de flux analysé devient une carte à part entière plutôt qu'une phrase
  sous le tableau.
- **L'entête de l'application reste visible en défilant**, et les tiroirs
  Détection/Comptage/Affichage & analyse s'ouvrent désormais **par-dessus** la
  page (un clic en dehors ou `Échap` les referme) au lieu de pousser la vidéo
  et les résultats vers le bas. Ils restent grisés tant qu'aucune vidéo n'est
  chargée. La scène vide propose une invite cliquable — glisser-déposer ou
  clic — au lieu d'une simple phrase, et le nom du fichier importé se lit
  désormais à l'autre bout de la barre, plutôt que juste après le bouton.
- **Le bas de l'écran, sous la vidéo, est refondu.** La chronologie cliquable
  et ses cinq onglets (Répartition, Par ligne & sens, Mouvements, Flux,
  Registre) laissent place à trois sections toujours visibles : une
  **Répartition** simplifiée (une carte par type de véhicule, le nombre
  d'entrées — cohérent par construction avec le KPI « Entrées au carrefour »),
  une **Statistique** (le total de véhicules ayant traversé le carrefour, puis
  une rangée compacte par ligne : entrées, sorties, solde et part du trafic),
  et le **Registre**. La navigation par clic dans les franchissements et la
  matrice origine-destination disparaissent sans remplacement — la barre de
  lecture standard suffit à se déplacer dans le temps.
- La Statistique dit désormais **quelle ligne sert le plus à entrer** et
  **laquelle sert le plus à sortir**, en nombre de passages. C'est une autre
  question que « le plus fort afflux », qui parle du solde : une ligne où 10
  véhicules entrent et 9 ressortent est la plus empruntée pour entrer sans
  remplir le carrefour pour autant.
- Le flux par ligne et la répartition par type se lisent en **deux camemberts
  côte à côte** plutôt qu'en barres : la part de chaque ligne et de chaque type
  se voit d'un coup d'œil, sans comparer des barres une à une.
- **Deux franchissements sur trois manquaient à l'appel dans un cas précis, et
  un quatrième était inventé dans un autre.** Un véhicule dont le suivi
  *commence* tout près d'une ligne — parce qu'il entre dans le champ à cet
  endroit, ou parce qu'une occlusion vient de couper sa piste — n'était pas
  compté quand il franchissait : la zone d'insensibilité qui entoure chaque
  trait servait alors de point de départ au lieu de point de passage. C'est le
  cas le plus fréquent en trafic dense. À l'inverse, quand le suivi réattribuait
  le numéro interne d'un véhicule disparu à un nouveau venu, celui-ci héritait
  de la position de son prédécesseur et pouvait se voir attribuer un
  franchissement qu'il n'avait pas fait. Les deux sont corrigés ; les totaux
  d'une même vidéo réanalysée peuvent donc monter **et** descendre.
- **Le suivi ne lâche plus un véhicule dont la détection faiblit un instant.**
  Le détecteur ne rejetait rien en dessous du seuil de confiance choisi, ce qui
  privait le suivi du mécanisme prévu pour traverser une occlusion partielle, un
  flou de mouvement ou un reflet. Un véhicule dont la confiance plongeait le
  temps d'une image voyait sa piste coupée : il était alors compté deux fois, et
  son franchissement pouvait être perdu. Mesuré sur une vidéo de trafic réelle :
  **21 % d'observations suivies en plus, aucun nouveau véhicule inventé, et neuf
  pistes fragmentées en moins** (92 → 83 objets suivis) pour un total de
  franchissements identique. Le seuil de confiance garde exactement le même sens
  pour vous : à partir de quand un objet devient un véhicule suivi.
- **Les vitesses peuvent enfin s'afficher en km/h de façon fiable.** Chaque ligne
  de comptage accepte sa **longueur réelle** (« cette ligne fait 7 m »), ce qui
  donne une échelle mesurée à l'endroit précis où les véhicules la franchissent.
  Une seule échelle pour toute l'image ne pouvait pas convenir : sur une caméra
  inclinée, un mètre vaut quelques pixels au loin et quelques dizaines au premier
  plan — un facteur près de 4 mesuré entre deux lignes d'une même scène. Le
  réglage global existant continue de fonctionner à l'identique si vous ne
  renseignez aucune longueur.
- **Le registre ne liste plus que les véhicules ayant franchi une ligne**, tous
  sens confondus. Les véhicules simplement détectés — à l'arrêt, en
  stationnement, ou vus quelques images dans un coin du champ — n'y figuraient
  qu'avec des « — » dans « Lignes franchies » et « Passages », donc sans rien
  qui permette de les vérifier.
- **« Véhicules ayant traversé le carrefour » compte désormais les véhicules
  entrés**, et non tous les objets suivis. Sur une même analyse, ce chiffre
  annonçait 106 juste au-dessus d'une répartition qui totalisait 28 entrées :
  les deux étaient justes dans leur unité, mais se lisaient comme une
  contradiction. Un véhicule qui entre deux fois compte pour un seul véhicule
  ici, et pour deux passages dans « Entrées au carrefour ».
- Basculer un sens de ligne entre entrée et sortie met à jour ces chiffres
  **immédiatement**, sans relancer l'analyse.
- Le **registre des véhicules** est plus détaillé : durée de présence, zones
  traversées et confiance de *détection* de la plaque (distincte de la
  confiance de lecture) s'ajoutent aux colonnes existantes, le type de véhicule
  s'affiche en français, et les en-têtes du tableau restent visibles pendant le
  défilement.
- Le registre gagne deux colonnes, **Entrée** et **Sortie**, qui donnent
  l'instant du franchissement au dixième de seconde — deux passages du même
  véhicule sur deux lignes voisines tombaient jusqu'ici dans la même seconde
  affichée. Basculer un sens entrée ↔ sortie déplace l'heure de colonne sans
  relancer l'analyse.
- **Le registre et la statistique se remplissent désormais pendant l'analyse**,
  et non plus seulement à la fin : l'aperçu en direct porte le registre des
  véhicules ayant déjà franchi une ligne, à une cadence plus lente que celle des
  boîtes pour ne pas alourdir le flux à mesure qu'il grossit.
- **L'écran de comptage est réorganisé autour du lecteur.** La barre du haut —
  import, réglages — **reste collée sous l'entête** quand on descend lire le
  registre ou la chronologie, au lieu de partir hors de l'écran. La géométrie
  (lignes, zones, presets) devient son **quatrième tiroir**, à côté de Détection,
  Comptage et Affichage & analyse : elle occupait en permanence le haut de la
  colonne de droite pour un réglage qu'on pose une fois avant de lancer. Les trois
  chiffres de machine — cadence serveur, latence, flux analysé — passent à
  l'extrémité de cette barre, en petit : ils tenaient trois des cinq cartes de
  résultats, à égalité visuelle avec les chiffres du carrefour. Le nom du fichier,
  qui occupait cette extrémité, est désormais **posé sur la vidéo**, coin
  haut-gauche, dans le même écrin que la résolution affichée en face.
- **La Répartition par type de véhicule rejoint les Résultats**, dans la colonne
  de droite, et perd son titre : ses quatre cartes découpent le chiffre « Entrées
  au carrefour » qu'elles totalisent exactement, et un écran de défilement entre
  les deux obligeait à retenir un nombre pour vérifier l'autre.
- **« Lancer l'analyse » et « Fermer » sont dans le lecteur**, à l'extrémité de sa
  rangée de commandes, là où se réglait la vitesse de lecture — laquelle rejoint le
  groupe de boutons qui lit. On choisit sa portion de vidéo sur le rail
  d'intervalle, puis on lance : deux gestes voisins, que la hauteur de la colonne
  de résultats séparait.
- **Le rail d'intervalle d'analyse a exactement la longueur de la barre de
  position.** Le temps courant était écrit à côté du curseur de lecture, ce qui
  raccourcissait ce rail-là d'une centaine de pixels : les deux échelles ne
  coïncidaient pas, et une borne posée au milieu de l'intervalle ne tombait pas au
  milieu de la vidéo. Les deux chiffres sont maintenant en entête de leur rail.
- **La chronologie des franchissements reste affichée après l'analyse.** Elle
  disparaissait à la seconde où l'analyse terminait, c'est-à-dire au moment précis
  où l'on vérifie un comptage : c'est la seule vue qui dise *quand* et *dans quel
  sens* chaque passage a eu lieu. Après coup, elle suit la tête de lecture comme le
  registre et les compteurs — elle ne montre jamais un franchissement que la vidéo
  n'a pas encore atteint.
- **Le bilan de chaque ligne est dans la colonne de résultats**, une carte par
  ligne tracée, sous le nom que vous lui avez donné : fréquentation, entrées,
  sorties et solde. Il fallait défiler jusqu'au bas de page pour savoir combien de
  véhicules étaient passés sur *une* ligne, alors que la question se pose en même
  temps que le total. Renommer une ligne ou basculer un sens entrée ↔ sortie s'y
  voit immédiatement, sans relancer l'analyse.
- **« Entrées au carrefour » s'appelle désormais « Passages en entrée »**, et
  occupe toute la largeur de la colonne. Le mot « carrefour » ne voulait rien dire
  quand on compte les passages sur une route à sens unique, alors que le chiffre,
  lui, restait juste.
- **« Objets suivis » a rejoint la cadence et la latence dans la barre du studio.**
  C'est le nombre de véhicules suivis à l'image affichée — un chiffre qui monte et
  redescend, pas un résultat — et il occupait la moitié des cartes de tête, à
  égalité visuelle avec le bilan du comptage.
- **La carte « Personne » ne disparaît plus d'un résultat qui en contient.** Elle
  suivait la case cochée dans les réglages : décocher « Personne » après une
  analyse effaçait le chiffre de l'analyse elle-même.
- **La colonne de droite ne reste plus vide en attendant l'analyse.** Elle affiche
  désormais « Configuration système » : le modèle retenu, les types comptés, le
  tracé, la portion de vidéo analysée, les plaques et la cadence — les six réglages
  qui
  partiront au serveur, relus d'un coup au lieu d'ouvrir quatre tiroirs pour les
  vérifier. Un tracé sans ligne, ou aucun type coché, y est signalé avec sa
  conséquence : « les zones seules ne produisent pas de franchissement ». Rien n'y
  empêche de lancer.
- **L'aperçu des résultats à venir est passé en haut de la colonne**, à la place
  exacte des vrais chiffres. Il vivait tout en bas de la page, sous la vidéo et la
  chronologie, là où il fallait défiler pour le trouver.
- **Le registre dit par où *et* quand, dans la même colonne.** « Lignes franchies »
  listait les deux sens dans une seule cellule, pendant que les colonnes « Entrée »
  et « Sortie » n'en portaient que l'heure : lire « ce véhicule est entré par la
  ligne 1 à 00:34 » demandait de recoller trois cellules, dont une au survol. Les
  colonnes s'appellent maintenant « Entrée par » et « Sortie par » et portent la
  ligne et l'heure. Un franchissement dont le rôle n'est plus lisible — ligne
  effacée du tracé depuis l'analyse — garde sa propre colonne, qui n'apparaît que
  s'il en existe.
- **Les barres entrées/sorties portent la couleur de leur ligne**, celle du trait
  tracé sur la vidéo, au lieu d'un gris uniforme — dans les Résultats comme dans la
  Statistique. Trois barres empilées se ressemblaient toutes, et relier une rangée
  au trait qu'on voit à l'écran demandait de relire son nom à chaque fois.
- **Changer d'onglet ne fait plus perdre son travail.** Passer du Studio à
  l'Historique ou au Benchmark, puis revenir, rendait la page telle qu'on l'avait
  ouverte : plus de vidéo, plus de tracé, plus de résultat — et il fallait tout
  recommencer pour avoir consulté l'historique dix secondes. Les trois pages
  conservent désormais leur état, y compris la position de lecture de la vidéo, une
  analyse en cours et la position de défilement de chacune.

### Modifié

- **L'analyse est un peu plus rapide quand elle lit des plaques.** Le serveur ne fait
  plus attendre la détection de l'image suivante pendant qu'il lit la plaque de la
  précédente : les deux avancent en parallèle. Mesuré sur une vue de circulation
  1080p, **+10 % d'images par seconde** quand la lecture de plaques travaille, +5 %
  quand elle repère des plaques sans les lire, et **rien du tout** quand aucune plaque
  n'est lisible — le gain suit exactement la quantité de lecture, et il n'y a rien à
  régler. Les comptages, les horodatages et les plaques publiées sont identiques au
  chiffre près : c'est le même travail, fait en même temps plutôt que l'un après
  l'autre.
  À savoir pour ne pas espérer davantage : la détection de plaques occupe elle aussi
  la carte graphique, et deux calculs sur la même carte ne peuvent pas se recouvrir.
  Le chemin qui reste pour aller nettement plus vite n'est pas un réglage — c'est un
  plan plus serré, où les plaques sont assez grandes pour être lues sans que le
  serveur cherche partout.

- **La barre du studio pilote l'analyse.** « Lancer l'analyse » quitte le bas du lecteur
  et rejoint l'import ; une fois l'analyse partie, il devient « Suspendre » et
  « Annuler », au même endroit. La progression les suit sous forme d'anneau — le
  pourcentage, centré au-dessus du compte d'images — au lieu d'un bloc sous la vidéo
  qu'il fallait aller chercher en défilant. Le bloc reste pour ce qu'il est seul à
  savoir dire : l'envoi du fichier, le chargement du modèle, une erreur, et ce qu'une
  pause coûte.
- **Le lancement dit à nouveau ce qu'il fait.** Une analyse qui démarre, ou qui attend
  son tour derrière une autre, affichait un anneau à « 0 % » et rien d'autre — le
  message « Lecture suspendue » restant le seul texte visible, le lancement passait
  pour un échec alors que l'analyse tournait. La progression écrit maintenant l'état
  en toutes lettres tant qu'elle n'a pas d'images à compter, l'attente d'une place sur
  le serveur est expliquée sous la vidéo, et la phrase sur la lecture figée commence
  par « Analyse en cours ».
- **Les boutons de la barre n'affichent plus que leur icône**, et leur nom se déplie au
  survol comme au clavier. Six libellés en toutes lettres ne tenaient plus sur une ligne
  dès que les alertes étaient armées.
- **Les chiffres de cadence sont là dès l'import de la vidéo**, à « — » tant qu'aucune
  analyse n'a tourné, et plus petits. Ils n'apparaissaient qu'au premier résultat, donc
  la barre changeait de forme au moment précis où l'on venait de lancer.
- **La navigation passe à gauche, dans un rail d'icônes.** Le bandeau de titre et
  d'onglets qui coiffait chaque page disparaît : Studio, Historique et Benchmark sont
  désormais trois icônes dans une colonne étroite, avec l'état du serveur et le thème
  en bas. Le haut de l'écran revient entièrement à la barre du studio, et la vidéo
  gagne la hauteur d'un bandeau — près de cent pixels, sur l'écran où la place manque
  le plus. Le sous-titre annonçait encore une « ré-identification » retirée il y a
  trois semaines ; il ne manquait à personne.
- **La barre du studio se lit par groupes et tient sur une ligne.** Chaque bouton
  porte son icône, un filet sépare l'import des réglages et les réglages des outils de
  scène, et les chevrons ont disparu — ils répétaient sept fois la même chose. Les
  chiffres de cadence, qui décrochaient en seconde ligne dès que la fenêtre se
  resserrait, se replient maintenant proprement dans un tiroir « État ». Géométrie,
  Recherche et Alertes se reconnaissent à leur icône, comme la cloche avant elles.
- **Les captures de véhicules sont effacées en même temps que la vidéo**, plus tôt
  que les chiffres. Une voiture et sa plaque recadrées sont exactement ce que la
  purge de la vidéo existe pour effacer ; le registre garde ses colonnes et affiche
  « capture purgée » à la place de la vignette.
- **La section « Franchissements » du bas de page est masquée.** Sa chronologie
  posait un fait par rangée sans dire lequel méritait qu'on aille voir ; la section
  « Alertes » prend sa place et répond à cette question-là. Rien n'est perdu : le
  détail complet des franchissements reste exportable en CSV, et la section peut être
  rendue telle quelle.
- **La colonne « Hors rôle » du registre s'appelle « Autres passages ».** Elle
  accueille désormais aussi les franchissements des lignes en « comptage seul », qui
  ont un rôle — délibérément choisi — et que « hors rôle » ferait passer pour un
  oubli.

### Corrigé

- **Un preset rechargé retrouve enfin ses sens d'entrée et de sortie.** Enregistrer une
  géométrie conservait le tracé, les noms et les couleurs, mais perdait en silence le
  rôle de chaque sens — entrée ou sortie — et les libellés qui vont avec. Le preset se
  rechargeait sans le moindre message, les lignes étaient au bon endroit, et pourtant
  presque tout l'écran se taisait : « Passages en entrée » affichait « — », les cartes
  par ligne perdaient leurs entrées et leurs sorties, la Statistique ne désignait plus
  aucune ligne dans ses comparatifs, le Registre n'avait plus d'heure d'entrée ni de
  sortie et faisait apparaître une colonne « Hors rôle », et la chronologie des
  Franchissements retombait sur son libellé générique. Les comptages, eux, restaient
  justes — ce qui rendait la panne d'autant plus difficile à nommer : le carrefour
  semblait analysé pour rien. Les presets déjà enregistrés se rechargent toujours et
  affichent « à préciser » sur leurs sens : redéclarez-les une fois, réenregistrez, et
  le preset est à jour. Rien n'est deviné à votre place — supposer « entrée » aurait
  produit un bilan faux sans le dire.
- **Le curseur « Confiance véhicules » agit enfin sur toutes les analyses, pas
  seulement sur la première.** Après le démarrage du serveur, la première analyse
  utilisait bien le seuil demandé ; toutes les suivantes reprenaient le sien en
  silence, quel que soit l'endroit où l'on posait le curseur. Rien ne le signalait :
  l'écran, la requête et les journaux annonçaient tous la bonne valeur. Mesuré sur une
  même vidéo, trois analyses de suite dans le même serveur — `20 % → 80 % → 20 %`
  rendait **3, 3 puis 3** véhicules ; il rend désormais **3, 1 puis 3**. Le direct
  était concerné aussi : une session caméra ouverte après une analyse héritait du seuil
  de celle-ci.
- **L'analyse avec repérage de plaques est 1,3× à 2× plus rapide.** Elle s'arrêtait
  net pendant une seconde entière, plusieurs fois par minute : sur une route calme, ces
  pauses représentaient les trois quarts du temps passé à repérer les plaques. Le
  détecteur de plaques recevait une image de forme légèrement différente pour chaque
  véhicule, et la bibliothèque de calcul réétalonnait ses algorithmes à chaque fois.
  Mesuré sur deux scènes réelles, en alternant les deux régimes : **7,2 → 14,9 puis
  6,1 → 10,4 images/s** sur une scène clairsemée, **8,0 → 10,7 puis 7,8 → 11,9** sur une
  scène chargée. Aucun chiffre publié ne change — mêmes véhicules, mêmes
  franchissements, mêmes plaques.
- **Une vidéo haute résolution ne coûte presque plus de cadence.** L'analyse
  ralentissait à mesure que la résolution montait, et pour une seule raison : le
  décodage des images attendait le calcul de l'image précédente au lieu de se faire
  pendant. Il se fait désormais en parallèle. Mesuré sur une même scène réencodée à
  quatre résolutions, sans plaques : **1080p 47 → 58 images/s, 1440p 35 → 59, 4K
  27 → 40** — et la cadence est devenue la **même** de 720p à 1440p, là où elle
  perdait 40 % en montant. Avec plaques et lecture actives, le 4K passe de 16 à
  21 images/s, c'est-à-dire la cadence du 720p. Aucun chiffre ne change : mêmes
  véhicules comptés, mêmes franchissements, mêmes plaques publiées.
- **Le repérage de plaques peut être plafonné, et il se mesure.** Deux réglages
  nouveaux, tous deux sans effet par défaut : un plafond de véhicules examinés par
  image, qui rend le coût du repérage indépendant du trafic (mesuré sur une scène à 6-14
  véhicules : **7,3 → 11,0 images/s à comptage identique**), et la taille d'entrée du
  modèle de plaques, réglable pour ceux qui filment des plans serrés.
- **Ce que le repérage de plaques coûte vraiment, dit clairement** : sur une vue de
  circulation 1080p, il pèse **73 %** du temps d'analyse et la lecture de texte 0,3 % —
  et surtout, **aucune plaque n'y est publiable** : elles font moins de 48 px de large
  quand la lecture en exige 64. L'application le disait déjà véhicule par véhicule
  (« plaque vue à 32 px »), mais rien ne disait que cela représentait les trois quarts
  du temps de calcul. Deux gestes le règlent : resserrer le plan, ou filmer plus défini.
- **Ce que la résolution apporte vraiment, dit clairement** : elle ne change *rien*
  à la détection des véhicules — l'image est ramenée à la taille d'entrée du modèle
  dans tous les cas — mais elle est ce qui rend les plaques lisibles. Sur la scène
  mesurée, la lecture ne se déclenche jamais en 720p (les plaques y font moins de
  64 px) et publie une plaque en 4K.
- **L'analyse avec repérage de plaques est deux fois plus rapide.** Activer les
  plaques et la lecture du texte faisait chuter la cadence bien plus que nécessaire :
  le repérage relançait le calcul **une fois par véhicule** au lieu d'une fois par
  image. Mesuré sur une vidéo réelle avec quatre véhicules à l'écran, plaques et
  lecture actives : **5,8 → 10,6 images analysées par seconde**, soit une analyse qui
  passe de 5 min 39 à 3 min 06 pour la même séquence. Aucun chiffre ne change —
  mêmes véhicules comptés, mêmes franchissements, même plaque publiée.
- **La plaque ne perd plus son premier caractère.** Le registre affichait `606L`
  pour une plaque `苏A·R606L`, à 81 % de confiance de lecture : un texte tronqué,
  présenté avec l'assurance d'un texte lu. Le serveur publie désormais `AR606L`.
  Trois causes distinctes, corrigées toutes les trois :
  - **la lecture n'avait pas le droit de recommencer.** Une plaque n'était relue
    que si la nouvelle image de la plaque était nettement meilleure que la
    précédente, ce qui ne laissait que deux ou trois lectures par véhicule —
    jamais assez pour que le vote tranche entre des graphies voisines. C'est le
    changement décisif, et il ne ralentit pas l'analyse : une plaque reconnue plus
    tôt arrête plus tôt le travail coûteux ;
  - **un caractère que le modèle ne connaît pas mangeait la lettre voisine.**
    L'idéogramme de province d'une plaque chinoise n'existe dans aucune classe du
    modèle de lecture, et le caractère juste à côté en faisait les frais. Mesuré
    sur 40 images de plaques réelles : lectures exactes 8 → 17. Le contrôle sur des
    plaques **françaises**, qui n'ont aucun idéogramme, s'améliore aussi — 39 → 43
    lectures justes sur 56, dont 4/8 → 7/8 pour les plaques de 64 px de large ;
  - **une lecture incomplète concurrençait la lecture complète**, et gagnait, parce
    qu'elle sort plus souvent. Elle la renforce désormais : plaques justes 1 sur 6
    → 3 sur 6.

  Le surcoût de lecture est réel (1,9×) et invisible à l'usage : l'analyse tourne à
  la même cadence.
- **La vidéo déposée est réellement supprimée au bout d'une heure.** Le réglage
  l'annonçait depuis le début, mais rien ne l'appliquait : les images restaient
  vingt-quatre heures, comme le reste de l'analyse. Le résultat, lui, se consulte
  toujours aussi longtemps — il ne contient que des boîtes et des chiffres.
- **Une camionnette n'est plus comptée deux fois.** Le détecteur pouvait la
  reconnaître à la fois comme voiture et comme camion, et les deux survivaient.
- **Un semi-remorque non plus.** Le détecteur émet parfois une boîte sur la cabine
  et une sur le véhicule entier ; la plus petite est désormais écartée, et le
  panneau de diagnostic dit combien.
- **Une analyse et un comptage en direct lancés en même temps ne se mélangent
  plus.** Ils partageaient le même modèle et donc le même suivi : les deux
  produisaient des chiffres plausibles et faux.
- Le service refuse de démarrer en production avec sa documentation ouverte, sauf
  choix explicite.
- Le nombre de requêtes par minute est limité, avec un délai d'attente annoncé.

### Décidé

- L'inférence est exclusivement côté serveur ; il n'y a plus de mode navigateur,
  et les images sont envoyées au serveur — ce que l'interface annonce.
- Aucun poids de modèle n'entre dans l'historique git : ils sont téléchargés à la
  demande, et l'interface distingue *au catalogue* / *téléchargé* / *résident*.
- Python est épinglé en 3.12 : `torch` ne publie pas de roue pour 3.14.
- `torch` s'installe dans la variante qui correspond à la machine — roue CPU ici,
  roue CUDA sur une machine NVIDIA — sans extra à choisir. `UV_TORCH_BACKEND`
  force la variante quand on veut un résultat reproductible.
- L'interface suit `DESIGN.md` : thème sombre, accent vert strictement
  fonctionnel, couleur réservée au canvas pour ce qu'elle encode.
