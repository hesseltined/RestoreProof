"""
Purpose: Well-known SMTP provider presets for Notifications UI.
Author: Doug Hesseltine
Created: 2026-07-12
Version: 1.0.0
"""

from typing import Any

SMTP_PRESETS: dict[str, dict[str, Any]] = {
    "generic": {
        "label": "Generic SMTP",
        "host": "",
        "port": 587,
        "use_tls": True,
        "use_ssl": False,
        "fields": ["host", "port", "use_tls", "use_ssl", "username", "password", "from_email", "from_name"],
        "help": "Enter any SMTP server settings manually.",
    },
    "microsoft365": {
        "label": "Microsoft 365 / Outlook",
        "host": "smtp.office365.com",
        "port": 587,
        "use_tls": True,
        "use_ssl": False,
        "fields": ["username", "password", "from_email", "from_name"],
        "help": "Use a mailbox or SMTP AUTH-enabled account. Username is usually the full email.",
    },
    "smtp2go": {
        "label": "SMTP2GO",
        "host": "mail.smtp2go.com",
        "port": 587,
        "use_tls": True,
        "use_ssl": False,
        "fields": ["username", "password", "from_email", "from_name"],
        "help": "Username/password come from the SMTP2GO dashboard (SMTP Users).",
    },
    "zoho": {
        "label": "Zoho Mail",
        "host": "smtp.zoho.com",
        "port": 587,
        "use_tls": True,
        "use_ssl": False,
        "fields": ["username", "password", "from_email", "from_name"],
        "help": "For Zoho EU use smtp.zoho.eu. Enable app-specific password if MFA is on.",
    },
    "gmail": {
        "label": "Gmail (App Password)",
        "host": "smtp.gmail.com",
        "port": 587,
        "use_tls": True,
        "use_ssl": False,
        "fields": ["username", "password", "from_email", "from_name"],
        "help": "Use a Google App Password (not your normal Gmail password).",
    },
    "sendgrid": {
        "label": "SendGrid SMTP",
        "host": "smtp.sendgrid.net",
        "port": 587,
        "use_tls": True,
        "use_ssl": False,
        "fields": ["password", "from_email", "from_name"],
        "help": "Username is always 'apikey'. Paste the API key as the password.",
        "username": "apikey",
    },
    "mailgun": {
        "label": "Mailgun SMTP",
        "host": "smtp.mailgun.org",
        "port": 587,
        "use_tls": True,
        "use_ssl": False,
        "fields": ["username", "password", "from_email", "from_name"],
        "help": "Use SMTP credentials from the Mailgun domain settings.",
    },
    "amazon_ses": {
        "label": "Amazon SES SMTP",
        "host": "email-smtp.us-east-1.amazonaws.com",
        "port": 587,
        "use_tls": True,
        "use_ssl": False,
        "fields": ["host", "username", "password", "from_email", "from_name"],
        "help": "Set host to your SES region endpoint. Use SMTP credentials (not IAM access keys).",
    },
}


def list_presets() -> list[dict[str, Any]]:
    return [{"id": key, **value} for key, value in SMTP_PRESETS.items()]
