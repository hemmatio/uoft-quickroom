#!/usr/bin/env python3
"""
U of T QuickRoom - Event-Loop Server (aiohttp) & LibCal API Connector
Fully non-blocking asynchronous architecture.
"""
import os
import sys
import json
import asyncio
from datetime import datetime, timedelta
from aiohttp import web, ClientSession, ClientTimeout

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CATALOG_PATH = os.path.join(BASE_DIR, 'catalog.json')
INDEX_PATH = os.path.join(BASE_DIR, 'index.html')

def load_catalog():
    if os.path.exists(CATALOG_PATH):
        with open(CATALOG_PATH, 'r') as f:
            return json.load(f)
    return []

CATALOG = load_catalog()

# Pre-read index.html in memory
with open(INDEX_PATH, 'r', encoding='utf-8') as f:
    INDEX_HTML = f.read()

async def query_libcal_grid_async(session: ClientSession, lid: int, gid: int, date_str: str) -> dict:
    """
    Non-blocking query to LibCal's /spaces/availability/grid for all rooms in a given group.
    """
    try:
        dt = datetime.strptime(date_str, "%Y-%m-%d")
        next_dt = dt + timedelta(days=1)
        end_date_str = next_dt.strftime("%Y-%m-%d")
    except Exception:
        end_date_str = date_str

    post_data = {
        'lid': str(lid),
        'gid': str(gid),
        'eid': '-1',
        'seat': '0',
        'seatId': '0',
        'zone': '0',
        'start': date_str,
        'end': end_date_str,
        'pageIndex': '0',
        'pageSize': '100'
    }

    headers = {
        'Content-Type': 'application/x-www-form-urlencoded; charset=UTF-8',
        'Referer': f'https://libcal.library.utoronto.ca/spaces?lid={lid}&gid={gid}',
        'X-Requested-With': 'XMLHttpRequest',
        'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)'
    }

    try:
        async with session.post(
            'https://libcal.library.utoronto.ca/spaces/availability/grid',
            data=post_data,
            headers=headers,
            timeout=ClientTimeout(total=8)
        ) as resp:
            return await resp.json(content_type=None)
    except Exception as e:
        print(f"Error querying grid for lid={lid}, gid={gid}: {e}")
        return {'slots': []}

async def check_group_availability_async(session: ClientSession, loc: dict, group: dict, date_str: str, start_time_str: str, duration_minutes: int, people_count: int = 0) -> tuple:
    """
    Non-blocking check of which rooms in a group are available for all consecutive 30-min slots
    between start_time and start_time + duration, matching group size rules.
    Returns (loc, group, matching_rooms).
    """
    lid = loc['lid']
    gid = group['gid']
    rooms = group.get('rooms', [])
    if people_count > 0:
        rooms = [
            r for r in rooms
            if r.get('min_occupancy', 1) <= people_count <= r.get('max_occupancy', 99)
        ]

    rooms_map = {r['eid']: r for r in rooms}
    if not rooms_map:
        return (loc, group, [])

    grid_data = await query_libcal_grid_async(session, lid, gid, date_str)
    slots = grid_data.get('slots', [])

    try:
        start_dt = datetime.strptime(f"{date_str} {start_time_str}", "%Y-%m-%d %H:%M")
    except Exception:
        return (loc, group, [])

    required_starts = []
    curr = start_dt
    end_dt = start_dt + timedelta(minutes=duration_minutes)
    while curr < end_dt:
        required_starts.append(curr.strftime("%Y-%m-%d %H:%M:%S"))
        curr += timedelta(minutes=30)

    # Index slots by (itemId, start)
    available_room_slots = {}
    for slot in slots:
        eid = slot.get('itemId')
        s_start = slot.get('start')
        class_name = slot.get('className', '')
        # Available if className is absent or contains 's-lc-eq-avail'
        is_avail = (not class_name) or ('s-lc-eq-avail' in class_name)
        if is_avail and s_start in required_starts:
            if eid not in available_room_slots:
                available_room_slots[eid] = {}
            available_room_slots[eid][s_start] = slot.get('checksum')

    # Room qualifies only if all requested intervals are available
    matching_rooms = []
    for eid, room in rooms_map.items():
        if eid in available_room_slots:
            slot_map = available_room_slots[eid]
            if all(req_start in slot_map for req_start in required_starts):
                matching_rooms.append({
                    'eid': eid,
                    'title': room.get('title'),
                    'capacity': room.get('capacity', 0),
                    'min_occupancy': room.get('min_occupancy', 1),
                    'max_occupancy': room.get('max_occupancy', 99),
                    'checksum': slot_map[required_starts[0]]
                })

    return (loc, group, matching_rooms)

routes = web.RouteTableDef()

@routes.get('/')
@routes.get('/index.html')
async def handle_index(request: web.Request) -> web.Response:
    return web.Response(text=INDEX_HTML, content_type='text/html', charset='utf-8')

@routes.get('/api/health')
async def handle_health(request: web.Request) -> web.Response:
    return web.json_response({'status': 'ok'})

@routes.get('/api/catalog')
async def handle_catalog(request: web.Request) -> web.Response:
    return web.json_response(CATALOG)

@routes.get('/api/search')
async def handle_search(request: web.Request) -> web.Response:
    query = request.query
    date_str = query.get('date', datetime.now().strftime("%Y-%m-%d"))
    start_time_str = query.get('startTime') or query.get('start') or '12:00'
    try:
        duration_minutes = int(query.get('duration', '60'))
    except ValueError:
        duration_minutes = 60

    # Campus filter (comma-separated list e.g. "UTSG,UTM")
    campus_param = query.get('campuses', 'UTSG,UTM,UTSC')
    allowed_campuses = set(campus_param.split(',')) if campus_param else {'UTSG', 'UTM', 'UTSC'}

    # Group size / people count filter
    raw_cap = query.get('peopleCount') or query.get('capacity') or query.get('groupSize') or query.get('minCapacity') or '0'
    try:
        people_count = int(raw_cap)
    except ValueError:
        people_count = 0

    # Building IDs filter
    lids_param = query.get('lids', '')
    allowed_lids = None
    if lids_param:
        try:
            allowed_lids = set(int(x.strip()) for x in lids_param.split(',') if x.strip())
        except ValueError:
            allowed_lids = None

    # Legacy single lid support
    preferred_lid = query.get('lid')
    if preferred_lid:
        try:
            allowed_lids = {int(preferred_lid)}
        except ValueError:
            pass

    # Filter locations by campus and allowed lids
    target_locations = [
        loc for loc in CATALOG
        if loc.get('campus', 'UTSG') in allowed_campuses
        and (allowed_lids is None or loc['lid'] in allowed_lids)
    ]

    # Gather all concurrent non-blocking calls
    tasks = []
    session: ClientSession = request.app['client_session']
    for loc in target_locations:
        for group in loc.get('groups', []):
            tasks.append(
                check_group_availability_async(
                    session, loc, group, date_str, start_time_str, duration_minutes, people_count
                )
            )

    results = await asyncio.gather(*tasks, return_exceptions=True)

    group_results = {}
    for res in results:
        if isinstance(res, Exception):
            print(f"Exception during async group check: {res}")
            continue
        loc, group, matches = res
        lid = loc['lid']
        if lid not in group_results:
            group_results[lid] = {'loc': loc, 'groups': []}
        if matches:
            group_results[lid]['groups'].append({
                'gid': group['gid'],
                'name': group['name'],
                'rooms': matches
            })

    results_by_location = []
    total_matching_rooms = 0

    # Reconstruct ordered results
    for loc in target_locations:
        lid = loc['lid']
        if lid in group_results and group_results[lid]['groups']:
            loc_groups = group_results[lid]['groups']
            loc_total = sum(len(g['rooms']) for g in loc_groups)
            results_by_location.append({
                'lid': lid,
                'name': loc['name'],
                'campus': loc.get('campus', 'UTSG'),
                'totalAvailable': loc_total,
                'groups': loc_groups
            })
            total_matching_rooms += loc_total

    payload = {
        'totalAvailableRooms': total_matching_rooms,
        'locations': results_by_location
    }
    return web.json_response(payload)

@routes.get('/api/book_handoff')
async def handle_book_handoff(request: web.Request) -> web.Response:
    query = request.query
    lid = query.get('lid', '')
    gid = query.get('gid', '')
    eid = query.get('eid', '')
    date_val = query.get('date', '')

    if eid and date_val:
        target_url = f"https://libcal.library.utoronto.ca/r/accessible/availability?lid={lid}&gid={gid}&space={eid}&date={date_val}&date_end={date_val}"
    elif eid:
        target_url = f"https://libcal.library.utoronto.ca/space/{eid}"
    else:
        target_url = f"https://libcal.library.utoronto.ca/spaces?lid={lid}&gid={gid}"

    raise web.HTTPFound(location=target_url)

async def init_app() -> web.Application:
    app = web.Application()
    app.add_routes(routes)

    # Manage shared persistent ClientSession with app lifecycle
    async def on_startup(app_instance):
        app_instance['client_session'] = ClientSession()

    async def on_cleanup(app_instance):
        await app_instance['client_session'].close()

    app.on_startup.append(on_startup)
    app.on_cleanup.append(on_cleanup)
    return app

def main():
    port = 29842
    host = '0.0.0.0'
    if len(sys.argv) > 1:
        port = int(sys.argv[1])
    if len(sys.argv) > 2:
        host = sys.argv[2]

    display_host = 'localhost' if host == '0.0.0.0' else host
    print(f"Server started on http://{display_host}:{port} (listening on {host}:{port}) [aiohttp event-loop]")
    app = asyncio.run(init_app())
    web.run_app(app, host=host, port=port, print=None)

if __name__ == '__main__':
    main()
