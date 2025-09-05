
NFL Fantasy Draft Helper (PPR) – Quick Start
===========================================
Files:
- rankings_ppr_master.csv
- draft_helper_plus.py

Requirements: Python 3.9+

How to run (your league from previous chat: 10 teams, you pick #3, 14 rounds, full PPR):
    python draft_helper_plus.py --teams 10 --pick 3 --rounds 14 --format ppr --csv rankings_ppr_master.csv

Core commands during the draft:
    suggest                      # SAFE & RISKY pick + top-25 board
    me "Player Name"            # record your pick
    other "Player Name"         # record another team's pick
    board                        # view top-25 remaining
    teams                        # show all rosters
    find "text"                  # quick search the board
    setrank espn "Name" 12       # update ESPN Mike Clay rank on the fly
    setrank fp "Name" 10         # update FantasyPros ECR rank
    setrank ds "Name" 8          # update DraftSharks rank
    tag "Name" rookie,boom_bust  # adjust risk tags to influence SAFE/RISKY
    add "New Guy" WR KC 300      # add any missing player (pos/team/rank)
    undo                         # undo last pick
    save                         # save draft_state.json

Tips:
- You can open rankings_ppr_master.csv in Excel/Google Sheets and paste in top-200 from ESPN/FantasyPros/DraftSharks.
- The tool automatically recomputes working ranks from the source columns (ESPN 50%, FP 30%, DS 20%; falls back to ConsensusRank).
- Unknown picks are handled: if someone takes a name not in the CSV, the tool will add it on the fly so you can keep drafting.
