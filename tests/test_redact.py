import pytest

from tender_desk.redact import Redactor, detect, find_addresses, find_emails, find_names, find_phones


def values(finder, text):
    return [text[s.start : s.end] for s in finder(text)]


# ---- emails ----
@pytest.mark.parametrize(
    "text, expected",
    [
        ("Email priya.nair@gmail.com today", ["priya.nair@gmail.com"]),
        ("Send to <tom+tenders@harbour-works.example>.", ["tom+tenders@harbour-works.example"]),
        ("TOM@OUTLOOK.COM", ["TOM@OUTLOOK.COM"]),
        ("a@b.com.au and c_d@e.net.au", ["a@b.com.au", "c_d@e.net.au"]),
    ],
)
def test_emails_found(text, expected):
    assert values(find_emails, text) == expected


@pytest.mark.parametrize("text", ["No at sign here", "Twitter handle @tradie only", "Cost 5 @ $10 each", "name at gmail dot com"])
def test_emails_near_misses(text):
    assert find_emails(text) == []


# ---- phones ----
@pytest.mark.parametrize(
    "text",
    [
        "0491 570 123",
        "0491570123",
        "0491-570-123",
        "+61 491 570 123",
        "+61491570123",
        "(02) 5550 1234",
        "02 5550 1234",
        "02-5550-1234",
        "0255501234",
        "+61 2 5550 1234",
        "07 5550 1234",
    ],
)
def test_phone_formats_found(text):
    assert values(find_phones, f"Call {text} now") == [text]


def test_local_number_needs_a_cue_word():
    assert values(find_phones, "Ph 5550 1234 after 4pm") == ["5550 1234"]
    assert find_phones("Allow 5550 1234 litres") == []


@pytest.mark.parametrize(
    "text",
    [
        "ABN 51 824 753 556",
        "ABN: 61 234 567 890",
        "Call 1300 555 019",
        "Call 1800 555 020",
        "Call 13 12 34",
        "12,500 m2 of clearing",
        "Reference 20261104",
        "lodged 04/11/2026",
        "0.5 mm clearance, 0.40 ratio",
        "Lot 4 DP 123456",
        "Quote 4471-22",
        "0412345 is too short",  # 7 digits after the 0
        "01 5550 1234 is not a valid area code",
    ],
)
def test_phone_near_misses(text):
    assert find_phones(text) == []


def test_known_gap_ten_digit_code_starting_02_is_flagged():
    """A part code that looks exactly like a phone number can't be told apart by digits. Documented in the README."""
    assert values(find_phones, "Hinge set code 0245 123 456") == ["0245 123 456"]


# ---- addresses ----
@pytest.mark.parametrize(
    "text",
    [
        "12 Wattle Street, Parramatta NSW 2150",
        "12 Wattle St Parramatta NSW 2150",
        "7A Banksia Ave, Box Hill VIC 3128",
        "Unit 4/18 Kestrel Rd, Manly NSW 2095",
        "18 Cobalt Drive",
        "12 Wattle Street\nParramatta NSW 2150",
        "PO Box 214, Newtown NSW 2042",
        "3 Mount Pleasant Road, Kellyville Ridge NSW 2155",
    ],
)
def test_addresses_found(text):
    assert values(find_addresses, f"Site is at {text}.") == [text]


@pytest.mark.parametrize(
    "text",
    [
        "Supply 120 x 45 mm treated pine, 240 lengths",
        "Allow 8 weeks from approval",
        "Order 14 Concrete Pump Hire days",
        "Install 6 Lane markers and 2 Road base layers",
        "12 m3 of concrete",
        "Sydney NSW 2000",
        "postcode 2150",
        "drawing 4471-22 Street elevation",
    ],
)
def test_address_near_misses(text):
    assert find_addresses(text) == []


# ---- names ----
@pytest.mark.parametrize(
    "text, name",
    [
        ("Attn: Priya Nair", "Priya Nair"),
        ("Contact: Tom O'Brien on 0491 570 123", "Tom O'Brien"),
        ("Mr Hamid Karimi will meet you", "Hamid Karimi"),
        ("Ms Linh Tran, linh@gmail.com", "Linh Tran"),
        ("Mrs Maria Lopez owns the house", "Maria Lopez"),
        ("Regards,\nDeb Kowalski\n0491 570 123", "Deb Kowalski"),
        ("Kind regards\nJames McAllister\nProject Manager", "James McAllister"),
        ("ATTN: JOHN SMITH", "JOHN SMITH"),
        ("Site contact: Sam", "Sam"),
        ("Thanks Dave for the visit", "Dave"),
    ],
)
def test_names_after_cues(text, name):
    assert values(find_names, text) == [name]


@pytest.mark.parametrize(
    "text",
    [
        "Contact: Bluegum Constructions Pty Ltd for access",
        "Contact: Ironbark Plumbing Pty Ltd, licensed plumber",
        "Contact: Corella Hardware",
        "Contact us on the number above",
        "Contact the site manager before 8am",
        "Please contact the council office",
        "Regards to the engineer's detail",
        "Mr and Mrs are not names",
        "Thanks for the quote",
    ],
)
def test_name_near_misses(text):
    assert find_names(text) == []


def test_name_with_no_cue_is_missed_by_design():
    assert find_names("Arrange access with Priya Nair, the owner, before 8am.") == []


def test_full_name_repeat_is_caught_but_first_name_alone_is_not():
    text = "Attn: Priya Nair.\nLater, ask Priya Nair again, or just Priya."
    found = values(find_names, text)
    assert found == ["Priya Nair", "Priya Nair"]  # the cue hit and the later repeat; the lone "Priya" is not caught


# ---- overlap and policy ----
def test_email_beats_name_inside_it_and_spans_never_overlap():
    spans = detect("Contact: Tom Smith tom.smith@gmail.com, 0491 570 123, 12 Wattle St, Manly NSW 2095")
    assert [s.type for s in spans] == ["PERSON", "EMAIL", "PHONE", "ADDRESS"]
    assert all(a.end <= b.start for a, b in zip(spans, spans[1:], strict=False))


def test_business_details_are_left_alone():
    text = "ABN 51 824 753 556. Contact: Bluegum Constructions Pty Ltd. Office 1300 555 019. Sydney NSW 2000."
    assert detect(text) == []


# ---- the redactor ----
def test_same_value_same_placeholder_across_formats():
    r = Redactor()
    out = r.redact("Call 0491 570 123 or +61 491 570 123 or 0491-570-123. Email A@b.com, a@B.com.")
    assert out.count("[PHONE_1]") == 3 and "[PHONE_2]" not in out
    assert out.count("[EMAIL_1]") == 2 and "[EMAIL_2]" not in out
    assert r.counts["PHONE"] == 3 and r.counts["EMAIL"] == 2


def test_round_trip_restores_the_original_text():
    text = "Attn: Priya Nair\nPh 0491 570 123, priya@gmail.com\nSite: 12 Wattle Street, Manly NSW 2095\n10 m3 concrete."
    r = Redactor()
    red = r.redact(text)
    for secret in ("Priya", "0491", "priya@gmail.com", "Wattle", "2095"):
        assert secret not in red
    assert "10 m3 concrete" in red
    assert r.restore(red) == text


def test_restore_leaves_an_unknown_placeholder_visible():
    r = Redactor()
    r.redact("Attn: Priya Nair")
    assert r.restore("[PERSON_1] and [PERSON_7]") == "Priya Nair and [PERSON_7]"


def test_restore_deep_handles_nested_data():
    r = Redactor()
    r.redact("Attn: Priya Nair")
    assert r.restore_deep({"a": ["x [PERSON_1]", {"b": "[PERSON_1]"}], "n": 3}) == {
        "a": ["x Priya Nair", {"b": "Priya Nair"}],
        "n": 3,
    }


def test_repr_never_shows_a_value():
    r = Redactor()
    r.redact("Attn: Priya Nair 0491 570 123")
    assert "Priya" not in repr(r) and "0491" not in repr(r)


def test_a_note_replaces_known_values_even_with_no_cue_but_the_tender_text_path_does_not():
    r = Redactor()
    r.redact("Attn: Priya Nair, 12 Wattle Street, Manly NSW 2095")
    assert (
        r.redact_note("Priya Nair wants it by Friday, at 12 wattle street, Manly NSW 2095")
        == "[PERSON_1] wants it by Friday, at [ADDRESS_1]"
    )
    assert Redactor().redact("Priya Nair wants it by Friday") == "Priya Nair wants it by Friday"  # no cue: missed by design
