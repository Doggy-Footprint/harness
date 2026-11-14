import pytest
from hypothesis import HealthCheck, given, seed, settings
from hypothesis import strategies as st

from analytics.brief_parser import locate_brief_turn, parse_brief_text


def text_block(value):
    return {"type": "text", "text": value}


def tool_use(identifier, name="Bash"):
    return {"type": "tool_use", "id": identifier, "name": name, "input": {}}


def tool_result(identifier):
    return {"type": "tool_result", "tool_use_id": identifier, "content": "ok"}


def assistant(*blocks, sidechain=False):
    return {"type": "assistant", "isSidechain": sidechain, "message": {"content": list(blocks)}}


def user(content, **flags):
    return {"type": "user", "message": {"content": content}, **flags}


def fact(value):
    return {"kind": "fact", "text": value}


def decision(value):
    return {"kind": "decision", "text": value}


def parsed(understanding=None, questions=()):
    return {"understanding": understanding, "questions": list(questions)}


def lines(*rows):
    return "\n".join(rows)



LOCATE_CASES = {
    "T01_tool_use_id_found": (
        [user("go"), assistant(tool_use("X")), assistant(text_block("body"))], "X", "body"),
    "T02_tool_use_id_not_found": (
        [user("go"), assistant(tool_use("Y"), text_block("body"))], "X", None),
    "T02b_empty_record_list": ([], "X", None),
    "T03_found_only_in_sidechain_record": (
        [user("go"), assistant(tool_use("X"), text_block("body"), sidechain=True)], "X", None),
    "T04_no_human_prompt_before_starts_at_first_record": (
        [assistant(text_block("a")), assistant(tool_use("X")), assistant(text_block("b")),
         user("next"), assistant(text_block("later"))], "X", "a\n\nb"),
    "T05_no_human_prompt_after_runs_to_the_end_and_earlier_turn_excluded": (
        [user("p1"), assistant(text_block("old")), user("p2"), assistant(text_block("a")),
         assistant(tool_use("X")), assistant(text_block("b"))], "X", "a\n\nb"),
    "T06_text_before_tool_use_in_same_record": (
        [user("go"), assistant(text_block("before"), tool_use("X"))], "X", "before"),
    "T07_text_in_later_records_of_the_turn": (
        [user("go"), assistant(tool_use("X")), user([tool_result("X")]),
         assistant(text_block("one")), assistant(text_block("two"))], "X", "one\n\ntwo"),
    "T08_sidechain_text_in_turn_excluded": (
        [user("go"), assistant(tool_use("X"), text_block("main")),
         assistant(text_block("side"), sidechain=True), assistant(text_block("tail"))],
        "X", "main\n\ntail"),
    "T09_is_meta_user_record_does_not_end_turn": (
        [user("go"), assistant(tool_use("X"), text_block("a")),
         user("meta prompt text", isMeta=True), assistant(text_block("b"))], "X", "a\n\nb"),
    "T10_user_string_starting_with_angle_bracket_does_not_end_turn": (
        [user("go"), assistant(tool_use("X"), text_block("a")),
         user("<local-command-stdout>x</local-command-stdout>"), assistant(text_block("b"))],
        "X", "a\n\nb"),
    "T10b_user_string_with_leading_whitespace_then_angle_bracket": (
        [user("go"), assistant(tool_use("X"), text_block("a")),
         user("  \n<command-name>x</command-name>"), assistant(text_block("b"))], "X", "a\n\nb"),
    "T10c_user_list_text_block_starting_with_angle_bracket": (
        [user("go"), assistant(tool_use("X"), text_block("a")),
         user([text_block("<system-reminder>r</system-reminder>")]), assistant(text_block("b"))],
        "X", "a\n\nb"),
    "T11_compact_summary_record_does_not_end_turn": (
        [user("go"), assistant(tool_use("X"), text_block("a")),
         user("This session is being continued", isCompactSummary=True),
         assistant(text_block("b"))], "X", "a\n\nb"),
    "T12_user_list_with_tool_result_does_not_end_turn": (
        [user("go"), assistant(tool_use("X"), text_block("a")), user([tool_result("X")]),
         assistant(text_block("b"))], "X", "a\n\nb"),
    "T12b_user_list_with_text_and_tool_result_does_not_end_turn": (
        [user("go"), assistant(tool_use("X"), text_block("a")),
         user([text_block("typed"), tool_result("X")]), assistant(text_block("b"))],
        "X", "a\n\nb"),
    "T18_is_meta_user_record_before_tool_use_keeps_earlier_text": (
        [user("go"), assistant(text_block("pre")), user("meta prompt text", isMeta=True),
         assistant(tool_use("X")), assistant(text_block("b"))], "X", "pre\n\nb"),
    "T19_angle_bracket_user_string_before_tool_use_keeps_earlier_text": (
        [user("go"), assistant(text_block("pre")),
         user("<local-command-stdout>x</local-command-stdout>"),
         assistant(tool_use("X")), assistant(text_block("b"))], "X", "pre\n\nb"),
    "T20_compact_summary_before_tool_use_keeps_earlier_text": (
        [user("go"), assistant(text_block("pre")),
         user("This session is being continued", isCompactSummary=True),
         assistant(tool_use("X")), assistant(text_block("b"))], "X", "pre\n\nb"),
    "T21_tool_result_user_list_before_tool_use_keeps_earlier_text": (
        [user("go"), assistant(text_block("pre")), user([tool_result("W")]),
         assistant(tool_use("X")), assistant(text_block("b"))], "X", "pre\n\nb"),
    "T13_user_list_with_text_block_ends_turn": (
        [user("go"), assistant(tool_use("X"), text_block("a")), user([text_block("next prompt")]),
         assistant(text_block("later"))], "X", "a"),
    "T13b_user_string_prompt_ends_turn": (
        [user("go"), assistant(tool_use("X"), text_block("a")), user("next prompt"),
         assistant(text_block("later"))], "X", "a"),
    "T13c_whitespace_only_user_string_does_not_end_turn": (
        [user("go"), assistant(tool_use("X"), text_block("a")), user("  \n "),
         assistant(text_block("b"))], "X", "a\n\nb"),
    "T14_empty_and_whitespace_text_blocks_dropped_and_text_stripped": (
        [user("go"), assistant(text_block(""), tool_use("X"), text_block("  \n "),
                               text_block("  x  "), text_block("y\n"))], "X", "x\n\ny"),
    "T15_thinking_blocks_ignored": (
        [user("go"), assistant({"type": "thinking", "thinking": "secret"}, tool_use("X"),
                               text_block("x"))], "X", "x"),
    "T16a_two_turns_first_id": (
        [user("p1"), assistant(tool_use("X"), text_block("one")), user("p2"),
         assistant(tool_use("Y"), text_block("two"))], "X", "one"),
    "T16b_two_turns_second_id": (
        [user("p1"), assistant(tool_use("X"), text_block("one")), user("p2"),
         assistant(tool_use("Y"), text_block("two"))], "Y", "two"),
    "T17_turn_with_no_text": (
        [user("go"), assistant(tool_use("X")), user([tool_result("X")])], "X", ""),
}


@pytest.mark.parametrize("records,tool_use_id,expected", list(LOCATE_CASES.values()),
                         ids=list(LOCATE_CASES))
def test_o1_locate_brief_turn_decision_table(records, tool_use_id, expected):
    assert locate_brief_turn(records, tool_use_id) == expected


def test_o1_first_matching_assistant_record_wins_over_a_later_duplicate_id():
    records = [user("p1"), assistant(tool_use("X"), text_block("first")), user("p2"),
               assistant(tool_use("X"), text_block("second"))]
    assert locate_brief_turn(records, "X") == "first"


def test_o1_sidechain_use_is_skipped_and_the_later_real_use_is_located():
    records = [user("p1"), assistant(tool_use("X"), text_block("side"), sidechain=True),
               user("p2"), assistant(tool_use("X"), text_block("real"))]
    assert locate_brief_turn(records, "X") == "real"



HEADING_CASES = {
    "fact_by_fact_question": (
        "## Fact question\n- Q", parsed(None, [fact("Q")])),
    "fact_by_korean_keyword": (
        "## 사실 질문\n- Q", parsed(None, [fact("Q")])),
    "decision_by_decision_round": (
        "## Decision round\n- Q", parsed(None, [decision("Q")])),
    "decision_by_korean_keyword": (
        "## 결정 라운드\n- Q", parsed(None, [decision("Q")])),
    "understanding_by_understood": (
        "## What I understood\nbody", parsed("body")),
    "understanding_by_understanding": (
        "## Understanding\nbody", parsed("body")),
    "understanding_by_korean_keyword": (
        "## 제가 이해한 내용\nbody", parsed("body")),
    "no_class_heading_yields_nothing": (
        "## Notes\n- Q\nbody", parsed(None, [])),
    "precedence_fact_over_understanding": (
        "## Fact question 이해\n- Q", parsed(None, [fact("Q")])),
    "precedence_fact_over_decision": (
        "## Fact question and decision round\n- Q", parsed(None, [fact("Q")])),
    "precedence_decision_over_understanding": (
        "## Decision round understanding\n- Q", parsed(None, [decision("Q")])),
    "emphasis_bold_and_title_case": (
        "## **Fact Questions**\n- Q", parsed(None, [fact("Q")])),
    "emphasis_backticks": (
        "## `Decision round`\n- Q", parsed(None, [decision("Q")])),
    "emphasis_uppercase": (
        "## UNDERSTOOD\nbody", parsed("body")),
    "emphasis_underscores": (
        "## __Fact Question__\n- Q", parsed(None, [fact("Q")])),
    "emphasis_single_star_korean": (
        "## *사실 질문*\n- Q", parsed(None, [fact("Q")])),
    "level_1": ("# Fact question\n- Q", parsed(None, [fact("Q")])),
    "level_2": ("## Fact question\n- Q", parsed(None, [fact("Q")])),
    "level_3": ("### Fact question\n- Q", parsed(None, [fact("Q")])),
    "level_4": ("#### Fact question\n- Q", parsed(None, [fact("Q")])),
    "level_5": ("##### Fact question\n- Q", parsed(None, [fact("Q")])),
    "level_6": ("###### Fact question\n- Q", parsed(None, [fact("Q")])),
    "level_7_is_not_a_heading": ("####### Fact question\n- Q", parsed(None, [])),
    "level_7_line_does_not_end_a_section": (
        "## Fact question\n- A\n####### Decision round\n- B",
        parsed(None, [fact("A"), fact("B")])),
    "no_space_after_hashes_is_not_a_heading": ("##Fact question\n- Q", parsed(None, [])),
    "no_space_line_does_not_end_a_section": (
        "## Fact question\n- A\n##Decision round\n- B", parsed(None, [fact("A"), fact("B")])),
    "trailing_hashes_removed": ("## Fact question ##\n- Q", parsed(None, [fact("Q")])),
    "trailing_hashes_without_space": ("## 결정 라운드 ###\n- Q", parsed(None, [decision("Q")])),
    "backtick_fence_hides_heading_and_items": (
        "## Fact question\n- A\n```\n## Decision round\n- X\n```\n- B",
        parsed(None, [fact("A"), fact("B")])),
    "tilde_fence_hides_heading_and_items": (
        "## Fact question\n- A\n~~~\n## Decision round\n- X\n~~~\n- B",
        parsed(None, [fact("A"), fact("B")])),
    "fenced_heading_alone_is_ignored": (
        "```\n## Fact question\n- X\n```\n- Y", parsed(None, [])),
    "unterminated_backtick_fence_ignores_the_rest": (
        "## Fact question\n- A\n```\n- B\n## Decision round\n- C", parsed(None, [fact("A")])),
    "unterminated_tilde_fence_ignores_the_rest": (
        "## Fact question\n- A\n~~~\n- B\n## 이해\nu", parsed(None, [fact("A")])),
    "fence_hides_understanding_heading": (
        "```\n## Understanding\nhidden\n```", parsed(None, [])),
    "backtick_fence_closed_by_a_tilde_line": (
        "## Fact question\n- A\n```\n- B\n~~~\n- C", parsed(None, [fact("A"), fact("C")])),
    "tilde_fence_closed_by_a_backtick_line": (
        "## Fact question\n- A\n~~~\n- B\n```\n- C", parsed(None, [fact("A"), fact("C")])),
    "item_kinds_follow_text_order_across_sections": (
        lines("## Decision round", "- D1", "## Fact question", "- F1", "## Decision round", "- D2"),
        parsed(None, [decision("D1"), fact("F1"), decision("D2")])),
}


@pytest.mark.parametrize("text,expected", list(HEADING_CASES.values()), ids=list(HEADING_CASES))
def test_o2_heading_classes(text, expected):
    assert parse_brief_text(text) == expected


def test_o2_text_without_headings_has_no_understanding_and_no_questions():
    assert parse_brief_text("just a paragraph\n- a bullet") == parsed(None, [])


def test_o2_empty_text():
    assert parse_brief_text("") == parsed(None, [])



BOUNDARY_CASES = {
    "next_heading_level_minus_one_ends": (
        "## Understanding\nbody\n# next\nafter", "body"),
    "next_heading_same_level_ends": (
        "## Understanding\nbody\n## next\nafter", "body"),
    "next_heading_level_plus_one_stays": (
        "## Understanding\nbody\n### sub\nmore\n## next\nafter", "body\n### sub\nmore"),
    "section_at_end_of_text": (
        "## Understanding\nline1\nline2", "line1\nline2"),
    "first_of_two_understanding_sections_used": (
        "## Understanding\nfirst\n## 이해\nsecond", "first"),
    "empty_first_section_is_none_not_the_second": (
        "## Understanding\n\n  \n## 이해\nsecond", None),
    "heading_with_nothing_after_is_none": ("## Understanding", None),
    "paragraphs_kept_and_outer_blank_lines_stripped": (
        "## Understanding\n\npara1\n\npara2\n\n## next", "para1\n\npara2"),
    "level_three_section_ended_by_level_one": (
        "### Understanding\nbody\n# top\nafter", "body"),
    "level_three_section_ended_by_level_two": (
        "### Understanding\nbody\n## next\nafter", "body"),
    "level_three_section_stays_through_level_four": (
        "### Understanding\nbody\n#### sub\nmore", "body\n#### sub\nmore"),
    "text_before_the_heading_is_not_included": (
        "preface\n## Understanding\nbody", "body"),
    "list_lines_stay_in_the_understanding_text": (
        "## Understanding\n- a\n- b", "- a\n- b"),
}


@pytest.mark.parametrize("text,expected", list(BOUNDARY_CASES.values()), ids=list(BOUNDARY_CASES))
def test_o3_section_boundaries_for_understanding(text, expected):
    assert parse_brief_text(text)["understanding"] == expected


def test_o3_fact_section_ends_at_a_lower_level_heading():
    text = "### Fact question\n- A\n## other\n- B"
    assert parse_brief_text(text)["questions"] == [fact("A")]


def test_o3_fact_section_continues_through_a_deeper_heading():
    text = "## Fact question\n- A\n### Detail\n- B\n## other\n- C"
    assert parse_brief_text(text)["questions"] == [fact("A"), fact("B")]


def test_o3_fact_section_ends_at_same_level_heading():
    text = "## Fact question\n- A\n## other\n- B"
    assert parse_brief_text(text)["questions"] == [fact("A")]



VALID_ITEM_LINES = {
    "dash_bullet": "- a",
    "star_bullet": "* a",
    "plus_bullet": "+ a",
    "number_dot": "1. a",
    "number_paren": "1) a",
    "bold_number_dot": "**1. a**",
    "bold_number_paren_with_tail": "**1) a** rest",
    "dash_bold_lead_with_tail": "- **a** rest",
    "number_dot_bold_lead_with_tail": "1. **a** rest",
}

INVALID_ITEM_LINES = {
    "indented_dash": " - a",
    "dash_without_space": "-a",
    "bold_without_number": "**a**",
    "table_row": "| a |",
    "empty_bold_bullet": "- ****",
    "empty_numbered_bold": "**1. **",
}


@pytest.mark.parametrize("line", list(VALID_ITEM_LINES.values()), ids=list(VALID_ITEM_LINES))
@pytest.mark.parametrize("heading,kind", [("## Fact question", "fact"), ("## Decision round", "decision")],
                         ids=["in_fact_section", "in_decision_section"])
def test_o4_valid_item_line_forms(heading, kind, line):
    assert parse_brief_text(heading + "\n" + line)["questions"] == [{"kind": kind, "text": "a"}]


@pytest.mark.parametrize("line", list(INVALID_ITEM_LINES.values()), ids=list(INVALID_ITEM_LINES))
def test_o4_invalid_item_line_forms(line):
    assert parse_brief_text("## Fact question\n" + line)["questions"] == []


def test_o4_section_holding_every_form_keeps_only_the_bold_numbered_items():
    rows = ["## Fact question", *VALID_ITEM_LINES.values(), *INVALID_ITEM_LINES.values()]
    assert parse_brief_text("\n".join(rows))["questions"] == [fact("a"), fact("a")]


def test_o4_section_without_bold_numbered_lines_keeps_every_list_line_form():
    list_forms = [line for name, line in VALID_ITEM_LINES.items() if not name.startswith("bold_number")]
    non_item_lines = [line for name, line in INVALID_ITEM_LINES.items() if name != "empty_numbered_bold"]
    rows = ["## Fact question", *list_forms, *non_item_lines]
    assert len(list_forms) == 7
    assert parse_brief_text("\n".join(rows))["questions"] == [fact("a")] * 7


def test_o4_c15_bold_numbered_lines_take_precedence_and_list_lines_stay_elsewhere():
    text = lines(
        "## Decision round", "**1. Q1?** (note)", "- reason: x", "- facts: y", "**2. Q2?**", "1. z",
        "## Decision round", "- **Q3?** more", "- w")
    assert parse_brief_text(text)["questions"] == [
        decision("Q1?"), decision("Q2?"), decision("Q3?"), decision("w")]


def test_o4_bold_lead_with_trailing_text_gives_only_the_bold_text():
    text = "## Fact question\n- **Q?** why this matters\n2) **R?** more **bold** words"
    assert parse_brief_text(text)["questions"] == [fact("Q?"), fact("R?")]


def test_o4_unterminated_bold_lead_keeps_the_whole_text_normalized():
    assert parse_brief_text("## Fact question\n- **Q")["questions"] == [fact("Q")]
    assert parse_brief_text("## Fact question\n- **Q and more")["questions"] == [fact("Q and more")]


def test_o4_text_that_only_contains_bold_later_is_kept_whole_normalized():
    assert parse_brief_text("## Fact question\n- see **Q?** now")["questions"] == [fact("see Q? now")]


def test_o4_indented_bold_numbered_line_is_not_an_item():
    assert parse_brief_text("## Fact question\n **1. a**")["questions"] == []


def test_o4_indented_bold_numbered_line_does_not_trigger_precedence():
    assert parse_brief_text("## Fact question\n **1. a**\n- b")["questions"] == [fact("b")]


def test_o4_multi_digit_numbers_are_items():
    assert parse_brief_text("## Fact question\n10. a")["questions"] == [fact("a")]
    assert parse_brief_text("## Decision round\n**10. a**")["questions"] == [decision("a")]


def test_o4_bold_numbered_line_only_under_a_deeper_heading_still_gives_precedence():
    text = "## Fact question\n- list one\n### Sub\n**1. bold**\n- list two"
    assert parse_brief_text(text)["questions"] == [fact("bold")]


def test_o4_empty_bold_lead_is_dropped_and_later_lines_still_count():
    text = "## Fact question\n- ****\n- real"
    assert parse_brief_text(text)["questions"] == [fact("real")]


def test_o4_item_inside_a_deeper_heading_counts_for_the_section():
    text = "## Fact question\n### Sub\n- A\n## other\n- B"
    assert parse_brief_text(text)["questions"] == [fact("A")]


def test_o4_item_outside_any_fact_or_decision_section_is_ignored():
    text = "- A\n## Notes\n- B\n## Fact question\n- C\n## Understanding\n- D"
    assert parse_brief_text(text)["questions"] == [fact("C")]


def test_o4_double_underscores_removed():
    assert parse_brief_text("## Fact question\n- __a__ b")["questions"] == [fact("a b")]


def test_o4_double_stars_removed_inside_a_bullet():
    assert parse_brief_text("## Fact question\n1. **A?**")["questions"] == [fact("A?")]


def test_o4_whitespace_runs_collapsed_and_ends_stripped():
    text = "## Fact question\n-   x  \t y   z  "
    assert parse_brief_text(text)["questions"] == [fact("x y z")]


def test_o4_item_whose_normalized_text_is_empty_is_dropped_among_others():
    text = "## Fact question\n- __ __\n- real\n- **  **"
    assert parse_brief_text(text)["questions"] == [fact("real")]


def test_o4_c1_korean_understanding_turn():
    text = lines(
        "## 제가 이해한 내용", "", "첫 문단입니다.", "", "둘째 문단입니다.", "",
        "## Fact question", "",
        "1. **A?**", "   - sub one", "   - sub two", "2. **B?**", "",
        "**묻지 않은 것:** 없음")
    assert parse_brief_text(text) == {
        "understanding": "첫 문단입니다.\n\n둘째 문단입니다.",
        "questions": [fact("A?"), fact("B?")]}


def test_o4_c2_english_decision_turn_with_table():
    text = lines(
        "## Decision round", "",
        "**1. Which store?** (note)", "   - opt a", "   - opt b", "",
        "| col | col |", "| --- | --- |", "| x | y |", "",
        "**2. Retry policy?**", "  - indented")
    assert parse_brief_text(text) == {
        "understanding": None,
        "questions": [decision("Which store?"), decision("Retry policy?")]}



BASE_TEXT = lines(
    "## 제가 이해한 내용", "", "첫째.", "", "둘째.", "",
    "## 사실 질문", "1. **A?**", "2. **B?**", "",
    "## 결정 라운드", "**1. C?** (note)", "",
    "## Notes", "closing words")
BASE_EXPECTED = {"understanding": "첫째.\n\n둘째.",
                 "questions": [fact("A?"), fact("B?"), decision("C?")]}


def test_o5_mr1_appended_paragraph_after_a_non_class_section_keeps_output():
    paragraph = "A plain paragraph with no heading and no bullets."
    assert parse_brief_text(BASE_TEXT) == BASE_EXPECTED
    assert parse_brief_text(BASE_TEXT + "\n\n" + paragraph) == BASE_EXPECTED


def test_o5_mr1_prepended_paragraph_before_any_heading_keeps_output():
    paragraph = "A plain paragraph with no heading and no bullets."
    assert parse_brief_text(paragraph + "\n\n" + BASE_TEXT) == BASE_EXPECTED


@pytest.mark.parametrize("korean,english", [("사실 질문", "fact question"),
                                            ("결정 라운드", "decision round"),
                                            ("이해", "understood")],
                         ids=["fact", "decision", "understanding"])
def test_o5_mr2_keyword_language_swap_keeps_output(korean, english):
    swapped = BASE_TEXT.replace(korean, english)
    assert swapped != BASE_TEXT
    assert parse_brief_text(swapped) == BASE_EXPECTED
    assert parse_brief_text(BASE_TEXT) == BASE_EXPECTED


def test_o5_mr2_all_three_swaps_at_once():
    swapped = lines(
        "## 제가 understood한 내용", "", "첫째.", "", "둘째.", "",
        "## fact question", "1. **A?**", "2. **B?**", "",
        "## decision round", "**1. C?** (note)", "",
        "## Notes", "closing words")
    assert parse_brief_text(swapped) == BASE_EXPECTED


def test_o5_mr3_splitting_one_text_block_into_two_records_keeps_output():
    part_one = "## Understanding\nfirst point"
    part_two = "second point\n\n## Fact question\n1. **A?**"
    whole = part_one + "\n\n" + part_two
    single = [user("go"), assistant(tool_use("X")), assistant(text_block(whole))]
    split = [user("go"), assistant(tool_use("X")), assistant(text_block(part_one)),
             assistant(text_block(part_two))]
    expected = {"understanding": "first point\n\nsecond point", "questions": [fact("A?")]}
    assert parse_brief_text(locate_brief_turn(single, "X")) == expected
    assert parse_brief_text(locate_brief_turn(split, "X")) == expected


def test_o5_mr4_records_after_the_next_human_prompt_keep_located_text():
    base = [user("go"), assistant(tool_use("X")), assistant(text_block("brief")), user("next")]
    extended = base + [assistant(text_block("later")), user("another"),
                       assistant(tool_use("Z"), text_block("z"))]
    assert locate_brief_turn(base, "X") == "brief"
    assert locate_brief_turn(extended, "X") == "brief"



POOL = ["t1", "t2", "t3"]
LINES = st.sampled_from([
    "## Fact question", "### 이해", "# Decision round", "## 사실 질문", "## 결정 라운드",
    "## Understood", "####### x", "##x", "```", "~~~", "- a", "* b", "+ c", "1. d", "2) e",
    "**1. Q?**", "**2) R** rest", "  - indented", "**bold**", "| a | b |", "- ****", "plain text",
    "", "한국어 문장", "## Notes", "## **Fact Questions** ##", "- __x__  y"])
TEXTS = st.one_of(
    st.lists(st.one_of(LINES, st.text(max_size=20)), max_size=25).map("\n".join),
    st.text(max_size=200))
BLOCKS = st.one_of(
    TEXTS.map(text_block),
    st.sampled_from(POOL).map(tool_use),
    st.sampled_from(POOL).map(tool_result),
    st.just({"type": "thinking", "thinking": "t"}))
CONTENTS = st.one_of(TEXTS, st.lists(BLOCKS, max_size=5))
FLAG = st.sampled_from([None, True, False])


def build_record(kind, sidechain, meta, compact, content):
    record = {"type": kind, "message": {"content": content}}
    for key, value in (("isSidechain", sidechain), ("isMeta", meta), ("isCompactSummary", compact)):
        if value is not None:
            record[key] = value
    return record


RECORDS = st.lists(
    st.builds(build_record, st.sampled_from(["assistant", "user", "attachment", "system", "summary"]),
              FLAG, FLAG, FLAG, CONTENTS),
    max_size=12)

RANDOM = settings(max_examples=300, derandomize=False, deadline=None,
                  suppress_health_check=[HealthCheck.too_slow, HealthCheck.data_too_large])


@seed(49)
@RANDOM
@given(RECORDS, st.sampled_from(POOL + ["absent"]))
def test_o9_locate_brief_turn_never_raises_and_returns_str_or_none(records, tool_use_id):
    result = locate_brief_turn(records, tool_use_id)
    assert result is None or isinstance(result, str)


@seed(49)
@RANDOM
@given(TEXTS)
def test_o9_parse_brief_text_never_raises_and_keeps_the_shape(text):
    result = parse_brief_text(text)
    assert isinstance(result, dict)
    assert set(result) == {"understanding", "questions"}
    assert result["understanding"] is None or isinstance(result["understanding"], str)
    assert isinstance(result["questions"], list)
    for item in result["questions"]:
        assert isinstance(item, dict)
        assert set(item) == {"kind", "text"}
        assert item["kind"] in {"fact", "decision"}
        assert isinstance(item["text"], str) and item["text"] != ""
