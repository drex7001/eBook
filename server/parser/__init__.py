from .base import Block, ParsedDoc, Region, Section  # noqa: F401
from .layout_parser import LayoutParser


def get_parser():
    return LayoutParser()
