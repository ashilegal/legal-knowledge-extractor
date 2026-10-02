from lke.classify import classify_section
from lke.models import Section


def section(text: str, title: str = "Topic", tables: bool = False) -> Section:
    return Section(section_id="s", doc_id="d", title=title, page_start=1, page_end=1,
                   text=text, token_estimate=len(text) // 4, has_tables=tables)


CASE_TEXT = ("In Shoemaker v. Myers (1990) 52 C3d 1, the court held that the plaintiff's claim "
             "was barred. The appellant argued otherwise but the judgment was affirmed. ") * 3
RULE_TEXT = ("Under Section 25F, an employer shall give one month's notice and must pay "
             "compensation unless the workman is exempt, provided that the rule applies. ") * 3
CONCEPT_TEXT = ('"Retrenchment" means the termination of service for any reason. The concept '
                "refers to termination other than punishment. The doctrine is known as. ") * 3
EXAMPLE_TEXT = ("For example, suppose an employer closes one unit. Illustration: a worker "
                "is dismissed after a scenario of losses. For instance, consider the following. ") * 3


def test_types_detected():
    assert classify_section(section(CASE_TEXT)).types[0] == "CASE"
    assert classify_section(section(RULE_TEXT)).types[0] == "RULE"
    assert classify_section(section(CONCEPT_TEXT)).types[0] == "CONCEPT"
    assert classify_section(section(EXAMPLE_TEXT)).types[0] == "EXAMPLE"


def test_table_suggests_comparison():
    text = "| Feature | EBL | CGL |\n| Errors | Covered | Excluded |\n" + "Some text here. " * 30
    assert "COMPARISON" in classify_section(section(text, tables=True)).types


def test_skips():
    assert classify_section(section("Too short.")).skip_reason == "too short"
    toc = "\n".join(f"Chapter {i} Something ........ {i * 10}" for i in range(1, 30))
    assert classify_section(section(toc)).skip_reason == "table of contents"
    assert classify_section(section("x " * 400, title="Index")).skip


def test_unclear_defaults_to_concept_and_flags_commentary():
    text = "PRACTICE POINTER: Always read the whole policy before advising the client. " * 5
    result = classify_section(section(text))
    assert result.unclear and result.types == ["CONCEPT"]
    assert "practice pointer" in result.proprietary_signals
