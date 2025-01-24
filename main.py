import requests
import json
import time
import base64
from bs4 import BeautifulSoup
import re
from concurrent.futures import ThreadPoolExecutor
import logging

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")

# Reference - https://gist.github.com/KobaKhit/5109896f18471f6240e4db973b2ee672

venue_url = 'https://www.stubhub.com/madison-square-garden-tickets/venue/1282/'
client_id = ""  # API users have this, I don't have it :)
client_secret = ""  # API users have this, I don't have it :)
stubhub_username = ""
stubhub_password = ""

class StubhubScraper:
    def __init__(self, client_id, client_secret):
        self.client_id = client_id
        self.client_secret = client_secret
        self.access_token = None
        id_secret = f"{self.client_id}:{self.client_secret}"
        base_auth_token = base64.b64encode(id_secret.encode()).decode()
        self.headers = {
            'Content-Type': 'application/x-www-form-urlencoded',
            'Authorization': f'Basic {base_auth_token}'
        }
        self.base_url = "https://api.stubhub.com"
        # self.authenticate()

    def authenticate(self):
        """Authenticate with StubHub API and get access token."""
        headers = self.headers
        body = {
            'grant_type': 'password',
            'username': stubhub_username,
            'password': stubhub_password,
            'scope': 'PRODUCTION'
        }
        try:
            response = requests.post(f"{self.base_url}/login", headers=headers, data=body)
            response.raise_for_status()
            auth_token = response.json()
            self.access_token = auth_token['access_token']
            self.headers = {
                'Authorization': f'Bearer {self.access_token}',
                'Accept': 'application/json',
                'Accept-Encoding': 'gzip'
            }
            logging.info("Authentication successful.")
        except requests.RequestException as e:
            logging.error(f"Authentication failed: {e}")
            raise

    def get_events(self):
        """Scrape events for a given venue."""
        """Here I was not able to find any endpoint so I have used the BeautifulSoup to scrape the website"""
        event_details = []
        try:
            response = requests.get(venue_url, headers=self.headers)
            response.raise_for_status()
            soup = BeautifulSoup(response.content, 'html.parser')
            events = soup.find_all('a', class_='sc-1x2zy2i-2 cYRIRc sc-97oil8-1 hZTepn')
            for event in events:
                try:
                    event_url = event['href']
                    match = re.search(r"/event/(\d+)/", event_url)
                    if not match:
                        continue
                    event_id = match.group(1)
                    event_name = event.find('p', class_='event-name-class').text.strip()
                    event_date = event.find('p', class_='event-date-class').text.strip()
                    event_details.append({
                        'event_id': event_id,
                        'event_name': event_name,
                        'event_date': event_date
                    })
                except (AttributeError, KeyError):
                    logging.warning("Error parsing event details.")
        except requests.RequestException as e:
            logging.error(f"Failed to scrape events: {e}")
        return event_details

    def process_listings(self, inventory):
        """Get details for each listing."""
        listings = inventory.get('listing', [])
        fields = ['listingId', 'sectionId', 'row', 'quantity', 'sellerSectionName', 'sectionName', 'zoneId', 'zoneName', 'dirtyTicketInd', 'score']
        processed = []
        for listing in listings:
            ret = {}
            for listing in listings:
                ret = {}
                for field in fields:
                    if field in listing:
                        ret[field] = listing[field]
                    else:
                        ret[field] = 'NA'
                ret['currentPrice'] = listing['currentPrice']['amount']
                ret['listingPrice'] = listing['listingPrice']['amount']
                ret['seatNumbers'] = listing['seatNumbers'].replace(',',';') if 'seatNumbers' in listing else 'NA'
                processed.append(ret)
        return processed

    def get_listings(self, event_id, pages=False):
        """Get all listings for a specific event."""
        request_count = 0
        inventory_url = f"{self.base_url}/search/inventory/v2"
        data = {'eventid': event_id, 'rows': 200, 'start': 0}
        inventory = requests.get(inventory_url, headers=self.headers, params=data).json()
        if pages:
            start = 200
            while start < inventory['totalListings']:
                data['start'] = start
                response = requests.get(inventory_url, headers=self.headers, params=data)
                response.raise_for_status()
                inventory['listing'] += response.json()['listing']
                start += 200
                request_count += 1
                if request_count > 10:
                    logging.warning("Request limit reached. Exiting.")
                    break

        return self.process_listings(inventory)

def fetch_event_listings(scraper, event):
    """Helper function for parallel fetching of event listings."""
    event_id = event['event_id']
    start_time = time.time()
    listings = scraper.get_listings(event_id)
    duration = time.time() - start_time
    logging.info(f"Fetched {len(listings)} listings for event {event['event_name']} in {duration:.2f} seconds.")
    return {'event_name': event['event_name'], 'listings': listings, 'duration': duration, 'success': len(listings) > 0}

if __name__ == "__main__":
    scraper = StubhubScraper(client_id, client_secret)
    events = scraper.get_events()
    logging.info(f"Found {len(events)} events.")

    total_time = 0
    failed_attempts = 0

    with ThreadPoolExecutor(max_workers=5) as executor:
        futures = [executor.submit(fetch_event_listings, scraper, event) for event in events]
        results = [future.result() for future in futures]

    for result in results:
        total_time += result['duration']
        if not result['success']:
            failed_attempts += 1

    avg_time = total_time / len(events) if events else 0
    success_rate = 100 * (1 - failed_attempts / len(events)) if events else 0

    logging.info(f"Average scrape time per event: {avg_time:.2f} seconds.")
    logging.info(f"Success rate: {success_rate:.2f}%. Failed attempts: {failed_attempts}.")
