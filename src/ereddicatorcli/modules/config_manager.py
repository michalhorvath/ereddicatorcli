import json
import os
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from .user_preferences import UserPreferences
from . import user_manager

CONFIG_FILENAME = "config.json"
DEFAULT_KEY = "__default__"


class ConfigError(Exception):
    """Base class for all config-store errors."""


class ConfigNotFoundError(ConfigError):
    """No stored config exists under the given name."""


class NoDefaultConfigError(ConfigError):
    """No name was given and no default config is set."""


class OptionError(ConfigError):
    """A config contains an unknown option or an invalid value."""


def _parse_bool(name: str, value: Any) -> bool:
    """
    Validate a boolean option value.

    Args:
        name (str): Name of the option being validated.
        value (Any): Raw value read from the config file.

    Returns:
        bool: The validated value.

    Raises:
        OptionError: If the value is not a JSON boolean.
    """
    if not isinstance(value, bool):
        raise OptionError(f"Option '{name}' must be true or false, got {value!r}.")
    return value


def _parse_optional_int(name: str, value: Any) -> Optional[int]:
    """
    Validate an integer option value that may also be null.

    Args:
        name (str): Name of the option being validated.
        value (Any): Raw value read from the config file.

    Returns:
        Optional[int]: The validated value, or None.

    Raises:
        OptionError: If the value is neither null nor a whole number.
    """
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int):
        raise OptionError(f"Option '{name}' must be a whole number or null, got {value!r}.")
    return value


def _parse_optional_str(name: str, value: Any) -> Optional[str]:
    """
    Validate a string option value that may also be null.

    Args:
        name (str): Name of the option being validated.
        value (Any): Raw value read from the config file.

    Returns:
        Optional[str]: The validated value, or None. Empty strings become None.

    Raises:
        OptionError: If the value is neither null nor a string.
    """
    if value is None:
        return None
    if not isinstance(value, str):
        raise OptionError(f"Option '{name}' must be text or null, got {value!r}.")
    value = value.strip()
    return value if value else None


def _parse_str_list(name: str, value: Any) -> List[str]:
    """
    Validate a list-of-strings option value.

    Args:
        name (str): Name of the option being validated.
        value (Any): Raw value read from the config file.

    Returns:
        List[str]: The validated list. Null becomes an empty list.

    Raises:
        OptionError: If the value is not a list of strings.
    """
    if value is None:
        return []
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        raise OptionError(f"Option '{name}' must be a list of subreddit names, got {value!r}.")
    return [item.strip() for item in value if item.strip()]


def _parse_optional_date(name: str, value: Any) -> Optional[datetime]:
    """
    Validate a date option value that may also be null.

    Accepts "YYYY-MM-DD" as well as any ISO 8601 date-time string.

    Args:
        name (str): Name of the option being validated.
        value (Any): Raw value read from the config file.

    Returns:
        Optional[datetime]: The parsed date, or None.

    Raises:
        OptionError: If the value is neither null nor a parsable date string.
    """
    if value is None:
        return None
    if not isinstance(value, str):
        raise OptionError(f"Option '{name}' must be a date string such as \"2024-01-31\" or null, got {value!r}.")
    text = value.strip()
    if not text:
        return None
    try:
        return datetime.fromisoformat(text)
    except ValueError as e:
        raise OptionError(
            f"Option '{name}' is not a valid date: {value!r}. Use \"YYYY-MM-DD\" or an ISO 8601 date-time."
        ) from e


def _parse_directory(name: str, value: Any) -> Optional[str]:
    """
    Validate a directory-path option value that may also be null.

    Args:
        name (str): Name of the option being validated.
        value (Any): Raw value read from the config file.

    Returns:
        Optional[str]: The expanded path, or None.

    Raises:
        OptionError: If the value is not null, not a string, or not an existing directory.
    """
    path = _parse_optional_str(name, value)
    if path is None:
        return None
    expanded = os.path.expanduser(path)
    if not os.path.isdir(expanded):
        raise OptionError(f"Option '{name}' points at {expanded}, which is not an existing directory.")
    return expanded


class Option:
    """
    Description of a single option that a config may set.

    Attributes:
        name (str): Key used in the JSON config file, matching the
            UserPreferences attribute it sets.
        parser (Callable): Function validating and converting a raw JSON value.
        default (Any): Value written into a freshly created config.
        description (str): One-line explanation shown by --config-options.
    """

    def __init__(self, name: str, parser: Callable, default: Any, description: str) -> None:
        self.name = name
        self.parser = parser
        self.default = default
        self.description = description

    def parse(self, value: Any) -> Any:
        """
        Validate and convert a raw JSON value for this option.

        Args:
            value (Any): Raw value read from the config file.

        Returns:
            Any: The validated value, in the type UserPreferences expects.

        Raises:
            OptionError: If the value is invalid for this option.
        """
        return self.parser(self.name, value)


OPTIONS: List[Option] = [
    Option("delete_comments", _parse_bool, False, "Edit comments, then delete them."),
    Option("delete_posts", _parse_bool, False, "Edit posts, then delete them."),
    Option("delete_without_edit_comments", _parse_bool, False, "Delete comments without editing them first."),
    Option("delete_without_edit_posts", _parse_bool, False, "Delete posts without editing them first."),
    Option("only_edit_comments", _parse_bool, False, "Edit comments without deleting them."),
    Option("only_edit_posts", _parse_bool, False, "Edit posts without deleting them."),
    Option("delete_saved", _parse_bool, False, "Unsave saved items."),
    Option("delete_upvotes", _parse_bool, False, "Remove upvotes."),
    Option("delete_downvotes", _parse_bool, False, "Remove downvotes."),
    Option("delete_hidden", _parse_bool, False, "Unhide hidden posts."),

    Option("preserve_gilded", _parse_bool, False, "Keep gilded comments and posts untouched."),
    Option("preserve_distinguished", _parse_bool, False, "Keep mod-distinguished comments and posts untouched."),
    Option("comment_karma_threshold", _parse_optional_int, None,
           "Keep comments whose karma is greater than or equal to this number. null processes all."),
    Option("post_karma_threshold", _parse_optional_int, None,
           "Keep posts whose karma is greater than or equal to this number. null processes all."),

    Option("whitelist_subreddits", _parse_str_list, [],
           "Subreddits to preserve (not process). Mutually exclusive with blacklist_subreddits."),
    Option("blacklist_subreddits", _parse_str_list, [],
           "Subreddits to exclusively process. Mutually exclusive with whitelist_subreddits."),

    Option("start_date", _parse_optional_date, None,
           "Ignore content created before this date, e.g. \"2024-01-31\". null means no lower bound."),
    Option("end_date", _parse_optional_date, None,
           "Ignore content created after this date, e.g. \"2024-12-31\". null means no upper bound."),

    Option("dry_run", _parse_bool, False, "Print what would happen without changing anything on Reddit."),
    Option("custom_replacement_text", _parse_optional_str, None,
           "Text to overwrite content with when editing. null uses random text."),
    Option("reddit_export_directory", _parse_directory, None,
           "Path to an extracted Reddit data export directory. null retrieves content via the API."),
]

OPTIONS_BY_NAME: Dict[str, Option] = {option.name: option for option in OPTIONS}


def get_config_path() -> Path:
    """
    Return the path of the JSON file holding all configs.

    Returns:
        Path: Path to config.json inside the application config directory.
    """
    return user_manager.get_config_dir() / CONFIG_FILENAME


def load_store() -> Dict[str, dict]:
    """
    Read the whole config file.

    Returns:
        Dict[str, dict]: Mapping of config name to its options, plus the
            "__default__" key naming the default config. Empty if no config
            file exists yet.

    Raises:
        ConfigError: If the file is not valid JSON or does not hold an object.
    """
    path = get_config_path()
    if not path.exists():
        return {}
    try:
        with open(path, "r", encoding="utf-8") as f:
            store = json.load(f)
    except json.JSONDecodeError as e:
        raise ConfigError(f"Config file at {path} is not valid JSON: {e}") from e
    if not isinstance(store, dict):
        raise ConfigError(f"Config file at {path} does not contain a JSON object.")
    return store


def save_store(store: Dict[str, dict]) -> None:
    """
    Write the whole config file atomically.

    Args:
        store (Dict[str, dict]): Mapping of config name to its options,
            optionally including the "__default__" key.
    """
    path = get_config_path()
    tmp_path = path.with_suffix(path.suffix + ".tmp")
    with open(tmp_path, "w", encoding="utf-8") as f:
        json.dump(store, f, indent=2)
    os.replace(tmp_path, path)


def list_configs() -> List[str]:
    """
    List the names of all stored configs.

    Returns:
        List[str]: Config names, excluding the internal default marker.
    """
    return [name for name in load_store() if name != DEFAULT_KEY]


def config_exists(name: str) -> bool:
    """
    Check whether a config is stored under the given name.

    Args:
        name (str): Config name to look for.

    Returns:
        bool: True if a config with that name exists.
    """
    return name != DEFAULT_KEY and name in load_store()


def get_default_config() -> Optional[str]:
    """
    Return the name of the config used when no config is named.

    Returns:
        Optional[str]: The default config name, or None if none is set.
    """
    return load_store().get(DEFAULT_KEY)


def set_default_config(name: str) -> None:
    """
    Mark an existing config as the default one.

    Args:
        name (str): Name of the config to make default.

    Raises:
        ConfigNotFoundError: If no config is stored under that name.
    """
    store = load_store()
    if name not in store or name == DEFAULT_KEY:
        raise ConfigNotFoundError(f"No config named '{name}'.")
    store[DEFAULT_KEY] = name
    save_store(store)


def load_config(name: Optional[str] = None) -> Dict[str, Any]:
    """
    Read the raw options of a config.

    Args:
        name (Optional[str]): Config name. Defaults to None, which resolves to
            the default config.

    Returns:
        Dict[str, Any]: The raw (unvalidated) options of the config.

    Raises:
        NoDefaultConfigError: If no name was given and no default is set.
        ConfigNotFoundError: If no config is stored under the resolved name.
        ConfigError: If the config is not a JSON object.
    """
    store = load_store()
    resolved_name = name
    if resolved_name is None:
        resolved_name = store.get(DEFAULT_KEY)
        if resolved_name is None:
            raise NoDefaultConfigError("No config name was specified and no default config is set.")
    if resolved_name not in store or resolved_name == DEFAULT_KEY:
        raise ConfigNotFoundError(f"No config named '{resolved_name}'.")
    data = store[resolved_name]
    if not isinstance(data, dict):
        raise ConfigError(f"Config '{resolved_name}' is not a JSON object.")
    return dict(data)


def save_config(name: str, data: Dict[str, Any], make_default: bool = False) -> None:
    """
    Store a config, replacing any config of the same name.

    The first config ever stored automatically becomes the default one.

    Args:
        name (str): Config name.
        data (Dict[str, Any]): Raw options to store.
        make_default (bool): Whether to mark this config as the default.
            Defaults to False.

    Raises:
        ConfigError: If the name is reserved.
    """
    if name == DEFAULT_KEY:
        raise ConfigError(f"'{DEFAULT_KEY}' is a reserved name and cannot be used for a config.")
    store = load_store()
    had_none_stored = len([key for key in store if key != DEFAULT_KEY]) == 0
    store[name] = data
    if make_default or had_none_stored:
        store[DEFAULT_KEY] = name
    save_store(store)


def remove_config(name: str) -> None:
    """
    Delete a stored config, clearing the default marker if it pointed at it.

    Args:
        name (str): Config name to delete.

    Raises:
        ConfigNotFoundError: If no config is stored under that name.
    """
    store = load_store()
    if name not in store or name == DEFAULT_KEY:
        raise ConfigNotFoundError(f"No config named '{name}'.")
    del store[name]
    if store.get(DEFAULT_KEY) == name:
        del store[DEFAULT_KEY]
    save_store(store)


def default_config_data() -> Dict[str, Any]:
    """
    Build a full set of options with every option at its default value.

    Returns:
        Dict[str, Any]: JSON-serialisable options ready to be written and edited.
    """
    return {option.name: option.default for option in OPTIONS}


def validate_config(data: Dict[str, Any], config_name: Optional[str] = None) -> Dict[str, Any]:
    """
    Validate a config's raw options and convert them to usable Python values.

    Only the options actually present in the config are returned, so that
    options a config leaves out keep their built-in defaults and can still be
    set by command line arguments.

    Args:
        data (Dict[str, Any]): Raw options read from the config file.
        config_name (Optional[str]): Config name, used in error messages.
            Defaults to None.

    Returns:
        Dict[str, Any]: Mapping of option name to validated value.

    Raises:
        OptionError: If an option is unknown, has an invalid value, or conflicts
            with another option.
    """
    where = f" in config '{config_name}'" if config_name else ""

    unknown = [key for key in data if key not in OPTIONS_BY_NAME]
    if unknown:
        raise OptionError(
            f"Unknown option{'s' if len(unknown) > 1 else ''}{where}: {', '.join(sorted(unknown))}.\n"
            "Run 'ereddicator --config-options' to see the supported options."
        )

    validated: Dict[str, Any] = {}
    for key, value in data.items():
        try:
            validated[key] = OPTIONS_BY_NAME[key].parse(value)
        except OptionError as e:
            raise OptionError(f"{e}{(' Found' + where + '.') if where else ''}") from e

    if validated.get("whitelist_subreddits") and validated.get("blacklist_subreddits"):
        raise OptionError(f"whitelist_subreddits and blacklist_subreddits cannot both be set{where}.")

    start_date = validated.get("start_date")
    end_date = validated.get("end_date")
    if start_date and end_date and start_date > end_date:
        raise OptionError(f"start_date must not be later than end_date{where}.")

    return validated


def apply_config(preferences: UserPreferences, validated: Dict[str, Any]) -> None:
    """
    Copy validated config options onto a UserPreferences instance.

    Args:
        preferences (UserPreferences): Preferences to update in place.
        validated (Dict[str, Any]): Options as returned by validate_config.
    """
    for key, value in validated.items():
        setattr(preferences, key, value)


def format_options_help() -> str:
    """
    Build the human-readable listing of every supported option.

    Returns:
        str: One line per option, giving its name, default and description.
    """
    lines = [f"Config file: {get_config_path()}", "", "Supported options:"]
    width = max(len(option.name) for option in OPTIONS)
    for option in OPTIONS:
        default = json.dumps(option.default)
        lines.append(f"  {option.name.ljust(width)}  (default {default})  {option.description}")
    return "\n".join(lines)


def format_config(name: str, data: Dict[str, Any]) -> str:
    """
    Render a stored config as pretty-printed JSON.

    Args:
        name (str): Config name.
        data (Dict[str, Any]): Raw options of the config.

    Returns:
        str: A heading followed by the config's JSON body.
    """
    marker = "  (default)" if get_default_config() == name else ""
    return f"Config '{name}'{marker}:\n{json.dumps(data, indent=2)}"


def _prompt_nonempty(prompt: str) -> str:
    """
    Ask for a value until a non-empty one is given.

    Args:
        prompt (str): Text shown to the user.

    Returns:
        str: The stripped, non-empty answer.
    """
    while True:
        value = input(prompt).strip()
        if value:
            return value
        print("This field can't be empty.")


def _prompt_bool(prompt: str, default: bool = False) -> bool:
    """
    Ask a yes/no question.

    Args:
        prompt (str): Question shown to the user, without the answer hint.
        default (bool): Answer used when the user just presses Enter.
            Defaults to False.

    Returns:
        bool: The chosen answer.
    """
    hint = "[Y/n]" if default else "[y/N]"
    while True:
        answer = input(f"{prompt} {hint}: ").strip().lower()
        if not answer:
            return default
        if answer in ("y", "yes"):
            return True
        if answer in ("n", "no"):
            return False
        print("Please answer y or n.")


def _prompt_choice(prompt: str, choices: List[str], default: int = 1) -> int:
    """
    Ask the user to pick one of several numbered choices.

    Args:
        prompt (str): Heading shown above the choices.
        choices (List[str]): Labels, listed as 1..len(choices).
        default (int): Choice used when the user just presses Enter.
            Defaults to 1.

    Returns:
        int: The 1-based number of the chosen entry.
    """
    print(prompt)
    for number, label in enumerate(choices, start=1):
        print(f"  {number}) {label}")
    while True:
        answer = input(f"Choose 1-{len(choices)} [{default}]: ").strip()
        if not answer:
            return default
        if answer.isdigit() and 1 <= int(answer) <= len(choices):
            return int(answer)
        print(f"Please enter a number between 1 and {len(choices)}.")


def _prompt_option(name: str, prompt: str, empty_value: Any = None) -> Any:
    """
    Ask for a value for one option, re-prompting until it validates.

    Typed text is first converted to the JSON type the option expects (a number
    for karma thresholds, a list for subreddits), then checked with the option's
    own parser, so the wizard accepts exactly what the config file accepts.

    Args:
        name (str): Option name, used for conversion, validation and messages.
        prompt (str): Text shown to the user.
        empty_value (Any): Raw value used when the user just presses Enter.
            Defaults to None.

    Returns:
        Any: A JSON-serialisable value for the option.
    """
    option = OPTIONS_BY_NAME[name]
    while True:
        answer = input(prompt).strip()
        if not answer:
            raw = empty_value
        elif option.parser is _parse_optional_int:
            try:
                raw = int(answer)
            except ValueError:
                print("Please enter a whole number, or leave it blank.")
                continue
        elif option.parser is _parse_str_list:
            raw = answer.replace(",", " ").split()
        else:
            raw = answer
        try:
            option.parse(raw)
        except OptionError as e:
            print(e)
            continue
        return raw


def _wizard_content_mode(item_type: str, data: Dict[str, Any]) -> None:
    """
    Ask how one kind of content should be handled and record the answer.

    The three mutually exclusive handling flags for the given content type are
    always written, so exactly one of them can end up true.

    Args:
        item_type (str): Either "comments" or "posts".
        data (Dict[str, Any]): Options being built, updated in place.
    """
    choice = _prompt_choice(
        f"\nHow should your {item_type} be handled?",
        [
            f"Leave {item_type} alone",
            f"Edit {item_type} only, without deleting (recommended)",
            f"Edit {item_type}, then delete them",
            f"Delete {item_type} without editing them first",
        ],
    )
    data[f"only_edit_{item_type}"] = choice == 2
    data[f"delete_{item_type}"] = choice == 3
    data[f"delete_without_edit_{item_type}"] = choice == 4


def run_new_config_wizard() -> str:
    """
    Interactively create (or overwrite) a stored config.

    The user is asked for a name and then for every option, with the option's
    default offered on an empty answer. The finished config is written with all
    options present, so it is easy to adjust later by hand. Which Reddit account
    to run against is not part of a config: it is chosen separately with
    -u/--user or by the default stored user.

    Returns:
        str: The name of the config that was saved.

    Raises:
        KeyboardInterrupt: If the user declines to overwrite an existing config.
        ConfigError: If the config file cannot be read or written.
    """
    print(f"Configs are stored in: {get_config_path()}\n")
    print("Press Enter at any prompt to accept the default shown in brackets.\n")

    name = _prompt_nonempty("Config name: ")
    while name == DEFAULT_KEY:
        print(f"'{DEFAULT_KEY}' is a reserved name.")
        name = _prompt_nonempty("Config name: ")
    if config_exists(name):
        confirm = input(f"A config named '{name}' already exists. Overwrite it? [y/N]: ").strip().lower()
        if confirm != "y":
            raise KeyboardInterrupt("Cancelled by user.")

    data: Dict[str, Any] = {}

    print("\n--- Content to process ---")
    _wizard_content_mode("comments", data)
    _wizard_content_mode("posts", data)

    print()
    data["delete_saved"] = _prompt_bool("Unsave your saved items?")
    data["delete_upvotes"] = _prompt_bool("Remove your upvotes?")
    data["delete_downvotes"] = _prompt_bool("Remove your downvotes?")
    data["delete_hidden"] = _prompt_bool("Unhide your hidden posts?")

    print("\n--- What to keep ---")
    data["preserve_gilded"] = _prompt_bool("Keep gilded content untouched?")
    data["preserve_distinguished"] = _prompt_bool("Keep mod-distinguished content untouched?")
    data["comment_karma_threshold"] = _prompt_option(
        "comment_karma_threshold", "Keep comments with at least this much karma (blank for none): "
    )
    data["post_karma_threshold"] = _prompt_option(
        "post_karma_threshold", "Keep posts with at least this much karma (blank for none): "
    )

    print()
    subreddit_choice = _prompt_choice(
        "Filter by subreddit?",
        [
            "No filter — process every subreddit",
            "Whitelist — preserve the listed subreddits, process everything else",
            "Blacklist — process only the listed subreddits",
        ],
    )
    data["whitelist_subreddits"] = []
    data["blacklist_subreddits"] = []
    if subreddit_choice == 2:
        data["whitelist_subreddits"] = _prompt_option(
            "whitelist_subreddits", "Subreddits to preserve (separated by spaces): ", empty_value=[]
        )
    elif subreddit_choice == 3:
        data["blacklist_subreddits"] = _prompt_option(
            "blacklist_subreddits", "Subreddits to process (separated by spaces): ", empty_value=[]
        )

    print()
    while True:
        data["start_date"] = _prompt_option(
            "start_date", "Ignore content created before this date, YYYY-MM-DD (blank for none): "
        )
        data["end_date"] = _prompt_option(
            "end_date", "Ignore content created after this date, YYYY-MM-DD (blank for none): "
        )
        try:
            validate_config(data)
            break
        except OptionError as e:
            print(f"{e}\nPlease enter the date range again.")

    print("\n--- How to process it ---")
    data["custom_replacement_text"] = _prompt_option(
        "custom_replacement_text", "Text to overwrite content with (blank for random text): "
    )
    data["reddit_export_directory"] = _prompt_option(
        "reddit_export_directory", "Reddit data export directory (blank to use the Reddit API): "
    )
    data["dry_run"] = _prompt_bool(
        "Dry run — only print what would happen, without changing anything on Reddit?"
    )

    if get_default_config() is None:
        make_default = _prompt_bool("\nNo default config is set. Make this the default?", default=True)
    else:
        make_default = _prompt_bool(
            f"\nThe default config is '{get_default_config()}'. Make this the default instead?"
        )

    save_config(name, data, make_default=make_default)

    print(f"\nSaved config '{name}' to {get_config_path()}")
    print(f"Default: {'yes' if get_default_config() == name else 'no'}")
    print(f"Run it with: ereddicator -c {name}")

    return name
