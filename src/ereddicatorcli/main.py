import argparse
import os
import signal
import subprocess
import sys
import threading
import time
from typing import Dict, List, Optional, Tuple
import praw
from .modules.reddit_auth import RedditAuth
from .modules.reddit_content_remover import RedditContentRemover
from .modules.user_preferences import UserPreferences
from .modules import config_manager, run_summary, user_manager


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


CONTENT_TYPES: Tuple[Tuple[str, str], ...] = (("comments", "comment"), ("posts", "post"))

MODES: Tuple[str, ...] = ("delete", "delete_only", "edit_only")


def _flag_name(attribute: str) -> str:
    """
    Render the command line spelling of a flag from its argparse attribute name.

    Args:
        attribute (str): Attribute name, such as "post_delete_only".

    Returns:
        str: The flag as typed, such as "--post-delete-only".
    """
    return "--" + attribute.replace("_", "-")


def _apply_content_mode(preferences: UserPreferences, item_type: str, mode: str) -> None:
    """
    Set the three mutually exclusive handling flags for one kind of content.

    Args:
        preferences (UserPreferences): Preferences to update in place.
        item_type (str): Either "comments" or "posts".
        mode (str): One of "delete" (edit, then delete), "delete_only" (delete
            without editing first) or "edit_only" (edit without deleting).
    """
    setattr(preferences, f"delete_{item_type}", mode == "delete")
    setattr(preferences, f"delete_without_edit_{item_type}", mode == "delete_only")
    setattr(preferences, f"only_edit_{item_type}", mode == "edit_only")


def resolve_content_modes(args: argparse.Namespace) -> Dict[str, Optional[str]]:
    """
    Work out which handling mode was asked for per kind of content.

    The unprefixed flags set both kinds at once, while the --comment-* and
    --post-* flags set one kind each and can be combined with each other. Mixing
    an unprefixed flag with a prefixed one is contradictory and rejected.

    Args:
        args (argparse.Namespace): Parsed command line arguments.

    Returns:
        Dict[str, Optional[str]]: Mode per content type, None where the command
            line asked for nothing and the config decides.

    Raises:
        SystemExit: If a flag for both kinds is combined with a per-kind flag.
    """
    both = next((mode for mode in MODES if getattr(args, mode)), None)
    per_type = {
        item_type: next((mode for mode in MODES if getattr(args, f"{prefix}_{mode}")), None)
        for item_type, prefix in CONTENT_TYPES
    }

    if both and any(per_type.values()):
        prefixed = []
        for item_type, prefix in CONTENT_TYPES:
            if per_type[item_type]:
                prefixed.append(_flag_name(f"{prefix}_{per_type[item_type]}"))
        print(f"{_flag_name(both)} already covers both comments and posts, so it cannot be "
              f"combined with {', '.join(prefixed)}.\n"
              "Use only the --comment-* and --post-* flags to handle the two differently.")
        sys.exit(1)

    return {item_type: per_type[item_type] or both for item_type, _ in CONTENT_TYPES}


def _merge_subreddits(existing: List[str], added: List[str]) -> List[str]:
    """
    Add subreddits to a list, keeping the order and ignoring case-insensitive duplicates.

    Args:
        existing (List[str]): Subreddits already on the list.
        added (List[str]): Subreddits to add.

    Returns:
        List[str]: The merged list.
    """
    merged = list(existing)
    seen = {sub.lower() for sub in merged}
    for sub in added:
        if sub.lower() not in seen:
            seen.add(sub.lower())
            merged.append(sub)
    return merged


def _split_subreddits(existing: List[str], removed: List[str]) -> Tuple[List[str], List[str]]:
    """
    Split a list of subreddits into the ones to keep and the ones to drop.

    Args:
        existing (List[str]): Subreddits currently on the list.
        removed (List[str]): Subreddits to drop, matched without regard to case.

    Returns:
        Tuple[List[str], List[str]]: The kept subreddits and the dropped ones,
            spelled as they were on the original list.
    """
    drop = {sub.lower() for sub in removed}
    kept = [sub for sub in existing if sub.lower() not in drop]
    dropped = [sub for sub in existing if sub.lower() in drop]
    return kept, dropped


def apply_subreddit_filters(preferences: UserPreferences, args: argparse.Namespace) -> None:
    """
    Apply the subreddit filter given on the command line to the config's lists.

    Whitelisting and blacklisting are mutually exclusive, so --whitelist and
    --blacklist replace both lists. The --add-* flags instead build on whatever
    the config set: adding to the list already in use, or, when the config uses
    the opposite list, removing the named subreddits from it. Dropping a
    subreddit from a blacklist stops it being processed, which is what
    whitelisting it means, and dropping one from a whitelist starts it being
    processed, which is what blacklisting it means.

    Args:
        preferences (UserPreferences): Preferences holding the config's lists,
            updated in place.
        args (argparse.Namespace): Parsed command line arguments.

    Raises:
        SystemExit: If --add-whitelist would empty the config's blacklist,
            leaving no subreddit to process.
    """
    if args.whitelist:
        preferences.whitelist_subreddits = _merge_subreddits([], args.whitelist)
        preferences.blacklist_subreddits = []
    elif args.blacklist:
        preferences.blacklist_subreddits = _merge_subreddits([], args.blacklist)
        preferences.whitelist_subreddits = []
    elif args.add_whitelist:
        if preferences.blacklist_subreddits:
            kept, dropped = _split_subreddits(preferences.blacklist_subreddits, args.add_whitelist)
            if not kept:
                print("--add-whitelist would remove every subreddit from the config's blacklist, "
                      "leaving nothing to process.\nPass --whitelist to replace the lists instead.")
                sys.exit(1)
            if dropped:
                print(f"The config uses a blacklist, so --add-whitelist removes "
                      f"{', '.join(dropped)} from it.")
            preferences.blacklist_subreddits = kept
        else:
            preferences.whitelist_subreddits = _merge_subreddits(
                preferences.whitelist_subreddits, args.add_whitelist
            )
    elif args.add_blacklist:
        if preferences.whitelist_subreddits:
            kept, dropped = _split_subreddits(preferences.whitelist_subreddits, args.add_blacklist)
            if dropped:
                print(f"The config uses a whitelist, so --add-blacklist removes "
                      f"{', '.join(dropped)} from it.")
            if not kept:
                print("The whitelist is now empty, so every subreddit will be processed.")
            preferences.whitelist_subreddits = kept
        else:
            preferences.blacklist_subreddits = _merge_subreddits(
                preferences.blacklist_subreddits, args.add_blacklist
            )


def build_preferences(args: argparse.Namespace, config_options: dict) -> UserPreferences:
    """
    Build the preferences for a run from the stored config and command line.

    The config is applied first and any argument given on the command line
    overrides it.

    Args:
        args (argparse.Namespace): Parsed command line arguments.
        config_options (dict): Validated options of the config that applies to
            this run, as returned by resolve_config.

    Returns:
        UserPreferences: The preferences the run will use.

    Raises:
        SystemExit: If the modifier flags given contradict each other.
    """
    preferences = UserPreferences()
    config_manager.apply_config(preferences, config_options)

    for item_type, mode in resolve_content_modes(args).items():
        if mode:
            _apply_content_mode(preferences, item_type, mode)

    if args.dry_run:
        preferences.dry_run = True
    elif args.no_dry_run:
        preferences.dry_run = False

    apply_subreddit_filters(preferences, args)

    return preferences


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


def resolve_config(args: argparse.Namespace) -> Tuple[Optional[str], dict]:
    """
    Load and validate the stored config that applies to this run.

    Args:
        args (argparse.Namespace): Parsed command line arguments.

    Returns:
        Tuple[Optional[str], dict]: Name of the selected config and its
            validated options. The name is None and the options are empty if no
            config applies to this run.

    Raises:
        SystemExit: If --no-config is combined with -c/--config.
        config_manager.ConfigError: If the selected config is missing or
            contains invalid options.
    """
    if args.no_config:
        if args.config:
            print("--no-config cannot be combined with -c/--config.")
            sys.exit(1)
        return None, {}

    name = args.config if args.config is not None else config_manager.get_default_config()
    if name is None:
        return None, {}

    validated = config_manager.validate_config(config_manager.load_config(name), name)
    print(f"Using config '{name}'.")
    return name, validated


def main():
    # Parse arguments
    parser = argparse.ArgumentParser(prog="ereddicator", description="EreddicatorCLI")
    
    parser.add_argument(
        "-y", "--yes", action="store_true",
        help="Skip the summary confirmation prompt and start the run immediately"
    )

    modifier_group = parser.add_argument_group(
        "modifiers",
        "Override how this run treats your content. The unprefixed handling flags cover both "
        "comments and posts, while the --comment-* and --post-* flags cover one kind each and "
        "may be combined with each other."
    )

    action_group = modifier_group.add_mutually_exclusive_group()
    action_group.add_argument("--delete", action="store_true",
                              help="Edit comments and posts, then delete them")
    action_group.add_argument("--delete-only", action="store_true",
                              help="Delete comments and posts without editing them first")
    action_group.add_argument("--edit-only", action="store_true",
                              help="Edit comments and posts without deleting them")

    comment_group = modifier_group.add_mutually_exclusive_group()
    comment_group.add_argument("--comment-delete", action="store_true",
                               help="Edit comments, then delete them")
    comment_group.add_argument("--comment-delete-only", action="store_true",
                               help="Delete comments without editing them first")
    comment_group.add_argument("--comment-edit-only", action="store_true",
                               help="Edit comments without deleting them")

    post_group = modifier_group.add_mutually_exclusive_group()
    post_group.add_argument("--post-delete", action="store_true",
                            help="Edit posts, then delete them")
    post_group.add_argument("--post-delete-only", action="store_true",
                            help="Delete posts without editing them first")
    post_group.add_argument("--post-edit-only", action="store_true",
                            help="Edit posts without deleting them")

    dry_run_group = modifier_group.add_mutually_exclusive_group()
    dry_run_group.add_argument("--dry-run", action="store_true",
                               help="Enable dry run mode (no actual changes made)")
    dry_run_group.add_argument("--no-dry-run", action="store_true",
                               help="Disable dry run mode enabled by the config (changes are made for real)")

    list_group = modifier_group.add_mutually_exclusive_group()
    list_group.add_argument("--whitelist", nargs="+", metavar="SUBREDDIT",
                            help="Subreddits to preserve (not process), replacing the config's lists")
    list_group.add_argument("--add-whitelist", nargs="+", metavar="SUBREDDIT",
                            help="Also preserve these subreddits: added to the config's whitelist, "
                                 "or removed from its blacklist")
    list_group.add_argument("--blacklist", nargs="+", metavar="SUBREDDIT",
                            help="Subreddits to exclusively process, replacing the config's lists")
    list_group.add_argument("--add-blacklist", nargs="+", metavar="SUBREDDIT",
                            help="Also process these subreddits: added to the config's blacklist, "
                                 "or removed from its whitelist")

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
        config_name, config_options = resolve_config(args)
    except config_manager.ConfigError as e:
        print(e)
        sys.exit(1)

    # Load user preferences: stored config first, then command line overrides.
    preferences = build_preferences(args, config_options)

    if not preferences.any_selected():
        print("No content types selected for deletion or editing. Exiting.")
        return

    # Read the account out of the user store, so the run can be summarised and
    # confirmed before authenticating.
    try:
        user_name, reddit_username = run_summary.resolve_account(args.user)
    except user_manager.UserError as e:
        print(f"{e}\nRun 'ereddicator --help' for user management options.")
        sys.exit(1)

    summary = run_summary.format_run_summary(preferences, user_name, reddit_username, config_name)
    if not run_summary.confirm_run(summary, args.yes):
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

    # Execute content remover
    run_content_remover(preferences, reddit, auth)


if __name__ == "__main__":
    main()
