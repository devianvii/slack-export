import argparse
import json
import os
from datetime import datetime
import shutil
import requests
from urllib.parse import urlparse

import SlackApiAdapter

OUTPUT_DIRECTORY = 'dump'


def filter_conversations(conversations):
    conversations_filtered = []
    for conversation in conversations:
        if not conversation['is_member']:
            continue
        conversations_filtered.append(conversation)
    return conversations_filtered


def dump_users(members):
    with open('users.json', 'w') as outFile:
        json.dump(members, outFile, indent=4)


def dump_private_channels_list(private_channels):
    with open('groups.json', 'w') as outFile:
        json.dump(private_channels, outFile, indent=4)


def dump_public_channels_list(public_channels):
    with open('channels.json', 'w') as outFile:
        json.dump(public_channels, outFile, indent=4)


def dump_mpim_list(mpim):
    with open('mpims.json', 'w') as outFile:
        json.dump(mpim, outFile, indent=4)


def dump_im_list(im):
    with open('dms.json', 'w') as outFile:
        json.dump(im, outFile, indent=4)


def mkdir(directory):
    if not os.path.isdir(directory):
        os.makedirs(directory)


def parse_time_stamp(time_stamp):
    """create datetime object from slack timestamp ('ts') string"""
    if '.' in time_stamp:
        t_list = time_stamp.split('.')
        if len(t_list) != 2:
            raise ValueError('Invalid time stamp')
        else:
            return datetime.utcfromtimestamp(float(t_list[0]))


def channel_rename(old_room_name, new_room_name):
    """move channel files from old directory to one with new channel name"""
    # check if any files need to be moved
    if not os.path.isdir(old_room_name):
        return
    mkdir(new_room_name)
    for fileName in os.listdir(old_room_name):
        shutil.move(os.path.join(old_room_name, fileName), new_room_name)
    os.rmdir(old_room_name)


def write_message_file(file_name, messages):
    directory = os.path.dirname(file_name)

    # if there's no data to write to the file, return
    if not messages:
        return

    if not os.path.isdir(directory):
        mkdir(directory)

    with open(file_name, 'w') as out_file:
        json.dump(messages, out_file, indent=4)


def parse_messages(room_dir, messages, room_type):
    name_change_flag = room_type + "_name"

    current_file_date = ''
    current_messages = []
    for message in messages:
        # first store the date of the next message
        ts = parse_time_stamp(message['ts'])
        file_date = '{:%Y-%m-%d}'.format(ts)

        # if it's on a different day, write out the previous day's messages
        if file_date != current_file_date:
            out_file_name = u'{room}/{file}.json'.format(room=room_dir, file=current_file_date)
            write_message_file(out_file_name, current_messages)
            current_file_date = file_date
            current_messages = []

        # check if current message is a name change
        # dms won't have name change events
        if room_type != "im" and ('subtype' in message) and message['subtype'] == name_change_flag:
            room_dir = message['name']
            old_room_path = message['old_name']
            newRoomPath = room_dir
            channel_rename(old_room_path, newRoomPath)

        current_messages.append(message)
    out_file_name = u'{room}/{file}.json'.format(room=room_dir, file=current_file_date)
    write_message_file(out_file_name, current_messages)


def downloadFiles(token, cookie_header=None):
    """
    Iterate through all json files, downloads files stored on files.slack.com and replaces the link with a local one
    Args:
        jsonDirectory: folder where the json files are in, will be searched recursively
    """
    print("Starting to download files")
    for root, subdirs, files in os.walk("."):
        for filename in files:
            if not filename.endswith('.json'):
                continue
            filePath = os.path.join(root, filename)
            data = []
            with open(filePath) as inFile:
                data = json.load(inFile)
                for msg in data:
                    for slackFile in msg.get("files", []):
                        # Skip deleted files
                        if slackFile.get("mode") == "tombstone":
                            continue

                        for key, value in slackFile.items():
                            # Find all entries referring to files on files.slack.com
                            if not isinstance(value, str) or not value.startswith("https://files.slack.com/"):
                                continue

                            url = urlparse(value)

                            localFile = os.path.join("../files.slack.com",
                                                     url.path[1:])  # Need to discard first "/" in URL, because:
                            # "If a component is an absolute path, all previous components are thrown away and joining continues
                            # from the absolute path component."
                            print("Downloading %s, saving to %s" % (url.geturl(), localFile))

                            # Create folder structure
                            os.makedirs(os.path.dirname(localFile), exist_ok=True)

                            # Check if file already downloaded, with same size
                            if os.path.exists(localFile) and os.path.getsize(localFile) == slackFile.get("size", -1):
                                print("Skipping already downloaded file: %s" % localFile)
                                continue

                            # Download files
                            headers = {"Authorization": "Bearer {}".format(token), **cookie_header}
                            r = requests.get(url.geturl(), headers=headers)
                            open(localFile, 'wb').write(r.content)

                            # Replace URL in data - suitable for use with slack-export-viewer if files.slack.com is linked
                            slackFile[key] = "/static/files.slack.com%s" % url.path

            # Save updated data to json file
            with open(filePath, "w") as outFile:
                json.dump(data, outFile, indent=4, sort_keys=True)

            print("Replaced all files in %s" % filePath)


def filter_users(users_list, users_white_list):
    filtered_users_list = []
    print(users_white_list)
    for user in users_list:
        if user['id'] in users_white_list:
            filtered_users_list.append(user)
    return filtered_users_list


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description='Export Slack history')
    parser.add_argument('--token', required=True, help="Slack API token")
    parser.add_argument('--cookie', required=True, help="a set of cookies for the xoxc api token")

    parser.add_argument(
        '--directMessages',
        nargs='*',
        default=None,
        metavar='USER_NAME',
        help="Export 1:1 DMs with the given users")

    parser.add_argument(
        '--privateChannels',
        nargs='*',
        default=None,
        metavar='CHANNEL_NAME',
        help="Export the given Private Channels")

    parser.add_argument(
        '--publicChannels',
        nargs='*',
        default=None,
        metavar='CHANNEL_NAME',
        help="Export the given Public Channels")

    parser.add_argument(
        '--directGroupMessages',
        action='store_true',
        default=None,
        help="Export mpim conversations")

    parser.add_argument(
        '--downloadSlackFiles',
        action='store_true',
        default=False,
        help="Downloads files from files.slack.com for local access, stored in 'files.slack.com' folder. "
             "Link this folder inside slack-export-viewer/slackviewer/static/ to have it work seamless with slack-export-viewer")

    parser.add_argument(
        '--excludeThreads',
        action='store_true',
        default=False,
        help="Ignore threads"
    )

    args = parser.parse_args()
    cookie_header = {'cookie': args.cookie}

    slack = SlackApiAdapter.SlackApiAdapter(headers=cookie_header, token=args.token)

    users_white_list = set()
    mkdir(OUTPUT_DIRECTORY)
    os.chdir(OUTPUT_DIRECTORY)

    if args.privateChannels is not None:
        private_channels_list = filter_conversations(slack.get_conversations('private_channel'))
        dump_private_channels_list(private_channels_list)
        print("Fetching messages from", len(private_channels_list), "private channels")
        for channel in private_channels_list:
            if args.privateChannels != [] and channel['name'] not in args.privateChannels:
                print(u"Private channel {0} not in the WhiteList. Passed.".format(channel['name']))
                continue
            channel_dir = channel['name']
            print(u"Fetching history for channel: {0}".format(channel_dir))
            mkdir(channel_dir)
            messages, channel_members = slack.get_channel_history(channel['id'], args.excludeThreads)
            users_white_list.update(channel_members)
            parse_messages(channel_dir, messages, 'group')

    if args.publicChannels is not None:
        public_channels_list = filter_conversations(slack.get_conversations('public_channel'))
        dump_public_channels_list(public_channels_list)
        print("Fetching messages from", len(public_channels_list), "public channels")
        for channel in public_channels_list:
            if args.publicChannels != [] and channel['name'] not in args.publicChannels:
                print(u"Public channel {0} not in the WhiteList. Passed.".format(channel['name']))
                continue
            channel_dir = channel['name']
            print(u"Fetching history for channel: {0}".format(channel_dir))
            mkdir(channel_dir)
            messages, channel_members = slack.get_channel_history(channel['id'], args.excludeThreads)
            users_white_list.update(channel_members)
            parse_messages(channel_dir, messages, 'channel')

    if args.directGroupMessages is not None:
        mpim_list = slack.get_conversations('mpim')
        dump_mpim_list(mpim_list)
        print("Fetching messages from", len(mpim_list), "direct groups")
        for channel in mpim_list:
            channel_dir = channel['name']
            print(u"Fetching history for direct group  channel: {0}".format(channel_dir))
            mkdir(channel_dir)
            messages, channel_members = slack.get_channel_history(channel['id'], args.excludeThreads)
            users_white_list.update(channel_members)
            parse_messages(channel_dir, messages, 'group')

    if args.directMessages is not None:
        im_list = slack.get_conversations('im')
        dump_im_list(im_list)
        print("Fetching messages from", len(im_list), "1:1 conversations")
        for channel in im_list:
            channel_dir = channel['id']
            print(u"Fetching history for 1:1 channel: {0}".format(channel_dir))
            mkdir(channel_dir)
            messages, channel_members = slack.get_channel_history(channel['id'], args.excludeThreads)
            users_white_list.update(channel_members)
            parse_messages(channel_dir, messages, 'im')

    users = filter_users(slack.get_users(), users_white_list)
    print(f"Users in chats:{len(users)}")
    dump_users(users)

    if args.downloadSlackFiles:
        downloadFiles(token=args.token, cookie_header=cookie_header)

    os.chdir('..')
    shutil.make_archive("dump", 'zip', OUTPUT_DIRECTORY, None)
    shutil.rmtree(OUTPUT_DIRECTORY)
    exit()
