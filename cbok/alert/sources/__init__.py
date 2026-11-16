"""Registered source adapters; importing performs no requests."""

from cbok.registry import Registry
from .base import Observation, SourceAdapter, SourceError, SourceItem


_sources = Registry('source')


def register_source(name, factory):
    return _sources.register(name, factory)


def create_source(adapter: str, config: dict) -> SourceAdapter:
    return _sources.get(adapter)(dict(config))


def list_sources():
    return _sources.items()


from .tencent import TencentSource

register_source('tencent', TencentSource)

__all__ = ['Observation', 'SourceAdapter', 'SourceError', 'SourceItem',
           'create_source', 'register_source', 'list_sources']
