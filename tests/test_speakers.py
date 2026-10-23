"""The voices of a recording (RFC 0038 §2): anonymous labels from a diarizer's turns, each text
segment given the voice that speaks most of it, overlaps, the spans file, and how a reader shows the
voices of a transcript line. `logbook.core.speakers` is pure: no record, no model; the turns here
are synthetic."""

from __future__ import annotations

import json

import pytest

from logbook.core import speakers
from logbook.core.speakers import Assigned, Span, VoiceTurn


def _turns(*rows: tuple[float, float, str]) -> list[VoiceTurn]:
    return [VoiceTurn(start, end, voice) for start, end, voice in rows]


# -- labels ---------------------------------------------------------------------------------------


def test_a_room_s_voices_are_numbered_by_first_speech_not_by_the_pipeline_s_ids():
    heard = [(5.0, 9.0, "SPEAKER_00"), (0.5, 4.0, "SPEAKER_01"), (9.5, 12.0, "SPEAKER_00")]
    assert speakers.label_room(heard) == _turns((0.5, 4.0, "S1"), (5.0, 9.0, "S2"), (9.5, 12.0, "S2"))


def test_a_turn_with_no_length_is_no_speech_and_names_no_voice():
    heard = [(1.0, 1.0, "SPEAKER_07"), (2.0, 3.0, "SPEAKER_00")]
    assert speakers.label_room(heard) == _turns((2.0, 3.0, "S1"))


def test_a_channel_with_one_voice_is_labelled_by_the_channel():
    labelled = speakers.label_channels(
        {"mic": [(0.0, 2.0, "SPEAKER_00"), (4.0, 5.0, "SPEAKER_00")], "system": [(2.0, 3.5, "SPEAKER_00")]}
    )
    assert labelled == _turns((0.0, 2.0, "mic"), (2.0, 3.5, "system"), (4.0, 5.0, "mic"))


def test_a_channel_with_several_voices_numbers_them_by_first_speech_within_the_channel():
    labelled = speakers.label_channels(
        {
            "mic": [(3.0, 4.0, "SPEAKER_00"), (0.0, 1.0, "SPEAKER_01")],
            "system": [(1.0, 2.0, "SPEAKER_00")],
        }
    )
    assert labelled == _turns((0.0, 1.0, "mic.1"), (1.0, 2.0, "system"), (3.0, 4.0, "mic.2"))


def test_labels_are_what_a_speaker_ref_can_split_at_its_first_hash():
    for label in ("S1", "mic", "mic.2", "system.1", "Speaker 2", "them"):
        assert speakers.is_label(label)
    for label in ("", "S#1", "a\nb", "x" * 65, 3, None):
        assert not speakers.is_label(label)


def test_the_order_of_voices_is_the_order_of_first_speech():
    turns = _turns((4.0, 5.0, "S2"), (0.0, 1.0, "S1"), (2.0, 3.0, "S3"))
    assert speakers.order(turns) == ["S1", "S3", "S2"]


# -- seconds and overlap --------------------------------------------------------------------------


def test_each_voice_s_seconds_count_its_own_speech_and_overlaps_count_for_both():
    turns = _turns((0.0, 10.0, "S1"), (8.0, 15.0, "S2"), (20.0, 22.0, "S1"))
    assert speakers.seconds(turns) == {"S1": 12.0, "S2": 7.0}
    assert speakers.overlap_seconds(turns) == pytest.approx(2.0)


def test_a_voice_overlapping_its_own_turns_is_not_overlap_and_is_not_counted_twice():
    turns = _turns((0.0, 5.0, "S1"), (3.0, 6.0, "S1"))
    assert speakers.seconds(turns) == {"S1": 6.0}
    assert speakers.overlap_seconds(turns) == 0.0


def test_overlap_counts_the_time_two_voices_or_more_speak_at_once_once():
    turns = _turns((0.0, 10.0, "S1"), (2.0, 8.0, "S2"), (4.0, 6.0, "S3"))
    assert speakers.overlap_seconds(turns) == pytest.approx(6.0)  # 2 s to 8 s, two or three speaking


# -- assigning text to voices ---------------------------------------------------------------------


def test_a_segment_goes_to_the_voice_that_speaks_most_of_it():
    turns = _turns((0.0, 6.4, "S1"), (6.4, 11.8, "S2"), (11.8, 15.0, "S1"))
    spans = [Span(2.1, 6.42), Span(6.42, 11.8), Span(11.8, 14.95)]
    assert speakers.assign(spans, turns) == [Assigned("S1"), Assigned("S2"), Assigned("S1")]


def test_a_segment_spoken_over_lists_the_others_that_speak_in_it_for_a_second_or_more():
    turns = _turns((11.66, 15.1, "S1"), (11.0, 12.9, "S2"), (14.5, 15.0, "S3"))
    [found] = speakers.assign([Span(11.8, 14.95)], turns)
    assert found == Assigned("S1", ("S2",))  # S2 speaks 1.1 s of it; S3 only 0.45 s


def test_a_segment_with_no_voice_in_it_has_no_speaker():
    turns = _turns((0.0, 2.0, "S1"))
    assert speakers.assign([Span(5.0, 7.0)], turns) == [Assigned(None)]


def test_a_tie_goes_to_the_voice_that_spoke_first():
    turns = _turns((5.0, 6.0, "S2"), (4.0, 5.0, "S1"), (0.0, 1.0, "S1"))
    [found] = speakers.assign([Span(4.0, 6.0)], turns)  # a second each
    assert found == Assigned("S1", ("S2",))


def test_word_times_decide_when_the_engine_gives_them():
    # the segment's span is mostly S2's, but every word in it is S1's: S2 spoke in the pauses
    turns = _turns((0.0, 1.0, "S1"), (1.0, 4.0, "S2"), (4.0, 5.0, "S1"))
    by_span = speakers.assign([Span(0.0, 5.0)], turns)
    by_words = speakers.assign([Span(0.0, 5.0, words=((0.1, 0.9), (4.1, 4.9)))], turns)
    assert by_span[0].speaker == "S2"
    assert by_words[0] == Assigned("S1", ("S2",))


def test_words_that_fall_where_nobody_spoke_leave_the_span_to_decide():
    turns = _turns((0.0, 3.0, "S2"))
    [found] = speakers.assign([Span(0.0, 4.0, words=((3.2, 3.9),))], turns)
    assert found.speaker == "S2"


def test_assigning_a_thousand_segments_against_a_thousand_turns_is_quick():
    turns = [VoiceTurn(i * 2.0, i * 2.0 + 2.5, f"S{i % 3 + 1}") for i in range(1000)]
    spans = [Span(i * 2.0 + 0.2, i * 2.0 + 1.8) for i in range(1000)]
    found = speakers.assign(spans, turns)
    assert [a.speaker for a in found[:3]] == ["S1", "S2", "S3"]


# -- the line's fields ----------------------------------------------------------------------------


def test_the_speakers_field_names_each_voice_in_order_of_first_speech_with_its_counts():
    turns = _turns((0.0, 6.4, "S1"), (6.4, 11.8, "S2"), (11.8, 15.0, "S1"), (30.0, 31.0, "S3"))
    assigned = speakers.assign([Span(0.5, 6.0), Span(6.5, 11.0), Span(12.0, 14.0)], turns)
    field = speakers.speakers_field(speakers.order(turns), assigned, speakers.seconds(turns))
    assert field == [
        {"label": "S1", "seconds": 9.6, "turns": 2},
        {"label": "S2", "seconds": 5.4, "turns": 1},
        {"label": "S3", "seconds": 1.0, "turns": 0},  # heard, but no segment is mostly theirs
    ]


def test_channels_from_me_and_a_source_name_are_written_only_where_given():
    assigned = [Assigned("mic"), Assigned("system")]
    field = speakers.speakers_field(
        ["mic", "system"],
        assigned,
        None,
        channels={"mic": "mic", "system": "system"},
        from_me="mic",
        names={"system": "Ola Nordmann"},
    )
    assert field == [
        {"label": "mic", "turns": 1, "channel": "mic", "from_me": True},
        {"label": "system", "turns": 1, "channel": "system", "name": "Ola Nordmann"},
    ]


def test_the_diarization_field_carries_what_was_given_in_the_rfc_s_order():
    spans = {
        "sha256": "a" * 64,
        "path": f"attachments/{'a' * 64}",
        "bytes": 10,
        "media_type": "application/json",
    }
    field = speakers.diarization_field(
        "pyannote", 1, model="pyannote/speaker-diarization-3.1", audio="c" * 64, overlap_s=38.204, spans=spans
    )
    assert list(field) == ["engine", "model", "audio", "channels", "overlap_s", "spans"]
    assert field["overlap_s"] == 38.2
    assert speakers.diarization_field("granola", 2) == {"engine": "granola", "channels": 2}


# -- the spans file -------------------------------------------------------------------------------


def test_the_spans_file_holds_a_segment_per_content_segment_and_the_diarizer_s_own_turns():
    # RFC 0038 §11's dinner, with Kari speaking on 1.2 s into the third segment (in the RFC's own
    # example she speaks 0.22 s of it, under the one second §2.3 asks of an overlap)
    turns = _turns((2.04, 6.51, "S1"), (6.38, 13.0, "S2"), (11.66, 15.1, "S1"))
    spans = [Span(2.1, 6.42), Span(6.42, 11.8), Span(11.8, 14.95)]
    assigned = speakers.assign(spans, turns)
    document = speakers.spans_document("5e0c" + "0" * 60, spans, assigned, turns)
    assert document == {
        "format": "speaker-spans/1",
        "content": "5e0c" + "0" * 60,
        "segments": [
            {"from": 2.1, "to": 6.42, "speaker": "S1"},
            {"from": 6.42, "to": 11.8, "speaker": "S2"},
            {"from": 11.8, "to": 14.95, "speaker": "S1", "overlap": ["S2"]},
        ],
        "turns": [
            {"from": 2.04, "to": 6.51, "speaker": "S1"},
            {"from": 6.38, "to": 13.0, "speaker": "S2"},
            {"from": 11.66, "to": 15.1, "speaker": "S1"},
        ],
    }


def test_spans_are_seconds_from_the_line_s_at_to_two_decimals_and_the_bytes_are_stable():
    turns = _turns((100.004, 101.996, "S1"))
    spans = [Span(100.0, 102.0)]
    document = speakers.spans_document("0" * 64, spans, speakers.assign(spans, turns), turns, offset=100.0)
    assert document["segments"] == [{"from": 0.0, "to": 2.0, "speaker": "S1"}]
    assert document["turns"] == [{"from": 0.0, "to": 2.0, "speaker": "S1"}]
    data = speakers.spans_bytes(document)
    assert data == speakers.spans_bytes(json.loads(data))  # the same document, the same bytes
    assert b" " not in data and data.startswith(b'{"content":')


# -- what a content file's segments are -----------------------------------------------------------


@pytest.mark.parametrize(
    ("text", "media_type", "count"),
    [
        ("Hei.\nHar du sett vannet?\n\n  \nJa.\n", "text/plain", 3),
        ('[{"text":"a"},{"text":""},{"text":"c"}]', "application/json", 3),
        ('{"segments":[{"text":"a"},{"text":"b"}]}', "application/json", 2),
        (
            "WEBVTT\n\n00:00.000 --> 00:01.000\n<v Kari>Hei\n\n00:01.000 --> 00:02.000\n<v Ola>Ja\n",
            "text/vtt",
            2,
        ),
        ("1\n00:00:00,000 --> 00:00:01,000\nHei\n\n2\n00:00:01,000 --> 00:00:02,000\nJa\n", "text/plain", 2),
        ("Kari: Hei\nOla: Ja\nKari: Fint\n", "text/markdown", 3),
        ("not json", "application/json", None),
    ],
)
def test_a_content_file_s_segments_are_counted_by_its_media_type(text, media_type, count):
    assert speakers.segment_count(text.encode("utf-8"), media_type) == count


# -- reading a line's voices back -----------------------------------------------------------------


def test_a_reader_shows_the_owner_only_from_from_me_and_every_other_voice_by_its_name_or_label():
    payload = {
        "speakers": [
            {"label": "mic", "seconds": 201.7, "turns": 38, "channel": "mic", "from_me": True},
            {"label": "system", "seconds": 188.3, "turns": 35, "channel": "system", "name": "Ola Nordmann"},
            {"label": "S3", "seconds": 41.5, "turns": 4},
            {"label": "S4", "turns": 0},
        ]
    }
    assert speakers.row_text(payload) == "you · Ola Nordmann · S3 · S4"  # who spoke most first, no minutes
    assert (
        speakers.row_text({"speakers": [{"label": "S1", "seconds": 1862.4, "turns": 212}]}) == "S1"
    )  # a voice not yet named is a person too


def test_the_json_of_a_voice_is_shaped_for_the_attributions_to_come():
    payload = {
        "speakers": [
            {"label": "mic", "seconds": 201.7, "turns": 38, "channel": "mic", "from_me": True},
            {"label": "S2", "seconds": 861.0, "turns": 97, "name": "Kari"},
        ]
    }
    assert speakers.to_json(payload) == [
        {
            "label": "mic",
            "person": None,
            "name": None,
            "seconds": 201.7,
            "basis": "channel",
            "consent": None,
            "owner": True,
        },
        {
            "label": "S2",
            "person": None,
            "name": "Kari",
            "seconds": 861.0,
            "basis": None,
            "consent": None,
            "owner": False,
        },
    ]


@pytest.mark.parametrize(
    "value",
    [
        None,
        "S1",
        3,
        [],
        ["S1"],
        [{"turns": 2}],
        [{"label": "S#1", "turns": 1}],
        [{"label": 7}],
        {"label": "S1"},
    ],
)
def test_a_reader_never_fails_on_speakers_it_cannot_read_and_shows_nothing_for_them(value):
    payload = {"speakers": value}
    assert speakers.row_text(payload) == ""
    assert speakers.to_json(payload) == []


def test_a_malformed_entry_is_skipped_and_the_rest_are_read():
    payload = {
        "speakers": [
            {"label": "S1", "seconds": "long", "turns": 2, "from_me": "yes", "name": 4},
            "S2",
            {"label": "S3", "seconds": -4, "turns": 1},
        ]
    }
    assert speakers.row_text(payload) == "S1 · S3"


def test_a_source_s_own_labels_stand_and_only_the_overlap_is_reckoned():
    turns = _turns((0.0, 4.0, "mic"), (1.0, 9.0, "system"))
    found = speakers.assign([Span(0.0, 4.0), Span(1.0, 9.0), Span(9.5, 10.0)], turns, ["mic", "system", None])
    assert found == [Assigned("mic", ("system",)), Assigned("system", ("mic",)), Assigned(None)]


@pytest.mark.parametrize(("start", "end"), [(0.13, 1.13), (0.14, 1.14), (0.38, 1.38)])
def test_a_voice_speaking_one_second_of_a_segment_is_in_its_overlap_whatever_the_float_error(start, end):
    turns = _turns((0.0, 300.0, "S1"), (start, end, "S2"))
    assert speakers.assign([Span(0.0, 300.0)], turns) == [Assigned("S1", ("S2",))]


def test_a_reversed_empty_or_nan_turn_is_no_speech_for_any_of_the_functions():
    bad = _turns((5.0, 3.0, "S9"), (2.0, 2.0, "S9"), (float("nan"), 4.0, "S9"))
    turns = _turns((0.0, 10.0, "S1"), (2.0, 8.0, "S2"), (7.0, 5.0, "S3")) + bad
    assert speakers.order(turns) == ["S1", "S2"]
    assert speakers.seconds(turns) == {"S1": 10.0, "S2": 6.0}
    assert speakers.overlap_seconds(turns) == pytest.approx(6.0)
    assert speakers.assign([Span(0.0, 10.0)], turns) == [Assigned("S1", ("S2",))]


def test_a_time_that_is_not_a_number_never_reaches_a_spans_file():
    with pytest.raises(ValueError, match="not a time"):
        speakers.spans_document("0" * 64, [Span(float("nan"), 1.0)], [Assigned(None)], [])


def test_a_label_with_a_trailing_newline_is_not_a_label():
    """Python's `re.search` lets `$` match before a final newline, so `jsonschema` in Python takes
    `S1\\n` for the profile's pattern; the pattern is ECMA's, and the writers check with `is_label`."""
    assert not speakers.is_label("S1\n")
