"""main.py内の純粋なヘルパー関数・PendingResultQueueの番犬テスト。

main()の巨大関数を複数モジュールへ分割する予定だが、これらのトップレベル関数の
入出力の振る舞いは変えない。分割後も`from main import ...`で同じ動作を保証できるよう、
分割先がどこであってもこのテストがそのまま通ることを基準にする。
"""

from main import (
    PendingResultQueue,
    build_penalty_text,
    normalize_bib_number,
    parse_penalty_counts,
)


def test_build_penalty_text_both_zero_is_empty():
    assert build_penalty_text(0, 0) == ""


def test_build_penalty_text_pt_only():
    assert build_penalty_text(2, 0) == "PT2"


def test_build_penalty_text_datsurin_only():
    assert build_penalty_text(0, 1) == "脱輪1"


def test_build_penalty_text_both():
    assert build_penalty_text(2, 1) == "PT2脱輪1"


def test_parse_penalty_counts_roundtrip():
    assert parse_penalty_counts("PT2脱輪1") == (2, 1)


def test_parse_penalty_counts_empty_string():
    assert parse_penalty_counts("") == (0, 0)


def test_parse_penalty_counts_pt_only():
    assert parse_penalty_counts("PT3") == (3, 0)


def test_normalize_bib_number_fullwidth_digits_to_halfwidth():
    assert normalize_bib_number("１２３") == "123"


def test_normalize_bib_number_strips_whitespace():
    assert normalize_bib_number("  42  ") == "42"


def test_pending_result_queue_first_enqueue_becomes_current():
    q = PendingResultQueue()
    became_current, remaining = q.enqueue(("A", "12", 73.0, "OK"))
    assert became_current is True
    assert remaining == 0


def test_pending_result_queue_second_enqueue_not_current():
    q = PendingResultQueue()
    q.enqueue(("A", "12", 73.0, "OK"))
    became_current, remaining = q.enqueue(("B", "34", 60.0, "OK"))
    assert became_current is False
    assert remaining == 1


def test_pending_result_queue_pop_current_advances_to_next():
    q = PendingResultQueue()
    q.enqueue(("A", "12", 73.0, "OK"))
    q.enqueue(("B", "34", 60.0, "OK"))
    next_item = q.pop_current()
    assert next_item == ("B", "34", 60.0, "OK")


def test_pending_result_queue_pop_current_empty_returns_none():
    q = PendingResultQueue()
    q.enqueue(("A", "12", 73.0, "OK"))
    q.pop_current()
    assert q.pop_current() is None


def test_pending_result_queue_remaining_after_current():
    q = PendingResultQueue()
    q.enqueue(("A", "12", 73.0, "OK"))
    q.enqueue(("B", "34", 60.0, "OK"))
    q.enqueue(("C", "56", 50.0, "OK"))
    assert q.remaining_after_current() == 2
