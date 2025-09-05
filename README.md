# 🏈 NFL Fantasy Draft Helper (PPR)

[![Python](https://img.shields.io/badge/Python-3.9%2B-blue.svg)](https://www.python.org/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

A command-line tool to help you **dominate your fantasy football draft**.  
It blends expert rankings from multiple sources (FantasyPros, ESPN Mike Clay, DraftSharks) into a **consensus big board** and suggests **safe vs. risky picks** based on your roster needs.

---

## 📂 Files
- **`draft_helper_plus.py`** → main CLI tool  
- **`rankings_ppr_master.csv`** → consensus rankings data  
- **`rankings_ppr_master_nflonly.csv`** → NFL-only subset  

---

## ⚙️ Requirements
- Python **3.9+**
- CSV file with rankings (included in repo)

---

## 🚀 Quick Start

Example: 10 teams, you pick #3, 14 rounds, full PPR:

```bash
python draft_helper_plus.py \
  --teams 10 \
  --pick 3 \
  --rounds 14 \
  --format ppr \
  --csv rankings_ppr_master.csv
```

---

## 🛠️ Core Commands

```bash
suggest               # show SAFE & RISKY picks
pick "Player Name"    # record your draft pick
board                 # show current draft board
top25                 # view top-25 remaining players
needs                 # display roster needs for every team
undo                  # undo last pick
save draft_state.json # save draft progress
```
---

## 💡 Tips

- Open `rankings_ppr_master.csv` in Excel or Google Sheets and paste in updated top-200 from ESPN, FantasyPros, or DraftSharks.  
- The tool blends ranks from **ESPN (50%)**, **FantasyPros (30%)**, and **DraftSharks (20%)**.  
- Unknown players are handled: if someone enters a name not in the CSV, the tool will add it on the fly so you can keep drafting.  
- Use `undo` to fix mistakes quickly, and `save draft_state.json` to back up progress mid-draft.  
- Customize player tags (e.g., rookie, injury, boom_bust) in the CSV to influence SAFE/RISKY suggestions.
