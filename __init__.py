"""Magik References Images (4 / 6 / 8 / 9 ports): node registration.

All behaviour lives in magik_references_images_.py. Importing it also registers the
/magik/4-references/* HTTP routes. The frontend extension is served from ./web.
"""
from .magik_references_images_ import (
    Magik4ReferencesImages,
    Magik6ReferencesImages,
    Magik8ReferencesImages,
    Magik9ReferencesImages,
)

NODE_CLASS_MAPPINGS = {'Magik4ReferencesImages': Magik4ReferencesImages,
                       'Magik6ReferencesImages': Magik6ReferencesImages,
                       'Magik8ReferencesImages': Magik8ReferencesImages,
                       'Magik9ReferencesImages': Magik9ReferencesImages}
NODE_DISPLAY_NAME_MAPPINGS = {'Magik4ReferencesImages': 'Magik 4 References Images',
                              'Magik6ReferencesImages': 'Magik 6 References Images',
                              'Magik8ReferencesImages': 'Magik 8 References Images',
                              'Magik9ReferencesImages': 'Magik 9 References Images'}
WEB_DIRECTORY = './web'

__all__ = ['NODE_CLASS_MAPPINGS', 'NODE_DISPLAY_NAME_MAPPINGS', 'WEB_DIRECTORY']
