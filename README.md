# AWS CLI SSO Profiles Plugin

Extend [AWS CLI] to introduce `aws configure sso-profiles` command, which
generates AWS CLI Profiles from the AWS Accounts and Roles available in AWS SSO.

> [!WARNING]
> This uses the "experimental" AWS CLI Plugin system, which can cause the AWS CLI
> to stop working. The [Troubleshooting](#troubleshooting) section describes how to
> disable this plugin.

## Installation

### AWS CLI default installation

You need an AWS CLI version above 2.22.13 (released December 9th 2025).

Upgrade if needed (see [AWS CLI install guide]):

```shell
curl "https://awscli.amazonaws.com/awscli-exe-linux-x86_64.zip" -o "awscliv2.zip" &&
unzip awscliv2.zip &&
sudo ./aws/install --bin-dir /usr/local/bin --install-dir /usr/local/aws-cli --update
```

### AWS CLI plugin installation

We need to install the Python package somewhere which is independent
of the AWS CLI version.
One way is to create a Python Virtual Environment for storing plugins.

```shell
python -m venv ~/.local/share/aws-cli-plugins &&
~/.local/share/aws-cli-plugins/bin/pip install git+https://github.com/neilramsay/aws-cli-sso-profiles-plugin.git
```

AWS CLI needs to be configured to load the plugin on start.

```shell
aws configure set plugins.cli_legacy_plugin_path "$(realpath ~/.local/share/aws-cli-plugins)"
aws configure set plugins.sso_profile aws_cli_sso_profiles_plugin.sso_profiles
```

## Usage

We need to configure an AWS SSO Session (if you haven't done it already).
The following will prompt you for your AWS SSO Instance settings (SSO Start URL, and SSO Region).

```shell
aws configure sso-session
```

Once you've got an AWS SSO Session configured, you can use this plugin to
generate AWS CLI Profiles.
These will be written to your `~/.aws/config` file.

```shell
aws configure sso-profiles
```

## Troubleshooting

### `The virtual environment was not created successfully because ensurepip is not available`

```plain
The virtual environment was not created successfully because ensurepip is not
available.  On Debian/Ubuntu systems, you need to install the python3-venv
package using the following command.

    apt install python3.12-venv

You may need to use sudo with that command.  After installing the python3-venv
package, recreate your virtual environment.
```

On Ubuntu, Python Virtual Environments are not available by default.
Please install it following the directions in the message (i.e. `apt install python3.12-venv` in this case.)

### `No module named 'aws_cli_sso_profiles_plugin'`

This happens when this plugin is not in the Python Path for aws-cli.

To get going **without this plugin**, remove the `cli_legacy_plugin_path` line from your User Configuration (usually `~/.aws/config`).

Otherwise, check the path in `cli_legacy_plugin_path` to ensure it points to
a real directory, and that directory has a `aws_cli_sso_profiles_plugin` subdirectory.

- If the directory is missing, create the Python virtual environment
  (see Installation section)
- If the directory exists, but `aws_cli_sso_profiles_plugin` is missing,
  use the Python virtual environment `pip` (in `[directory]/bin/pip`)
  to install this plugin (see [Installation](#installation) section)

## References

- [AWS CLI GitHub]
- [AWS CLI Docs]

[AWS CLI]: https://github.com/aws/aws-cli
[AWS CLI GitHub]: https://github.com/aws/aws-cli
[AWS CLI Docs]: https://docs.aws.amazon.com/cli/latest/userguide/cli-chap-welcome.html
[AWS CLI install guide]: https://docs.aws.amazon.com/cli/latest/userguide/getting-started-install.html
