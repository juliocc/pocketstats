import os
import time
import datetime
import json

import redis
import requests
from pocket import Pocket
from functional import compose

class PocketItem(object):
    def __init__(self, json):
        to_datetime = compose(datetime.datetime.utcfromtimestamp,
                              float)

        self.title = json.get('resolved_title')
        self.url = json.get('resolved_url')
        self.item_id = json.get('item_id')
        self.time_added = to_datetime(json.get('time_added'))
        self.time_read = to_datetime(json.get('time_read'))
        self.time_updated = to_datetime(json.get('time_updated'))
        self.status = int(json.get('status'))

    @property
    def is_new(self):
        return self.status == 0

    @property
    def is_read(self):
        return self.status == 1

    @property
    def is_deleted(self):
        return self.status == 2

    def __repr__(self):
        return u"<PocketItem {}>".format(self.item_id)

def get_credentials():
    "Extract Pocket API credentials from environment"
    consumer_key = os.environ.get('POCKET_KEY')
    access_token = os.environ.get('POCKET_TOKEN')
    if not consumer_key or not access_token:
        raise ValueError("No key/token found in POCKET_TOKEN or POCKET_KEY")

    return consumer_key, access_token

class PocketStats(object):
    def __init__(self):
        self.redis = redis.StrictRedis(host='localhost', port=6379, db=0)
        self.key, self.token = get_credentials()
        self.pocket = Pocket(self.key, self.token)

    def get_last_sync(self):
        return self.redis.get('pocketstats.last_sync')

    def sync_data(self):
        "Fetch latest data from Pocket to our local redis cache"
        since = self.get_last_sync()
        if since is None:
            since = 'all'

        print("sync since: " + since)
        data, response = self.pocket.get(since=since)

        # pocket returns an empty list instead of an empty dict if
        # there are no changes, so we have to manually check before
        # iterating
        if data['list']:
            for id, item in data['list'].iteritems():
                print("syncing " + id)
                self.redis.set('pocketstats.item:' + id,
                               json.dumps(item))
        else:
            print("Up to date")

        self.redis.set('pocketstats.last_sync', time.time())
        self.redis.bgsave()

    def get_items(self, sync=False):
        "Return all know items as a list of PocketItems.  Sync against pocket if `sync' is true"

        if sync:
            self.sync_data()

        itemskeys = self.redis.keys('pocketstats.item:*')
        items = []
        for doc in self.redis.mget(itemskeys):
            parsed_json = json.loads(doc)
            if parsed_json.get('resolved_url') is not None:
                items.append(PocketItem(parsed_json))

        return items

    def get_stats(self):
        items = self.get_items(True)

if __name__ == '__main__':
    stats = PocketStats()
    stats.get_stats()
