import os
import json
import requests
from datetime import datetime, date
from dateutil.relativedelta import relativedelta
from dotenv import load_dotenv
from jinja2 import Environment, FileSystemLoader

load_dotenv()

ACCESS_TOKEN = os.getenv('META_ACCESS_TOKEN')
AD_ACCOUNT_ID = os.getenv('META_AD_ACCOUNT_ID')
BASE_URL = "https://graph.facebook.com/v19.0"

CZECH_MONTHS = [
    '', 'Leden', 'Únor', 'Březen', 'Duben', 'Květen', 'Červen',
    'Červenec', 'Srpen', 'Září', 'Říjen', 'Listopad', 'Prosinec',
]

ROLLING_PERIODS = [
    {'key': '7d',  'label': 'Posledních 7 dní',  'preset': 'last_7d'},
    {'key': '30d', 'label': 'Posledních 30 dní', 'preset': 'last_30d'},
    {'key': '90d', 'label': 'Posledních 90 dní', 'preset': 'last_90d'},
]


def build_monthly_periods(count=4):
    """Vygeneruje posledních `count` měsíců včetně aktuálního."""
    today = date.today()
    periods = []
    for i in range(count - 1, -1, -1):
        first = (today.replace(day=1) - relativedelta(months=i))
        if i == 0:
            last = today
        else:
            last = first + relativedelta(months=1) - relativedelta(days=1)
        label = f"{CZECH_MONTHS[first.month]} {first.year}"
        periods.append({
            'key': first.strftime('%Y-%m'),
            'label': label,
            'time_range': {'since': first.strftime('%Y-%m-%d'), 'until': last.strftime('%Y-%m-%d')},
        })
    return periods


def get_account_insights(date_preset=None, time_range=None):
    url = f"{BASE_URL}/{AD_ACCOUNT_ID}/insights"
    params = {
        'fields': 'reach,impressions,frequency,spend,cpm',
        'level': 'account',
        'access_token': ACCESS_TOKEN,
    }
    if time_range:
        params['time_range'] = json.dumps(time_range)
    else:
        params['date_preset'] = date_preset
    r = requests.get(url, params=params)
    if not r.ok:
        return {}
    data = r.json().get('data', [])
    return data[0] if data else {}


def get_top_ads(date_preset=None, time_range=None, limit=5):
    url = f"{BASE_URL}/{AD_ACCOUNT_ID}/insights"
    params = {
        'fields': 'ad_id,ad_name,reach,impressions,spend,cpm,actions',
        'level': 'ad',
        'sort': 'reach_descending',
        'limit': limit,
        'access_token': ACCESS_TOKEN,
    }
    if time_range:
        params['time_range'] = json.dumps(time_range)
    else:
        params['date_preset'] = date_preset
    r = requests.get(url, params=params)
    if not r.ok:
        return []
    return r.json().get('data', [])


def get_ad_creative(ad_id):
    url = f"{BASE_URL}/{ad_id}"
    params = {
        'fields': 'creative{image_url,thumbnail_url,object_story_spec,effective_object_story_id}',
        'access_token': ACCESS_TOKEN,
    }
    r = requests.get(url, params=params)
    if r.status_code != 200:
        return {'url': None, 'type': 'unknown', 'preview_url': None}

    creative = r.json().get('creative', {})
    spec = creative.get('object_story_spec', {})

    # Sestav odkaz na Facebook post
    story_id = creative.get('effective_object_story_id', '')
    preview_url = None
    if story_id and '_' in story_id:
        page_id, post_id = story_id.split('_', 1)
        preview_url = f"https://www.facebook.com/permalink.php?story_fbid={post_id}&id={page_id}"

    # Video — pouze pokud spec obsahuje video_data
    if spec.get('video_data'):
        return {'url': creative.get('thumbnail_url'), 'type': 'video', 'preview_url': preview_url}

    # Přímá image URL — nejvyšší kvalita
    if creative.get('image_url'):
        return {'url': creative['image_url'], 'type': 'image', 'preview_url': preview_url}

    # Link reklama s obrázkem
    if spec.get('link_data', {}).get('picture'):
        return {'url': spec['link_data']['picture'], 'type': 'image', 'preview_url': preview_url}

    # Carousel — první karta
    child_attachments = spec.get('link_data', {}).get('child_attachments', [])
    if child_attachments and child_attachments[0].get('picture'):
        return {'url': child_attachments[0]['picture'], 'type': 'carousel', 'preview_url': preview_url}

    # Photo reklama
    if spec.get('photo_data', {}).get('url'):
        return {'url': spec['photo_data']['url'], 'type': 'image', 'preview_url': preview_url}

    # Fallback thumbnail
    if creative.get('thumbnail_url'):
        return {'url': creative['thumbnail_url'], 'type': 'unknown', 'preview_url': preview_url}

    return {'url': None, 'type': 'unknown', 'preview_url': None}


def get_engagement(actions):
    if not actions:
        return 0
    tracked = {'post_reaction', 'comment', 'post', 'page_engagement'}
    return sum(int(a.get('value', 0)) for a in actions if a.get('action_type') in tracked)


def fmt_number(value):
    try:
        return f"{int(float(value)):,}".replace(',', '\u00a0')
    except (ValueError, TypeError):
        return '—'


def fmt_currency(value):
    try:
        return f"{float(value):,.0f}\u00a0Kč".replace(',', '\u00a0')
    except (ValueError, TypeError):
        return '—'


def fmt_decimal(value, decimals=2):
    try:
        return f"{float(value):.{decimals}f}".replace('.', ',')
    except (ValueError, TypeError):
        return '—'


def build_period_data(period):
    print(f"  Načítám {period['label']}...")
    preset = period.get('preset')
    time_range = period.get('time_range')
    account = get_account_insights(date_preset=preset, time_range=time_range)
    raw_ads = get_top_ads(date_preset=preset, time_range=time_range, limit=20)

    for ad in raw_ads:
        creative = get_ad_creative(ad['ad_id'])
        ad['creative_url'] = creative['url']
        ad['creative_type'] = creative['type']
        ad['preview_url'] = creative['preview_url']
        ad['engagement'] = get_engagement(ad.get('actions', []))

    def format_ad(i, ad):
        return {
            'rank':          i + 1,
            'name':          ad.get('ad_name', 'Neznámá reklama'),
            'reach':         fmt_number(ad.get('reach', 0)),
            'impressions':   fmt_number(ad.get('impressions', 0)),
            'spend':         fmt_currency(ad.get('spend', 0)),
            'engagement':    fmt_number(ad.get('engagement', 0)),
            'creative_url':  ad.get('creative_url'),
            'creative_type': ad.get('creative_type', 'unknown'),
            'preview_url':   ad.get('preview_url'),
        }

    videos = [ad for ad in raw_ads if ad['creative_type'] == 'video'][:5]
    statics = [ad for ad in raw_ads if ad['creative_type'] != 'video'][:5]
    top_engaged = sorted(raw_ads, key=lambda a: a['engagement'], reverse=True)[:3]

    return {
        'key':   period['key'],
        'label': period['label'],
        'metrics': {
            'reach':       fmt_number(account.get('reach', 0)),
            'impressions': fmt_number(account.get('impressions', 0)),
            'frequency':   fmt_decimal(account.get('frequency', 0)),
            'spend':       fmt_currency(account.get('spend', 0)),
            'cpm':         fmt_currency(account.get('cpm', 0)),
        },
        'top_videos':   [format_ad(i, ad) for i, ad in enumerate(videos)],
        'top_statics':  [format_ad(i, ad) for i, ad in enumerate(statics)],
        'top_engaged':  [format_ad(i, ad) for i, ad in enumerate(top_engaged)],
    }


def main():
    print("Načítám data z Meta API...")
    all_periods = build_monthly_periods(4) + ROLLING_PERIODS
    periods_data = [build_period_data(p) for p in all_periods]

    now = datetime.now()
    today = f"{now.day}. {now.month}. {now.year}"

    env = Environment(loader=FileSystemLoader('.'))
    template = env.get_template('template.html')
    html = template.render(generated_at=today, periods=periods_data)

    output = f"report_{now.strftime('%Y-%m-%d')}.html"
    with open(output, 'w', encoding='utf-8') as f:
        f.write(html)

    print(f"✓ Report uložen: {output}")


if __name__ == '__main__':
    main()
