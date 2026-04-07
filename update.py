import urllib.request, json, datetime, re, ssl, time

TZ = 2  # Prague CEST = UTC+2

GOLEMIO_TOKEN = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpZCI6NTE3MSwiaWF0IjoxNzc1NTkwMjMwLCJleHAiOjExNzc1NTkwMjMwLCJpc3MiOiJnb2xlbWlvIiwianRpIjoiNDI0M2JmMzEtNjdkZS00NTA3LTk1YjEtNzJkYTU2YmJjZWZhIn0.UjHd1nfam7MUNy_JyZ7lAlkmYCc-bJv7qOL_oSD3kOE"
STOP_ID = "U905Z2"  # Škola Nebušice B → Bořislavka

now_dt   = datetime.datetime.now(datetime.timezone(datetime.timedelta(hours=TZ)))
now_h    = now_dt.hour
updated_at = now_dt.strftime('%d.%m %H:%M')

# ── WEATHER ───────────────────────────────────────────────────────────────────
weather_url = (
    'https://api.open-meteo.com/v1/forecast'
    '?latitude=50.0755&longitude=14.4378'
    '&current_weather=true'
    '&hourly=relativehumidity_2m,apparent_temperature,windspeed_10m,temperature_2m,weathercode'
    '&daily=weathercode,temperature_2m_max,temperature_2m_min'
    '&timezone=Europe%2FPrague'
    '&forecast_days=2'
)

temp = humidity = feels = wind = ''
code = 0
forecast = []
weather_ok = False
tom_code = 0
tom_max = ''
tom_min = ''

for attempt in range(3):
    try:
        with urllib.request.urlopen(weather_url, timeout=15) as r:
            wd = json.loads(r.read())
        cw   = wd['current_weather']
        temp = str(round(cw['temperature']))
        wind = str(round(cw['windspeed']))
        code = int(cw['weathercode'])
        h    = wd['hourly']
        humidity = str(h['relativehumidity_2m'][now_h])
        feels    = str(round(h['apparent_temperature'][now_h]))
        for i, t in enumerate(h['time']):
            hh = int(t.split('T')[1].split(':')[0])
            if hh < now_h:
                continue
            label = 'Сейчас' if len(forecast) == 0 else f"{hh:02d}:00"
            forecast.append({'label': label, 'temp': round(h['temperature_2m'][i]), 'code': int(h['weathercode'][i])})
            if len(forecast) >= 6:
                break
        # Tomorrow summary
        tom_code = int(wd['daily']['weathercode'][1]) if 'daily' in wd else 0
        tom_max  = round(wd['daily']['temperature_2m_max'][1]) if 'daily' in wd else ''
        tom_min  = round(wd['daily']['temperature_2m_min'][1]) if 'daily' in wd else ''
        weather_ok = True
        print(f"Weather: {temp}C code={code}, tomorrow: code={tom_code} {tom_min}-{tom_max}C")
        break
    except Exception as e:
        print(f"Weather attempt {attempt+1} failed: {e}")
        time.sleep(5)

# ── BUSES (Golemio live) ──────────────────────────────────────────────────────
buses_json = '[]'
try:
    bus_url = (
        f'https://api.golemio.cz/v2/pid/departureboards'
        f'?ids={STOP_ID}&minutesAfter=120&limit=12&includeMetroStops=false'
    )
    req = urllib.request.Request(bus_url, headers={'X-Access-Token': GOLEMIO_TOKEN})
    with urllib.request.urlopen(req, timeout=15) as r:
        bd = json.loads(r.read())

    deps = bd.get('departures', [])
    buses = []
    for dep in deps:
        route = dep['route']['short_name']
        if route not in ('161', '312', '907'):
            continue
        ts = dep['departure_timestamp'].get('predicted') or dep['departure_timestamp'].get('scheduled', '')
        if not ts:
            continue
        # Parse ISO time e.g. "2026-04-07T21:34:44+02:00"
        t_str = ts[11:16]  # "HH:MM"
        dep_dt = datetime.datetime.fromisoformat(ts)
        diff = int((dep_dt - now_dt).total_seconds() / 60)
        if diff < 0:
            continue
        delay_s = dep.get('delay', {}).get('seconds', 0) or 0
        buses.append({'route': route, 'time': t_str, 'diff': diff, 'delay': delay_s})

    buses_json = json.dumps(buses, ensure_ascii=False)
    print(f"Buses: {len(buses)} departures")
except Exception as e:
    print(f"Buses failed: {e}")

# ── ICS SCHEDULE ──────────────────────────────────────────────────────────────
ICS_URL = 'https://api.veracross.eu/isp/subscribe/5F8B8AC7-FD73-4B86-8E64-8A5774618990.ics?uid=52F8A28F-D369-4EC8-B945-4CBF8135B1D6'
SKIP = {'Homeroom 6.3', 'Advisory-MS 6.3', 'MS Lunch'}

events = []
try:
    headers = {
        'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
        'Accept': 'text/calendar,*/*',
    }
    req = urllib.request.Request(ICS_URL, headers=headers)
    with urllib.request.urlopen(req, timeout=30) as r:
        ics = r.read().decode('utf-8', errors='ignore')
    print(f"ICS: {len(ics)} bytes")

    today = now_dt.date()
    for block in re.findall(r'BEGIN:VEVENT(.*?)END:VEVENT', ics, re.DOTALL):
        def get(field, blk=block):
            m = re.search(r'^' + field + r':(.+)$', blk, re.MULTILINE)
            return m.group(1).strip() if m else ''

        summary = get('SUMMARY')
        if summary in SKIP:
            continue
        dtstart  = get('DTSTART')
        dtend    = get('DTEND')
        desc     = get('DESCRIPTION')
        location = get('LOCATION')

        try:
            if dtstart.endswith('Z'):
                dt     = datetime.datetime.strptime(dtstart, '%Y%m%dT%H%M%SZ') + datetime.timedelta(hours=TZ)
                dt_end = datetime.datetime.strptime(dtend,   '%Y%m%dT%H%M%SZ') + datetime.timedelta(hours=TZ)
            else:
                dt     = datetime.datetime.strptime(dtstart[:15], '%Y%m%dT%H%M%S')
                dt_end = datetime.datetime.strptime(dtend[:15],   '%Y%m%dT%H%M%S')
        except Exception:
            continue

        if dt.date() < today:
            continue

        desc_parts = re.split(r'\\;', desc)
        school_day = ''
        room = location.strip()
        for part in desc_parts:
            part = part.strip()
            if part.startswith('Day:'):
                school_day = part[4:].strip()
            elif part.startswith('Room:'):
                room = part[5:].strip()

        if ' - ' in room:
            parts = room.split(' - ', 1)
            room = parts[1].strip() + ' (' + parts[0].strip() + ')'

        short = re.sub(r'\s+\d+\.\d+$', '', summary)
        short = re.sub(r'^MS ', '', short)

        events.append({
            'date':  dt.strftime('%Y-%m-%d'),
            'start': dt.strftime('%H:%M'),
            'end':   dt_end.strftime('%H:%M'),
            'title': short,
            'day':   school_day,
            'room':  room,
        })

    seen = set()
    uniq = []
    for ev in events:
        key = (ev['date'], ev['start'], ev['title'])
        if key not in seen:
            seen.add(key)
            uniq.append(ev)
    events = sorted(uniq, key=lambda x: (x['date'], x['start']))
    print(f"Events: {len(events)}")
except Exception as e:
    print(f"ICS failed: {e}")

# ── UPDATE HTML ───────────────────────────────────────────────────────────────
with open('index.html', 'r', encoding='utf-8') as f:
    html = f.read()

if weather_ok:
    html = re.sub(r"temp: '[^']*'",      "temp: '" + temp + "'",         html)
    html = html.replace("tomCode: __TOM_CODE__", "tomCode: " + str(tom_code))
    html = re.sub(r"tomCode: \d+", "tomCode: " + str(tom_code), html)
    html = re.sub(r"tomMax: '[^']*'", "tomMax: '" + str(tom_max) + "'", html)
    html = re.sub(r"tomMin: '[^']*'", "tomMin: '" + str(tom_min) + "'", html)
    html = re.sub(r"feels: '[^']*'",     "feels: '" + feels + "'",       html)
    html = re.sub(r"humidity: '[^']*'",  "humidity: '" + humidity + "'", html)
    html = re.sub(r"wind: '[^']*'",      "wind: '" + wind + "'",         html)
    html = re.sub(r"code: (__CODE__|\d+)", "code: " + str(code),         html)
    html = re.sub(r"updatedAt: '[^']*'", "updatedAt: '" + updated_at + "'", html)
    html = re.sub(
        r"forecast: (__FORECAST__|\[.*?\])",
        "forecast: " + json.dumps(forecast, ensure_ascii=False),
        html, flags=re.DOTALL
    )

# Buses — inject live data
html = re.sub(
    r'var LIVE_BUSES = \[.*?\];',
    'var LIVE_BUSES = ' + buses_json + ';',
    html, flags=re.DOTALL
)

if events:
    html = re.sub(
        r'var ALISA_EVENTS = \[.*?\];',
        'var ALISA_EVENTS = ' + json.dumps(events, ensure_ascii=False) + ';',
        html, flags=re.DOTALL
    )

with open('index.html', 'w', encoding='utf-8') as f:
    f.write(html)

print("Done.")
