from typing import TYPE_CHECKING, NamedTuple, cast

import botocore.config
from awscli.customizations.configure.sso import (
    ConfigureSSOCommand,
    profile_to_section,
)
from awscli.customizations.sso.utils import (
    LOGIN_ARGS,
    PrintOnlyHandler,
    do_sso_login,
)
from awscli.customizations.utils import uni_print
from botocore import UNSIGNED
from prompt_toolkit.validation import ValidationError, Validator

if TYPE_CHECKING:
    from argparse import Namespace
    from typing import Literal, NoReturn

    from awscli.commands import CLICommand
    from botocore.hooks import HierarchicalEmitter
    from botocore.session import Session
    from prompt_toolkit.document import Document


def awscli_initialize(event_hooks: "HierarchicalEmitter") -> None:
    """Part of the Botocore Hooks Interface used by AWS CLI

    Parameters
    ----------
    event_hooks : HierarchicalEmitter
        Botocore hooks
    """

    # Inject our handler for `aws configure`
    event_hooks.register(
        event_name="building-command-table.configure", handler=_inject_commands
    )


def _inject_commands(
    command_table: dict[str, "CLICommand"],
    session: "Session",
    **kwargs,  # noqa: ANN003
) -> None:
    """Inject our commands in to `aws configure`

    Parameters
    ----------
    command_table : _type_
        _description_
    session : _type_
        _description_
    """
    command_table["sso-profiles"] = ConfigureSSOProfiles(session)


class ConfigureSSOProfiles(ConfigureSSOCommand):
    NAME = "sso-profiles"
    SYNOPSIS = "aws configure sso-profiles"
    DESCRIPTION = (
        "Generate AWS CLI Profiles from AWS SSO Session Accounts and Roles. \n\n"
        "This will interactively prompt the user for the SSO Session (previously "
        "created with `aws configure sso` or `aws configure sso-session`) and "
        "default CLI Region for the Profiles. "
        "These can also be supplied with the --sso-session and --region options.\n\n"
        "Profiles will be generated with the name "
        "[SSO_SESSION]_[AWS_ACCOUNT_NAME]_[SSO_ROLE_NAME] (with Account and Role name "
        "spaces and '.' replaced with '-'). \n\n"
        "The Profiles are written to the User's Configuration File "
        "(the default location is ~/.aws/config)."
    )
    ARG_TABLE = LOGIN_ARGS + [
        # CustomArgument - check out argparse
        {
            "name": "sso-session",
            "help_text": "SSO Session name to lookup AWS Accounts and Roles.",
        }
    ]

    def _run_main(
        self, parsed_args: "Namespace", parsed_globals: "Namespace"
    ) -> "Literal[0]":
        # Borrowed from aws-cli ConfigureSSOCommand._run_main
        # ---------------------8<----------------------------
        self._unset_session_profile()
        on_pending_authorization = None
        if parsed_args.no_browser:
            on_pending_authorization = PrintOnlyHandler()
        # ---------------------------------------------------

        # Choose AWS SSO Session from User Configuration File
        sso_session_name = self._get_sso_session(parsed_args)
        sso_session_config = self._get_sso_session_config(sso_session_name)

        # Choose CLI default region for profiles written to User Configuration File
        cli_region = self._get_cli_region(parsed_globals, sso_session_config)

        # Push existing CLI Profiles in a Set for cross referencing later
        self._existing_sso_profiles = {
            SsoRole(
                sso_session=profile_data["sso_session"],
                account_id=profile_data["sso_account_id"],
                role_name=profile_data["sso_role_name"],
            ): profile_name
            for profile_name, profile_data in cast(
                dict[str, dict[str, dict[str, str]]], self._session.full_config
            )
            .get("profiles", {})
            .items()
            if {"sso_session", "sso_account_id", "sso_role_name"}.issubset(
                profile_data.keys()
            )
        }

        # Authenticate against SSO so we can query Accounts and Roles
        sso_token = do_sso_login(
            session=self._session,
            session_name=sso_session_name,
            sso_region=sso_session_config["sso_region"],
            start_url=sso_session_config["sso_start_url"],
            registration_scopes=sso_session_config["registration_scopes"],
            on_pending_authorization=on_pending_authorization,
            parsed_globals=parsed_globals,
        )

        # Borrowed from aws-cli ConfigureSSOCommand._run_main
        # ---------------------8<----------------------------
        client_config = botocore.config.Config(
            signature_version=UNSIGNED,
            region_name=sso_session_config["sso_region"],
            retries={"max_attempts": 5, "mode": "adaptive"},
        )
        sso_client = self._session.create_client("sso", config=client_config)
        # ---------------------------------------------------

        # Loop through Accounts and Roles to add to User Configuration File
        for account in self._get_all_accounts(sso_client, sso_token)["accountList"]:
            for role in self._get_all_roles(
                sso_client, sso_token, account["accountId"]
            )["roleList"]:
                sso_role = SsoRole(
                    sso_session=sso_session_name,
                    account_id=account["accountId"],
                    role_name=role["roleName"],
                )
                self._upsert_profile(
                    sso_role,
                    sso_session_name,
                    cli_region,
                )

        return 0

    def _get_sso_session(self, parsed_args: "Namespace") -> str:
        """Get the AWS SSO Session to use.

        Parameters
        ----------
        parsed_args : Namespace
            AWS CLI arguments

        Returns
        -------
        str
            AWS SSO Session name from User Configuration File
        """
        if parsed_args.sso_session in self._sso_sessions:
            return parsed_args.sso_session

        return self._prompter.get_value(
            prompt_text="SSO session name",
            current_value=None,
            completions=sorted(self._sso_sessions),
            validator=ValueInListValidator(
                self._sso_sessions, None, "Not a valid SSO Session"
            ),
        )

    def _get_cli_region(
        self, parsed_globals: "Namespace", sso_session_config: dict
    ) -> str:
        """Get the AWS Region for the Profile default Region.

        Parameters
        ----------
        parsed_globals : Namespace
            AWS CLI Global global arguments
        sso_session_config : _type_
            AWS SSO Session from User Configuration File

        Returns
        -------
        str
            AWS Region Code (ap-southeast-2 for example)
        """
        # Check STS for available Regions
        regions = self._session.get_available_regions("sts")

        # Explicitly passed - use that
        if parsed_globals.region in regions:
            return parsed_globals.region

        # Use SSO Region as default for prompt
        default_region = sso_session_config["sso_region"]

        return self._prompter.get_value(
            prompt_text="Default client Region",
            current_value=default_region,
            completions=regions,
            validator=ValueInListValidator(
                regions, default_region, "Not a valid Region"
            ),
        )

    def _upsert_profile(
        self,
        sso_role: "SsoRole",
        account_name: str,
        cli_region: str,
    ) -> None:
        """Update Profile in User Configuration File.

        Parameters
        ----------
        sso_session : str
            The AWS SSO Session name
        account_name : str
            The AWS Account Name
        account_id : str
            The AWS Account ID
        role_name : str
            SSO IAM Role Name
        cli_region : str
            Default CLI Region
        """
        generated_profile_name = (
            f"{sso_role.sso_session}_{account_name}_{sso_role.role_name}"
        ).translate(str.maketrans(" .", "--"))
        profile_values = {
            "sso_session": sso_role.sso_session,
            "sso_account_id": sso_role.account_id,
            "sso_role_name": sso_role.role_name,
            "region": cli_region,
        }

        if profile_name := self._existing_sso_profiles.get(sso_role):
            # Write out to console profile being skipped
            uni_print(
                f"{generated_profile_name} - skipping "
                f"- already present/renamed ({profile_name})\n"
            )
        else:
            # Write out to console profile being written
            uni_print(f"Creating {generated_profile_name}\n")
            profile_section = profile_to_section(generated_profile_name)
            self._update_section(profile_section, profile_values)
            self._write_new_config(generated_profile_name)


class ValueInListValidator(Validator):
    """Validate provided value is a List."""

    def __init__(
        self, valid_values: list[str], default_value: str | None, error_message: str
    ) -> None:
        super().__init__()
        self._valid_values = valid_values
        self._default_value = default_value
        self._error_message = error_message

    def _raise_validation_error(self, document: "Document", message: str) -> "NoReturn":
        index = len(document.text)
        raise ValidationError(index, message)

    def validate(self, document: "Document") -> None:
        if document.text in self._valid_values:
            return
        elif document.text == "" and self._default_value in self._valid_values:
            return
        self._raise_validation_error(document, self._error_message)


class SsoRole(NamedTuple):
    sso_session: str
    account_id: str
    role_name: str
