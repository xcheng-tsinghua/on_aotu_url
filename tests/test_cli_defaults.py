from __future__ import annotations

from src.main import build_arg_parser


def test_cli_defaults_are_long_running() -> None:
    args = build_arg_parser().parse_args([])

    assert args.target_inspected_count == 0
    assert args.max_scrolls == 0
    assert args.scroll_patience == 50
    assert args.max_candidates_buffer == 5000
    assert args.candidates_json is None
