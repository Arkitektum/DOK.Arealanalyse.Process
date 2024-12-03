from uuid import UUID
from .analysis import Analysis
from .result_status import ResultStatus
from .config.dataset_config import DatasetConfig
from ..services.kartkatalog import get_kartkatalog_metadata


class EmptyAnalysis(Analysis):
    def __init__(self, dataset_id: UUID, config: DatasetConfig, result_status: ResultStatus):
        super().__init__(dataset_id, config, None, None, None, 0)
        self.result_status = result_status

    async def run(self):
        self.title = self.geolett['tittel'] if self.geolett else self.config.title
        self.themes = self.config.themes
        self.run_on_dataset = await get_kartkatalog_metadata(self.dataset_id)

    def add_run_algorithm(self) -> None:
        raise NotImplementedError

    def run_queries(self) -> None:
        return NotImplementedError

    def set_distance_to_object(self) -> None:
        return NotImplementedError