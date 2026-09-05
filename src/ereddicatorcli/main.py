import argparse
import os
import signal
import sys
import threading
import time
import praw
from .modules.reddit_auth import RedditAuth
from .modules.reddit_content_remover import RedditContentRemover
from .modules.user_preferences import UserPreferences
from .modules import user_manager


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
        content_remover.interrupt_flag = True
        print("Saving processed IDs before exit...")
        content_remover.save_processed_ids()
        print("Forcing exit in 5 seconds if graceful shutdown fails...")

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
    parser = argparse.ArgumentParser(prog="ereddicator", description="EreddicatorCLI")
    
    action_group = parser.add_mutually_exclusive_group()
    action_group.add_argument("--delete", action="store_true", help="Delete content after editing")
    action_group.add_argument("--delete-only", action="store_true", help="Delete content without editing")
    action_group.add_argument("--edit-only", action="store_true", help="Only edit content without deleting")
    
    parser.add_argument("--dry-run", action="store_true", help="Enable dry run mode (no actual changes made)")
    list_group = parser.add_mutually_exclusive_group()
    list_group.add_argument("--whitelist", nargs="+", help="List of subreddits to preserve (not process)")
    list_group.add_argument("--blacklist", nargs="+", help="List of subreddits to exclusively process")

    user_group = parser.add_argument_group("user management")
    user_group.add_argument(
        "-u", "--user", metavar="NAME",
        help="Name of the stored user to use for this run (defaults to the user marked as default)"
    )

    mgmt_group = user_group.add_mutually_exclusive_group()
    mgmt_group.add_argument(
        "--new-user", action="store_true",
        help="Interactively create (or overwrite) a stored user, then exit"
    )
    mgmt_group.add_argument(
        "--remove-user", metavar="NAME",
        help="Delete a stored user (with confirmation), then exit"
    )
    mgmt_group.add_argument(
        "--list-users", action="store_true",
        help="List stored user names and the current default, then exit"
    )
    mgmt_group.add_argument(
        "--set-default-user", metavar="NAME",
        help="Set an existing stored user as the default used when -u/--user is omitted, then exit"
    )

    args = parser.parse_args()

    if args.new_user:
        try:
            user_manager.run_new_user_wizard()
        except (KeyboardInterrupt, EOFError):
            print("\nCancelled.")
        return

    if args.remove_user:
        name = args.remove_user
        if not user_manager.user_exists(name):
            print(f"No stored user named '{name}'.")
            return
        confirm = input(f"Remove user '{name}'? This cannot be undone. [y/N]: ").strip().lower()
        if confirm != "y":
            print("Cancelled.")
            return
        was_default = user_manager.get_default_user() == name
        user_manager.remove_user(name)
        print(f"Removed user '{name}'.")
        if was_default:
            print("That was your default user. No default is set now — "
                  "run --new-user or pass -u/--user NAME explicitly next time.")
        return

    if args.set_default_user:
        name = args.set_default_user
        try:
            user_manager.set_default_user(name)
        except user_manager.UserNotFoundError as e:
            print(e)
            return
        print(f"Default user set to '{name}'.")
        return

    if args.list_users:
        names = user_manager.list_users()
        default = user_manager.get_default_user()
        if not names:
            print("No stored users. Run 'ereddicator --new-user' to create one.")
        else:
            print("Stored users:")
            for n in names:
                print(f"  {n}" + ("  (default)" if n == default else ""))
        return

    # Keep trying authentication until successful or user gives up.
    reddit = None
    auth = None
    while reddit is None:
        try:
            # Create an instance of RedditAuth and get the Reddit instance
            auth = RedditAuth(user=args.user)
            reddit = auth.get_reddit_instance()
        except Exception as e:
            error_message = str(e)

            if "cancelled by user" in error_message.lower() or "application has been destroyed" in error_message.lower():
                print(e)
                return

            print(e)
    
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
