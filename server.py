#!/usr/bin/env python3
"""
U of T QuickRoom Finder - Multi-threaded Server & LibCal API Connector
"""
import os
import sys
import json
import urllib.request
import urllib.parse
from http.server import HTTPServer, BaseHTTPRequestHandler
from datetime import datetime, timedelta
from concurrent.futures import ThreadPoolExecutor, as_completed

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CATALOG_PATH = os.path.join(BASE_DIR, 'catalog.json')
INDEX_PATH = os.path.join(BASE_DIR, 'index.html')

def load_catalog():
    if os.path.exists(CATALOG_PATH):
        with open(CATALOG_PATH, 'r') as f:
            return json.load(f)
    return []

CATALOG = load_catalog()

def query_libcal_grid(lid, gid, date_str):
    """
    Query LibCal's /spaces/availability/grid for all rooms in a given group.
    Returns the parsed JSON response with slots.
    """
    try:
        dt = datetime.strptime(date_str, "%Y-%m-%d")
        next_dt = dt + timedelta(days=1)
        end_date_str = next_dt.strftime("%Y-%m-%d")
    except Exception:
        end_date_str = date_str

    post_data = urllib.parse.urlencode({
        'lid': lid,
        'gid': gid,
        'eid': -1,
        'seat': 0,
        'seatId': 0,
        'zone': 0,
        'start': date_str,
        'end': end_date_str,
        'pageIndex': 0,
        'pageSize': 100
    }).encode('utf-8')

    req = urllib.request.Request(
        'https://libcal.library.utoronto.ca/spaces/availability/grid',
        data=post_data,
        headers={
            'Content-Type': 'application/x-www-form-urlencoded; charset=UTF-8',
            'Referer': f'https://libcal.library.utoronto.ca/spaces?lid={lid}&gid={gid}',
            'X-Requested-With': 'XMLHttpRequest',
            'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)'
        }
    )

    try:
        with urllib.request.urlopen(req, timeout=8) as resp:
            return json.loads(resp.read().decode('utf-8'))
    except Exception as e:
        print(f"Error querying grid for lid={lid}, gid={gid}: {e}")
        return {'slots': []}

def check_group_availability(loc, group, date_str, start_time_str, duration_minutes, people_count=0):
    """
    Checks which rooms in a group are available for all consecutive 30-min slots
    between start_time and start_time + duration, matching group size rules
    (min_occupancy <= people_count <= max_occupancy).
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
        return []

    grid_data = query_libcal_grid(lid, gid, date_str)
    slots = grid_data.get('slots', [])

    try:
        start_dt = datetime.strptime(f"{date_str} {start_time_str}", "%Y-%m-%d %H:%M")
    except Exception:
        return []

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

    return matching_rooms

class RoomFinderHandler(BaseHTTPRequestHandler):
    def log_message(self, format, *args):
        # Keep console output clean
        pass

    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path
        query = urllib.parse.parse_qs(parsed.query)

        if path == '/' or path == '/index.html':
            self.send_response(200)
            self.send_header('Content-Type', 'text/html; charset=utf-8')
            self.end_headers()
            with open(INDEX_PATH, 'rb') as f:
                self.wfile.write(f.read())
            return

        if path == '/api/catalog':
            self.send_response(200)
            self.send_header('Content-Type', 'application/json')
            self.end_headers()
            self.wfile.write(json.dumps(CATALOG).encode('utf-8'))
            return

        if path == '/api/search':
            date_str = query.get('date', [datetime.now().strftime("%Y-%m-%d")])[0]
            start_time_str = query.get('startTime', ['12:00'])[0]
            duration_minutes = int(query.get('duration', ['60'])[0])
            
            # Campus filter (comma-separated list e.g. "UTSG,UTM")
            campus_param = query.get('campuses', ['UTSG,UTM,UTSC'])[0]
            allowed_campuses = set(campus_param.split(',')) if campus_param else {'UTSG', 'UTM', 'UTSC'}

            # Group size / people count filter
            try:
                people_count = int(query.get('peopleCount', query.get('minCapacity', ['0']))[0])
            except ValueError:
                people_count = 0

            # Building IDs filter (either single lid or comma-separated lids e.g. from map)
            lids_param = query.get('lids', [''])[0]
            allowed_lids = None
            if lids_param:
                try:
                    allowed_lids = set(int(x.strip()) for x in lids_param.split(',') if x.strip())
                except ValueError:
                    allowed_lids = None

            # Legacy single lid support
            preferred_lid = query.get('lid', [None])[0]
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

            # Flatten group tasks for concurrent execution
            tasks = []
            for loc in target_locations:
                for group in loc.get('groups', []):
                    tasks.append((loc, group))

            group_results = {}
            with ThreadPoolExecutor(max_workers=10) as executor:
                future_to_task = {
                    executor.submit(check_group_availability, loc, group, date_str, start_time_str, duration_minutes, people_count): (loc, group)
                    for loc, group in tasks
                }
                for future in as_completed(future_to_task):
                    loc, group = future_to_task[future]
                    try:
                        matches = future.result()
                    except Exception as e:
                        print(f"Error checking {loc['name']} / {group['name']}: {e}")
                        matches = []
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

            self.send_response(200)
            self.send_header('Content-Type', 'application/json')
            self.end_headers()
            self.wfile.write(json.dumps(payload).encode('utf-8'))
            return

        if path == '/api/book_handoff':
            lid = query.get('lid', [''])[0]
            gid = query.get('gid', [''])[0]
            eid = query.get('eid', [''])[0]
            date_val = query.get('date', [''])[0]
            
            # Direct handoff to room page with exact preloaded date
            if eid and date_val:
                target_url = f"https://libcal.library.utoronto.ca/r/accessible/availability?lid={lid}&gid={gid}&space={eid}&date={date_val}&date_end={date_val}"
            elif eid:
                target_url = f"https://libcal.library.utoronto.ca/space/{eid}"
            else:
                target_url = f"https://libcal.library.utoronto.ca/spaces?lid={lid}&gid={gid}"
                
            self.send_response(302)
            self.send_header('Location', target_url)
            self.end_headers()
            return

        self.send_response(404)
        self.end_headers()
        self.wfile.write(b"Not Found")

def run(port=5050):
    server_address = ('127.0.0.1', port)
    httpd = HTTPServer(server_address, RoomFinderHandler)
    print(f"Server started on http://127.0.0.1:{port}")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nShutting down server.")
        httpd.server_close()

if __name__ == '__main__':
    port = 5050
    if len(sys.argv) > 1:
        port = int(sys.argv[1])
    run(port)
