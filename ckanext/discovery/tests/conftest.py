# -*- coding: utf-8 -*-

import pytest

from ckanext.discovery.plugins.search_suggestions.model import create_tables


@pytest.fixture
def clean_db(reset_db):
    reset_db()
    create_tables()
