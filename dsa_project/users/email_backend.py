"""E-mail "backend" that only PRINTS e-mails in the terminal where the server runs.

Real e-mail sending is outside the scope of this project. Django's own console backend prints
the e-mail in its encoded form, which cuts long lines with "=" signs: a reset link copied from
there would be broken. This one prints the plain text exactly as the student would read it.
"""

import sys

from django.core.mail.backends.base import BaseEmailBackend

LINE = "=" * 72


class ReadableConsoleEmailBackend(BaseEmailBackend):
    def __init__(self, *args, stream=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.stream = stream or sys.stdout

    def send_messages(self, email_messages):
        for message in email_messages:
            self.stream.write(
                f"\n{LINE}\n"
                f"E-MAIL (printed here, NOT really sent)\n"
                f"To: {', '.join(message.to)}\n"
                f"Subject: {message.subject}\n"
                f"{'-' * 72}\n"
                f"{message.body}\n"
                f"{LINE}\n"
            )
        self.stream.flush()
        return len(email_messages)
