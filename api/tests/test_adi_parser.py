"""The ADI parser on its own. Needs no database.

ADI is length-prefixed, so a value is exactly the next LEN characters, whatever they contain.
Splitting on text is the classic mistake; these cases are the ones that catch it.
"""
from atlas_api.adif_records import parse_adi, userdefs


def f(name: str, value: str, typ: str = "") -> str:
    """One ADI field with its length computed, so a fixture can't be miscounted by hand."""
    return f"<{name}:{len(value)}{':' + typ if typ else ''}>{value}"


def test_a_value_may_contain_a_tag_and_even_eor():
    a = parse_adi(f("COMMENT", "see <EOR> here") + f("CALL", "W1AW") + "<EOR>")
    assert a.records == [{"COMMENT": "see <EOR> here", "CALL": "W1AW"}]


def test_line_breaks_count_as_characters():
    a = parse_adi(f("QSO_TRANSCRIPT", "NAME\r\nFRED") + f("CALL", "W1AW") + "<EOR>")
    assert a.records[0]["QSO_TRANSCRIPT"] == "NAME\r\nFRED" and a.records[0]["CALL"] == "W1AW"


def test_a_header_exists_exactly_when_the_file_does_not_begin_with_a_tag():
    assert parse_adi("<CALL:4>W1AW<EOR>").header == {}
    a = parse_adi("my log <ADIF_VER:5>3.1.7<EOH><CALL:4>W1AW<EOR>")
    assert a.header == {"ADIF_VER": ("3.1.7", None)} and a.records == [{"CALL": "W1AW"}]


def test_field_names_are_case_insensitive():
    assert parse_adi("<Call:4>W1AW<band:3>20m<EOR>").records == [{"CALL": "W1AW", "BAND": "20m"}]


def test_a_type_indicator_is_read_not_kept_in_the_value():
    assert parse_adi("<CALL:4:S>W1AW<EOR>").records == [{"CALL": "W1AW"}]


def test_an_empty_record_is_not_a_record():
    assert parse_adi("<EOR><CALL:4>W1AW<EOR><EOR>").records == [{"CALL": "W1AW"}]


def test_userdef_constraints_come_from_the_header():
    h = parse_adi("h " + f("USERDEF1", "MY_POWER_CATEGORY,{QRPP,QRP,QRO}", "E") + f("USERDEF2", "MY_TEMP,{-50:150}", "N")
                  + f("USERDEF3", "MY_AMP", "S") + "<EOH>").header
    u = userdefs(h)
    assert u["MY_POWER_CATEGORY"].values == {"QRPP", "QRP", "QRO"}
    assert u["MY_TEMP"].range == (-50.0, 150.0)
    assert u["MY_AMP"].values is None and u["MY_AMP"].range is None
