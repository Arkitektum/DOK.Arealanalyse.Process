from os import path
from pathlib import Path
import json
from uuid import UUID
from typing import List, Dict, Literal
import aiohttp
from ..models.config.dataset_config import DatasetConfig
from ..services.config import get_dataset_configs
from ..utils.helpers.common import should_refresh_cache
from ..utils.constants import APP_FILES_DIR

__CACHE_DAYS = 7


def get_dataset_type(config: DatasetConfig) -> Literal['wfs', 'arcgis', 'ogc_api']:
    if config.wfs is not None:
        return 'wfs'
    elif config.arcgis is not None:
        return 'arcgis'
    elif config.ogc_api is not None:
        return 'ogc_api'

    return None


async def get_dataset_ids(data: dict, municipality_number: str) -> Dict[UUID, bool]:
    include_chosen_dok = data.get('includeFilterChosenDOK', True)

    if include_chosen_dok:
        kartgrunnlag = await __get_kartgrunnlag(municipality_number)
    else:
        kartgrunnlag = []

    dataset_ids = __get_datasets_by_theme(data.get('theme'))
    datasets: Dict[UUID, bool] = {}

    for id in dataset_ids:
        should_analyze = len(
            kartgrunnlag) == 0 or id is None or id in kartgrunnlag
        datasets[id] = should_analyze

    return datasets


def __get_datasets_by_theme(theme: str) -> List[UUID]:
    dataset_configs = get_dataset_configs()
    dataset_ids = []

    for config in dataset_configs:
        themes = list(map(lambda theme: theme.lower(), config.themes))

        if theme is None or theme.lower() in themes:
            dataset_ids.append(config.dataset_id)

    return dataset_ids


async def __get_kartgrunnlag(municipality_number: str) -> List[str]:
    if municipality_number is None:
        return []

    file_path = Path(path.join(
        APP_FILES_DIR, 'resources/dok-datasets', f'{municipality_number}.json'))

    if not file_path.exists() or should_refresh_cache(file_path, __CACHE_DAYS):
        file_path.parent.mkdir(parents=True, exist_ok=True)
        dataset_ids = await __fetch_dataset_ids(municipality_number)
        json_object = json.dumps(dataset_ids, indent=2)

        with file_path.open('w', encoding='utf-8') as file:
            file.write(json_object)

        return dataset_ids
    else:
        with file_path.open(encoding='utf-8') as file:
            dataset_ids = json.load(file)

        return dataset_ids


async def __fetch_dataset_ids(municipality_number: str) -> List[str]:
    response = await __fetch_kartgrunnlag(municipality_number)

    if response is None:
        return []

    contained_items = response.get('containeditems', [])
    datasets = []

    for dataset in contained_items:
        if dataset.get('ConfirmedDok') == 'JA' and dataset.get('dokStatus') == 'Godkjent':
            metadata_url = dataset.get('MetadataUrl')
            splitted = metadata_url.split('/')
            datasets.append(splitted[-1])

    return datasets


async def __fetch_kartgrunnlag(municipality_number: str) -> dict:
    try:
        url = f'https://register.geonorge.no/api/det-offentlige-kartgrunnlaget-kommunalt.json?municipality={
            municipality_number}'

        async with aiohttp.ClientSession() as session:
            async with session.get(url) as response:
                if response.status != 200:
                    return None

                return await response.json()
    except:
        return None