import getpass
import json
import os
from pathlib import Path
from typing import Dict, List, Optional

import platformdirs

from .oauth_handler import RedditOAuth

APP_NAME = "ereddicatorcli"
USERS_FILENAME = "users.json"
DEFAULT_KEY = "__default__"


class UserError(Exception):
    """Base class for all user-store errors."""


class UserNotFoundError(UserError):
    """No stored user exists under the given name."""


class NoDefaultUserError(UserError):
    """No name was given and no default user is set."""


def get_config_dir() -> Path:
    path = Path(platformdirs.user_config_dir(APP_NAME, appauthor=False))
    path.mkdir(parents=True, exist_ok=True)
    return path


def get_users_path() -> Path:
    return get_config_dir() / USERS_FILENAME


def get_data_dir() -> Path:
    path = Path(platformdirs.user_data_dir(APP_NAME, appauthor=False))
    path.mkdir(parents=True, exist_ok=True)
    return path


def load_store() -> Dict[str, dict]:
    path = get_users_path()
    if not path.exists():
        return {}
    try:
        with open(path, "r", encoding="utf-8") as f:
            store = json.load(f)
    except json.JSONDecodeError as e:
        raise UserError(f"User file at {path} is not valid JSON: {e}") from e
    if not isinstance(store, dict):
        raise UserError(f"User file at {path} does not contain a JSON object.")
    return store


def save_store(store: Dict[str, dict]) -> None:
    path = get_users_path()
    tmp_path = path.with_suffix(path.suffix + ".tmp")
    with open(tmp_path, "w", encoding="utf-8") as f:
        json.dump(store, f, indent=2)
    os.chmod(tmp_path, 0o600)
    os.replace(tmp_path, path)


def list_users() -> List[str]:
    return [name for name in load_store() if name != DEFAULT_KEY]


def user_exists(name: str) -> bool:
    return name in load_store()


def get_default_user() -> Optional[str]:
    return load_store().get(DEFAULT_KEY)


def set_default_user(name: str) -> None:
    store = load_store()
    if name not in store:
        raise UserNotFoundError(f"No stored user named '{name}'.")
    store[DEFAULT_KEY] = name
    save_store(store)


def load_user(name: Optional[str] = None) -> Dict[str, str]:
    store = load_store()
    resolved_name = name
    if resolved_name is None:
        resolved_name = store.get(DEFAULT_KEY)
        if resolved_name is None:
            raise NoDefaultUserError(
                "No user name was specified and no default user is set."
            )
    if resolved_name not in store or resolved_name == DEFAULT_KEY:
        raise UserNotFoundError(f"No stored user named '{resolved_name}'.")
    return dict(store[resolved_name])


def save_user(name: str, data: Dict[str, str], make_default: bool = False) -> None:
    store = load_store()
    had_none_stored = len([k for k in store if k != DEFAULT_KEY]) == 0
    store[name] = data
    if make_default or had_none_stored:
        store[DEFAULT_KEY] = name
    save_store(store)


def update_user_fields(name: str, **fields) -> None:
    store = load_store()
    if name not in store or name == DEFAULT_KEY:
        raise UserNotFoundError(f"No stored user named '{name}'.")
    store[name].update(fields)
    save_store(store)


def remove_user(name: str) -> None:
    store = load_store()
    if name not in store or name == DEFAULT_KEY:
        raise UserNotFoundError(f"No stored user named '{name}'.")
    del store[name]
    if store.get(DEFAULT_KEY) == name:
        del store[DEFAULT_KEY]
    save_store(store)


def _prompt_nonempty(prompt: str) -> str:
    while True:
        value = input(prompt).strip()
        if value:
            return value
        print("This field can't be empty.")


def run_new_user_wizard() -> str:
    print(f"Users are stored in: {get_users_path()}\n")

    print("Auth method:")
    print("  1) Traditional username/password")
    print("  2) OAuth (Google login or other non-password Reddit login)")
    method = ""
    while method not in ("1", "2"):
        method = input("Choose 1 or 2: ").strip()

    data: Dict[str, str] = {}

    if method == "1":
        name = _prompt_nonempty("Reddit username: ")
        data["username"] = name
        data["password"] = getpass.getpass("Reddit password: ")
        two_factor_code = input("Two-factor code (leave blank if not used): ").strip()
        data["two_factor_code"] = two_factor_code if two_factor_code else "None"

        data["client_id"] = _prompt_nonempty("Client ID: ")
        data["client_secret"] = _prompt_nonempty("Client Secret: ")
    else:
        client_id = _prompt_nonempty("Client ID: ")
        client_secret = _prompt_nonempty("Client Secret: ")
        data["client_id"] = client_id
        data["client_secret"] = client_secret

        print(
            "\nNo username/password needed for OAuth. A browser window will open to "
            "authorise this app. The stored user will be named after the Reddit "
            "username you authorise with."
        )
        try:
            oauth = RedditOAuth(client_id=client_id, client_secret=client_secret)
            name, refresh_token = oauth.perform_oauth_flow()
        except Exception as e:
            error_str = str(e).lower()
            if "401" in error_str or "unauthorized" in error_str:
                raise UserError(
                    "OAuth: Invalid client ID or client secret. Please double-check your Reddit API credentials."
                ) from e
            elif "timeout" in error_str or "did not receive" in error_str:
                raise UserError(
                    "OAuth: Timeout waiting for authorisation. Please try again and complete the "
                    "authorisation in your browser within 5 minutes."
                ) from e
            else:
                raise UserError(f"OAuth: {e}") from e
        data["username"] = name
        data["refresh_token"] = refresh_token
        print(f"Successfully authorised as {name}")

    if user_exists(name):
        confirm = input(f"A user named '{name}' already exists. Overwrite it? [y/N]: ").strip().lower()
        if confirm != "y":
            raise KeyboardInterrupt("Cancelled by user.")

    if get_default_user() is None:
        answer = input("No default user is set. Set this as the default? [Y/n]: ").strip().lower()
        make_default = answer != "n"
    else:
        make_default = False

    save_user(name, data, make_default=make_default)

    is_default = get_default_user() == name
    print(f"\nSaved user '{name}' to {get_users_path()}")
    print(f"Default: {'yes' if is_default else 'no'}")

    return name
