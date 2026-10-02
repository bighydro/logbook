"""A synthetic Google Takeout mbox of any size, for the mail adapter's scale tests.

Every sender and recipient is at `example.org`, every name is drawn from two short lists of common
Norwegian given names and surnames and refers to nobody; the bodies are made-up sentences and the
attachments are random bytes. The mix is meant to look like a real mailbox: six short plain-text
messages in ten, three HTML newsletters as `multipart/alternative`, one with base64 attachments of
20 KB to 1.5 MB — about 50 KB per message on average — with `X-Gmail-Labels`, `X-GM-THRID`, threads by
`In-Reply-To`/`References`, folded headers, quoted-printable, mboxrd `>From ` escapes, the odd message
with no `Message-ID` and the odd one with no `Date`. Deterministic for one seed."""

from __future__ import annotations

import base64
import random
from datetime import UTC, datetime, timedelta
from email.utils import format_datetime
from pathlib import Path

FIRST = ("Kari", "Ola", "Per", "Anne", "Nils", "Ingrid", "Lars", "Sigrid", "Eirik", "Marit", "Jon", "Liv")
LAST = ("Nordmann", "Hansen", "Berg", "Haugen", "Dahl", "Moen", "Lie", "Strand", "Vik", "Holm")
LABELS = (
    "Inbox",
    "Important",
    "Category Personal",
    "Category Promotions",
    "Category Updates",
    "Sent",
    "Starred",
    "Unread",
    "Archived",
    "Spam",
    "Trash",
)
WORDS = (
    "berth",
    "rope",
    "harbour",
    "saturday",
    "mooring",
    "plan",
    "weekend",
    "fjord",
    "weather",
    "invoice",
    "meeting",
    "photos",
    "thanks",
    "tomorrow",
    "ferry",
    "cabin",
    "tickets",
    "dinner",
    "lighthouse",
    "regatta",
)
BLOB_SIZES = (20_000, 60_000, 150_000, 400_000, 1_500_000)
BLOB_WEIGHTS = (8, 6, 4, 2, 1)
EPOCH = datetime(2016, 1, 1, 8, 0, tzinfo=UTC)
OWNER = "kari.nordmann@example.org"


class Generator:
    def __init__(self, seed: int = 0) -> None:
        self.rng = random.Random(seed)
        self.people = [
            (f"{first} {last}", f"{first.lower()}.{last.lower()}@example.org")
            for first in FIRST
            for last in LAST
        ]
        self.blobs = [self._blob(size) for size in BLOB_SIZES]
        self.recent: list[str] = []  # message ids, for threads
        self.n = 0

    def _blob(self, size: int) -> bytes:
        return base64.encodebytes(self.rng.randbytes(size))  # wrapped at 76, as a mailer writes it

    def _sentence(self) -> str:
        words = [self.rng.choice(WORDS) for _ in range(self.rng.randint(4, 12))]
        return " ".join(words).capitalize() + "."

    def _paragraph(self, sentences: int) -> str:
        return " ".join(self._sentence() for _ in range(sentences))

    def message(self) -> bytes:
        """One message with its separator line, ending in one blank line."""
        rng = self.rng
        self.n += 1
        n = self.n
        name, address = rng.choice(self.people)
        when = EPOCH + timedelta(seconds=n * 3600 + rng.randint(0, 3599))
        message_id = f"{n:09d}.{rng.randrange(1 << 32):08x}@mail.example.org"
        shape = rng.random()
        labels = rng.sample(LABELS, rng.randint(1, 3))
        sent = address == OWNER
        if sent:
            labels = ["Sent", *[label for label in labels if label not in ("Inbox", "Sent")]]
        thread = f"17{n:017d}"
        head = [
            f"From {thread}@xxx {when.strftime('%a %b %d %H:%M:%S +0000 %Y')}",
            f"X-GM-THRID: {thread}",
            f"X-Gmail-Labels: {','.join(labels)}",
            f"Delivered-To: {OWNER}",
            f"Received: by 2002:a05:6000:{n % 4096:x} with SMTP id {rng.randrange(1 << 48):x};",
            f"        {format_datetime(when)}",
            "ARC-Seal: i=1; a=rsa-sha256; t=1700000000; cv=none; d=example.org; s=arc;",
            "        b=" + base64.b64encode(rng.randbytes(96)).decode("ascii"),
            "        " + base64.b64encode(rng.randbytes(96)).decode("ascii"),
            "MIME-Version: 1.0",
        ]
        if n % 97 != 0:  # one in 97 has no Message-ID, keyed by digest
            head.append(f"Message-ID: <{message_id}>")
        if self.recent and rng.random() < 0.4:
            parent = rng.choice(self.recent)
            head.append(f"In-Reply-To: <{parent}>")
            head.append(f"References: <{parent}>")
        if n % 89 != 0:  # one in 89 has no Date: timed by the separator
            head.append(f"Date: {format_datetime(when)}")
        head.append(f"From: {name} <{address}>")
        to_name, to_address = rng.choice(self.people) if sent else ("Kari Nordmann", OWNER)
        head.append(f"To: {to_name} <{to_address}>")
        if rng.random() < 0.3:
            cc_name, cc_address = rng.choice(self.people)
            head.append(f"Cc: {cc_name} <{cc_address}>")
        subject = self._sentence()[:-1]
        if rng.random() < 0.2:
            subject = f"=?utf-8?q?{subject.replace(' ', '_')}_=E2=80=93_v=C3=A5r?="
        elif self.recent and rng.random() < 0.5:
            subject = "Re: " + subject
        head.append(f"Subject: {subject}")
        self.recent.append(message_id)
        if len(self.recent) > 50:
            self.recent.pop(0)
        if shape < 0.6:
            body = self._plain(rng)
        elif shape < 0.9:
            body = self._newsletter(rng)
        else:
            body = self._with_attachments(rng)
        return "\n".join(head).encode("utf-8") + b"\n" + body + b"\n"

    def _plain(self, rng: random.Random) -> bytes:
        text = self._paragraph(rng.randint(2, 20))
        lines = [text[i : i + 72] for i in range(0, len(text), 72)]
        if rng.random() < 0.1:
            lines.insert(1, ">From the east berth you can see the lighthouse.")  # mboxrd
        if rng.random() < 0.5:
            lines += ["", "> " + self._sentence(), "> " + self._sentence()]
        return (
            'Content-Type: text/plain; charset="utf-8"\nContent-Transfer-Encoding: 8bit\n\n'
            + "\n".join(lines)
            + "\n"
        ).encode("utf-8")

    def _newsletter(self, rng: random.Random) -> bytes:
        paragraphs = [self._paragraph(rng.randint(3, 8)) for _ in range(rng.randint(10, 60))]
        plain = "\n\n".join(paragraphs)
        html = "<html><head><style>p { color: #333 }</style></head><body>\n"
        html += "<table><tr><td>\n"
        html += "\n".join(f"<p>{p} se p=C3=A5 dette &amp; les mer.</p>" for p in paragraphs)
        html += '\n<p><a href=3D"https://example.org/x">Les mer</a></p></td></tr></table></body></html>\n'
        html_lines = [html[i : i + 70] + "=" for i in range(0, len(html), 70)]
        return (
            'Content-Type: multipart/alternative; boundary="alt0"\n\n'
            '--alt0\nContent-Type: text/plain; charset="utf-8"\nContent-Transfer-Encoding: 8bit\n\n'
            + plain
            + '\n\n--alt0\nContent-Type: text/html; charset="utf-8"\n'
            + "Content-Transfer-Encoding: quoted-printable\n\n"
            + "\n".join(html_lines)
            + "\n--alt0--\n"
        ).encode("utf-8")

    def _with_attachments(self, rng: random.Random) -> bytes:
        parts = [
            b'--mixed0\nContent-Type: text/plain; charset="utf-8"\n\n'
            + self._paragraph(rng.randint(1, 4)).encode("utf-8")
            + b"\n"
        ]
        for i in range(rng.randint(1, 2)):
            blob = rng.choices(self.blobs, BLOB_WEIGHTS)[0]
            name = f"{rng.choice(WORDS)}-{i}.{rng.choice(('pdf', 'jpg', 'zip'))}"
            parts.append(
                f'--mixed0\nContent-Type: application/octet-stream; name="{name}"\n'
                f'Content-Disposition: attachment; filename="{name}"\n'
                "Content-Transfer-Encoding: base64\n\n".encode()
                + blob
            )
        return b'Content-Type: multipart/mixed; boundary="mixed0"\n\n' + b"".join(parts) + b"--mixed0--\n"


def write_mbox(path: Path, target_bytes: int, seed: int = 0) -> int:
    """Write a synthetic mbox of at least `target_bytes` to `path`; how many messages it holds."""
    generator = Generator(seed)
    written = 0
    with path.open("wb") as fh:
        while written < target_bytes:
            data = generator.message()
            fh.write(data)
            written += len(data)
    return generator.n
