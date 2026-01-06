from cbok.conf.schema import Option, Group
from cbok import exception


DEFAULT = Group(
    name="default",
    title="Default settings",
    options=[
        Option("workspace", default="",
        help="CBoK workspace, absolutely path of CBoK parent"),
        Option("debug", default=True, help="Enable debug log level"),
        Option("log_dir", default="/var/log/",
        help="CBoK log directory, if you are in MacOS, it will be "
             "forced to ~/Library/Logs/"),
    ],
)

DATABASE = Group(
    name="database",
    title="Database settings",
    options=[
        Option("user", default="root", help="Database user have access to"),
        Option("password", default="", help="Database password"),
        Option("host", default="127.0.0.1", help="Database host"),
        Option("port", default=3306, help="Database port"),
    ],
)

EMAIL = Group(
    name="email",
    title="Email settings",
    options=[
        Option("host", default="", help="SMTP server host"),
        Option("port", default=25, help="SMTP server port"),
        Option("host_user", default="", help="SMTP username"),
        Option("host_password", default="", help="SMTP password"),
        Option("use_tls", default=False, help="Use SSL connection"),
        Option("from", default="", help="Who is sending the email"),
    ],
)

PROXY = Group(
    name="proxy",
    title="proxy settings",
    options=[
        Option("type", default="socks5h", help="Proxy type"),
        Option("cipher", default="aes-256-gcm", help="Encryption method"),
        Option("password", default="", help="VPS password"),
        Option("vps_server", default="", help="VPS IP or hostname"),
        Option("port", default=9646, help="VPS port"),
        Option("localhost", default="127.0.0.1", help="Proxy local host on"),
        Option("localport", default=1080, help="Proxy local port listen to"),
    ],
)

ALERT_ACCOUNT = Group(
    name="alert_account",
    title="alert account settings",
    options=[
        Option("google", default="",
        help="Google account, format as username, password"),
    ]
)

LLM_API_KEY = Group(
    name="llm_api_key",
    title="LLM api key",
    options=[
        Option("deepseek", default="", help="API key of deepseek"),
    ]
)

ALL_GROUPS = [DEFAULT, DATABASE, EMAIL, PROXY, ALERT_ACCOUNT, LLM_API_KEY]


def validate_section_strict(conf, group):
    """
    Rules:
    1. Section missing  -> ignore all options (OK)
    2. Section present  -> all declared options must exist and be non-empty

    WARNING: You must comment out the whole section if you do not want to
             use the feature
    """
    if not conf.has_section(group.name):
        return  # section not enabled, ignore options

    for opt in group.options:
        if not conf.has_option(group.name, opt.name):
            raise exception.ConfigValidateFailed(err_msg=
                f"Missing option [{group.name}] {opt.name}"
            )

        value = conf.get(group.name, opt.name)
        if not value.strip():
            raise exception.ConfigValidateFailed(err_msg=
                f"Empty option [{group.name}] {opt.name}"
            )
