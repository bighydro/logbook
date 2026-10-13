"""`policy/owner.json` lists the owner's handles beside their names, emails and phones: the logins a
service shows for them (GitHub's first), so a line that names one is the owner's own and never a person
the owner met. The key is optional, as the others are: a file written before it existed reads as
listing none, and `logbook init` writes it empty so the owner finds it. Everything is synthetic: Ines
Nordmann of Oslo does not exist, and neither do her logins.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from logbook.contrib import doctor
from logbook.core import policy, present
from logbook.core.store import Logbook


@pytest.fixture
def lb(tmp_path: Path) -> Logbook:
    return Logbook.init(tmp_path / "lb", "Europe/Oslo")


def _write(lb: Logbook, data: object) -> None:
    policy.owner_path(lb.root).write_text(json.dumps(data), encoding="utf-8")


def test_init_writes_the_handles_key_empty(lb: Logbook) -> None:
    written = json.loads(policy.owner_path(lb.root).read_text(encoding="utf-8"))
    assert written == {"names": [], "emails": [], "phones": [], "handles": []}


def test_a_file_without_the_key_lists_no_handles(lb: Logbook) -> None:
    _write(lb, {"names": ["Ines Nordmann"], "emails": [], "phones": []})
    assert policy.owner_aliases(lb.root)["handles"] == []


def test_handles_are_read_stripped_as_the_other_keys_are(lb: Logbook) -> None:
    _write(lb, {"names": [], "emails": [], "phones": [], "handles": [" ines-example ", "", "@InesN"]})
    assert policy.owner_aliases(lb.root)["handles"] == ["ines-example", "@InesN"]


def test_handles_that_are_not_a_list_of_strings_name_the_file(lb: Logbook) -> None:
    _write(lb, {"names": [], "handles": "ines-example"})
    with pytest.raises(policy.PolicyError, match=r"owner\.json") as e:
        policy.owner_aliases(lb.root)
    assert '"handles"' in str(e.value)


def test_handle_spells_a_handle_as_a_ref_carries_it() -> None:
    assert policy.handle(" @Ines-Example ") == "ines-example"
    assert policy.handle("github:Ines-Example") == "github:ines-example"
    assert policy.handle("@") is None and policy.handle("   ") is None


def test_the_owner_is_known_by_a_handle_as_by_an_address() -> None:
    owner = present.owner_of("owner-id", [], {"handles": ["@Ines-Example", "github:ines-x"]}, {})
    assert ("handle", "ines-example") in owner.refs
    assert ("handle", "github:ines-x") in owner.refs


def test_doctor_counts_the_handles_listed(lb: Logbook) -> None:
    _write(lb, {"names": ["Ines Nordmann"], "emails": [], "phones": [], "handles": ["ines-example"]})
    check = doctor.owner_check(lb.root)
    assert check.status == "pass" and "1 names, 1 handles" in check.detail
