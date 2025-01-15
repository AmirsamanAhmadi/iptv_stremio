from flask import Flask, request, jsonify
import requests
from datetime import datetime, timedelta
from apscheduler.schedulers.background import BackgroundScheduler
import time

# Constants
IPTV_CHANNELS_URL = 'https://iptv-org.github.io/api/channels.json'
IPTV_STREAMS_URL = 'https://iptv-org.github.io/api/streams.json'
FETCH_INTERVAL = 300  # 5 minutes
CACHE_TTL = 600  # 10 minutes

# Filters (Relaxed for Debugging)
INCLUDED_COUNTRIES = []  # Remove country filter entirely for now
INCLUDED_LANGUAGES = ['fars', 'spa', 'ron', 'rus', 'fra', 'deu', 'eng']  # Allow more languages
EXCLUDED_CATEGORIES = []  # No category exclusions for now

# Flask app
app = Flask(__name__)

# In-memory cache
cache = {}
cache_expiry = {}

# Helper function to fetch data with caching
def fetch_with_cache(url):
    now = datetime.utcnow()
    
    # Check if cached data is still valid
    if url in cache and cache_expiry[url] > now:
        print(f"Serving cached data for {url}")
        return cache[url]
    
    print(f"Fetching fresh data from {url}")
    try:
        response = requests.get(url)
        response.raise_for_status()  # Will raise an error for 4xx/5xx responses
        data = response.json()
        cache[url] = data
        cache_expiry[url] = now + timedelta(seconds=CACHE_TTL)
        print(f"Fetched {len(data)} items from {url}")
        return data
    except requests.exceptions.RequestException as e:
        print(f"Error fetching {url}: {e}")
        return cache.get(url, None)  # Return cached data if available

# Function to filter channels based on predefined filters
def filter_channels(channels):
    print(f"Filtering channels: {len(channels)} total channels before filtering")
    filtered = []

    # Log a few channels before filtering for debugging
    print("Sample channels before filtering:")
    for i, channel in enumerate(channels[:5]):
        print(f"{i + 1}. {channel.get('name', 'Unknown')} (Country: {channel.get('country')}, Languages: {channel.get('languages')}, Categories: {channel.get('categories')})")
    
    for channel in channels:
        # Check if the channel has the necessary fields for filtering
        country = channel.get('country', '')
        languages = channel.get('languages', [])
        categories = channel.get('categories', [])
        
        # Check if the channel matches all the filters
        country_match = country in INCLUDED_COUNTRIES if INCLUDED_COUNTRIES else True  # Skip country filter if empty
        language_match = any(lang in INCLUDED_LANGUAGES for lang in languages)
        category_match = not any(cat in EXCLUDED_CATEGORIES for cat in categories)
        
        # Log filtering decision
        if country_match and language_match and category_match:
            filtered.append(channel)
        else:
            print(f"Channel {channel.get('name', 'Unknown')} filtered out:")
            print(f"  Country: {country} (Match: {country_match})")
            print(f"  Languages: {languages} (Match: {language_match})")
            print(f"  Categories: {categories} (Match: {category_match})")
    
    print(f"{len(filtered)} channels after filtering")
    return filtered

# Function to match streams to channels
def match_streams_to_channels(channels, streams):
    print(f"Matching streams to {len(channels)} channels")
    for channel in channels:
        channel_streams = [stream for stream in streams if stream.get('channel') == channel.get('id')]
        if channel_streams:
            channel['streams'] = channel_streams
    return channels

# Fetch and filter channels with streams
def fetch_channels():
    print("Fetching channels and streams...")
    channels = fetch_with_cache(IPTV_CHANNELS_URL)
    if not channels:
        print("No channels fetched.")
        return []
    streams = fetch_with_cache(IPTV_STREAMS_URL)
    if not streams:
        print("No streams fetched.")
        return []

    filtered_channels = filter_channels(channels)
    
    # If no channels after filtering, show a few sample channels for debugging
    if not filtered_channels:
        print("No channels after filtering. Here's a sample of the first 5 channels:")
        for i, channel in enumerate(channels[:5]):
            print(f"{i + 1}. {channel.get('name', 'Unknown')} (Country: {channel.get('country')}, Languages: {channel.get('languages')}, Categories: {channel.get('categories')})")
    
    return match_streams_to_channels(filtered_channels, streams)

# Background job to refresh data periodically
def refresh_data():
    try:
        channels = fetch_channels()
        if channels:
            print(f"Fetched {len(channels)} channels.")
        else:
            print("No channels found after refresh.")
    except Exception as e:
        print(f"Error refreshing data: {e}")

# Schedule the background job
scheduler = BackgroundScheduler()
scheduler.add_job(refresh_data, 'interval', seconds=FETCH_INTERVAL)
scheduler.start()

# Gracefully shut down the scheduler on app exit
def graceful_shutdown():
    print("Shutting down scheduler...")
    scheduler.shutdown()

# Function to send JSON responses with CORS headers
def respond_with(data):
    resp = jsonify(data)
    resp.headers['Access-Control-Allow-Origin'] = '*'
    resp.headers['Access-Control-Allow-Headers'] = '*'
    return resp

# Endpoints
@app.route('/manifest.json')
def manifest():
    manifest_data = {
        "id": "org.iptv.addon",
        "version": "0.0.1",
        "name": "IPTV Addon",
        "description": "Addon to fetch IPTV channels.",
        "resources": ["catalog", "stream"],
        "types": ["tv"],
        "catalogs": [
            {
                "type": "tv",
                "id": "iptv_catalog",
                "name": "IPTV Channels",
                "genres": ["Entertainment", "News", "Sports"]
            }
        ]
    }
    return respond_with(manifest_data)

@app.route('/catalog/<type>/<id>.json')
def catalog(type, id):
    if type == "tv" and id == "iptv_catalog":
        channels = fetch_channels()
        metas = [
            {
                "id": channel.get('id'),
                "type": "tv",
                "name": channel.get('name'),
                "poster": channel.get('logo'),
                "genres": channel.get('categories', [])
            }
            for channel in channels
        ]
        return jsonify({"metas": metas})
    else:
        return jsonify({"metas": []})

@app.route('/stream/<type>/<id>.json')
def stream(type, id):
    if type == "tv":
        channels = fetch_channels()
        for channel in channels:
            if channel.get('id') == id:
                streams = channel.get('streams', [])
                streams_data = [
                    {
                        "title": stream.get('title', 'Stream'),
                        "url": stream.get('url')
                    }
                    for stream in streams
                ]
                return jsonify({"streams": streams_data})
    return jsonify({"streams": []})

# Entry point of the application
if __name__ == '__main__':
    try:
        # Initial data load and logging of fetched channels
        print("Fetching initial data...")
        channels = fetch_channels()
        if channels:
            print(f"Fetched {len(channels)} channels.")
        else:
            print("No channels found during the initial fetch.")

        # Start the Flask app
        app.run(host='0.0.0.0', port=7001)
    except (KeyboardInterrupt, SystemExit):
        pass
    finally:
        graceful_shutdown()  # Ensure scheduler shuts down gracefully
