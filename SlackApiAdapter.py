import requests
import json
import sys
from time import sleep


DEFAULT_TIMEOUT = 60
DEFAULT_RETRIES = 3
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
                url, timeout=self.timeout, **kwargs
            )

            if response.status_code == requests.codes.ok:
                break

            # handle HTTP 429 as documented at
            # https://api.slack.com/docs/rate-limits
            if response.status_code == requests.codes.too_many:
                retry_in_seconds = int(response.headers.get('retry-after', DEFAULT_WAIT))
                print("Rate limit hit. Retrying in {0} second{1}.".format(retry_in_seconds,
                                                                          "s" if retry_in_seconds > 1 else ""))
                sleep(retry_in_seconds)

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

    def get_conversations(self, types):
        conversations_list = []
        req_conversations = self._conversations_list_request(types=types)
        conversations_list.extend(req_conversations.body['channels'])
        cursor = req_conversations.body['response_metadata']['next_cursor']
        while cursor != '':
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
                sys.stdout.write(".")
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

    def get_channel_history(self, channel_id, exclude_threads=False):
        last_timestamp = None
        messages = []
        users = set()

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
                sys.stdout.write(".")
                sys.stdout.flush()
                last_timestamp = messages[-1]['ts']  # -1 means last element in a list
                sleep(1)  # Respect the Slack API rate limit
            else:
                break

        if last_timestamp is not None:
            print("")
        messages.sort(key=lambda t: t['ts'])
        if exclude_threads:
            for i, message in enumerate(messages, 0):
                if message.get('reply_count') is not None:
                    messages[i]['replies'] = []
                    users.add(messages[i].get('user'))
        else:
            replies = []
            for i, message in enumerate(messages, 0):
                users.add(messages[i].get('user'))
                if message.get('reply_count') == 0 and message.get('reply_users_count') == 0:
                    messages[i]['replies'] = []
                    continue
                if message.get('reply_count'):
                    print(f"Thread found in {channel_id} messages {i}/{len(messages)}")
                    rp = self.get_replies(channel_id, message["thread_ts"])
                    for reply_pos, reply in enumerate(rp, 1):
                        if messages[i].get('replies'):
                            messages[i]['replies'].append({'user': reply.get('user'), 'ts': reply['ts']})
                        else:
                            messages[i]['replies'] = [{'user': reply.get('user'), 'ts': reply['ts']}]
                        if reply.get('subtype') == 'thread_broadcast':
                            continue
                        users.add(reply.get('user'))
                        replies.append(reply)
            messages.extend(replies)
            messages.sort(key=lambda t: t['ts'])
        return messages, users

    def _users_request(self, presence=False, request_limit=1000, cursor=None):
        re = 'users.list?limit={limit}'.format(limit=request_limit)
        if cursor:
            re += "&cursor={cursor}".format(cursor=cursor)
        return self.get(re, params={'presence': int(presence)})

    def get_users(self):
        members_list = []
        req_members = self._users_request()
        members_list.extend(req_members.body['members'])
        cursor = req_members.body['response_metadata']['next_cursor']
        while cursor != '':
            req_members = self._users_request(cursor=cursor)
            members_list.extend(req_members.body['members'])
            cursor = req_members.body['response_metadata']['next_cursor']
            print(f"Fetched {len(members_list)} team members")
        print(f"Total users fetched: {len(members_list)}")
        return members_list
