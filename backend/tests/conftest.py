import pytest

from bankrecon.generator import Dataset, GeneratorConfig, generate_dataset


@pytest.fixture(scope="session")
def dataset() -> Dataset:
    return generate_dataset(GeneratorConfig(seed=7))
