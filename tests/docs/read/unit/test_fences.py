from python_docs_mcp.services.fences import Fence, fence_before, read_fence, scan_fence


class TestReadFence:
    def test_a_backtick_fence_keeps_its_marker_and_info_string(self) -> None:
        assert read_fence('  ````python x') == Fence(marker='````', info='python x')

    def test_a_backtick_fence_cannot_carry_a_backtick_in_its_info_string(self) -> None:
        assert read_fence('```a`b') is None

    def test_a_tilde_fence_may_carry_a_backtick_in_its_info_string(self) -> None:
        assert read_fence('~~~a`b') == Fence(marker='~~~', info='a`b')

    def test_four_spaces_of_indent_is_not_a_fence(self) -> None:
        assert read_fence('    ```') is None


class TestIsClosedBy:
    fence = Fence(marker='````', info='')

    def test_a_longer_run_of_the_same_character_closes(self) -> None:
        assert self.fence.is_closed_by('`````  ')

    def test_a_shorter_run_does_not_close(self) -> None:
        assert not self.fence.is_closed_by('```')

    def test_another_character_does_not_close(self) -> None:
        assert not self.fence.is_closed_by('~~~~')

    def test_an_info_string_does_not_close(self) -> None:
        assert not self.fence.is_closed_by('````python')


class TestFenceBefore:
    text = '```py\ncode\n```\n~~~\nbody'

    def test_an_offset_inside_a_fence_returns_it(self) -> None:
        assert fence_before(self.text, len('```py\ncode\n```\n~~~\nbo')) == Fence(marker='~~~')

    def test_an_offset_in_the_middle_of_a_closing_line_still_counts_the_fence_as_open(self) -> None:
        assert fence_before(self.text, len('```py\ncode\n``')) == Fence(marker='```', info='py')

    def test_an_offset_after_a_closed_fence_returns_none(self) -> None:
        assert fence_before(self.text, len('```py\ncode\n```\n')) is None


class TestScanFence:
    def test_a_partial_last_line_counts_as_a_line(self) -> None:
        assert scan_fence('text\n```py') == Fence(marker='```', info='py')
