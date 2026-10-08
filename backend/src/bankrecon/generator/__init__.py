"""Synthetic data generator: a fictional company's invoices, bank statement and ground truth."""

from bankrecon.generator.config import GeneratorConfig, NoiseConfig
from bankrecon.generator.dataset import Dataset, generate_dataset

__all__ = ["Dataset", "GeneratorConfig", "NoiseConfig", "generate_dataset"]
