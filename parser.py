# Données a parser tous les jours
# -------------------------------
# Nombre pages vues par google
# Nombre requetes google
# Nombre pages vues quand un user agent bot/non-bot
# Nombre requetes quand un user agent bot/non-bot
# Nombre 404s
# Nombre pages indexées dans google


# Agregats
# --------------------------------
# Top user agents
# Top referers google
# Top pays

import datetime
import json
from pathlib import Path
import collections
from collections import Counter
from copy import deepcopy
from jinja2 import Environment, PackageLoader, select_autoescape
from user_agents import parse as parse_ua


env = Environment(
    loader=PackageLoader('parser', 'templates'),
    autoescape=select_autoescape(['html', 'xml'])
)

LOGS_FILES = [Path("./logs/access.log")]
OUTPUT_DIR = Path("./local")
LAST_RUN_FILE = OUTPUT_DIR / Path("parser_data.json")
BOTS_UA = ["curl", "bot", "statping", "spider", "crawler", "bing", "http"]
TRAFFIC_TYPES = ["google", "bots", "users"]

COLLECT_COUNTERS = {
    "status": Counter(),
    "path_types": Counter(),
    "duration_ranges": Counter(),
    "hits": 0,
    "pages": 0,
}

NOW = datetime.datetime.utcnow()
NOW_TIMESTAMP = NOW.timestamp()

DAY = datetime.timedelta(days=1)


def collect_counters_to_dict(counters):
    dicts = {}
    for k, v in counters.items():
        if isinstance(v, Counter):
            v = dict(v)
        dicts[k] = v

    return dicts


COLLECT_DICTS = collect_counters_to_dict(COLLECT_COUNTERS)


def get_last_run():
    try:
        with open(LAST_RUN_FILE, "r") as f:
            last_run = json.load(f)
    except FileNotFoundError:
        last_run = {}

    return {
        "last_timestamp": 0.0,
        **last_run
    }


def iterate_lines_from(start):
    for log_file in LOGS_FILES:
        with open(log_file, "r") as f:
            for line in f:
                rq = json.loads(line)
                if rq['ts'] >= start:
                    yield rq


def get_day_file_name(date):
    path = OUTPUT_DIR / str(date.year).zfill(4) / str(date.month).zfill(2)
    path.mkdir(exist_ok=True, parents=True)
    return str(path / (str(date.day).zfill(2) + ".json"))


def read_day_data(date):
    try:
        with open(get_day_file_name(date), "r") as f:
            return json.load(f)
    except FileNotFoundError:
        return {
            "ua_tops": {},
            "google": deepcopy(COLLECT_DICTS),
            "bots": deepcopy(COLLECT_DICTS),
            "users": deepcopy(COLLECT_DICTS),
        }


def fuse_dicts(ad, bd):
    t = {}
    ks = set(ad.keys()).union(set(bd.keys()))
    for k in ks:
        a = ad.get(k, 0)
        b = bd.get(k, 0)

        if isinstance(a, dict):
            t[k] = fuse_dicts(a, b)
        else:
            t[k] = a + b
    return t


def fuse_day_data(dicts: list):
    total = dicts[0]
    keys = list(total.keys())
    for part in dicts[1:]:
        for k in keys:
            a = total[k]
            b = part[k]

            if isinstance(a, dict):
                total[k] = fuse_dicts(a, b)
            else:
                total[k] = a + b

    return total


def agregate_requests_data(it, end):
    end_ts = end.timestamp()

    ret = {
        "ua_tops": Counter(),
        "google": deepcopy(COLLECT_COUNTERS),
        "bots": deepcopy(COLLECT_COUNTERS),
        "users": deepcopy(COLLECT_COUNTERS),
    }

    rq_ts = None

    for rq in it:
        # print(rq)

        # Capture data
        rq_ts_ = rq['ts']
        if rq_ts_ > end_ts:
            break
        rq_ts = rq_ts_

        rq_ip = rq["request"].get("headers", {}).get("X-Forwarded-For", [None])[0]
        if not rq_ip:
            rq_ip = rq["request"]["remote_addr"].split(":")[0]

        rq_status = rq["status"]
        rq_duration = rq["duration"]
        rq_ua = rq["request"].get("headers", {}).get("User-Agent", [""])[0]
        rq_path = rq["request"]["uri"]
        if rq_path.startswith("/static"):
            rq_path_type = "/static"
        elif "assets" in rq_path:
            rq_path_type = "*asset*"
        else:
            path_elements = rq_path.split('/')
            elements_types = []
            for element in path_elements:
                if "?" in element:
                    element = element.split("?", 1)[0]

                if element.isdigit():
                    element = "<pk>"

                elements_types.append(element)

            rq_path_type = '/'.join(elements_types)

        rq_type = "users"

        if "google" in rq_ua.lower():
            rq_type = "google"
        elif any(bua.lower() in rq_ua.lower() for bua in BOTS_UA):
            rq_type = "bots"

        rq_is_page = "." not in rq_path

        # Agregate
        ret[rq_type]["status"][str(rq_status)] += 1
        ret[rq_type]["path_types"][rq_path_type] += 1
        ret[rq_type]["duration_ranges"][str(round(rq_duration, 1))] += 1
        ret[rq_type]["hits"] += 1
        if rq_is_page:
            ret[rq_type]["pages"] += 1

        ret["ua_tops"][rq_ua] += 1

    return {
        "last_timestamp": rq_ts,
        "ua_tops": dict(ret["ua_tops"]),
        "google": collect_counters_to_dict(ret["google"]),
        "bots": collect_counters_to_dict(ret["bots"]),
        "users": collect_counters_to_dict(ret["users"]),
    }


def store_day_data(date, data):
    with open(get_day_file_name(date), "w") as f:
        return json.dump(data, f, indent=4, sort_keys=True)


def get_ua_chart(ua_tops):
    by_browser = Counter()
    by_type = Counter()

    for user_agent, count in ua_tops.items():
        parsed = parse_ua(user_agent)

        if parsed.is_bot or user_agent == "Statping":
            ua_type = "bot"
        elif parsed.is_pc:
            ua_type = "pc"
        elif parsed.is_mobile:
            ua_type = "mobile"
        elif parsed.is_tablet:
            ua_type = "tablet"
        else:
            ua_type = "unknown"

        by_browser[parsed.browser.family] += count
        by_type[ua_type] += count

    basic_data = {
        'chart': {
            'type': 'column'
        },
        'title': {
            'text': 'User agents data'
        },
        'xAxis': {
            'type': 'category',
        },
        'yAxis': {
            'min': 0,
            'title': {
                'text': 'Requests'
            }
        },
        'legend': {
            'enabled': True
        },
        'tooltip': {
            'pointFormat': '{point.x}: <b>{point.y} requests</b>'
        },
        'series': [{
            'name': 'By type',
            'data': by_type.most_common(),
        }, {
            'name': 'By browser',
            'data': by_browser.most_common(),
        },
        ]
    }

    return basic_data


def get_traffic_data(days_datas):
    series = [{
            'name': traffic_type,
            'visible': traffic_type != "bots",
            'data': []
        } for traffic_type in TRAFFIC_TYPES]

    for day_data in days_datas:
        for i, traffic_type in enumerate(TRAFFIC_TYPES):
            series[i]['data'].append(day_data[traffic_type]['pages'])

    basic_data = {
        'title': {
            'text': 'Traffic amounts'
        },

        'yAxis': {
            'title': {
                'text': 'Requests'
            }
        },

        'legend': {
            'layout': 'vertical',
            'align': 'right',
            'verticalAlign': 'middle'
        },

        'plotOptions': {
            'series': {
                'label': {
                    'connectorAllowed': False
                },
                'pointStart': 1
            }
        },

        'series': series,
    }

    return basic_data


def render_month(date):
    output_dir = OUTPUT_DIR / str(date.year).zfill(4) / str(date.month).zfill(2)
    output_file = output_dir / "index.html"

    days_datas = []
    dates = []
    days = []
    current_date = date.replace(day=1)
    while current_date.month == date.month and current_date < NOW + DAY:
        dates.append(current_date)
        days.append(str(current_date.day).zfill(2))
        days_datas.append(read_day_data(current_date))
        current_date += DAY

    month_data = fuse_day_data(deepcopy(days_datas))

    template = env.get_template('month.jinja2')

    with open(output_file, "w") as f:
        f.write(template.render(month_data=month_data, days_datas=days_datas,
                                date=date, TRAFFIC_TYPES=TRAFFIC_TYPES,
                                ua_tops=get_ua_chart(month_data["ua_tops"]),
                                traffic_data=get_traffic_data(days_datas),
                                dates=dates,
                                days=days))
    print("Generated", output_file)


def render_day(date):
    output_dir = OUTPUT_DIR / str(date.year).zfill(4) / str(date.month).zfill(2)
    output_file = output_dir / (str(date.day).zfill(2) + ".html")

    day_data = read_day_data(date)

    template = env.get_template('day.jinja2')

    with open(output_file, "w") as f:
        f.write(template.render(day_data=day_data, date=date, TRAFFIC_TYPES=TRAFFIC_TYPES,
                                ua_tops=get_ua_chart(day_data["ua_tops"]),
                                day=str(date.day).zfill(2)))

    print("Generated", output_file)


def update_htmls(dates):
    first_date = dates[0]

    render_month(first_date)

    for date in dates:
        render_day(date)
        if date.day == 1:
            render_month(date)


def main():
    last_run = get_last_run()

    if last_run["last_timestamp"] < 1:
        frq = next(iterate_lines_from(last_run["last_timestamp"]))
        last_run["last_timestamp"] = frq['ts']

    iterator = iterate_lines_from(last_run["last_timestamp"])
    done_up_to = datetime.datetime.fromtimestamp(last_run["last_timestamp"])
    done_up_to = done_up_to.replace(hour=0, minute=0, second=0, microsecond=0)

    to_update = []

    while done_up_to < NOW:
        print("Collecting data for ", done_up_to.date())
        stored_data = read_day_data(done_up_to)

        end_at = done_up_to + DAY
        agregated = agregate_requests_data(iterator, end_at)
        last_run["last_timestamp"] = agregated['last_timestamp']

        del agregated["last_timestamp"]
        fused = fuse_day_data([stored_data, agregated])
        store_day_data(done_up_to, fused)

        to_update.append(done_up_to)

        done_up_to = end_at

    if to_update:
        print("Updating HTMLs...")
        update_htmls(to_update)

    if last_run["last_timestamp"] is None:
        print("Nothing done, aborting")
    else:
        with open(LAST_RUN_FILE, "w") as f:
            json.dump(last_run, f)


if __name__ == "__main__":
    main()
