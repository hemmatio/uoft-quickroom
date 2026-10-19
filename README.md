# U of T QuickRoom Finder

A fast, lightweight web app and API aggregator for University of Toronto study rooms and LibCal spaces.

## Features
- **Parallel Multi-Room Availability**: Aggregates live availability across 170 bookable rooms in 13 libraries concurrently.
- **Rule-Based Group Size Filtering**: Respects library policies (e.g. solo users can book Robarts Stacks/OISE/Graham individual rooms; group rooms requiring 2+, 3+, or 5+ people are strictly filtered).
- **Campus Filtering**: Toggle between St. George (UTSG), Mississauga (UTM), and Scarborough (UTSC).
- **UTSG Drag-to-Box Map Filter**: Drag a rectangular bounding box on the stylized campus map to isolate specific buildings.
- **Auto-Selection**: One-click optimal room picker meeting all specified constraints.
- **Direct Date Handoff**: 1-click booking loads LibCal with the exact date pre-filtered for checkout.

## Usage

### Quick Management CLI (Permanent tmux session)
Run the interactive CLI manager:
```bash
./quickroom.sh
```
Or run directly via subcommands:
- `./quickroom.sh 1` or `./quickroom.sh start` — Start server in a background tmux session (auto-restart enabled)
- `./quickroom.sh 2` or `./quickroom.sh kill` — Kill server and tmux session
- `./quickroom.sh 3` or `./quickroom.sh logs` — View logs (with live follow or tmux attach)
- `./quickroom.sh 4` or `./quickroom.sh open` — Launch browser / display direct URLs

### Manual Server Run
```bash
python3 server.py [port] [host]
```
Default port is obscure port `29842` (listening on `0.0.0.0` for open access).

