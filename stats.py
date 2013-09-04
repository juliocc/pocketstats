import os
import time
import datetime
import json
import operator

import redis
import requests
from pocket import Pocket
from functional import compose
from dateutil.relativedelta import relativedelta
from jinja2 import Environment, FileSystemLoader

from SortedCollection import SortedCollection

class PocketItem(object):
    def __init__(self, json):
        to_datetime = compose(datetime.datetime.utcfromtimestamp,
                              float)

        self.title = json.get('resolved_title').strip()
        self.url = json.get('resolved_url')
        self.item_id = json.get('item_id')
        self.time_added = to_datetime(json.get('time_added'))
        self.time_read = to_datetime(json.get('time_read'))
        self.time_updated = to_datetime(json.get('time_updated'))
        self._status = int(json.get('status'))

    @property
    def is_new(self):
        return self._status == 0

    is_unread = is_new

    @property
    def is_read(self):
        return self._status == 1

    @property
    def is_deleted(self):
        return self._status == 2

    @property
    def status(self):
        return ["undread", "read", "deleted"][self._status]

    def __repr__(self):
        return u"<PocketItem {}>".format(self.item_id)

    def __str__(self):
        return u"({}, {}, A:{}, R:{}, U:{})".format(self.item_id,
                                                    self.status,
                                                    self.time_added,
                                                    self.time_read,
                                                    self.time_updated)

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

        loader = FileSystemLoader(os.path.join(os.path.dirname(os.path.realpath(__file__)), "reports"))
        print os.path.join(os.path.dirname(os.path.realpath(__file__)), "reports")
        self.env = Environment(loader=loader)


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

    def render(self, template, **kwargs):
        template = self.env.get_template(template)
        return template.render(**kwargs)

    def _get_items_since(self, sorted_collection, since):
        first = sorted_collection.find_ge(since)
        index = sorted_collection.index(first)
        return sorted_collection[index:]

    def get_stats(self):
        items = self.get_items(False)
        read = filter(operator.attrgetter("is_read"), items)
        unread = filter(operator.attrgetter("is_unread"), items)

        read_sorted = SortedCollection(read, operator.attrgetter('time_read'))
        unread_sorted = SortedCollection(unread, operator.attrgetter('time_added'))

        # find items read less than a week ago
        now = datetime.datetime.now()
        _7_days_ago = now + relativedelta(days=-7)
        _30_days_ago = now + relativedelta(days=-30)

        print self.render("report.txt",
                          total=len(items),
                          total_read=len(read),
                          total_unread=len(unread),
                          now=now,

                          newly_added_7d=self._get_items_since(unread_sorted, _7_days_ago),
                          newly_read_7d=self._get_items_since(read_sorted, _7_days_ago),

                          newly_added_30d=self._get_items_since(unread_sorted, _30_days_ago),
                          newly_read_30d=self._get_items_since(read_sorted, _30_days_ago)
                      )

if __name__ == '__main__':
    stats = PocketStats()
    stats.get_stats()
