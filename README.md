# EreddicatorCLI

This Python CLI app allows you to edit and/or delete all your Reddit comments, posts, saved items, upvotes, downvotes, and hidden posts. However, upvotes and downvotes on archived posts will remain. There is no way to undo them. You can disable "make my votes public" in your preferences: https://www.reddit.com/prefs/

> **Note:**
> This project is a command-line fork of the original GUI application, [Ereddicator](https://github.com/Jelly-Pudding/ereddicator). It provides the same powerful content removal features but is optimized for terminal environments and automated workflows.

> **Tip:**
> If you are looking for an alternative CLI Reddit content deletion tool, you might also want to check out [shreddit](https://github.com/andrewbanchich/shreddit), an excellent well-maintained Rust-based project for managing your Reddit history.

## Contents

- [Features](#features)
- [Command Line Arguments](#command-line-arguments)
- [Reddit Data Export Request](#reddit-data-export-request)
- [Instructions (for Python Users)](#instructions-for-python-users)
- [Support Me](#buy-me-a-coffee)

## Features

- **Selective Content Removal**: Choose which types of content to delete. Options include:
  - Comments
  - Posts
  - Saved items
  - Upvoted content
  - Downvoted content
  - Hidden posts
- **Reddit Data Export Support**: You can process content from Reddit's data export. Although it requires more effort on your part, it is ***highly recommended*** you take advantage of this feature as it ensures all of your content is processed. See [Reddit Data Export Request](#reddit-data-export-request) for instructions.
- **OAuth Authentication Support**: For users who log in to Reddit via Google ("Login with Google"), you can authenticate via OAuth.
- **Edit-Only Mode**: For comments and posts, you can choose to only edit the content without deleting it. This is ***highly recommended*** for a couple of reasons:
  - Reddit is capable of restoring deleted content, but if you edit content first and leave it edited for some time, any future restoration would likely recover the edited version rather than the original content.
  - Web crawlers and archives that previously captured your content may overwrite their records with your edited version.
- **Delete-Only Mode**: For comments and posts, you can choose to directly delete content without editing it first. This can be useful if you want to avoid potential auto-moderator actions that might be triggered by edited content. Some subreddits may have auto-moderators configured to take action on edited content which could result in unwanted bans.
- **Karma Threshold**: You can set karma thresholds for comments and posts. Content with karma above or equal to the threshold will be preserved.
- **Preserve Gilded Content**: Option to preserve comments and posts that have been gilded (received Reddit gold).
- **Preserve Distinguished Content**: Option to preserve comments and posts that have been distinguished by moderators.
- **Subreddit Filtering**:
  - Whitelist: Specify subreddits to exclude from processing.
  - Blacklist: Specify subreddits to exclusively process, ignoring all others.
- **Date Range Filtering**: Set a specific date range to process content from, allowing you to target content from a particular time period.
- **Dry Run Mode**: Simulate the removal process without actually making any changes. In this mode, Ereddicator will print out what actions would be taken (e.g. what comments and posts will be deleted) without modifying any of your Reddit content.
- **Custom Replacement Text**: Specify custom text to replace your content during editing or before deletion. If not provided, random text will be used.
- **Persistent Processing**: Tracks which items have already been processed across multiple runs, ensuring that items are not processed again if the script is restarted or interrupted.
- **Advertise Option**: When enabled, there's a 50% chance for each comment or post to be replaced with a simple message mentioning Ereddicator instead of random text or custom text.

## Command Line Arguments

You can run the script with the following arguments to set or override preferences:

```text
usage: main.py [-h]
               [--delete | --delete_only | --edit_only]
               [--dry_run]
               [--whitelist WHITELIST [WHITELIST ...]
               | --blacklist BLACKLIST [BLACKLIST ...]]

EreddicatorCLI

options:
  -h, --help            show this help message and exit
  --delete              Delete content after editing
  --delete_only         Delete content without editing
  --edit_only           Only edit content without deleting
  --dry_run             Enable dry run mode (no actual changes made)
  --whitelist WHITELIST [WHITELIST ...]
                        List of subreddits to preserve (not process)
  --blacklist BLACKLIST [BLACKLIST ...]
                        List of subreddits to exclusively process
```

## Reddit Data Export Request
Reddit's API is limited and sometimes does not retrieve all comments and posts. If you want to ensure you get everything, you will need to make a Reddit data export request:

1. Go to https://www.reddit.com/settings/data-request
2. Fill in the form:
   * Select the appropriate request type based on your location:
      * If you're in the EU/UK: Select "General Data Protection Regulation (GDPR)"
      * If you're in California: Select "California Consumer Privacy Act (CCPA)"
      * For all other locations: Select "Other"
   * For date range, select "I want data from my full time at Reddit"
3. Submit the request.

Reddit will process your request and send a message to your Reddit inbox (it is very fast usually and takes minutes, but it can take 1-2 days). The message will contain a download link. Extract the contents of the `.zip` file to a folder. You will then be able to select this folder when [using Ereddicator](#instructions-for-windows-users) (look for the `Reddit Export Directory` option).


## Instructions (for Python Users)

### Installation

1. Git clone this repository: `git clone https://github.com/michalhorvath/ereddicatorcli.git`
2. Navigate to the project directory:
   ```
   cd ereddicatorcli
   ```
3. Install the required dependencies:
   ```
   pip install -r requirements.txt
   ```

### Instructions

1. **Optional First Step** - Make a Reddit data request ([see here for instructions](#reddit-data-export-request)). While Ereddicator works without this, using Reddit's data export ensures all of your content is processed.
2. Obtain a `client_id` and `client_secret` and save these in a notepad file:
   - Go to https://www.reddit.com/prefs/apps
   - Click "Create App" or "Create Another App".
   - You can name it anything. It does not matter.
   - Choose "script" for personal use.
   - For the "redirect uri", put http://localhost:8080

   ![Creating Reddit App](images/create-app.png)

   - After creation, the client_id is the string under "personal use script". For example, it may look like this: "AE9-zURLEvI1pze_rqH4Iw".
   - The client_secret is what appears next to "secret". It will look like this: "ZeqnEO_F21BrzzgOpb_es4kOfbhTww"

   ![Finding Client ID and Secret](images/client-id-and-secret.png)

3. Create a file named `reddit_credentials.ini` in the same directory as the script.
4. Add your Reddit API credentials to the file in one of the following formats:

   **For traditional Reddit accounts:**
   ```
   [reddit]
   client_id = YOUR_CLIENT_ID
   client_secret = YOUR_CLIENT_SECRET
   username = YOUR_USERNAME
   password = YOUR_PASSWORD
   # Leave as None if you don't use two-factor authentication
   two_factor_code = None
   ```
   **For Reddit accounts that use Google login:**
   ```
   [reddit]
   client_id = YOUR_CLIENT_ID
   client_secret = YOUR_CLIENT_SECRET
   # The refresh_token will be filled in after your first login
   ```
5. Navigate to the `src` directory.
6. Run the script using Python: `python main.py` or provide arguments like `python main.py --delete --blacklist aww me_irl`. (See [Command Line Arguments](#command-line-arguments) for options).
7. Keep the terminal where you ran the Python command visible throughout the entire process. This terminal displays authentication status, error messages, and progress updates.
8. If you're using Google login, you'll be prompted to authorise via a browser. After successful authorisation, the refresh token will be saved for future use.
