import os
import sys
import praw
from typing import Optional
from prawcore.exceptions import OAuthException, ResponseException
from .oauth_handler import RedditOAuth
from . import user_manager


class RedditAuth:
    """
    A class to handle Reddit authentication using PRAW.

    This class manages the reading of Reddit API credentials for a stored user,
    and creates an authenticated Reddit instance.
    """

    def __init__(self, user: Optional[str] = None, user_agent: str = "ereddicatorcli") -> None:
        """
        Initialise the RedditAuth instance.

        Args:
            user (Optional[str]): Name of the stored user to use.
                Defaults to None, which resolves to the default user at read time.
            user_agent (str): User agent string for Reddit API. Defaults to "ereddicatorcli".
        """
        self.user = user
        self.user_agent = user_agent
        self.client_id = None
        self.client_secret = None
        self.username = None
        self.password = None
        self.two_factor_code = None
        self.refresh_token = None
        self.use_oauth = False

    def _read_user(self) -> None:
        """
        Read Reddit API credentials for the stored user.

        This method is called when Ereddicator is running as a Python script. It
        reads the credentials for the user named by self.user, resolving it to
        the default user (and updating self.user in place) if none was
        specified.

        Raises:
            user_manager.UserError: If no usable user is found.
        """
        data = user_manager.load_user(self.user)
        if self.user is None:
            self.user = user_manager.get_default_user()

        self.client_id = data["client_id"].strip()
        self.client_secret = data["client_secret"].strip()

        # Check if we have a refresh token or plan to use OAuth
        if "refresh_token" in data:
            self.refresh_token = data["refresh_token"]
            self.use_oauth = True
            # Username might be stored if we've authenticated before
            if "username" in data:
                self.username = data["username"]
                print(f"Using stored refresh token for {self.username}")
            else:
                print("Refresh token found, will fetch username during authentication")
        # Check for OAuth mode without refresh token (first-time setup)
        elif "username" not in data and "password" not in data:
            print("OAuth mode detected (no username/password provided)")
            self.use_oauth = True
            try:
                print("Starting OAuth authorization flow...")
                oauth = RedditOAuth(
                    client_id=self.client_id,
                    client_secret=self.client_secret,
                    user_agent=self.user_agent
                )
                self.username, self.refresh_token = oauth.perform_oauth_flow()

                # Save the refresh token for future use
                user_manager.update_user_fields(
                    self.user,
                    username=self.username,
                    refresh_token=self.refresh_token,
                )

                print(f"Successfully authenticated as {self.username}")
                print(f"Refresh token saved to user '{self.user}'")
            except Exception as e:
                error_str = str(e).lower()
                if "401" in error_str or "unauthorized" in error_str:
                    error_msg = "OAuth: Invalid client ID or client secret. Please double-check your Reddit API credentials."
                elif "timeout" in error_str or "did not receive" in error_str:
                    error_msg = "OAuth: Timeout waiting for authorisation. Please try again and complete the authorisation in your browser within 5 minutes."
                else:
                    error_msg = f"OAuth: {e}"
                raise Exception(error_msg)
        else:
            # Traditional username/password authentication
            self.username = data["username"].strip()
            self.password = data["password"].strip()
            self.two_factor_code = data.get("two_factor_code", "None").strip()

    def get_reddit_instance(self) -> praw.Reddit:
        """
        Create and return an authenticated Reddit instance.

        This method reads the stored user if it hasn't been set,
        creates a Reddit instance, and verifies the authentication. It
        will cause a SystemExit if any errors occur.

        Returns:
            praw.Reddit: An authenticated Reddit instance.

        Raises:
            user_manager.UserError: If no usable user is found.
            OAuthException: If authentication fails due to OAuth issues.
            ResponseException: If there's an issue with the Reddit API response.
        """
        try:
            if not (self.client_id and self.client_secret and (self.username or self.refresh_token)):
                self._read_user()

            print("Retrieving Reddit Authentication instance...")

            if self.use_oauth and self.refresh_token:
                reddit = praw.Reddit(
                    client_id=self.client_id,
                    client_secret=self.client_secret,
                    refresh_token=self.refresh_token,
                    user_agent=self.user_agent
                )
                # If username wasn't provided, get it from the API
                if not self.username:
                    self.username = reddit.user.me().name
            else:
                if self.two_factor_code and self.two_factor_code != "None":
                    self.two_factor_code = self.two_factor_code.replace(" ", "")
                    password = f"{self.password}:{self.two_factor_code}"
                else:
                    password = self.password

                reddit = praw.Reddit(
                    client_id=self.client_id,
                    client_secret=self.client_secret,
                    username=self.username,
                    password=password,
                    user_agent=self.user_agent
                )

            # Verify authentication worked
            reddit.user.me()

            if self.use_oauth:
                print(f"Successfully authenticated as {self.username} using OAuth.")
            else:
                print(f"Successfully authenticated as {self.username}.")

            return reddit

        except user_manager.UserError as e:
            error_msg = f"{e}\nRun 'ereddicator --help' for user management options."
            raise user_manager.UserError(error_msg) from e
        except (OAuthException, ResponseException) as e:
            error_str = str(e).lower()
            if "only script apps may use password auth" in error_str or "unauthorized_client" in error_str:
                error_msg = ("Wrong Reddit app type: You created a 'web app' but need a 'personal use script' app.\n"
                           "Please go to https://www.reddit.com/prefs/apps and create a new app:\n"
                           "1. Click 'Create App' or 'Create Another App'\n"
                           "2. Choose 'script' (not 'web app')\n"
                           "3. Set redirect URI to: http://localhost:8080")
            elif "401" in error_str or "unauthorized" in error_str:
                error_msg = "Invalid client ID, client secret, username, or password. Please double-check your Reddit API credentials."
            elif "403" in error_str or "forbidden" in error_str:
                error_msg = "Access forbidden. Your Reddit app might not have the required permissions."
            elif "two-factor" in error_str or "2fa" in error_str:
                error_msg = "Two-factor authentication required. Please enter your 2FA code."
            elif "invalid_grant" in error_str:
                error_msg = "Invalid username or password. Please double-check your Reddit login credentials. If you have two-factor authentication enabled also ensure your 2FA code is correct."
            else:
                error_msg = str(e)

            raise Exception(error_msg)
