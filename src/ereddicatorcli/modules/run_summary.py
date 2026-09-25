from datetime import datetime
from typing import List, Optional, Tuple

from .user_preferences import UserPreferences
from . import user_manager


def resolve_account(user: Optional[str] = None) -> Tuple[str, Optional[str]]:
    """
    Work out which stored user, and which Reddit account, a run will use.

    This only reads the user store, so the account can be shown before any
    authentication happens.

    Args:
        user (Optional[str]): Name of the stored user given on the command line.
            Defaults to None, which resolves to the default stored user.

    Returns:
        Tuple[str, Optional[str]]: Name of the stored user, and the Reddit
            username it holds. The username is None for an OAuth user that has
            not been authorised yet, as Reddit only reveals it during
            authorisation.

    Raises:
        user_manager.UserError: If the named user does not exist, or if no name
            was given and no default user is set.
    """
    data = user_manager.load_user(user)
    name = user if user is not None else user_manager.get_default_user()
    username = data.get("username")
    return name, username.strip() if username else None


def _format_date(value: datetime) -> str:
    """
    Render a date for the run summary, dropping a midnight time component.

    Args:
        value (datetime): Date to render.

    Returns:
        str: The date as "YYYY-MM-DD", with a time appended if it is not midnight.
    """
    if (value.hour, value.minute, value.second) == (0, 0, 0):
        return value.strftime("%Y-%m-%d")
    return value.strftime("%Y-%m-%d %H:%M:%S")


def _describe_content_mode(preferences: UserPreferences, item_type: str) -> str:
    """
    Describe how one kind of content will be handled.

    The flags are read in the same order of precedence the content remover
    applies them, so the summary matches what will actually happen even if a
    hand-edited config sets more than one of them.

    Args:
        preferences (UserPreferences): Preferences for this run.
        item_type (str): Either "comments" or "posts".

    Returns:
        str: A short description of the handling method.
    """
    if getattr(preferences, f"delete_without_edit_{item_type}"):
        return "delete without editing first"
    if getattr(preferences, f"only_edit_{item_type}"):
        return "edit only, without deleting"
    if getattr(preferences, f"delete_{item_type}"):
        return "edit, then delete"
    return "leave alone"


def _describe_preserved(preferences: UserPreferences) -> str:
    """
    Describe which content is kept untouched regardless of the other settings.

    Args:
        preferences (UserPreferences): Preferences for this run.

    Returns:
        str: A comma-separated list, or a note that nothing is preserved.
    """
    preserved = []
    if preferences.preserve_gilded:
        preserved.append("gilded content")
    if preferences.preserve_distinguished:
        preserved.append("mod-distinguished content")
    return ", ".join(preserved) if preserved else "nothing in particular"


def _describe_thresholds(preferences: UserPreferences) -> str:
    """
    Describe the karma thresholds that spare highly-rated content.

    Args:
        preferences (UserPreferences): Preferences for this run.

    Returns:
        str: One clause per threshold that is set, or "none".
    """
    thresholds = []
    if preferences.comment_karma_threshold is not None:
        thresholds.append(f"keep comments with karma >= {preferences.comment_karma_threshold}")
    if preferences.post_karma_threshold is not None:
        thresholds.append(f"keep posts with karma >= {preferences.post_karma_threshold}")
    return "; ".join(thresholds) if thresholds else "none"


def _describe_subreddits(preferences: UserPreferences) -> str:
    """
    Describe the subreddit filter that applies to the run.

    Args:
        preferences (UserPreferences): Preferences for this run.

    Returns:
        str: The active list and how it is used, or a note that no filter applies.
    """
    if preferences.whitelist_subreddits:
        return "preserve (whitelist): " + ", ".join(preferences.whitelist_subreddits)
    if preferences.blacklist_subreddits:
        return "process only (blacklist): " + ", ".join(preferences.blacklist_subreddits)
    return "all subreddits"


def _describe_date_range(preferences: UserPreferences) -> str:
    """
    Describe the date range content must fall in to be processed.

    Args:
        preferences (UserPreferences): Preferences for this run.

    Returns:
        str: The bounded range, the single bound that is set, or "any date".
    """
    start, end = preferences.start_date, preferences.end_date
    if start and end:
        return f"{_format_date(start)} to {_format_date(end)}"
    if start:
        return f"from {_format_date(start)} onwards"
    if end:
        return f"up to {_format_date(end)}"
    return "any date"


def format_run_summary(preferences: UserPreferences, user_name: str,
                       reddit_username: Optional[str], config_name: Optional[str]) -> str:
    """
    Build the summary of the account and settings a run will use.

    Args:
        preferences (UserPreferences): Fully resolved preferences for this run,
            with command line overrides already applied.
        user_name (str): Name of the stored user the run will authenticate as.
        reddit_username (Optional[str]): Reddit username held by that stored
            user, or None if it is not known before authorisation.
        config_name (Optional[str]): Name of the stored config in use, or None
            if the run is not using one.

    Returns:
        str: A boxed, multi-line summary ready to print.
    """
    rows: List[Optional[Tuple[str, str]]] = [
        ("Reddit account", f"u/{reddit_username}" if reddit_username
            else "not known yet - will be confirmed during OAuth authorisation"),
        ("Stored user", user_name),
        ("Config", config_name if config_name else "none"),
        None,
        ("Comments", _describe_content_mode(preferences, "comments")),
        ("Posts", _describe_content_mode(preferences, "posts")),
        ("Saved items", "unsave" if preferences.delete_saved else "leave alone"),
        ("Upvotes", "remove" if preferences.delete_upvotes else "leave alone"),
        ("Downvotes", "remove" if preferences.delete_downvotes else "leave alone"),
        ("Hidden posts", "unhide" if preferences.delete_hidden else "leave alone"),
        None,
        ("Preserve", _describe_preserved(preferences)),
        ("Karma thresholds", _describe_thresholds(preferences)),
        ("Subreddits", _describe_subreddits(preferences)),
        ("Date range", _describe_date_range(preferences)),
        ("Replacement text", f'"{preferences.custom_replacement_text}"'
            if preferences.custom_replacement_text else "random text"),
        ("Content source", preferences.reddit_export_directory
            if preferences.reddit_export_directory else "Reddit API"),
        ("Dry run", "yes - nothing on Reddit will be changed" if preferences.dry_run
            else "no - changes are permanent and cannot be undone"),
    ]

    width = max(len(row[0]) for row in rows if row)
    body = [f"  {row[0].ljust(width)}  {row[1]}" if row else "" for row in rows]
    rule = "=" * max(len(line) for line in body)

    return "\n".join(["", rule, "  ABOUT TO RUN EREDDICATOR", rule, *body, rule])


def confirm_run(summary: str, assume_yes: bool = False) -> bool:
    """
    Show the run summary and ask the user to confirm it.

    Args:
        summary (str): Summary to display, as built by format_run_summary.
        assume_yes (bool): Whether -y/--yes was given, skipping the question.
            Defaults to False.

    Returns:
        bool: True if the run should go ahead, False if the user declined.
    """
    print(summary)

    if assume_yes:
        print("\nConfirmation skipped (-y/--yes). Starting...")
        return True

    try:
        answer = input("\nProceed with these settings? [y/N]: ").strip().lower()
    except (KeyboardInterrupt, EOFError):
        print("\nCancelled. Nothing was changed.")
        return False

    if answer in ("y", "yes"):
        return True

    print("Cancelled. Nothing was changed.")
    return False
