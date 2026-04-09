#!/usr/bin/env python3
"""
Simulateur de temps de réflexion humain pour Stockfish
Cadences longues OTB : 1h+15s, 1h30+30s, etc.
"""

import chess
import chess.engine
import time
import random
import sys
import os
from dataclasses import dataclass, field
from typing import Optional

# ─────────────────────────────────────────────
#  Configuration
# ─────────────────────────────────────────────

STOCKFISH_PATH = r"C:\Users\ismai\Desktop\chess-simulator\stockfish\stockfish-windows-x86-64-avx2.exe"   # ← adapter selon votre système
STOCKFISH_ELO  = 1800                         # ← adapter à votre niveau

# Cadence (en secondes)
TIME_CONTROL = {
    "base_time":  3600,   # 1 heure
    "increment":  15,     # 15 secondes par coup
    "bonus_move": 40,     # coup 40 (None pour désactiver)
    "bonus_time": 0,      # temps ajouté au coup 40 (0 = désactivé)
}

# Profondeur d'analyse Stockfish (MultiPV pour score difficulté)
MULTIPV        = 3
ANALYSIS_TIME  = 0.5      # secondes d'analyse (impact sur CPU, pas sur le délai affiché)

# Temps de base et coefficient de conversion score → secondes
T_BASE       = 20         # secondes minimum
T_COEFF      = 45         # secondes par point de score
T_NOISE_MIN  = 10         # bruit aléatoire minimum (secondes)
T_NOISE_MAX  = 60         # bruit aléatoire maximum (secondes)
T_MIN        = 3          # jamais moins de 3 secondes
T_MAX        = 600        # jamais plus de 10 minutes

# ─────────────────────────────────────────────
#  Couleurs ANSI
# ─────────────────────────────────────────────

class C:
    RESET  = "\033[0m"
    BOLD   = "\033[1m"
    DIM    = "\033[2m"
    RED    = "\033[91m"
    GREEN  = "\033[92m"
    YELLOW = "\033[93m"
    BLUE   = "\033[94m"
    CYAN   = "\033[96m"
    WHITE  = "\033[97m"
    GRAY   = "\033[90m"

def banner():
    print(f"""
{C.CYAN}{C.BOLD}
  ╔══════════════════════════════════════════════╗
  ║   ♟  Simulateur de Réflexion OTB  ♟          ║
  ║      Stockfish × Temps Humain                ║
  ╚══════════════════════════════════════════════╝
{C.RESET}""")

# ─────────────────────────────────────────────
#  Horloge simulée
# ─────────────────────────────────────────────

@dataclass
class Clock:
    white: float = TIME_CONTROL["base_time"]
    black: float = TIME_CONTROL["base_time"]
    increment: float = TIME_CONTROL["increment"]
    move_count: int = 0

    def apply_increment(self, color: chess.Color):
        if color == chess.WHITE:
            self.white += self.increment
        else:
            self.black += self.increment

    def deduct(self, color: chess.Color, seconds: float):
        if color == chess.WHITE:
            self.white = max(0, self.white - seconds)
        else:
            self.black = max(0, self.black - seconds)

    def get(self, color: chess.Color) -> float:
        return self.white if color == chess.WHITE else self.black

    def fmt(self, seconds: float) -> str:
        m, s = divmod(int(seconds), 60)
        h, m = divmod(m, 60)
        if h:
            return f"{h}h{m:02d}m{s:02d}s"
        return f"{m:02d}m{s:02d}s"

    def display(self):
        w_color = C.GREEN if self.white > 300 else (C.YELLOW if self.white > 60 else C.RED)
        b_color = C.GREEN if self.black > 300 else (C.YELLOW if self.black > 60 else C.RED)
        print(f"  {C.GRAY}Pendule ──{C.RESET}  "
              f"Blanc {w_color}{self.fmt(self.white)}{C.RESET}  │  "
              f"Noir {b_color}{self.fmt(self.black)}{C.RESET}")

# ─────────────────────────────────────────────
#  Calcul du score de complexité
# ─────────────────────────────────────────────

def score_phase(board: chess.Board) -> float:
    """Phase de la partie : ouverture / milieu / finale."""
    move_num = board.fullmove_number
    # Compter les pièces majeures
    major_pieces = len(board.pieces(chess.QUEEN, chess.WHITE)) \
                 + len(board.pieces(chess.QUEEN, chess.BLACK)) \
                 + len(board.pieces(chess.ROOK, chess.WHITE)) \
                 + len(board.pieces(chess.ROOK, chess.BLACK))

    if move_num <= 10:
        return 1.0   # ouverture
    elif major_pieces >= 4:
        return 3.0   # milieu de jeu
    else:
        return 4.0   # finale

def score_tactical(board: chess.Board) -> float:
    """Richesse tactique : captures, échecs, pièces non défendues."""
    score = 0.0
    legal = list(board.legal_moves)

    captures = sum(1 for m in legal if board.is_capture(m))
    checks    = sum(1 for m in legal if board.gives_check(m))

    score += min(captures * 0.4, 2.5)
    score += min(checks   * 0.6, 2.5)
    return min(score, 5.0)

def score_criticality(prev_eval: Optional[float], curr_eval: Optional[float]) -> float:
    """Variation brutale de l'évaluation."""
    if prev_eval is None or curr_eval is None:
        return 0.0
    delta = abs(curr_eval - prev_eval)
    # 1 pion ≈ 100 centipions → normaliser
    return min(delta / 50, 8.0)   # max 8 pour une variation de 4 pions

def score_difficulty(infos: list) -> float:
    """Difficulté du choix : écarts entre les N meilleurs coups."""
    if len(infos) < 2:
        return 0.0
    scores = []
    for info in infos:
        score = info.get("score")
        if score and not score.is_mate():
            scores.append(score.relative.score())
    if len(scores) < 2:
        return 0.0
    gap = abs(scores[0] - scores[1]) / 100.0  # en pions
    # Plus le gap est petit, plus c'est difficile
    if gap < 0.1:
        return 4.0
    elif gap < 0.3:
        return 3.0
    elif gap < 0.7:
        return 2.0
    elif gap < 1.5:
        return 1.0
    else:
        return 0.0

def score_clock_pressure(remaining: float) -> float:
    """Pression à la pendule : zeitnot → coups plus rapides."""
    if remaining > 1800:   # > 30 min
        return 0.0
    elif remaining > 600:  # 10–30 min
        return -1.5
    elif remaining > 300:  # 5–10 min
        return -2.5
    else:                  # < 5 min → zeitnot
        return -3.0

def score_position_state(curr_eval: Optional[float]) -> float:
    """Position gagnante / perdante / équilibrée."""
    if curr_eval is None:
        return 0.0
    cp = curr_eval  # centipions du point de vue du joueur qui a bougé
    if cp > 150:    # gagné → consolider
        return 1.5
    elif cp < -150: # perdant → chercher ressources
        return 3.0
    else:
        return 0.0  # équilibré

def compute_complexity_score(
    board: chess.Board,
    infos: list,
    prev_eval: Optional[float],
    curr_eval: Optional[float],
    clock_remaining: float,
) -> float:
    """Score total pondéré selon le cahier des charges."""
    s_phase    = score_phase(board)
    s_tactical = score_tactical(board)
    s_crit     = score_criticality(prev_eval, curr_eval)
    s_diff     = score_difficulty(infos)
    s_clock    = score_clock_pressure(clock_remaining)
    s_pos      = score_position_state(curr_eval)

    total = (
        s_phase
        + s_tactical  * 2
        + s_crit      * 3
        + s_diff      * 2
        + s_clock
        + s_pos
    )

    print(f"\n  {C.GRAY}Scores de complexité :{C.RESET}")
    print(f"    Phase       {_bar(s_phase, 4)}  {s_phase:.1f}")
    print(f"    Tactique    {_bar(s_tactical, 5)}  {s_tactical:.1f} ×2")
    print(f"    Criticité   {_bar(s_crit, 8)}  {s_crit:.1f} ×3")
    print(f"    Difficulté  {_bar(s_diff, 4)}  {s_diff:.1f} ×2")
    print(f"    Pendule     {_bar(max(0, s_clock+3), 3)}  {s_clock:+.1f}")
    print(f"    Position    {_bar(s_pos, 3)}  {s_pos:.1f}")
    print(f"  {C.BOLD}  Score total : {total:.2f}{C.RESET}")

    return max(0.0, total)

def _bar(val: float, max_val: float, width: int = 8) -> str:
    filled = int(round(val / max_val * width)) if max_val else 0
    filled = max(0, min(width, filled))
    return f"{C.CYAN}{'█' * filled}{'░' * (width - filled)}{C.RESET}"

# ─────────────────────────────────────────────
#  Conversion score → temps
# ─────────────────────────────────────────────

def score_to_time(score: float, move_num: int) -> float:
    t = T_BASE + T_COEFF * score
    # Plafond strict selon la phase
    if move_num <= 10:
        t = min(t, 45)       # max 45s en ouverture
        noise = random.uniform(2, 15)
    elif move_num <= 25:
        t = min(t, 180)      # max 3min en milieu de jeu
        noise = random.uniform(5, 40)
    else:
        noise = random.uniform(T_NOISE_MIN, T_NOISE_MAX)
    
    if random.random() < 0.4:
        noise = -noise
    return max(T_MIN, min(T_MAX, t + noise))

# ─────────────────────────────────────────────
#  Affichage du compte à rebours
# ─────────────────────────────────────────────

def countdown(seconds: float, move_san: str):
    total = int(seconds)
    intervals = [
        (total,        f"{C.YELLOW}♟  Stockfish réfléchit…{C.RESET}"),
        (total // 2,   f"{C.YELLOW}♟  Stockfish analyse en profondeur…{C.RESET}"),
        (15,           f"{C.CYAN}♟  Stockfish finalise son choix…{C.RESET}"),
        (5,            f"{C.GREEN}♟  Stockfish joue !{C.RESET}"),
    ]

    print(f"\n  ⏱  Temps de réflexion simulé : {C.BOLD}{total}s{C.RESET}")

    start = time.time()
    last_msg = ""
    while True:
        elapsed = time.time() - start
        remaining = total - elapsed
        if remaining <= 0:
            break

        # Message contextuel
        msg = intervals[0][1]
        for threshold, text in intervals:
            if remaining <= threshold:
                msg = text

        if msg != last_msg:
            print(f"  {msg}")
            last_msg = msg

        # Barre de progression
        pct = elapsed / total
        bar_w = 40
        filled = int(pct * bar_w)
        bar = f"{'█' * filled}{'░' * (bar_w - filled)}"
        rem_fmt = f"{int(remaining):>3}s"
        print(f"  {C.CYAN}{bar}{C.RESET} {rem_fmt}", end="\r")
        time.sleep(0.5)

    print()  # newline après la barre
    print(f"\n  {C.GREEN}{C.BOLD}➤  Le coup du moteur est : {move_san}{C.RESET}\n")

# ─────────────────────────────────────────────
#  Boucle principale
# ─────────────────────────────────────────────

def parse_move(board: chess.Board, user_input: str) -> Optional[chess.Move]:
    """Accepte SAN ou UCI."""
    user_input = user_input.strip()
    try:
        return board.parse_san(user_input)
    except Exception:
        pass
    try:
        return board.parse_uci(user_input)
    except Exception:
        pass
    return None

def format_eval(cp: Optional[float]) -> str:
    if cp is None:
        return "?"
    pawns = cp / 100
    sign  = "+" if pawns >= 0 else ""
    color = C.GREEN if pawns > 0.2 else (C.RED if pawns < -0.2 else C.YELLOW)
    return f"{color}{sign}{pawns:.2f}{C.RESET}"

def main():
    banner()

    # Vérifier Stockfish
    sf_path = STOCKFISH_PATH
    if not os.path.exists(sf_path):
        # Essayer de trouver dans PATH
        import shutil
        found = shutil.which("stockfish")
        if found:
            sf_path = found
        else:
            print(f"{C.RED}✗  Stockfish introuvable. "
                  f"Modifiez STOCKFISH_PATH dans le script.{C.RESET}")
            sys.exit(1)

    print(f"  {C.GREEN}✓{C.RESET}  Stockfish : {sf_path}")
    print(f"  {C.GREEN}✓{C.RESET}  Elo simulé : {STOCKFISH_ELO}")
    print(f"  {C.GREEN}✓{C.RESET}  Cadence    : "
          f"{TIME_CONTROL['base_time']//60}min + {TIME_CONTROL['increment']}s")
    print()

    # Choix de la couleur
    while True:
        c = input(f"  Vous jouez les {C.BOLD}Blancs (b){C.RESET} ou les "
                  f"{C.BOLD}Noirs (n){C.RESET} ? ").strip().lower()
        if c in ("b", "blanc", "blancs", "white", "w"):
            player_color = chess.WHITE
            break
        elif c in ("n", "noir", "noirs", "black"):
            player_color = chess.BLACK
            break
        print("  Répondre b ou n.")

    print()

    board    = chess.Board()
    clock    = Clock()
    prev_eval: Optional[float] = None
    eval_history =[]

    with chess.engine.SimpleEngine.popen_uci(sf_path) as engine:

        # Configurer le niveau Elo
        try:
            engine.configure({"UCI_LimitStrength": True, "UCI_Elo": STOCKFISH_ELO})
        except Exception:
            pass  # certaines versions de Stockfish n'acceptent pas ces options

        def evaluate_draw_offer(board: chess.Board, eval_history: list) -> tuple[bool, str]:
            """Le moteur évalue si la nulle est acceptable."""
        
        # 1. Répétition de position (déjà dans python-chess)
        if board.is_repetition(2):
            return True, "répétition de position détectée"
        
        # 2. Pat
        if board.is_stalemate():
            return True, "pat"
        
        # 3. Matériel insuffisant
        if board.is_insufficient_material():
            return True, "matériel insuffisant"
        
        # 4. Position équilibrée depuis 20 coups
        if len(eval_history) >= 20:
            last_20 = eval_history[-20:]
            if all(-30 < e < 30 for e in last_20 if e is not None):
                return True, "position équilibrée depuis 20 coups"
        
        # 5. Moteur en train de perdre → accepte plus facilement
        if eval_history:
            last = eval_history[-1]
            if last is not None and last < -80:
                return True, "position difficile pour le moteur"
        
        # 6. Moteur gagnant → refuse
        if eval_history:
            last = eval_history[-1]
            if last is not None and last > 80:
                return False, "position favorable au moteur, nulle refusée"
        
            return False, "nulle refusée"
    
        while not board.is_game_over():

            clock.display()
            print(f"\n  {C.GRAY}Position (FEN) :{C.RESET}")
            print(f"  {board.fen()}")
            print()

            turn = board.turn

            # ── Joueur ───────────────────────────────────────────────────
            if turn == player_color:
                print(f"  {C.BOLD}{C.WHITE}▶  Votre coup (SAN ou UCI, ex: e4 / e2e4) :{C.RESET} ", end="")
                raw = input().strip()

                if raw.lower() in ("quit", "exit", "q", "abandon"):
                    print(f"\n  {C.YELLOW}Partie abandonnée. Vous perdez.{C.RESET}")
                    break

                if raw.lower() in ("nulle", "draw", "="):
                    print(f"\n  {C.YELLOW}Nulle proposée — acceptée par le moteur.{C.RESET}")
                    break

                if raw.lower() in ("aide", "help", "?"):
                    print(f"""
                {C.CYAN}Commandes disponibles :{C.RESET}
                    {C.BOLD}abandon{C.RESET}   → vous perdez la partie
                    {C.BOLD}nulle{C.RESET}     → proposer nulle (acceptée automatiquement)
                    {C.BOLD}quit{C.RESET}      → quitter le programme
                    {C.BOLD}aide{C.RESET}      → afficher cette aide
                """)
                    continue

                move = parse_move(board, raw)
                if move is None or move not in board.legal_moves:
                    print(f"  {C.RED}✗  Coup illégal ou non reconnu. Réessayez.{C.RESET}")
                    continue

                t_start = time.time()
                board.push(move)
                clock.apply_increment(player_color)
                t_elapsed = time.time() - t_start
                clock.deduct(player_color, t_elapsed)

                print(f"  {C.GREEN}✓{C.RESET}  Coup joué : {C.BOLD}{move.uci()}{C.RESET}")

            # ── Moteur ───────────────────────────────────────────────────
            else:
                engine_color = chess.BLACK if player_color == chess.WHITE else chess.WHITE
                remaining    = clock.get(engine_color)

                print(f"  {C.YELLOW}{C.BOLD}♟  Stockfish (tour {board.fullmove_number})…{C.RESET}")

                # ── Analyse MultiPV pour le score de complexité (sans limite Elo) ──
                infos = engine.analyse(
                    board,
                    chess.engine.Limit(time=ANALYSIS_TIME),
                    multipv=MULTIPV,
                    options={"UCI_LimitStrength": False}
                )

                curr_eval_raw = None
                if infos:
                    info0 = infos[0] if isinstance(infos, list) else infos
                    score = info0.get("score")
                    if score and not score.is_mate():
                        curr_eval_raw = score.relative.score()

                # ── Coup joué avec la vraie limite Elo ──  ← C'est ici le fix
                result = engine.play(
                    board,
                    chess.engine.Limit(time=ANALYSIS_TIME),
                    options={"UCI_LimitStrength": True, "UCI_Elo": STOCKFISH_ELO}
                )
                best_move = result.move

                # Score de complexité
                score_total = compute_complexity_score(
                    board,
                    infos if isinstance(infos, list) else [infos],
                    prev_eval,
                    curr_eval_raw,
                    remaining,
                )
                prev_eval = curr_eval_raw

                # Temps simulé
                wait_time = score_to_time(score_total, board.fullmove_number)
                wait_time = min(wait_time, remaining * 0.25)  # ne pas dépasser 25% du temps restant

                # SAN avant de pousser le coup
                move_san = board.san(best_move)

                # Countdown et affichage
                eval_str = format_eval(curr_eval_raw)
                print(f"  Évaluation : {eval_str}")
                countdown(wait_time, move_san)

                # Appliquer le coup
                t_start = time.time()
                board.push(best_move)
                clock.apply_increment(engine_color)
                t_elapsed = time.time() - t_start + wait_time
                clock.deduct(engine_color, t_elapsed)

        # ── Fin de partie ─────────────────────────────────────────────
        print(f"\n  {C.CYAN}{C.BOLD}══════════════  Fin de partie  ══════════════{C.RESET}")
        result = board.result()
        outcome = board.outcome()
        print(f"  Résultat : {C.BOLD}{result}{C.RESET}")
        if outcome:
            if outcome.winner == player_color:
                print(f"  {C.GREEN}{C.BOLD}🏆  Félicitations, vous avez gagné !{C.RESET}")
            elif outcome.winner is None:
                print(f"  {C.YELLOW}  Partie nulle.{C.RESET}")
            else:
                print(f"  {C.RED}  Stockfish a gagné.{C.RESET}")
        print()

if __name__ == "__main__":
    main()
