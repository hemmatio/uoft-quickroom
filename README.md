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
```bash
python3 server.py [port]
```
Default port is `5050`.
