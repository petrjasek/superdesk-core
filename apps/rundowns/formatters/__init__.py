from abc import abstractmethod, ABC
from typing import List

from .. import types

class BaseFormatter(ABC):
    id: str
    name: str

    @abstractmethod
    def export(self, dest, show: types.IShow, rundown: types.IRundown, items: List[types.IRundownItem]) -> None:
        pass
