import argparse
import os
import signal
import sys
import threading
import time
import praw
from modules.reddit_auth import RedditAuth
from modules.reddit_content_remover import RedditContentRemover
from modules.user_preferences import UserPreferences
from modules import credentials_manager


def run_content_remover(preferences: UserPreferences, reddit: praw.Reddit, auth: RedditAuth) -> None:
    """
    Execute the content removal process based on user preferences.

    This function initialises the content remover, sets up interrupt handlers,
    and runs the content removal process in a loop until all content is removed
    or an interrupt is received.

    Args:
        preferences (UserPreferences): User-defined preferences for content removal.
        reddit (praw.Reddit): Authenticated Reddit instance for API interactions.
        auth (RedditAuth): Reddit authentication object containing user information.

    Raises:
        Exception: Any unexpected errors during the content removal process.
    """
    if not preferences.any_selected():
        print("No content types selected for deletion or editing. Exiting.")
        return

    run_count = 0
    content_remover = RedditContentRemover(reddit, auth.username, preferences)

    def interrupt_handler(signum, frame):
        print("\nInterrupt received. Stopping content removal...")
        print("Saving processed IDs before exit...")
        content_remover.save_processed_ids()
        print("Forcing exit in 5 seconds if graceful shutdown fails...")
        content_remover.interrupt_flag = True

        # Set a timer to force exit if graceful shutdown doesn't work
        def force_exit():
            print("\nForcing exit...")
            os._exit(1)

        timer = threading.Timer(5.0, force_exit)
        timer.start()

    signal.signal(signal.SIGINT, interrupt_handler)
    signal.signal(signal.SIGTERM, interrupt_handler)

    try:
        while True:
            run_count += 1
            print(f"\nStarting run #{run_count}")
            print("Processing Reddit content...")
            deleted_counts, edited_counts = content_remover.delete_all_content()

            if content_remover.interrupt_flag:
                print("Run interrupted.")
                break

            print("\nContent processed in this run:")
            for item_type, count in deleted_counts.items():
                print(f"{item_type.capitalize()} deleted: {count}")
            for item_type, count in edited_counts.items():
                print(f"{item_type.capitalize()} edited: {count}")

            if all(count == 0 for count in deleted_counts.values()):
                print("\nNo content was deleted in this run. Stopping runs...")
                break
            print("\nSome content was deleted. Running the script again in 7 seconds...")
            for _ in range(70):  # Check interrupt every 0.1 seconds
                if content_remover.interrupt_flag:
                    break
                time.sleep(0.1)
            if content_remover.interrupt_flag:
                break

    except Exception as e:
        print(f"An unexpected error occurred: {e}")
        print("Saving processed IDs before exit...")
        content_remover.save_processed_ids()
    finally:
        print(f"\nTotal content processed across {run_count} {'run' if run_count == 1 else 'runs'}:")
        for item_type, count in content_remover.total_deleted_dict.items():
            print(f"{item_type.capitalize()} deleted: {count}")
        for item_type, count in content_remover.total_edited_dict.items():
            print(f"{item_type.capitalize()} edited: {count}")


def main():
    # Parse arguments
    parser = argparse.ArgumentParser(description="EreddicatorCLI")
    
    action_group = parser.add_mutually_exclusive_group()
    action_group.add_argument("--delete", action="store_true", help="Delete content after editing")
    action_group.add_argument("--delete_only", action="store_true", help="Delete content without editing")
    action_group.add_argument("--edit_only", action="store_true", help="Only edit content without deleting")
    
    parser.add_argument("--dry_run", action="store_true", help="Enable dry run mode (no actual changes made)")
    list_group = parser.add_mutually_exclusive_group()
    list_group.add_argument("--whitelist", nargs="+", help="List of subreddits to preserve (not process)")
    list_group.add_argument("--blacklist", nargs="+", help="List of subreddits to exclusively process")

    credentials_group = parser.add_argument_group("credential management")
    credentials_group.add_argument(
        "-c", "--credentials", metavar="NAME",
        help="Name of the stored credential profile to use for this run (defaults to the profile marked as default)"
    )

    mgmt_group = credentials_group.add_mutually_exclusive_group()
    mgmt_group.add_argument(
        "--new-credentials", action="store_true",
        help="Interactively create (or overwrite) a stored credential profile, then exit"
    )
    mgmt_group.add_argument(
        "--remove-credentials", metavar="NAME",
        help="Delete a stored credential profile (with confirmation), then exit"
    )
    mgmt_group.add_argument(
        "--list-credentials", action="store_true",
        help="List stored credential profile names and the current default, then exit"
    )

    args = parser.parse_args()

    if args.new_credentials:
        try:
            credentials_manager.run_new_credentials_wizard()
        except (KeyboardInterrupt, EOFError):
            print("\nCancelled.")
        return

    if args.remove_credentials:
        name = args.remove_credentials
        if not credentials_manager.profile_exists(name):
            print(f"No stored credential profile named '{name}'.")
            return
        confirm = input(f"Remove credential profile '{name}'? This cannot be undone. [y/N]: ").strip().lower()
        if confirm != "y":
            print("Cancelled.")
            return
        was_default = credentials_manager.get_default_profile() == name
        credentials_manager.remove_profile(name)
        print(f"Removed profile '{name}'.")
        if was_default:
            print("That was your default profile. No default is set now — "
                  "run --new-credentials or pass -c/--credentials NAME explicitly next time.")
        return

    if args.list_credentials:
        profiles = credentials_manager.list_profiles()
        default = credentials_manager.get_default_profile()
        if not profiles:
            print("No stored credential profiles. Run 'python main.py --new-credentials' to create one.")
        else:
            print("Stored credential profiles:")
            for p in profiles:
                print(f"  {p}" + ("  (default)" if p == default else ""))
        return

    # Keep trying authentication until successful or user gives up.
    reddit = None
    auth = None
    while reddit is None:
        try:
            # Create an instance of RedditAuth and get the Reddit instance
            auth = RedditAuth(profile_name=args.credentials)
            reddit = auth.get_reddit_instance()
        except Exception as e:
            error_message = str(e)

            if "cancelled by user" in error_message.lower() or "application has been destroyed" in error_message.lower():
                print(e)
                return

            print(e)
            return
    
    # Load user preferences

    preferences = UserPreferences()
    
    if args.delete:
        preferences.delete_comments = True
        preferences.delete_posts = True
        preferences.only_edit_comments = False
        preferences.only_edit_posts = False
        preferences.delete_without_edit_comments = False
        preferences.delete_without_edit_posts = False
    elif args.delete_only:
        preferences.delete_without_edit_comments = True
        preferences.delete_without_edit_posts = True
        preferences.delete_comments = False
        preferences.delete_posts = False
        preferences.only_edit_comments = False
        preferences.only_edit_posts = False
    elif args.edit_only:
        preferences.only_edit_comments = True
        preferences.only_edit_posts = True
        preferences.delete_comments = False
        preferences.delete_posts = False
        preferences.delete_without_edit_comments = False
        preferences.delete_without_edit_posts = False

    if args.dry_run:
        preferences.dry_run = True

    if args.whitelist:
        preferences.whitelist_subreddits = args.whitelist

    if args.blacklist:
        preferences.blacklist_subreddits = args.blacklist

    # Execute content remover
    run_content_remover(preferences, reddit, auth)


if __name__ == "__main__":
    main()
