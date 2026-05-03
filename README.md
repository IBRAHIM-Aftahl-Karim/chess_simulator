# ♟️ Chess Human Simulator

Une interface Python conçue pour simuler un comportement de réflexion humain face à un moteur d'échecs (Stockfish).

## 🎯 Le Projet

Passionné d'échecs, j'ai créé cet outil pour pallier la frustration de jouer contre une IA qui répond instantanément. Ce simulateur introduit une latence adaptative basée sur la complexité de la position, recréant l'immersion d'une partie réelle "Over The Board" (OTB).

## 🛠️ Stack Technique

- Langage : Python 3.8+
- Logique de jeu : `python-chess`
- Moteur d'analyse : Stockfish (via protocole UCI)
- Interface : GUI développée en Python (Tkinter)

## ✨ Fonctionnalités clés

- **Interface Graphique** : Visualisation du plateau et déplacement des pièces au clic ou via saisie texte (SAN/UCI).
- **Algorithme de Temporisation** : Simulation d'un temps de réflexion humain selon la phase de jeu et la complexité de la position.
- **Pendule intégrée** : Gestion complète du temps avec incrément et bonus au coup X.
- **Niveaux ajustables** : Slider Elo de 800 à 2800.

## 📁 Structure du répertoire

* **chess_gui.py** : #Fichier principal.
* **stockfish/** : Dossier à créer, contenant le binaire Stockfish.
* **.gitignore**
* **README.md**


## 🚀 Installation \& Utilisation

1. Cloner le dépot
```bash
git clone https://github.com/IBRAHIM-Aftahl-Karim/chess_simulator.git
cd chess_simulator
```

2. Installer les dépendances :
```bash
pip install python-chess
```

3. Télécharger Stockfish sur [stockfishchess.org](https://stockfishchess.org/download/) et placer l'exécutable dans le dossier `stockfish/`.

4. Lancer le simulateur :
```bash
python chess_gui.py
```

## ⚠️ Notes

- La promotion d'un pion se fait toujours en dame via le clic. Pour choisir une autre pièce, utiliser la saisie texte (ex: `a8=N`).
- Compatible Windows, Linux et macOS.

