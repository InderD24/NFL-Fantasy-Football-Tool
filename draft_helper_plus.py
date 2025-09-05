# Upgrade draft_helper_plus.py with:
# - "Your Roster Needs" line in `suggest`
# - New command `board_full` to print the full draft board (all teams & picks)
# - New command `needs` to print roster needs for every team
# The rest of the behavior remains unchanged.

#!/usr/bin/env python3
import argparse, csv, json, math, os, sys, textwrap, re, time
from collections import defaultdict, deque

# ----------------------------
# Utility & Data Structures
# ----------------------------

STARTING_SLOTS_DEFAULT = {
    "QB": 1,
    "RB": 2,
    "WR": 2,
    "TE": 1,
    "FLEX": 1,  # RB/WR/TE
    "K": 1,
    "DST": 1,
}
FLEX_ELIGIBLE = {"RB","WR","TE"}

SAFE_TAGS = {"established","young","usage","role","dual_threat"}
RISKY_TAGS = {"rookie","injury","age","boom_bust","volatility","off_field","contract","committee","volatile"}

def parse_args():
    p = argparse.ArgumentParser(description="Live PPR draft helper (multi-source ranks, safe/risky suggestions).")
    p.add_argument("--teams", type=int, default=10, help="Number of teams (default 10)")
    p.add_argument("--pick", type=int, required=True, help="Your draft slot (1-indexed), e.g. 3")
    p.add_argument("--rounds", type=int, default=14, help="Total rounds, default 14")
    p.add_argument("--csv", default="rankings_ppr_master.csv", help="Rankings CSV path")
    p.add_argument("--format", default="ppr", choices=["ppr","half","std"], help="Scoring (informational)")
    p.add_argument("--roster", default="", help="Override starting slots, e.g. QB:1,RB:2,WR:2,TE:1,FLEX:1,K:1,DST:1")
    return p.parse_args()

def parse_roster(s):
    slots = dict(STARTING_SLOTS_DEFAULT)
    if not s:
        return slots
    for part in s.split(","):
        k,v = part.split(":")
        slots[k.strip().upper()] = int(v)
    return slots

def composite_rank(row):
    """
    Compute a composite 'working rank' using ESPN_Clay, FP_ECR, DS if available.
    Lower is better.
    Weighted average: ESPN 0.5, FP 0.3, DS 0.2 (fallback to whatever exists).
    Finally fallback to ConsensusRank.
    """
    fields = []
    weights = []
    def try_float(x):
        try:
            return float(x)
        except:
            return None
    espn = try_float(row.get("ESPN_Clay_Rank",""))
    fp   = try_float(row.get("FP_ECR_Rank",""))
    ds   = try_float(row.get("DS_Rank",""))
    cons = try_float(row.get("ConsensusRank",""))
    if espn is not None:
        fields.append(espn); weights.append(0.5)
    if fp is not None:
        fields.append(fp); weights.append(0.3)
    if ds is not None:
        fields.append(ds); weights.append(0.2)
    if fields:
        wavg = sum(f*w for f,w in zip(fields,weights)) / sum(weights)
        return wavg
    return cons if cons is not None else 9999.0

def load_players(csv_path):
    players = []
    with open(csv_path, newline="", encoding="utf-8") as f:
        r = csv.DictReader(f)
        for row in r:
            row = {k: (v.strip() if isinstance(v,str) else v) for k,v in row.items()}
            row["work_rank"] = composite_rank(row)
            row["taken_by"] = None
            row["RiskTag"] = row.get("RiskTag","")
            players.append(row)
    # Deduplicate by name keeping best (lowest) work_rank
    unique = {}
    for p in players:
        name = p["Player"]
        if name not in unique or p["work_rank"] < unique[name]["work_rank"]:
            unique[name] = p
    return list(unique.values())

def snake_pick_order(teams, rounds):
    # Returns list of (round, pick_within_round, global_pick, team_slot)
    order = []
    global_pick = 1
    for rnd in range(1, rounds+1):
        rng = range(1, teams+1) if rnd % 2 == 1 else range(teams, 0, -1)
        for slot in rng:
            order.append((rnd, (slot if rnd%2==1 else (teams-slot+1)), global_pick, slot))
            global_pick += 1
    return order

# -------- Roster helpers (starters & needs) --------

def assign_starters(roster, roster_slots):
    """Return a shallow-copied list where each player has a _starter_slot assigned (pos or FLEX) if they fill a starting slot."""
    ro = [dict(p) for p in roster]
    for pl in ro:
        pl["_starter_slot"] = None
    # fill fixed positions first
    for pos in ["QB","RB","WR","TE","K","DST"]:
        need = roster_slots.get(pos,0)
        filled = 0
        for pl in ro:
            if filled >= need: break
            if pl["Pos"] == pos and pl["_starter_slot"] is None:
                pl["_starter_slot"] = pos
                filled += 1
    # fill FLEX
    flex_need = roster_slots.get("FLEX",0)
    filled_flex = 0
    if flex_need > 0:
        for pl in ro:
            if filled_flex >= flex_need: break
            if pl["_starter_slot"] is None and pl["Pos"] in FLEX_ELIGIBLE:
                pl["_starter_slot"] = "FLEX"
                filled_flex += 1
    return ro

def needs_for_roster(roster, roster_slots):
    """Return dict of how many starters remain to be filled for each slot."""
    ro = assign_starters(roster, roster_slots)
    need = {}
    for pos, req in roster_slots.items():
        have = sum(1 for p in ro if p.get("_starter_slot") == pos)
        need[pos] = max(0, req - have)
    return need

def needs_str(need_dict):
    parts = []
    for pos in ["QB","RB","WR","TE","FLEX","K","DST"]:
        if pos in need_dict:
            remain = need_dict[pos]
            if remain > 0:
                parts.append(f"{pos}:{remain}")
    return ", ".join(parts) if parts else "All starters filled"

# -------- Scoring & suggestion --------

def pos_need_multiplier(roster_slots, my_roster, pos, round_idx):
    """
    Increase value for positions where we still need starters.
    De-emphasize K/DST until late (after round ~10).
    """
    if pos in ("K","DST"):
        if round_idx < 10:
            return 0.4
        else:
            return 0.9

    # Direct positional need
    ro = assign_starters(my_roster, roster_slots)
    starters_have = sum(1 for p in ro if p.get("_starter_slot") == pos)
    starters_needed = roster_slots.get(pos,0)
    needed = 1.0
    if starters_have < starters_needed:
        needed += 0.6
    else:
        # Flex need
        if pos in FLEX_ELIGIBLE:
            flex_have = sum(1 for p in ro if p.get("_starter_slot") == "FLEX")
            flex_needed = roster_slots.get("FLEX",0)
            if flex_have < flex_needed:
                needed += 0.3
    return needed

def risk_score(row):
    tags = set([t.strip() for t in (row.get("RiskTag","") or "").split(",") if t.strip()])
    safe = len(tags & SAFE_TAGS)
    risky = len(tags & RISKY_TAGS)
    # Higher = riskier
    return max(0, risky - safe)

def value_score(row, roster_slots, my_roster, round_idx):
    # Lower work_rank is better; convert to descending score
    wr = float(row.get("work_rank", 9999.0))
    base = -wr
    pos = row.get("Pos","")
    need = pos_need_multiplier(roster_slots, my_roster, pos, round_idx)
    # Gentle TE premium if top tiers
    tier = (row.get("Tier","") or "").lower()
    if pos == "TE" and ("tier 1" in tier or "tier 1-2" in tier):
        base += 2.0
    # Slight WR bump in full PPR (informational only here)
    if pos == "WR":
        base += 1.0
    return base * need

def printable_player(row):
    parts = [row.get("Player",""), row.get("Team",""), row.get("Pos","")]
    by = row.get("Bye","")
    if by:
        parts.append(f"Bye {by}")
    tags = row.get("RiskTag","")
    if tags:
        parts.append(f"[{tags}]")
    return " ".join([p for p in parts if p])

class Draft:
    def __init__(self, teams, my_slot, rounds, players, roster_slots):
        self.teams = teams
        self.my_slot = my_slot
        self.rounds = rounds
        self.players = players
        self.order = snake_pick_order(teams, rounds)
        self.picks = []  # list of dicts: {global_pick, team_slot, player_name}
        self.team_rosters = {i: [] for i in range(1, teams+1)}
        self.roster_slots = roster_slots

    def next_pick_index(self):
        return len(self.picks)

    def on_clock_team(self):
        idx = self.next_pick_index()
        if idx >= len(self.order): return None
        _, _, _, slot = self.order[idx]
        return slot

    def round_and_pick(self):
        idx = self.next_pick_index()
        if idx >= len(self.order): return (None, None, None)
        rnd, pwr, gp, slot = self.order[idx]
        return rnd, pwr, gp

    def available_players(self):
        return [p for p in self.players if not p.get("taken_by")]

    def find_player(self, name):
        name_norm = name.strip().lower()
        for p in self.players:
            if p["Player"].strip().lower() == name_norm:
                return p
        # try loose match
        cands = [p for p in self.players if name_norm in p["Player"].strip().lower()]
        return cands[0] if cands else None

    def add_player_if_missing(self, name, pos="WR", team="", work_rank=9999.0, risktag="volatile"):
        if self.find_player(name):
            return
        row = {
            "ConsensusRank": str(int(work_rank)) if work_rank < 9999 else "",
            "Player": name,
            "Team": team,
            "Pos": pos,
            "Bye": "",
            "FP_ECR_Rank": "",
            "ESPN_Clay_Rank": "",
            "DS_Rank": "",
            "RiskTag": risktag,
            "Tier": "",
            "Notes": "added-live",
            "work_rank": float(work_rank),
            "taken_by": None
        }
        self.players.append(row)

    def record_pick(self, team_slot, player_name):
        p = self.find_player(player_name)
        if not p:
            # Auto-add unknown player with low priority
            self.add_player_if_missing(player_name, pos="WR", team="", work_rank=1500, risktag="volatile")
            p = self.find_player(player_name)
        if p.get("taken_by"):
            return f"{p['Player']} is already taken by Team {p['taken_by']}."
        p["taken_by"] = team_slot
        self.picks.append({"global_pick": len(self.picks)+1, "team_slot": team_slot, "player": p["Player"]})
        self.team_rosters[team_slot].append(p)
        return f"Recorded pick #{len(self.picks)}: Team {team_slot} -> {p['Player']} ({p['Pos']})"

    def undo(self):
        if not self.picks: return "No picks to undo."
        last = self.picks.pop()
        # clear player
        for p in self.players:
            if p["Player"] == last["player"] and p.get("taken_by") == last["team_slot"]:
                p["taken_by"] = None
                break
        # remove from roster
        r = self.team_rosters[last["team_slot"]]
        for i in range(len(r)-1, -1, -1):
            if r[i]["Player"] == last["player"]:
                r.pop(i); break
        return f"Undid pick #{last['global_pick']} ({last['player']})"

    # ---------- New: Roster needs strings ----------
    def my_needs_str(self):
        my_roster = list(self.team_rosters[self.my_slot])
        need = needs_for_roster(my_roster, self.roster_slots)
        return needs_str(need)

    def all_needs_report(self):
        lines = ["=== Roster Needs (starters remaining) ==="]
        for t in range(1, self.teams+1):
            need = needs_for_roster(self.team_rosters[t], self.roster_slots)
            lines.append(f"Team {t}: {needs_str(need)}")
        return "\n".join(lines)

    def suggest(self):
        rnd, pwr, gp = self.round_and_pick()
        if rnd is None:
            return "Draft complete."
        on_clock = self.on_clock_team()
        my_turn = (on_clock == self.my_slot)

        # Build my roster view with inferred starter slots
        my_roster = list(self.team_rosters[self.my_slot])
        # Label starters & flex
        my_roster_with_slots = assign_starters(my_roster, self.roster_slots)

        avail = self.available_players()
        # Score candidates
        scored = []
        for p in avail:
            vs = value_score(p, self.roster_slots, my_roster_with_slots, rnd)
            rs = risk_score(p)
            scored.append((vs, rs, p))
        # Sort by value desc
        scored.sort(key=lambda x: (-x[0], x[1]))

        # SAFE pick: prefer lower risk_score
        safe = None
        for vs, rs, p in scored:
            if rs <= 0 or "rookie" not in (p.get("RiskTag","")):
                safe = p; break
        if not safe and scored:
            safe = scored[0][2]
        # RISKY pick: prefer higher risk_score + value
        risky = None
        risky_sorted = sorted(scored, key=lambda x: (-x[0] + 0.5*x[1]))
        if risky_sorted:
            risky = risky_sorted[0][2]

        # Build top board
        top_board = [p for _,__,p in scored[:25]]
        lines = []
        lines.append(f"On clock: Team {on_clock}  (Round {rnd}, Overall #{gp})")
        if my_turn:
            lines.append("It's YOUR pick.")
        # New line: show user's roster needs
        lines.append(f"Your Roster Needs: {self.my_needs_str()}")
        lines.append("Recommendation:")
        lines.append(f"  SAFE  -> {printable_player(safe) if safe else 'n/a'}")
        lines.append(f"  RISKY -> {printable_player(risky) if risky else 'n/a'}")
        lines.append("Top-25 board:")
        for i,p in enumerate(top_board, start=1):
            lines.append(f"{i:>2}. {printable_player(p)}")
        return "\n".join(lines)

    def show_board(self, n=25):
        rnd, _, _ = self.round_and_pick()
        my_roster = list(self.team_rosters[self.my_slot])
        avail = self.available_players()
        scored = [(value_score(p, self.roster_slots, assign_starters(my_roster, self.roster_slots), rnd), p) for p in avail]
        scored.sort(key=lambda x: -x[0])
        out = []
        for i, (_, p) in enumerate(scored[:n], start=1):
            out.append(f"{i:>2}. {printable_player(p)}")
        return "\n".join(out)

    def show_teams(self):
        out = []
        for t in range(1, self.teams+1):
            out.append(f"Team {t}:")
            roster = self.team_rosters[t]
            if not roster:
                out.append("  (empty)")
                continue
            for pl in roster:
                out.append(f"  - {printable_player(pl)}")
        return "\n".join(out)

    def board_full(self):
        out = ["=== Draft Board Snapshot ==="]
        for t in range(1, self.teams+1):
            out.append(f"Team {t}:")
            roster = self.team_rosters[t]
            if not roster:
                out.append("  (empty)")
                continue
            for pl in roster:
                out.append(f"  - {pl['Player']} {pl['Team']} {pl['Pos']}")
        return "\n".join(out)

    def save(self, path="draft_state.json"):
        data = {
            "teams": self.teams,
            "my_slot": self.my_slot,
            "rounds": self.rounds,
            "picks": self.picks,
            "team_rosters": {
                str(k): [{"Player": p["Player"], "Team": p["Team"], "Pos": p["Pos"]} for p in v]
                for k,v in self.team_rosters.items()
            },
        }
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
        return f"Saved -> {path}"

def repl(draft: "Draft"):
    HELP = textwrap.dedent("""\
    Commands:
      suggest                      Show SAFE & RISKY recommendation + top-25 board + YOUR roster needs
      board                        Show top-25 board
      board_full                   Show full draft board (all teams & picks)
      teams                        Show all team rosters
      needs                        Show roster needs for every team
      find "text"                  Search players by substring
      me "Player Name"             Record YOUR pick
      other "Player Name"          Record someone else's pick
      add "Name" POS TEAM [rank]   Add a player (if missing), default rank=1500
      setrank [espn|fp|ds|consensus] "Name" N   Update rank live
      tag "Name" tag1,tag2         Update risk tags (comma-separated)
      undo                         Undo last pick
      save                         Save draft_state.json
      help                         Show commands
      quit                         Exit
    """)
    print("Type 'help' for commands.")
    while True:
        try:
            line = input("> ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\nBye")
            return
        if not line: 
            continue
        low = line.lower()
        if low in {"quit","exit"}:
            print("Bye")
            return
        if low == "help":
            print(HELP); continue
        if low == "suggest":
            print(draft.suggest()); continue
        if low == "board":
            print(draft.show_board()); continue
        if low == "board_full":
            print(draft.board_full()); continue
        if low == "needs":
            print(draft.all_needs_report()); continue
        if low == "teams":
            print(draft.show_teams()); continue
        if low.startswith("find "):
            q = line[5:].strip().strip('"').lower()
            hits = [p for p in draft.available_players() if q in p["Player"].lower()]
            if not hits: print("No matches."); continue
            for i,p in enumerate(hits[:50], start=1):
                print(f"{i:>2}. {printable_player(p)}")
            continue
        if low.startswith("me "):
            name = line[3:].strip().strip('"')
            print(draft.record_pick(draft.my_slot, name)); continue
        if low.startswith("other "):
            name = line[6:].strip().strip('"')
            team = draft.on_clock_team()
            if team == draft.my_slot:
                idx = draft.next_pick_index()
                for j in range(idx, len(draft.order)):
                    _,_,_, slot = draft.order[j]
                    if slot != draft.my_slot:
                        team = slot; break
            print(draft.record_pick(team, name)); continue
        if low.startswith("add "):
            m = re.match(r'add\s+"([^"]+)"\s+([A-Z]+)\s+([A-Z]{2,3})\s*(\d+)?', line)
            if not m:
                print('Usage: add "Name" POS TEAM [rank]'); continue
            nm, pos, tm, rk = m.group(1), m.group(2), m.group(3), m.group(4)
            rank = float(rk) if rk else 1500.0
            draft.add_player_if_missing(nm, pos=pos, team=tm, work_rank=rank, risktag="volatile")
            print(f'Added {nm} ({pos}, {tm}) with rank {rank}.'); continue
        if low.startswith("setrank "):
            m = re.match(r'setrank\s+(espn|fp|ds|consensus)\s+"([^"]+)"\s+(\d+)', low)
            if not m:
                print('Usage: setrank [espn|fp|ds|consensus] "Name" N'); continue
            src, nm, rk = m.group(1), m.group(2), int(m.group(3))
            p = draft.find_player(nm)
            if not p:
                print("Player not found."); continue
            if src == "espn":
                p["ESPN_Clay_Rank"] = str(rk)
            elif src == "fp":
                p["FP_ECR_Rank"] = str(rk)
            elif src == "ds":
                p["DS_Rank"] = str(rk)
            else:
                p["ConsensusRank"] = str(rk)
            p["work_rank"] = float(rk) if src=="consensus" else composite_rank(p)
            print(f"Set {src} rank for {p['Player']} to {rk}."); continue
            # no recompute for all; lazy recompute occurs on next suggest/board
        if low.startswith("tag "):
            m = re.match(r'tag\s+"([^"]+)"\s+(.+)$', line, flags=re.IGNORECASE)
            if not m:
                print('Usage: tag "Name" tag1,tag2'); continue
            nm, tags = m.group(1), m.group(2)
            p = draft.find_player(nm)
            if not p:
                print("Player not found."); continue
            p["RiskTag"] = tags
            print(f"Updated RiskTag for {p['Player']} -> {tags}"); continue
        if low == "undo":
            print(draft.undo()); continue
        if low == "save":
            print(draft.save()); continue

        print("Unknown command. Type 'help' for commands.")

def main():
    args = parse_args()
    roster_slots = parse_roster(args.roster)
    players = load_players(args.csv)
    if not players:
        print("No players loaded from CSV. Please check --csv path.")
        return
    draft = Draft(args.teams, args.pick, args.rounds, players, roster_slots)
    print(f"Loaded {len(players)} players from {args.csv}.")
    print(f"Teams: {args.teams}, Your slot: {args.pick}, Rounds: {args.rounds}, Scoring: {args.format.upper()}")
    print("Roster:", ", ".join(f"{k}:{v}" for k,v in roster_slots.items()))
    rnd, pwr, gp = draft.round_and_pick()
    print(f"You're at Round {rnd}, Overall #{gp}. Type 'suggest' to start.")
    repl(draft)

if __name__ == "__main__":
    main()

