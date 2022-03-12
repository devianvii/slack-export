import requests
import json
import sys
from time import sleep


DEFAULT_OBJECTS_LIMIT = 4000
DEFAULT_TIMEOUT = 10
DEFAULT_RETRIES = 0
# seconds to wait after a 429 error if Slack's API doesn't provide one
DEFAULT_WAIT = 20


class Error(Exception):
    pass


def get_api_url(method):
    return 'https://slack.com/api/{}'.format(method)


class Response(object):
    def __init__(self, body):
        self.raw = body
        self.body = json.loads(body)
        self.successful = self.body['ok']
        self.error = self.body.get('error')

    def __str__(self):
        return json.dumps(self.body)


class SlackApiAdapter:
    def __init__(self, token, headers=None,
                 timeout=DEFAULT_TIMEOUT,
                 session=None,
                 rate_limit_retries=DEFAULT_RETRIES):
        self.headers = headers
        self.token = token
        self.timeout = timeout
        self.session = session
        self.rate_limit_retries = rate_limit_retries

    def _request(self, request_method, method, **kwargs):
        if self.token:
            kwargs.setdefault('params', {})['token'] = self.token
            kwargs['headers'] = self.headers
        url = get_api_url(method)

        # while we have rate limit retries left, fetch the resource and back
        # off as Slack's HTTP response suggests
        for retry_num in range(self.rate_limit_retries):
            response = request_method(
                url, timeout=self.timeout, proxies=self.proxies, **kwargs
            )

            if response.status_code == requests.codes.ok:
                break

            # handle HTTP 429 as documented at
            # https://api.slack.com/docs/rate-limits
            if response.status_code == requests.codes.too_many:
                time.sleep(int(
                    response.headers.get('retry-after', DEFAULT_WAIT)
                ))
                continue

            response.raise_for_status()
        else:
            # with no retries left, make one final attempt to fetch the
            # resource, but do not handle too_many status differently
            response = request_method(
                url, timeout=self.timeout, **kwargs
            )
            response.raise_for_status()

        response = Response(response.text)
        if not response.successful:
            raise Error(response.error)

        return response

    def _session_get(self, url, params=None, **kwargs):
        kwargs.setdefault('allow_redirects', True)
        return self.session.request(
            method='get', url=url, params=params, **kwargs
        )

    def _session_post(self, url, data=None, **kwargs):
        return self.session.request(
            method='post', url=url, data=data, **kwargs
        )

    def get(self, api, **kwargs):
        return self._request(
            self._session_get if self.session else requests.get,
            api, **kwargs
        )

    def post(self, api, **kwargs):
        return self._request(
            self._session_post if self.session else requests.post,
            api, **kwargs
        )

    def _conversations_list_request(self, cursor=None, exclude_archived=None, types=None, limit=1000):
        if isinstance(types, (list, tuple)):
            types = ','.join(types)
        conversations_list = self.get(
            'conversations.list',
            params={
                'cursor': cursor,
                'exclude_archived': exclude_archived,
                'types': types,
                'limit': limit
            }
        )
        return conversations_list

    def get_conversations(self, types, limit=DEFAULT_OBJECTS_LIMIT):
        conversations_list = []
        req_conversations = self._conversations_list_request(types=types)
        conversations_list.extend(req_conversations.body['channels'])
        cursor = req_conversations.body['response_metadata']['next_cursor']
        while cursor != '' and len(conversations_list) < limit:
            req_conversations = self._conversations_list_request(types=types, cursor=cursor)
            conversations_list.extend(req_conversations.body['channels'])
            cursor = req_conversations.body['response_metadata']['next_cursor']
        return conversations_list

    def _conversations_history_request(self, channel, cursor=None, limit=1000, latest=None, oldest=None):
        messages_list = self.get('conversations.history',
                                 params={
                                     'channel': channel,
                                     'cursor': cursor,
                                     'latest': latest,
                                     'oldest': oldest,
                                     'limit': limit
                                 }
                                 )
        return messages_list

    def _replies_request(self, channel, thread_ts, cursor=None, limit=1000, latest=None, oldest=None):
        replies_list = self.get(
            'conversations.replies',
            params={
                'channel': channel,
                'ts': thread_ts,
                'cursor': cursor,
                'latest': latest,
                'oldest': oldest,
                'limit': limit
            }
        )
        return replies_list

    # TODO: use cursor logic
    def get_replies(self, channel_id, thread_ts):
        replies = []
        last_timestamp = None

        while True:
            try:
                response = self._replies_request(channel=channel_id,
                                                 thread_ts=thread_ts,
                                                 latest=last_timestamp,
                                                 oldest=0).body
            #   print(response)
            except requests.exceptions.HTTPError as e:
                if e.response.status_code == 429:
                    retryInSeconds = int(e.response.headers["Retry-After"])
                    print("Rate limit hit. Retrying in {0} second{1}.".format(retryInSeconds,
                                                                              "s" if retryInSeconds > 1 else ""))
                    sleep(retryInSeconds)
                    response = self._replies_request(channel=channel_id,
                                                     thread_ts=thread_ts,
                                                     latest=last_timestamp,
                                                     oldest=0).body

            replies.extend(response["messages"])
            if response["has_more"]:
                sys.stdout.write("../slack-export-new")
                sys.stdout.flush()
                last_timestamp = replies[-1]["ts"]  # -1 means last element in a list
                sleep(1)  # Respect the Slack API rate limit
            else:
                break
        if last_timestamp is not None:
            print("")

        replies.sort(key=lambda replies: replies["ts"])
        replies = replies[1:]
        return replies

    def get_channel_history(self, channel_id):
        last_timestamp = None
        messages = []

        while True:
            try:
                response = self._conversations_history_request(channel=channel_id, latest=last_timestamp, oldest=0).body
            except requests.exceptions.HTTPError as e:
                if e.response.status_code == 429:
                    retryInSeconds = int(e.response.headers['Retry-After'])
                    print(u"Rate limit hit. Retrying in {0} second{1}.".format(retryInSeconds,
                                                                               "s" if retryInSeconds > 1 else ""))
                    sleep(retryInSeconds)
                    response = self._conversations_history_request(channel=channel_id, latest=last_timestamp,
                                                                   oldest=0).body

            messages.extend(response['messages'])

            if response['has_more']:
                sys.stdout.write("../slack-export-new")
                sys.stdout.flush()
                last_timestamp = messages[-1]['ts']  # -1 means last element in a list
                sleep(0.5)  # Respect the Slack API rate limit
            else:
                break

        if last_timestamp is not None:
            print("")
        messages.sort(key=lambda t: t['ts'])
        replies = []
        for i, message in enumerate(messages, 0):
            if message.get('reply_count', 0) > 0:
                print("Thread found in message {}/{}".format(i, len(messages)))
                rp = self.get_replies(channel_id, message["thread_ts"])
                for reply_pos, reply in enumerate(rp, 1):
                    if messages[i].get('replies'):
                        messages[i]['replies'].append({'user': reply.get('user'), 'ts': reply['ts']})
                    else:
                        messages[i]['replies'] = [{'user': reply.get('user'), 'ts': reply['ts']}]
                    if reply.get('subtype') == 'thread_broadcast':
                        continue
                    replies.append(reply)
        messages.extend(replies)
        messages.sort(key=lambda t: t['ts'])
        return messages

