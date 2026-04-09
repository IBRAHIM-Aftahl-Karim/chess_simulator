\# ♟️ Chess Human Simulator



Une interface Python conçue pour simuler un comportement de réflexion humain face à un moteur d'échecs (Stockfish). 



\## 🎯 Le Projet

Passionné d'échecs, j'ai créé cet outil pour pallier la frustration de jouer contre une IA qui répond instantanément. Ce simulateur introduit une latence adaptative basée sur la complexité de la position, recréant l'immersion d'une partie réelle "Over The Board" (OTB).



\## Stack Technique

* Langage : Python 3
* Logique de jeu : `python-chess`
* Moteur d'analyse : Stockfish (via protocole UCI)
* Interface :\*\* GUI développée en Python (Tkinter)



\## Fonctionnalités clés

* Interface Graphique : Visualisation du plateau et déplacement des pièces.
* Algorithme de Temporisation : Simulation d'un temps de réflexion humain (pondération aléatoire et logique).
* Communication Inter-processus : Gestion des flux d'entrée/sortie avec l'exécutable Stockfish.



\## 📁 Structure du répertoire

* chess\_gui.py` : Gestion de l'interface utilisateur et des événements.
* `chess-simulator.py` : Logique principale et interaction avec le moteur de jeu.
* `stockfish/` : Dossier contenant les binaires du moteur d'analyse.



\## 🚀 Installation \& Utilisation

1\. Cloner le dépôt :

&#x20;  ```bash

&#x20;  git clone \[https://github.com/TON\_PSEUDO/chess-simulator.git](https://github.com/TON\_PSEUDO/chess-simulator.git)

