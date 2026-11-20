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


@pytest.mark.parametrize(
    "text", ["No at sign here", "Twitter handle @tradie only", "Cost 5 @ $10 each", "Meet at the gate at 7.30"]
)
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


def test_known_gap_ten_digit_code_with_no_label_is_flagged():
    """A code that looks exactly like a phone number can't be told apart by digits; only a label before it (part, code, sku...) does."""
    assert values(find_phones, "Hinge set 0245 123 456, 40 sets") == ["0245 123 456"]
    assert find_phones("Hinge set code 0245 123 456") == []


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
    assert find_names("The owner is Priya Nair and she works from home.") == []
    assert find_names("Priya Nair has the keys.") == []


def test_full_name_repeat_is_caught_but_first_name_alone_is_not():
    text = "Attn: Priya Nair.\nLater, ask Priya Nair again, or just Priya."
    found = values(find_names, text)
    assert found == ["Priya Nair", "Priya Nair", "Priya"]  # the cue hit, the later full repeat, and the first name on its own


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


# ---- v3 ----
def test_codes_that_look_like_phones_are_left_alone_when_labelled_as_codes():
    for t in ("SKU 0312 884 120", "Part no. 0245 667 310", "Invoice 0418 220 305", "Ref: 0412 345 678", "order #0412345678"):
        assert find_phones(t) == [], t
    assert values(find_phones, "Call 0412 345 678 now") == ["0412 345 678"]


@pytest.mark.parametrize("text", ["0491.570.123", "04 9157 0123", "+61 (0)491 570 123", "(08) 5550 1234", "+61 8 5550 1234"])
def test_more_phone_formats(text):
    assert values(find_phones, f"Mobile {text} now") == [text]


def test_local_number_cue_may_sit_a_few_words_before():
    assert values(find_phones, "Please phone the office on 5901 7866 to book") == ["5901 7866"]
    assert find_phones("Quantity 5901 7866 kg") == []


@pytest.mark.parametrize(
    "text",
    [
        "14 Eucalypt Boulevard, Subiaco WA 6008",
        "Unit 4, 18 Great Western Highway, Bathurst NSW 2795",
        "Lot 12 Blue Gum Road, Unley SA 5061",
        "7 Heritage Oak Esplanade Southport QLD 4215",
        "Pelican Estate, Subiaco",
        "92 dunmore road, subiaco",
    ],
)
def test_more_address_forms(text):
    assert values(find_addresses, f"Site: {text}.") == [text]


@pytest.mark.parametrize(
    "text",
    [
        "Match the 14 Grove Street style balusters",
        "Order 6 Walk Row brackets",
        "Reuse the 2 Park Lane Pavers",
        "Add 12 Boundary Road base layers",
        "Drawing 5120-07 Street elevation",
    ],
)
def test_address_near_misses_v3(text):
    assert find_addresses(text) == []


def test_obfuscated_email():
    assert values(find_emails, "Reach me at anil.mehta at iinet dot net dot au today") == ["anil.mehta at iinet dot net dot au"]
    assert find_emails("Meet at the gate at 7.30 at the latest") == []


@pytest.mark.parametrize(
    "text, name",
    [
        ("Owner: Rafael Nguyen", "Rafael Nguyen"),
        ("Prepared by: Mei-Ling O'Connell.", "Mei-Ling O'Connell"),
        ("Contact name: Hugo De Souza", "Hugo De Souza"),
        ("Arrange access with Callum Strand (owner) before 8am", "Callum Strand"),
        ("Ask for Bianca Pereira, the site supervisor, on 0491 570 123", "Bianca Pereira"),
        ("Send the quote to Tamsin Castellano (t@example.com)", "Tamsin Castellano"),
        ("Dr. Sunita Whitaker owns it", "Sunita Whitaker"),
        ("Signed Declan Kavanagh", "Declan Kavanagh"),
    ],
)
def test_more_name_forms(text, name):
    assert values(find_names, text) == [name]


def test_a_surname_or_first_name_alone_is_caught_after_the_full_name():
    found = values(find_names, "Attn: Rafael Nguyen. Later, Rafael will call. Ask Nguyen for the keys.")
    assert found == ["Rafael Nguyen", "Rafael", "Nguyen"]


@pytest.mark.parametrize(
    "text",
    [
        "Name: Concrete Supplies Pty Ltd",
        "Ask for Drawing 5 details",
        "Call Silverton Roofing Pty Ltd",
        "From: Harbour View Electrical",
    ],
)
def test_more_name_near_misses(text):
    assert find_names(text) == []


def test_an_extra_detector_adds_only_clean_person_spans():
    from tender_desk.redact import Span

    text = "Speak with Priya Nair today. Ping Silverton Roofing Pty Ltd. ABN 51 824 753 556 call 1300 555 019."

    def at(needle):
        return text.index(needle), text.index(needle) + len(needle)

    def model(t):  # a stand-in for a local model: finds a name, a company, an ABN and a phone-like number
        return [
            Span("PERSON", *at("Priya Nair")),
            Span("PERSON", *at("Silverton Roofing Pty Ltd")),
            Span("PHONE", *at("1300 555 019")),
            Span("PERSON", *at("51 824 753 556")),
        ]

    r = Redactor(extra_detectors=[model])
    out = r.redact(text)
    assert "Priya" not in out and "Silverton Roofing Pty Ltd" in out
    assert "ABN 51 824 753 556" in out and "1300 555 019" in out  # a model's PHONE span is ignored, and the policy stays
