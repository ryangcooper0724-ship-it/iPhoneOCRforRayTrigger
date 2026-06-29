"""待機中（次にスタート予定）のゼッケン番号を最大3件保持する。

並んでいる時点でゼッケン番号がわかっている前提で、待機1〜3にあらかじめ
入力しておき、枠が空くたびに待機1の番号を順に空き枠へ進める。
"""


class WaitingList:
    CAPACITY = 3

    def __init__(self):
        self._entries: list[str] = ["" for _ in range(self.CAPACITY)]

    def get_entries(self) -> list[str]:
        return list(self._entries)

    def set_entry(self, index: int, bib_number: str) -> None:
        self._entries[index] = bib_number

    def pop_next(self) -> str | None:
        """待機1のゼッケン番号を取り出し、待機2→1、待機3→2に詰める。

        待機1が空の場合は何もせずNoneを返す。
        """
        if not self._entries[0]:
            return None

        value = self._entries[0]
        self._entries = self._entries[1:] + [""]
        return value
