# ADR 0025 — La calibration se fait par ligne, pas pour l'image entière

- **Statut** : accepté
- **Date** : 2026-08-17

## Contexte

La conversion des vitesses en km/h existait déjà : `to_kmh(px_s,
pixels_per_meter)`, alimentée par un curseur « Échelle (px/m) » unique pour toute
l'image. Sans échelle, le registre affiche des px/s — refus délibéré d'inventer
une distance réelle.

**Une échelle unique ne peut pas être juste.** Une caméra de trafic regarde la
chaussée en biais : sur le plan du sol, un mètre vaut quelques pixels au fond de
l'image et quelques dizaines au premier plan. Mesuré sur une vidéo du dépôt, en
supposant une même largeur de 7 m sur les quatre lignes tracées, les échelles
locales s'échelonnent de **37 à 143 px/m — un facteur 3,9** entre le trait le plus
lointain et le plus proche. Un curseur unique est donc juste à une profondeur et
faux partout ailleurs, et l'erreur passe telle quelle dans les km/h du registre.

Les deux façons connues de faire mieux :

1. **une homographie 4 points** — l'utilisateur marque un quadrilatère au sol dont
   il connaît les dimensions, et tout se calcule en coordonnées terrain. C'est la
   méthode la plus précise, et la plus coûteuse : nouvel écran de calibration,
   transformation de toutes les trajectoires ;
2. **une longueur réelle par ligne** — le rapport `longueur en pixels / longueur en
   mètres` donne une échelle **mesurée** à la profondeur où ce trait est posé.

## Décision

La seconde. Une ligne de comptage porte `lengthMeters` (`length_m` au domaine), sa
longueur réelle en mètres, facultative.

Trois raisons de la préférer à l'homographie, dans cet ordre :

- **les lignes sont déjà tracées là où il faut** — en travers de la chaussée, à la
  profondeur où les véhicules passent, c'est-à-dire là où leur vitesse intéresse ;
- **la mesure est à la portée de l'utilisateur sans matériel** : une largeur de
  chaussée, un passage piéton. L'homographie demande de connaître *deux*
  dimensions d'un quadrilatère et de le marquer avec soin ;
- **plusieurs lignes échantillonnent le gradient** de perspective sans qu'on ait à
  le modéliser.

`ScaleField` porte la règle de choix : **la ligne calibrée la plus proche**, la
distance étant mesurée au *segment* et non à sa droite support — une ligne dont on
s'est éloigné le long de son prolongement n'est pas « proche ». Pas
d'interpolation entre deux lignes : elle produirait, entre elles, une échelle que
personne n'a mesurée.

La conversion se fait **déplacement par déplacement**, à l'échelle du milieu de
chaque segment, et les mètres sont cumulés à part des pixels. Convertir le total
de pixels à la fin avec une échelle unique annulerait toute la calibration locale
pour un véhicule qui change de profondeur.

## Conséquences

- **Purement additif.** Sans aucune ligne calibrée, `ScaleField` retombe sur
  l'échelle globale et `SpeedEstimator` se comporte exactement comme avant :
  une configuration existante rend les mêmes chiffres. Vérifié par deux tests
  nommés, et sur vidéo réelle — 71 véhicules, 0 km/h avant calibration comme
  auparavant, 71 km/h avec l'échelle globale comme auparavant.
- **La mesure locale l'emporte sur le curseur global**, jamais l'inverse : sinon,
  calibrer une ligne ne changerait rien tant que le curseur est posé.
- **`lengthMeters` est le seul champ de ligne que le serveur interprète.** Les noms
  et les rôles ne font que traverser et se corrigent après coup (ADR 0016, 0023) ;
  **une longueur corrigée demande une réanalyse**, et l'interface le dit.
- Vide, zéro ou négatif valent tous « non calibrée », normalisés dans le reducer
  **et** dans le champ de saisie : `gt=0` côté serveur refuserait un zéro en 422,
  et une longueur nulle donnerait une échelle infinie — donc une vitesse infinie
  affichée comme un chiffre.
- Un preset enregistré avant cette ADR n'a pas le champ ; `withDirectionDefaults`
  le complète à `null`, comme il complète déjà les rôles.
