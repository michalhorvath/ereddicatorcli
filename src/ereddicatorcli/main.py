import argparse
import os
import signal
import subprocess
import sys
import threading
import time
import praw
from .modules.reddit_auth import RedditAuth
from .modules.reddit_content_remover import RedditContentRemover
from .modules.user_preferences import UserPreferences
from .modules import config_manager, user_manager


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


def handle_config_commands(args: argparse.Namespace) -> bool:
    """
    Run any config management command given on the command line.

    Args:
        args (argparse.Namespace): Parsed command line arguments.

    Returns:
        bool: True if a management command was handled and the program should
            exit, False if the run should continue.

    Raises:
        config_manager.ConfigError: If the config file cannot be read, or the
            named config is missing or invalid.
    """
    if args.config_options:
        print(config_manager.format_options_help())
        return True

    if args.new_config:
        try:
            config_manager.run_new_config_wizard()
        except (KeyboardInterrupt, EOFError):
            print("\nCancelled.")
        return True

    if args.remove_config:
        name = args.remove_config
        if not config_manager.config_exists(name):
            print(f"No config named '{name}'.")
            return True
        confirm = input(f"Remove config '{name}'? This cannot be undone. [y/N]: ").strip().lower()
        if confirm != "y":
            print("Cancelled.")
            return True
        was_default = config_manager.get_default_config() == name
        config_manager.remove_config(name)
        print(f"Removed config '{name}'.")
        if was_default:
            print("That was your default config. No default is set now — "
                  "pass -c/--config NAME explicitly or set a new default.")
        return True

    if args.set_default_config:
        name = args.set_default_config
        config_manager.set_default_config(name)
        print(f"Default config set to '{name}'.")
        return True

    if args.list_configs:
        names = config_manager.list_configs()
        default = config_manager.get_default_config()
        if not names:
            print("No stored configs. Run 'ereddicator --new-config' to create one.")
        else:
            print(f"Config file: {config_manager.get_config_path()}")
            print("Stored configs:")
            for name in names:
                print(f"  {name}" + ("  (default)" if name == default else ""))
        return True

    if args.show_config:
        name = args.config if args.config is not None else config_manager.get_default_config()
        data = config_manager.load_config(args.config)
        print(config_manager.format_config(name, data))
        return True

    if args.edit_config:
        path = config_manager.get_config_path()
        if not path.exists():
            print(f"No config file at {path}. Run 'ereddicator --new-config' to create one.")
            return True
        editor = os.environ.get("EDITOR") or os.environ.get("VISUAL") or "nano"
        try:
            subprocess.call([editor, str(path)])
        except OSError as e:
            print(f"Could not open '{editor}': {e}\nEdit {path} manually instead.")
            sys.exit(1)
        try:
            store = config_manager.load_store()
            for name in config_manager.list_configs():
                config_manager.validate_config(store[name], name)
        except config_manager.ConfigError as e:
            raise config_manager.ConfigError(f"The config file is not usable as saved:\n{e}") from e
        return True

    return False


def resolve_config(args: argparse.Namespace) -> dict:
    """
    Load and validate the stored config that applies to this run.

    Args:
        args (argparse.Namespace): Parsed command line arguments.

    Returns:
        dict: Validated options of the selected config, empty if no config
            applies to this run.

    Raises:
        SystemExit: If --no-config is combined with -c/--config.
        config_manager.ConfigError: If the selected config is missing or
            contains invalid options.
    """
    if args.no_config:
        if args.config:
            print("--no-config cannot be combined with -c/--config.")
            sys.exit(1)
        return {}

    name = args.config if args.config is not None else config_manager.get_default_config()
    if name is None:
        return {}

    validated = config_manager.validate_config(config_manager.load_config(name), name)
    print(f"Using config '{name}'.")
    return validated


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

    user_mgmt_group = user_group.add_mutually_exclusive_group()
    user_mgmt_group.add_argument(
        "--new-user", action="store_true",
        help="Interactively create (or overwrite) a stored user, then exit"
    )
    user_mgmt_group.add_argument(
        "--remove-user", metavar="NAME",
        help="Delete a stored user (with confirmation), then exit"
    )
    user_mgmt_group.add_argument(
        "--list-users", action="store_true",
        help="List stored user names and the current default, then exit"
    )
    user_mgmt_group.add_argument(
        "--set-default-user", metavar="NAME",
        help="Set an existing stored user as the default used when -u/--user is omitted, then exit"
    )

    config_group = parser.add_argument_group(
        "configuration",
        "Named configs are stored in a JSON config file and can set more options than the "
        "arguments above expose. Any argument given on the command line overrides the config. "
        "Which account to run against is not part of a config: use -u/--user."
    )
    config_group.add_argument(
        "-c", "--config", metavar="NAME",
        help="Name of the stored config to use for this run (defaults to the config marked as default)"
    )
    config_group.add_argument(
        "--no-config", action="store_true",
        help="Ignore the default config for this run"
    )

    config_mgmt_group = config_group.add_mutually_exclusive_group()
    config_mgmt_group.add_argument(
        "--new-config", action="store_true",
        help="Interactively create (or overwrite) a stored config, then exit"
    )
    config_mgmt_group.add_argument(
        "--remove-config", metavar="NAME",
        help="Delete a stored config (with confirmation), then exit"
    )
    config_mgmt_group.add_argument(
        "--list-configs", action="store_true",
        help="List stored config names and the current default, then exit"
    )
    config_mgmt_group.add_argument(
        "--set-default-config", metavar="NAME",
        help="Set an existing stored config as the default used when -c/--config is omitted, then exit"
    )
    config_mgmt_group.add_argument(
        "--show-config", action="store_true",
        help="Print the config selected by -c/--config (or the default one), then exit"
    )
    config_mgmt_group.add_argument(
        "--config-options", action="store_true",
        help="List every option a config can set, then exit"
    )
    config_mgmt_group.add_argument(
        "--edit-config", action="store_true",
        help="Open the config file in $EDITOR, then exit"
    )

    args = parser.parse_args()

    try:
        if handle_config_commands(args):
            return
    except config_manager.ConfigError as e:
        print(e)
        sys.exit(1)

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

    # Validate the config before authenticating, so a broken one is reported early.
    try:
        config_options = resolve_config(args)
    except config_manager.ConfigError as e:
        print(e)
        sys.exit(1)

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
    
    # Load user preferences: stored config first, then command line overrides.

    preferences = UserPreferences()
    config_manager.apply_config(preferences, config_options)

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

    # Whitelisting and blacklisting are mutually exclusive, so a list given on the
    # command line replaces both lists from the config rather than adding to them.
    if args.whitelist:
        preferences.whitelist_subreddits = args.whitelist
        preferences.blacklist_subreddits = []

    if args.blacklist:
        preferences.blacklist_subreddits = args.blacklist
        preferences.whitelist_subreddits = []

    # Execute content remover
    run_content_remover(preferences, reddit, auth)


if __name__ == "__main__":
    main()
