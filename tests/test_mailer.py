from unittest.mock import MagicMock, patch

from arxiv_tldr.config import load_config
from arxiv_tldr.mailer import GmailMailer, Message


def test_gmail_mailer_sends_multipart_over_tls_with_app_password():
    with patch("arxiv_tldr.mailer.smtplib.SMTP_SSL") as ssl_cls:
        smtp = ssl_cls.return_value.__enter__.return_value = MagicMock()
        GmailMailer("me@gmail.com", "app-pw").send(
            Message(subject="S", html="<p>h</p>", text="t", recipients=["a@x.org", "b@x.org"])
        )
    assert ssl_cls.call_args.args[:2] == ("smtp.gmail.com", 465)
    smtp.login.assert_called_once_with("me@gmail.com", "app-pw")
    sent = smtp.send_message.call_args.args[0]
    assert sent["To"] == "a@x.org, b@x.org"
    assert sent["Subject"] == "S"
    assert sent.get_body(("html",)) is not None


def test_gmail_credentials_and_recipients_come_from_env_file(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    for name in ("GMAIL_ADDRESS", "GMAIL_APP_PASSWORD", "RECIPIENTS"):
        # load_dotenv writes os.environ directly; register the variable so it is undone.
        monkeypatch.setenv(f"ARXIV_TLDR_{name}", "")
        monkeypatch.delenv(f"ARXIV_TLDR_{name}")
    (tmp_path / ".env").write_text(
        "ARXIV_TLDR_GMAIL_ADDRESS=me@gmail.com\nARXIV_TLDR_GMAIL_APP_PASSWORD=pw\n"
        "ARXIV_TLDR_RECIPIENTS=a@x.org, b@x.org\n"
    )
    config = load_config()
    assert (config.gmail_address, config.gmail_app_password) == ("me@gmail.com", "pw")
    assert config.recipients == ("a@x.org", "b@x.org")
