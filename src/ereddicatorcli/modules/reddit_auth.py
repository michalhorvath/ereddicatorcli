import os
import sys
import praw
from typing import Optional
from prawcore.exceptions import OAuthException, ResponseException
from .oauth_handler import RedditOAuth
from . import credentials_manager


class RedditAuth:
    """
    A class to handle Reddit authentication using PRAW.

    This class manages the reading of Reddit API credentials from a file or user input,
    and creates an authenticated Reddit instance.
    """

    def __init__(self, credentials_name: Optional[str] = None, user_agent: str = "ereddicatorcli") -> None:
        """
        Initialise the RedditAuth instance.

        Args:
            credentials_name (Optional[str]): Name of the stored credentials to use.
                Defaults to None, which resolves to the default credentials at read time.
            user_agent (str): User agent string for Reddit API. Defaults to "ereddicatorcli".
        """
        self.credentials_name = credentials_name
        self.user_agent = user_agent
        self.client_id = None
        self.client_secret = None
        self.username = None
        self.password = None
        self.two_factor_code = None
        self.refresh_token = None
        self.use_oauth = False

    def _read_credentials(self) -> None:
        """
        Read Reddit API credentials from the stored credentials.

        This method is called when Ereddicator is running as a Python script. It
        reads the credentials named by self.credentials_name, resolving it to the
        default credentials (and updating self.credentials_name in place) if none
        was specified.

        Raises:
            credentials_manager.CredentialsError: If no usable credentials are found.
        """
        creds = credentials_manager.load_credentials(self.credentials_name)
        if self.credentials_name is None:
            self.credentials_name = credentials_manager.get_default_credentials()

        self.client_id = creds["client_id"].strip()
        self.client_secret = creds["client_secret"].strip()

        # Check if we have a refresh token or plan to use OAuth
        if "refresh_token" in creds:
            self.refresh_token = creds["refresh_token"]
            self.use_oauth = True
            # Username might be stored if we've authenticated before
            if "username" in creds:
                self.username = creds["username"]
                print(f"Using stored refresh token for {self.username}")
            else:
                print("Refresh token found, will fetch username during authentication")
        # Check for OAuth mode without refresh token (first-time setup)
        elif "username" not in creds and "password" not in creds:
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
                credentials_manager.update_credentials_fields(
                    self.credentials_name,
                    username=self.username,
                    refresh_token=self.refresh_token,
                )

                print(f"Successfully authenticated as {self.username}")
                print(f"Refresh token saved to credentials '{self.credentials_name}'")
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
            self.username = creds["username"].strip()
            self.password = creds["password"].strip()
            self.two_factor_code = creds.get("two_factor_code", "None").strip()

    def get_reddit_instance(self) -> praw.Reddit:
        """
        Create and return an authenticated Reddit instance.

        This method reads the credentials if they haven't been set,
        creates a Reddit instance, and verifies the authentication. It
        will cause a SystemExit if any errors occur.

        Returns:
            praw.Reddit: An authenticated Reddit instance.

        Raises:
            credentials_manager.CredentialsError: If no usable credentials are found.
            OAuthException: If authentication fails due to OAuth issues.
            ResponseException: If there's an issue with the Reddit API response.
        """
        try:
            if not (self.client_id and self.client_secret and (self.username or self.refresh_token)):
                self._read_credentials()

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

        except credentials_manager.CredentialsError as e:
            error_msg = f"{e}\nRun 'python main.py --help' for credential management options."
            raise credentials_manager.CredentialsError(error_msg) from e
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
