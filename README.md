
# Slack Exporter
Originaly forked from: https://github.com/chr1spy1/slack-export which is https://github.com/andriuspetrauskis/slack-export forked repo.

But it has changed a bit. In this version:
* Adapted to the new version of Slack API. 
* Removed redundant functions (to make you and me less worried).
* Simplified in some places (sorry, everything that is not needed for my purpose was bloody cut out).
* Made compatible with latest `slack-export-viewer` (but replays are arranged randomly :(. I think it is `slack-export-viewer` problem, I need time to find out).
* excludeNonMember by default (you don't need these conversations, right?).
* Makes a zip file by default.


## Description

The included script `slack_export.py` works with a provided token to export Channels, Private Channels, Direct Messages and Multi Person Messages.

This script finds public channels, private channels, direct messages and group direct messages that your user participates in, downloads the complete history for those converations and writes each conversation out to seperate json files.

This use of the API is blessed by Slack : https://get.slack.help/hc/en-us/articles/204897248
"If you want to export the contents of your own private groups and direct messages
please see our API documentation."
And I quote the original author:
`This script is provided in an as-is state, and I guarantee no updates or quality of service at this time.`

## Dependencies
```
pip install requests  # https://requests.readthedocs.io/en/master/
```
To view history you will need `slack-export-viewer`.

## How to use
1. Export your history with files or without.
2. Open zip file with `slack-export-viewer`

### 1. History export
```
python slack_export.py --token <token> --cookie "b=<b>; d=<d>; x=<x>" --directMessages --directGroupMessages --excludeThreads --downloadSlackFiles
```
A guide to get your client token and cookie can be found on the ircslackd repo, see link below:
https://github.com/adsr/irslackd/wiki/IRC-Client-Config#xoxc-tokens
I'm not certain which cookies are necessary but there is a cookie table provided by slack here:
https://slack.com/intl/en-au/cookie-table#

#### Supported Arguments
##### Export all 1:1 direct messages

`--directMessages`

##### Export all group direct messages

`--directGroupMessages`
##### Export all private channels

`--privateChannels`
##### Export certain private channels

`--privateChannels my_channel team_channel`
##### Export all public channels

`--publicChannels`
##### Export certain public channels

`--publicChannels my_public_channel team_public_channel`
##### Do NOT export Threads
Threads are requested per message, so it will take a long time to export it. Use this flag if you don't really interested in threads.

`--excludeThreads`
##### Download files
Downloads files from files.slack.com for local access, stored in `files.slack.com` folder.
Link this folder inside slack-export-viewer/slackviewer/static/ to have it work seamless with slack-export-viewer.
The files will be downloaded into the `files.slack.com` local folder (inside the current working directory) and re-used for
all future export (files are compared for size before attempting to download them). This option will also
replace the URLs inside the export to point to the downloaded files assuming they are accessible with
`/static/files.slack.com/` from the slack-export-viewer webserver.

`--downloadSlackFiles`

### 2. Using slack-export-viewer

`./slack-export-viewer/app.py -z slack-export/dump.zip -p 8081`

#### Lnking files.slack.com with `slack-export-viewer`
```
python slack_export.py --token xoxc-123... --cookie "b=...; d=...; x=..." --privateChannels --downloadSlackFiles

# Clone slack-export-viewer from github
cd ..
git clone https://github.com/hfaran/slack-export-viewer.git

# Link the files.slack.com archive
ln -s ../../../slack-export/files.slack.com slack-export-viewer/slackviewer/static/files.slack.com

# Run slack-export-viewer with the archive previously created
./slack-export-viewer/app.py -z slack-export/dump.zip -p 8081
```

