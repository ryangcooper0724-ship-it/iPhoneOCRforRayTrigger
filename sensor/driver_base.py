"""光電管ドライバの共通インターフェース定義。"""

from abc import ABC, abstractmethod


class SensorDriverBase(ABC):
    """YDCI実機ドライバ・モックドライバが実装すべき共通インターフェース。"""

    @abstractmethod
    def connect(self) -> tuple[bool, str]:
        """接続を試みる。(成功フラグ, メッセージ) を返す。"""

    @abstractmethod
    def read_channel(self, channel_no: int) -> int:
        """指定チャンネルの入力値（0 or 1）を返す。"""

    @abstractmethod
    def close(self) -> None:
        """接続を閉じる。"""

    @property
    @abstractmethod
    def is_mock(self) -> bool:
        """モックドライバかどうか。"""
