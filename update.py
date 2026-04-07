import urllib.request, json, datetime, re, ssl

TZ = 2  # Prague CEST = UTC+2

# ── WEATHER ──────────────────────────────────────────────────────────────────
url = (
    'https://api.open-meteo.com/v1/forecast'
    '?latitude=50.0755&longitude=14.4378'
    '&current_weather=true'
    '&hourly=relativehumidity_2m,apparent_temperature,windspeed_10m,temperature_2m,weathercode'
    '&timezone=Europe%2FPrague'
    '&forecast_days=1'
)
now_dt   = datetime.datetime.now(datetime.timezone(datetime.timedelta(hours=TZ)))
now_h    = now_dt.hour
updated_at = now_dt.strftime('%d.%m %H:%M')

temp = humidity = feels = wind = ''
code = 0
forecast = []
weather_ok = False

for attempt in range(3):
    try:
        with urllib.request.urlopen(url, timeout=15) as r:
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
        weather_ok = True
        print(f"Weather: {temp}C code={code}")
        break
    except Exception as e:
        print(f"Weather attempt {attempt+1} failed: {e}")
        import time; time.sleep(5)

if not weather_ok:
    print("Weather unavailable, keeping existing data")

# ── ICS SCHEDULE ─────────────────────────────────────────────────────────────
ICS_URL = 'https://api.veracross.eu/isp/subscribe/5F8B8AC7-FD73-4B86-8E64-8A5774618990.ics?uid=52F8A28F-D369-4EC8-B945-4CBF8135B1D6'

SKIP = {'Homeroom 6.3', 'Advisory-MS 6.3', 'MS Lunch'}

events = []
ics = ''

try:
    ctx = ssl.create_default_context()
    headers = {
        'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
        'Accept': 'text/calendar,*/*',
        'Accept-Language': 'en-US,en;q=0.9',
    }
    req = urllib.request.Request(ICS_URL, headers=headers)
    with urllib.request.urlopen(req, timeout=30, context=ctx) as r:
        ics = r.read().decode('utf-8', errors='ignore')
    print(f"ICS fetched: {len(ics)} bytes")
except Exception as e:
    print(f"ICS fetch failed: {e}")

if ics:
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

        # Parse Day and Room from DESCRIPTION
        # Format: "Block: A\; Day: MS1-ABCDE\; Room: 135"
        desc_parts = re.split(r'\\;', desc)
        school_day = ''
        room = location.strip()
        for part in desc_parts:
            part = part.strip()
            if part.startswith('Day:'):
                school_day = part[4:].strip()
            elif part.startswith('Room:'):
                room = part[5:].strip()

        # Prettify room: "129 - Idea Lab" -> "Idea Lab (129)"
        if ' - ' in room:
            parts = room.split(' - ', 1)
            room = parts[1].strip() + ' (' + parts[0].strip() + ')'

        # Shorten summary: remove "MS " prefix and version like "6.1"
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

    # Deduplicate and sort
    seen = set()
    uniq = []
    for ev in events:
        key = (ev['date'], ev['start'], ev['title'])
        if key not in seen:
            seen.add(key)
            uniq.append(ev)
    events = sorted(uniq, key=lambda x: (x['date'], x['start']))
    print(f"Events parsed: {len(events)}")

# ── UPDATE HTML ───────────────────────────────────────────────────────────────
with open('index.html', 'r', encoding='utf-8') as f:
    html = f.read()

if weather_ok:
    html = re.sub(r"temp: '[^']*'",      "temp: '" + temp + "'",         html)
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

if events:
    events_json = json.dumps(events, ensure_ascii=False)
    html = re.sub(
        r'var ALISA_EVENTS = \[.*?\];',
        'var ALISA_EVENTS = ' + events_json + ';',
        html, flags=re.DOTALL
    )
    print("ALISA_EVENTS updated")

with open('index.html', 'w', encoding='utf-8') as f:
    f.write(html)

print("Done.")
